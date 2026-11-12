"""
tts_engine.py - Edge-TTS লাইব্রেরি দিয়ে উচ্চমানের প্রাকৃতিক বাংলা অডিও জেনারেশন
কোনো এপিআই কী লাগে না, সম্পূর্ণ ফ্রি ও আনলিমিটেড
"""

import asyncio
import edge_tts
from pathlib import Path
import logging
from config import TTS_VOICE, TTS_RATE, TTS_PITCH

logger = logging.getLogger(__name__)

async def generate_bangla_voiceover(text: str, output_audio_path: Path, output_vtt_path: Path = None) -> bool:
    """
    বাংলা টেক্সট থেকে প্রাকৃতিক অডিও ও সাবটাইটেল টাইমস্ট্যাম্প তৈরি করে
    """
    try:
        logger.info(f"Edge-TTS দিয়ে বাংলা অডিও তৈরি হচ্ছে... কণ্ঠ: {TTS_VOICE}")
        communicate = edge_tts.Communicate(
            text=text,
            voice=TTS_VOICE,
            rate=TTS_RATE,
            pitch=TTS_PITCH
        )

        if output_vtt_path:
            submaker = edge_tts.SubMaker()
            with open(output_audio_path, "wb") as audio_file:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_file.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        submaker.create_sub((chunk["offset"], chunk["duration"]), chunk["text"])

            with open(output_vtt_path, "w", encoding="utf-8") as vtt_file:
                vtt_file.write(submaker.generate_subs())
            logger.info("সাবটাইটেল ফাইল (.vtt) সফলভাবে তৈরি হয়েছে")
        else:
            await communicate.save(str(output_audio_path))

        logger.info(f"অডিও সফলভাবে সেভ হয়েছে: {output_audio_path}")
        return True

    except Exception as e:
        logger.error(f"TTS জেনারেশনে ত্রুটি: {str(e)}")
        return False

def make_voiceover_sync(text: str, output_audio_path: Path, output_vtt_path: Path = None):
    """সিঙ্ক র‍্যাপার সহজে রান করার জন্য"""
    return asyncio.run(generate_bangla_voiceover(text, output_audio_path, output_vtt_path))
