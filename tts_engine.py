"""
Edge-TTS, gTTS এবং Hugging Face দিয়ে বাংলা ভয়েসওভার ও sentence-level VTT তৈরি।
সব provider-এর অডিও FFmpeg দিয়ে একই WAV format-এ normalize হয়।
"""

import asyncio
import logging
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from config import HF_TOKEN, TTS_PITCH, TTS_RATE, TTS_VOICE

logger = logging.getLogger(__name__)

SENTENCE_ENDINGS = ("।", "|", ".", "?", "!", "…")

VOICE_POOL = list(dict.fromkeys([
    TTS_VOICE,
    "bn-BD-NabanitaNeural",
    "bn-BD-PradeepNeural",
    "bn-IN-TanishaaNeural",
    "bn-IN-BashkarNeural",
]))


def split_sentences(text: str) -> list[str]:
    """বাংলা দাঁড়ি/প্রশ্নবোধক ইত্যাদি ধরে বাক্য ভাগ করে।"""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return []

    sentences = []
    buffer = ""
    for char in cleaned:
        buffer += char
        if char in SENTENCE_ENDINGS and buffer.strip():
            sentences.append(buffer.strip())
            buffer = ""

    if buffer.strip():
        sentences.append(buffer.strip())

    return sentences


async def _synthesize_edge(text: str, voice: str, output_audio_path: Path) -> dict:
    """Edge-TTS দিয়ে একটি বাক্যের অডিও এবং boundary timing তৈরি করে।"""
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=TTS_RATE,
        pitch=TTS_PITCH,
    )

    start_ticks = None
    end_ticks = 0
    audio_bytes = 0

    with open(output_audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
                audio_bytes += len(chunk["data"])
            elif chunk["type"] in {"WordBoundary", "SentenceBoundary"}:
                offset = int(chunk["offset"])
                end_offset = offset + int(chunk["duration"])
                start_ticks = (
                    offset if start_ticks is None else min(start_ticks, offset)
                )
                end_ticks = max(end_ticks, end_offset)

    if audio_bytes < 512:
        raise RuntimeError("Edge-TTS থেকে কোনো অডিও পাওয়া যায়নি")

    start_ticks = start_ticks or 0
    return {
        "start": start_ticks * 1e-7,
        "end": end_ticks * 1e-7,
    }


def _synthesize_gtts_sync(text: str, output_audio_path: Path) -> bool:
    """gTTS দিয়ে বাংলা MP3 তৈরি করে।"""
    from gtts import gTTS

    gTTS(text=text, lang="bn", slow=False).save(str(output_audio_path))
    return output_audio_path.exists() and output_audio_path.stat().st_size > 512


def _synthesize_hf_sync(text: str, output_audio_path: Path) -> bool:
    """
    Hugging Face Inference API-তে facebook/mms-tts-ben চেষ্টা করে।
    HF_TOKEN ঐচ্ছিক; public inference-এর access/limit পরিবর্তন হতে পারে।
    """
    url = (
        "https://api-inference.huggingface.co/models/facebook/mms-tts-ben"
    )
    headers = {"Accept": "audio/*"}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    for attempt in range(1, 4):
        try:
            response = requests.post(
                url,
                headers=headers,
                json={"inputs": text},
                timeout=60,
            )
        except requests.RequestException as exc:
            logger.warning("Hugging Face network error, চেষ্টা %s/3: %s", attempt, exc)
            if attempt < 3:
                time.sleep(2 * attempt)
                continue
            return False

        content_type = response.headers.get("content-type", "").lower()
        is_audio = "json" not in content_type and len(response.content) > 512

        if response.ok and is_audio:
            output_audio_path.write_bytes(response.content)
            return True

        # Model cold start / temporary overload হলে আবার চেষ্টা।
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(2 * attempt)
            continue

        logger.warning(
            "Hugging Face TTS response: %s %s",
            response.status_code,
            response.text[:250],
        )
        return False

    return False


async def _synthesize_with_fallbacks(
    text: str,
    output_audio_path: Path,
) -> dict:
    """Edge-TTS voice rotation → gTTS → Hugging Face।"""
    for voice in VOICE_POOL:
        for attempt in range(1, 3):
            output_audio_path.unlink(missing_ok=True)
            try:
                meta = await _synthesize_edge(text, voice, output_audio_path)
                logger.info("Edge-TTS সফল: %s", voice)
                return meta
            except Exception as exc:
                logger.warning(
                    "Edge-TTS ব্যর্থ (কণ্ঠ %s, চেষ্টা %s): %s",
                    voice,
                    attempt,
                    exc,
                )
                output_audio_path.unlink(missing_ok=True)
                if attempt < 2:
                    await asyncio.sleep(2 * attempt)

    output_audio_path.unlink(missing_ok=True)
    try:
        logger.warning("Edge-TTS কণ্ঠগুলো ব্যর্থ; gTTS fallback চেষ্টা হচ্ছে।")
        if await asyncio.to_thread(
            _synthesize_gtts_sync,
            text,
            output_audio_path,
        ):
            return {"start": 0.0, "end": 0.0}
    except Exception as exc:
        logger.warning("gTTS ব্যর্থ: %s", exc)

    output_audio_path.unlink(missing_ok=True)
    try:
        logger.warning("gTTS ব্যর্থ; Hugging Face MMS fallback চেষ্টা হচ্ছে।")
        if await asyncio.to_thread(
            _synthesize_hf_sync,
            text,
            output_audio_path,
        ):
            return {"start": 0.0, "end": 0.0}
    except Exception as exc:
        logger.warning("Hugging Face TTS ব্যর্থ: %s", exc)

    raise RuntimeError(
        "Edge-TTS, gTTS এবং Hugging Face—সব TTS মাধ্যম ব্যর্থ হয়েছে।"
    )


def _run_ffmpeg(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(
        args,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True,
        timeout=120,
    )


def _convert_to_standard_wav(raw_path: Path, wav_path: Path) -> None:
    """Provider-এর অডিওকে এক format: mono, 24 kHz, PCM WAV-এ রূপান্তর করে।"""
    _run_ffmpeg([
        "ffmpeg",
        "-y",
        "-i",
        str(raw_path),
        "-vn",
        "-ar",
        "24000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(wav_path),
    ])


def _concat_wav_segments_to_mp3(
    wav_paths: list[Path],
    output_path: Path,
) -> None:
    """Normalized WAV বাক্যগুলো জুড়ে এক MP3 তৈরি করে।"""
    if not wav_paths:
        raise ValueError("কোনো WAV segment নেই")

    list_path = wav_paths[0].parent / "segments.txt"
    list_path.write_text(
        "".join(f"file '{path.name}'\n" for path in wav_paths),
        encoding="utf-8",
    )

    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-ar",
            "24000",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "64k",
            str(output_path),
        ],
        cwd=wav_paths[0].parent,
    )


def _audio_duration(path: Path) -> float:
    """ffprobe দিয়ে normalized বাক্যের সঠিক দৈর্ঘ্য বের করে।"""
    output = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        timeout=20,
    ).decode().strip()

    duration = float(output)
    if duration <= 0:
        raise RuntimeError(f"অডিও duration অবৈধ: {path}")
    return duration


def _vtt_ts(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


async def generate_bangla_voiceover(
    text: str,
    output_audio_path: Path,
    output_vtt_path: Path = None,
) -> bool:
    """বাংলা অডিও তৈরি ও প্রতিটি বাক্যের প্রকৃত duration দিয়ে VTT লেখে।"""
    try:
        sentences = split_sentences(text)[:40]
        if not sentences:
            raise ValueError("সাবটাইটেল/ভয়েসের জন্য কোনো টেক্সট পাওয়া যায়নি")

        output_audio_path = Path(output_audio_path)
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)

        if output_vtt_path:
            output_vtt_path = Path(output_vtt_path)
            output_vtt_path.parent.mkdir(parents=True, exist_ok=True)

        event_lines = []
        wav_paths = []
        cursor = 0.0

        # Temporary directory output-এর একই filesystem-এ থাকায় final replace নিরাপদ।
        with tempfile.TemporaryDirectory(
            prefix="reel-tts-",
            dir=output_audio_path.parent,
        ) as temp:
            temp_dir = Path(temp)

            for idx, sentence in enumerate(sentences):
                raw_path = temp_dir / f"segment_{idx:02d}.raw"
                wav_path = temp_dir / f"segment_{idx:02d}.wav"

                await _synthesize_with_fallbacks(sentence, raw_path)
                await asyncio.to_thread(
                    _convert_to_standard_wav,
                    raw_path,
                    wav_path,
                )

                duration = await asyncio.to_thread(_audio_duration, wav_path)
                start = cursor
                end = cursor + duration

                event_lines.append((start, end, sentence))
                wav_paths.append(wav_path)
                cursor = end

            final_temp = temp_dir / "voiceover.mp3"
            await asyncio.to_thread(
                _concat_wav_segments_to_mp3,
                wav_paths,
                final_temp,
            )

            if not final_temp.exists() or final_temp.stat().st_size < 1024:
                raise RuntimeError("FFmpeg থেকে বৈধ MP3 তৈরি হয়নি")

            final_temp.replace(output_audio_path)

        if output_vtt_path:
            with open(output_vtt_path, "w", encoding="utf-8") as vtt_file:
                vtt_file.write("WEBVTT\n\n")
                for idx, (start, end, sentence) in enumerate(event_lines, 1):
                    vtt_file.write(
                        f"{idx}\n"
                        f"{_vtt_ts(start)} --> {_vtt_ts(end)}\n"
                        f"{sentence}\n\n"
                    )

        logger.info("অডিও ও sentence-level VTT তৈরি হয়েছে: %s", output_audio_path)
        return True

    except Exception as exc:
        logger.error("TTS জেনারেশনে ত্রুটি: %s", exc)
        return False


def make_voiceover_sync(
    text: str,
    output_audio_path: Path,
    output_vtt_path: Path = None,
):
    """সিঙ্ক র্যাপার।"""
    return asyncio.run(
        generate_bangla_voiceover(text, output_audio_path, output_vtt_path)
    )
