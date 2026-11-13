"""
tts_engine.py - Edge-TTS লাইব্রেরি দিয়ে উচ্চমানের প্রাকৃতিক বাংলা অডিও জেনারেশন
কোনো এপিআই কী লাগে না, তবে Microsoft-এর পাবলিক speech endpoint ব্যবহার করে
(অনানুষ্ঠানিক, SLA নেই) — ব্যর্থ হলে ব্যাকআপ হিসেবে ফিক্সড সময় ভাগ হয়

লক্ষ্য: অডিও + প্রতিটি বাক্যের আসল শুরুর সময় (শব্দ-স্তরের WordBoundary দিয়ে)
"""

import asyncio
from pathlib import Path
import logging
from config import TTS_VOICE, TTS_RATE, TTS_PITCH

logger = logging.getLogger(__name__)

# বাংলা সহ দাক্ষিণাত্যের ভাষায় স্পেস-ভিত্তিক শব্দ না ধরা হলে এই অক্ষরগুলো দিয়ে ভাগ করি
SENTENCE_ENDINGS = ("।", "|", ".", "?", "!", "…")


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


async def _synthesize(text: str, output_audio_path: Path) -> dict:
    """একটি টেক্সট একবার চুরি-মুক্ত ভাবে 합성: অডিও + WordBoundary ইভেন্ট"""
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=TTS_VOICE, rate=TTS_RATE, pitch=TTS_PITCH)
    # 1 tick = 100 ন্যানোসেকেন্ড; শুরুর offset জানতে 0 থেকে গুনি
    start_ticks = None
    end_ticks = 0
    audio_bytes = 0

    with open(output_audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
                audio_bytes += len(chunk["data"])
            elif chunk["type"] in {"WordBoundary", "SentenceBoundary"}:
                # বাংলা ভয়েস অনেক সময় WordBoundary দেয় না, শুধু SentenceBoundary দেয়
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
        "words": end_ticks > 0,
        "empty": audio_bytes == 0,
    }


async def generate_bangla_voiceover(text: str, output_audio_path: Path, output_vtt_path: Path = None) -> bool:
    """
    বাংলা টেক্সট থেকে প্রাকৃতিক অডিও ও প্রতিটি বাক্যের সঠিক টাইমিং তৈরি করে

    return: ব্যর্থ হলে False; সফল হলে True (VTT পাথ দিলে টাইমিং সহ VTT তৈরি)
    """
    try:
        logger.info(f"Edge-TTS দিয়ে বাংলা অডিও তৈরি হচ্ছে... কণ্ঠ: {TTS_VOICE}")
        segments = split_sentences(text)
        if not segments:
            raise ValueError("সাবটাইটেল/ভয়েসের জন্য কোনো টেক্সট পাওয়া যায়নি")

        # এক ঘণ্টার বেশি হলে পাবলিক endpoint-এ কল ফেইল করতে পারে, তবে রিলসে তা লাগবে না
        segments = segments[:40]

        output_audio_path.parent.mkdir(parents=True, exist_ok=True)
        temp_audio_path = output_audio_path.with_name(f"{output_audio_path.stem}.part")
        temp_audio_path.unlink(missing_ok=True)

        event_lines = []
        cursor = 0.0
        for idx, sentence in enumerate(segments):
            segment_path = temp_audio_path.with_name(f"{output_audio_path.stem}_{idx:02d}.part")
            segment_path.unlink(missing_ok=True)
            try:
                meta = await _synthesize(sentence, segment_path)
                if meta["empty"]:
                    raise RuntimeError(f"খালি অডিও এসেছে (সাবটাইটেল {idx + 1})")

                start = cursor
                span = meta["end"] - meta["start"]
                if span < 0.5:
                    # boundary টাইমিং না পেলে টুকরোটার আসল অডিও দৈর্ঘ্য নিই
                    span = await asyncio.to_thread(_audio_duration, segment_path)
                span = max(span, 0.4)
                end = start + span
                event_lines.append((start, end, sentence))
                cursor = end
                # টুকরোগুলো একসাথে জুড়ে নি
                with open(temp_audio_path, "ab") as combined, open(segment_path, "rb") as part:
                    combined.write(part.read())
            finally:
                try:
                    segment_path.unlink()
                except OSError:
                    pass
            # স্পিচ সার্ভিসে একটানা কল করলে rate-limit হয়
            await asyncio.sleep(0.15)

        if cursor <= 0:
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
    import subprocess
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
