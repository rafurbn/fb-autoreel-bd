"""
config.py - FB AutoReel BD কনফিগারেশন ফাইল
প্রয়োজনীয় API Keys ও সেটিংস লোড করে
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# .env ফাইল লোড করা
load_dotenv()

# ডিরেক্টরি সেটআপ
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
MUSIC_DIR = ASSETS_DIR / "music"

OUTPUT_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(exist_ok=True)
MUSIC_DIR.mkdir(exist_ok=True)

# Google Gemini API কী (বিনামূল্যে https://aistudio.google.com থেকে সংগ্রহ করুন)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Facebook Graph API ক্রেডেনশিয়াল (Permanent Page Access Token)
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "")
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "")

# Pexels API Key (বিনামূল্যে 9:16 ব্যাকগ্রাউন্ড ভিডিওর জন্য https://www.pexels.com/api/)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")

# Edge-TTS ভয়েস সেটিংস (ন্যাচারাল বাংলা পুরুষ ও নারী কণ্ঠ)
# বিকল্প: 'bn-BD-PradeepNeural' (পুরুষ) অথবা 'bn-BD-NabanitaNeural' (নারী)
TTS_VOICE = os.getenv("TTS_VOICE", "bn-BD-PradeepNeural")
TTS_RATE = "+0%"  # গতি স্বাভাবিক রাখতে
TTS_PITCH = "+0Hz"

# ব্র্যান্ডিং ও মনিটাইজেশন সেটিংস
BRAND_LOGO_PATH = ASSETS_DIR / "logo.png"
BRAND_NAME = os.getenv("BRAND_NAME", "হাসির মেলা BD")
FONT_PATH = FONTS_DIR / "Kalpurush.ttf"

# FFmpeg কালার ফিল্টার (ফেইসবুকের "Unoriginal Content" পলিসি এড়াতে ডিজিটাল ফিঙ্গারপ্রিন্ট পরিবর্তন)
COLOR_FILTER = "eq=contrast=1.06:brightness=0.03:saturation=1.12"
