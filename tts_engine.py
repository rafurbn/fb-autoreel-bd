"""
tts_engine.py - Edge-TTS + মাল্টি-লেয়ার ব্যাকআপ (Voice Rotation, gTTS, HuggingFace)
লক্ষ্য: অডিও + প্রতিটি বাক্যের আসল শুরুর সময় (.vtt সাবটাইটেল) নিশ্চিত করা
"""

import asyncio
from pathlib import Path
import logging
import subprocess
import requests
from config import TTS_VOICE, TTS_RATE, TTS_PITCH

logger = logging.getLogger(__name__)

SENTENCE_ENDINGS = ("।", "|", ".", "?", "!", "…")

# ধাপ-১ ও ধাপ-২: মূল ভয়েস এবং বিকল্প বাংলা ভয়েসগুলোর তালিকা
BACKUP_VOICES = [
    TTS_VOICE,
    "bn-BD-NabanitaNeural",
    "bn-BD-PradeepNeural",
    "bn-IN-TanishaaNeural",
    "bn-IN-BashkarNeural",
]
# ডুপ্লিকেট ভয়েস বাদ দিয়ে ক্রম ঠিক রাখা
VOICE_POOL = list(dict.fromkeys(BACKUP_VOICES))


def split_sentences(text: str) -> list[str]:
    """বাংলা দাঁড়ি/প্রশ্নবোধক ইত্যাদি ধরে বাক্য ভাগ করে"""
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
    """Edge-TTS দিয়ে একটি বাক্য তৈরি (অডিও + WordBoundary)"""
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=TTS_RATE, pitch=TTS_PITCH)
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
                if start_ticks is None or offset < start_ticks:
                    start_ticks = offset
                end_ticks = max(end_ticks, end_offset)

    if start_ticks is None:
        start_ticks = 0

    return {
        "text": text,
        "start": start_ticks * 1e-7,
        "end": end_ticks * 1e-7,
        "empty": audio_bytes < 512,
    }


def _synthesize_gtts_sync(text: str, output_audio_path: Path) -> bool:
    """ব্যাকআপ ১: gTTS (Google Translate TTS)"""
    from gtts import gTTS
    tts = gTTS(text=text, lang="bn", slow=False)
    tts.save(str(output_audio_path))
    return output_audio_path.exists() and output_audio_path.stat().st_size > 512


def _synthesize_hf_sync(text: str, output_audio_path: Path) -> bool:
    """ব্যাকআপ ২: Hugging Face Free Inference API (Meta MMS Bengali)"""
    api_url = "https://huggingface.co"
    response = requests.post(api_url, json={"inputs": text}, timeout=25)
    if response.status_code == 200 and len(response.content) > 512:
        with open(output_audio_path, "wb") as f:
            f.write(response.content)
        return True
    return False


async def _synthesize_with_fallbacks(text: str, output_audio_path: Path) -> dict:
    """ধাপ-১, ধাপ-২ এবং ২টি ব্যাকআপ চালিয়ে অডিও নিশ্চিত করে"""
    # ধাপ-১ ও ধাপ-২: Edge-TTS ভয়েস রোটেশন ও রিট্রাই
    for voice in VOICE_POOL:
        for attempt in range(1, 3):  # প্রতিটি ভয়েসে ২ বার চেষ্টা
            try:
                meta = await _synthesize_edge(text, voice, output_audio_path)
                if not meta["empty"]:
                    return meta
            except Exception as e:
                logger.warning(f"Edge-TTS ব্যর্থ ({voice}, চেষ্টা {attempt}): {e}")
                await asyncio.sleep(2.5 * attempt)

    # ব্যাকআপ ১: gTTS
    try:
        logger.warning("Edge-TTS সব ভয়েস ব্যর্থ। ব্যাকআপ ১ (gTTS) চালু হচ্ছে...")
        ok = await asyncio.to_thread(_synthesize_gtts_sync, text, output_audio_path)
        if ok:
            return {"text": text, "start": 0.0, "end": 0.0, "empty": False}
    except Exception as e:
        logger.warning(f"ব্যাকআপ ১ (gTTS) ব্যর্থ: {e}")

    # ব্যাকআপ ২: Hugging Face Meta MMS
    try:
        logger.warning("ব্যাকআপ ২ (Hugging Face MMS) চালু হচ্ছে...")
        ok = await asyncio.to_thread(_synthesize_hf_sync, text, output_audio_path)
        if ok:
            return {"text": text, "start": 0.0, "end": 0.0, "empty": False}
    except Exception as e:
        logger.warning(f"ব্যাকআপ ২ (Hugging Face) ব্যর্থ: {e}")

    raise RuntimeError("সবগুলো TTS মাধ্যম (Edge-TTS, gTTS, HuggingFace) ব্যর্থ হয়েছে।")


def _convert_to_standard_mp3(raw_path: Path, final_mp3_path: Path):
    """ভিন্ন ভিন্ন ব্যাকআপের অডিও ফরম্যাটকে একরকম MP3-তে রূপান্তর করে যাতে জোড়া লাগাতে সমস্যা না হয়"""
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(raw_path),
            "-ar", "24000", "-ac", "1", "-b:a", "64k",
            str(final_mp3_path)
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True
    )


async def generate_bangla_voiceover(text: str, output_audio_path: Path, output_vtt_path: Path = None) -> bool:
    """
    বাংলা টেক্সট থেকে প্রাকৃতিক অডিও ও প্রতিটি বাক্যের সঠিক টাইমিং তৈরি করে
    return: ব্যর্থ হলে False; সফল হলে True
    """
    try:
        logger.info(f"মাল্টি-লেয়ার TTS দিয়ে বাংলা অডিও তৈরি হচ্ছে... মূল কণ্ঠ: {TTS_VOICE}")
        segments = split_sentences(text)
        if not segments:
            raise ValueError("সাবটাইটেল/ভয়েসের জন্য কোনো টেক্সট পাওয়া যায়নি")

        segments = segments[:40]
        output_audio_path.parent.mkdir(parents=True, exist_ok=True)
        temp_audio_path = output_audio_path.with_name(f"{output_audio_path.stem}.part")
        temp_audio_path.unlink(missing_ok=True)

        event_lines = []
        cursor = 0.0

        for idx, sentence in enumerate(segments):
            raw_seg = temp_audio_path.with_name(f"{output_audio_path.stem}_{idx:02d}_raw.part")
            norm_seg = temp_audio_path.with_name(f"{output_audio_path.stem}_{idx:02d}.mp3")
            raw_seg.unlink(missing_ok=True)
            norm_seg.unlink(missing_ok=True)

            try:
                meta = await _synthesize_with_fallbacks(sentence, raw_seg)

                # অডিও ফরম্যাট ঠিক করা (যাতে Edge-TTS ও ব্যাকআপ অডিও একসাথে জোড়া লাগলে ক্র্যাশ না করে)
                await asyncio.to_thread(_convert_to_standard_mp3, raw_seg, norm_seg)

                start = cursor
                span = meta["end"] - meta["start"]
                if span < 0.5:
                    span = await asyncio.to_thread(_audio_duration, norm_seg)
                span = max(span, 0.4)
                end = start + span

                event_lines.append((start, end, sentence))
                cursor = end

                with open(temp_audio_path, "ab") as combined, open(norm_seg, "rb") as part:
                    combined.write(part.read())
            finally:
                raw_seg.unlink(missing_ok=True)
                norm_seg.unlink(missing_ok=True)

            await asyncio.sleep(0.2)

        if cursor <= 0 or not temp_audio_path.exists() or temp_audio_path.stat().st_size < 1024:
            raise RuntimeError("TTS থেকে কোনো বৈধ অডিও পাওয়া যায়নি")

        temp_audio_path.replace(output_audio_path)

        if output_vtt_path:
            logger.info("টাইমিং সহ সাবটাইটেল ফাইল (.vtt) সফলভাবে তৈরি হয়েছে")
            with open(output_vtt_path, "w", encoding="utf-8") as vtt_file:
                vtt_file.write("WEBVTT\n\n")
                for idx, (start, end, line) in enumerate(event_lines, 1):
                    vtt_file.write(f"{idx}\n{_vtt_ts(start)} --> {_vtt_ts(end)}\n{line}\n\n")

        logger.info(f"অডিও সফলভাবে সেভ হয়েছে: {output_audio_path}")
        return True

    except Exception as e:
        logger.error(f"TTS জেনারেশনে ত্রুটি: {str(e)}")
        return False


def _audio_duration(path: Path) -> float:
    """ffprobe দিয়ে অডিও টুকরোটার সঠিক দৈর্ঘ্য (সেকেন্ড)"""
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path)
        ], timeout=20).decode().strip()
        return float(out)
    except Exception:
        return 0.0


def _vtt_ts(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    secs = (millis // 1000) % 60
    mins = (millis // 60000) % 60
    hours = millis // 3600000
    return f"{hours:02d}:{mins:02d}:{secs:02d}.{millis % 1000:03d}"


def make_voiceover_sync(text: str, output_audio_path: Path, output_vtt_path: Path = None):
    """সিঙ্ক র্যাপার সহজে রান করার জন্য"""
    return asyncio.run(generate_bangla_voiceover(text, output_audio_path, output_vtt_path))
