"""
config.py - FB AutoReel BD কনফিগারেশন
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
MUSIC_DIR = ASSETS_DIR / "music"

for directory in (OUTPUT_DIR, ASSETS_DIR, FONTS_DIR, MUSIC_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def _get_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = value.strip()
    return cleaned if cleaned else default


# স্ক্রিপ্ট তৈরির API
GEMINI_API_KEY = _get_env("GEMINI_API_KEY")
GROQ_API_KEY = _get_env("GROQ_API_KEY")

# Hugging Face token ঐচ্ছিক। Free inference-এর access/limit পরিবর্তন হতে পারে।
HF_TOKEN = _get_env("HF_TOKEN")

# Facebook Graph API
FB_PAGE_ID = _get_env("FB_PAGE_ID")
FB_PAGE_ACCESS_TOKEN = _get_env("FB_PAGE_ACCESS_TOKEN")

# Stock footage API
PEXELS_API_KEY = _get_env("PEXELS_API_KEY")
PIXABAY_API_KEY = _get_env("PIXABAY_API_KEY")

# প্রথমে এই Edge-TTS কণ্ঠ; ব্যর্থ হলে tts_engine.py-তে অন্য বাংলা কণ্ঠ চেষ্টা হবে।
TTS_VOICE = _get_env("TTS_VOICE", "bn-BD-NabanitaNeural")
TTS_RATE = "+0%"
TTS_PITCH = "+0Hz"

# ব্র্যান্ডিং
BRAND_LOGO_PATH = ASSETS_DIR / "logo.png"
BRAND_NAME = _get_env("BRAND_NAME", "হাসির মেলা BD")
FONT_PATH = FONTS_DIR / "Kalpurush.ttf"

COLOR_FILTER = "eq=contrast=1.06:brightness=0.03:saturation=1.12"
