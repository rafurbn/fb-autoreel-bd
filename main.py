"""
main.py - সম্পূর্ণ স্বয়ংক্রিয় পাইপলাইন নির্বাহক
কমান্ড-লাইন থেকে একবার চালানো বা APScheduler দিয়ে প্রতিদিন নির্দিষ্ট সময়ে রান করার সুবিধা
"""

import sys
import argparse
import datetime
from pathlib import Path
import logging
import re

from config import OUTPUT_DIR, BRAND_LOGO_PATH, MUSIC_DIR
from gemini_agent import generate_viral_reel_script, CATEGORY_LABELS
from tts_engine import make_voiceover_sync
from media_fetcher import fetch_vertical_background_video
from video_editor import render_final_monetized_reel, build_subtitle_events, get_media_duration
from fb_uploader import upload_reel_to_facebook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("AutoReelBD")

_BG_MUSIC_NAMES = ("sample_bg.mp3", "sample_bg.m4a", "sample_bg.wav", "background.mp3")

def find_bg_music() -> Path | None:
    """assets/music ফোল্ডারে যেকোনো নামে থাকা ব্যাকগ্রাউন্ড মিউজিক খুঁজে; না থাকলে None"""
    for name in _BG_MUSIC_NAMES:
        candidate = MUSIC_DIR / name
        if candidate.is_file():
            return candidate
    if MUSIC_DIR.is_dir():
        for candidate in sorted(MUSIC_DIR.iterdir()):
            if candidate.is_file() and candidate.suffix.lower() in {".mp3", ".m4a", ".wav", ".aac"}:
                return candidate
    logger.warning(f"ব্যাকগ্রাউন্ড মিউজিক পাওয়া যায়নি ({MUSIC_DIR}) — মিউজিক ছাড়াই রেন্ডার হবে।")
    return None

_VTT_TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$")

def _vtt_to_seconds(value: str) -> float:
    match = _VTT_TIME_RE.match(value.strip())
    if not match:
        raise ValueError(f"অবৈধ VTT টাইমস্ট্যাম্প: {value}")
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000

def load_vtt_events(vtt_path: Path) -> list:
    """TTS থেকে তৈরি .vtt ফাইল পড়ে (শুরু, শেষ, লেখা) tuples দেয়"""
    if not vtt_path.is_file():
        return []
    events = []
    times = None
    for line in vtt_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "-->" in line:
            parts = [part.strip() for part in line.split("-->")]
            try:
                times = (_vtt_to_seconds(parts[0]), _vtt_to_seconds(parts[1]))
            except (IndexError, ValueError):
                times = None
        elif times and line and not line.isdigit() and line != "WEBVTT":
            events.append((times[0], times[1], line))
            times = None
    return events

def execute_daily_reel_pipeline(dry_run=False, category="funny", offline=False):
    """এক ক্লিকে সম্পূর্ণ ভিডিও জেনারেশন ও পাবলিশ প্রক্রিয়া সম্পন্ন করে"""
    today_tag = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("==================================================")
    logger.info(f"দৈনিক অটোমেটেড ভিডিও প্রসেস শুরু: {today_tag} (category={category}, offline={offline})")
    logger.info("==================================================")

    # ধাপ ১: স্ক্রিপ্ট তৈরি
    script_data = generate_viral_reel_script(category=category, offline=offline)
    title = script_data.get("title", "Bangla Reel")
    spoken_text = script_data.get("spoken_script")
    search_prompt = script_data.get("video_search_prompt", "smiling person vertical")
    subtitles = script_data.get("subtitles", [])
    caption = script_data.get("caption", title)
    hashtags = script_data.get("hashtags", [])

    if not spoken_text or not str(spoken_text).strip():
        logger.error("স্ক্রিপ্টে ভয়েসওভার টেক্সট নেই, পাইপলাইন বন্ধ করা হলো।")
        return False

    # ফাইল পাথ নির্ধারণ
    audio_path = OUTPUT_DIR / f"voice_{today_tag}.mp3"
    vtt_path = OUTPUT_DIR / f"voice_{today_tag}.vtt"
    raw_video_path = OUTPUT_DIR / f"raw_video_{today_tag}.mp4"
    final_video_path = OUTPUT_DIR / f"final_reel_{today_tag}.mp4"
    bg_music = find_bg_music()
    logo_path = BRAND_LOGO_PATH if BRAND_LOGO_PATH.is_file() else None
    if logo_path is None:
        logger.warning(f"লোগো পাওয়া যায়নি ({BRAND_LOGO_PATH}) — ওয়াটারমার্ক ছাড়াই রেন্ডার হবে।")

    # ধাপ ২: ভয়েস তৈরি (Edge-TTS) — সাথে আসল টাইমিং
    logger.info("ধাপ ২: বাংলা ভয়েসওভার প্রস্তুত করা হচ্ছে...")
    tts_success = make_voiceover_sync(spoken_text, audio_path, output_vtt_path=vtt_path)
    if not tts_success:
        logger.error("TTS সম্পন্ন করা যায়নি, পাইপলাইন স্থগিত!")
        return False

    # ধাপ ৩: ব্যাকগ্রাউন্ড ভিডিও আনা
    logger.info("ধাপ ৩: হাই-কোয়ালিটি ব্যাকগ্রাউন্ড ভিডিও ডাউনলোড...")
    fetch_success = fetch_vertical_background_video(search_prompt, raw_video_path)
    if not fetch_success:
        logger.error("ভিডিও ডাউনলোড ব্যর্থ!")
        return False

    # ধাপ ৪: এডিটিং, সাবটাইটেল ও ব্র্যান্ডিং (FFmpeg)
    logger.info("ধাপ ৪: FFmpeg দিয়ে সাবটাইটেল, ওয়াটারমার্ক ও কালার ফিল্টার রেন্ডারিং...")
    subtitle_events = load_vtt_events(vtt_path)
    audio_duration = get_media_duration(audio_path)
    if audio_duration <= 0:
        audio_duration = 35.0
    if subtitle_events:
        logger.info(f"TTS টাইমিং থেকে {len(subtitle_events)}টি সাবটাইটেল ইভেন্ট পাওয়া গেছে।")
    else:
        logger.warning("TTS টাইমিং পাওয়া যায়নি; সাবটাইটেল অডিও দৈর্ঘ্য অনুযায়ী ভাগ করা হবে।")

    # আসল টাইমিং থাকলে সেটাই যাবে; না থাকলে স্ক্রিপ্টের লাইন অডিও দৈর্ঘ্যের মধ্যে ভাগ হবে
    subtitle_lines = (
        [{"text": text} for _, _, text in subtitle_events] if subtitle_events else subtitles
    )

    render_success = render_final_monetized_reel(
        raw_video_path=raw_video_path,
        voice_audio_path=audio_path,
        subtitles_list=subtitle_lines,
        output_video_path=final_video_path,
        bg_music_path=bg_music,
        logo_path=logo_path,
        subtitle_events=subtitle_events,
        subtitle_fallback_span=(0.0, audio_duration),
    )

    if not render_success:
        logger.error("ভিডিও রেন্ডারিং ফেইল করেছে!")
        return False

    logger.info(f"ইউনিক মনিটাইজেবল ভিডিও রেডি: {final_video_path}")

    # ধাপ ৫: ফেইসবুকে পোস্ট
    if dry_run:
        logger.info("[DRY RUN MODE]: ফেইসবুকে আপলোড স্কিপ করা হলো। ভিডিও আউটপুট ফোল্ডারে দেখতে পারেন।")
        return True

    logger.info("ধাপ ৫: ফেইসবুক পেজে স্বয়ংক্রিয় আপলোড শুরু হচ্ছে...")
    uploaded = upload_reel_to_facebook(final_video_path, caption=caption, hashtags=hashtags)

    if uploaded:
        logger.info("অভিনন্দন! আজকের ভিডিও ফেইসবুকে সফলভাবে লাইভ হয়েছে!")
        return True

    logger.error("ফেইসবুক আপলোড সম্পন্ন হয়নি। দয়া করে টোকেন ও পেজ আইডি চেক করুন।")
    return False

def schedule_mode(run_hour=9, run_minute=0, category="funny"):
    """সার্ভারে APScheduler দিয়ে প্রতিদিন নির্দিষ্ট সময়ে রান করার অপশন (এশিয়া/ঢাকা সময়)"""
    from apscheduler.schedulers.blocking import BlockingScheduler
    scheduler = BlockingScheduler(timezone="Asia/Dhaka")
    logger.info(
        f"শিডিউলার চালু হয়েছে! প্রতিদিন বাংলাদেশ সময় {run_hour:02d}:{run_minute:02d}-এ "
        f"({category}) ভিডিও পোস্ট হবে..."
    )
    scheduler.add_job(
        execute_daily_reel_pipeline, 'cron',
        hour=run_hour, minute=run_minute, kwargs={"category": category},
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("শিডিউলার বন্ধ করা হয়েছে।")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FB AutoReel BD Automation Runner")
    parser.add_argument("--test", action="store_true", help="টেস্ট মোড: ভিডিও বানাবে কিন্তু ফেসবুকে পোস্ট করবে না")
    parser.add_argument("--schedule", action="store_true", help="সার্বক্ষণিক শিডিউলার মোডে চালানো")
    parser.add_argument("--hour", type=int, default=9, help="প্রতিদিন পোস্ট করার নির্দিষ্ট ঘণ্টা (0-23)")
    parser.add_argument("--minute", type=int, default=0, help="প্রতিদিন পোস্ট করার মিনিট (0-59)")
    parser.add_argument(
        "--category", type=str.lower, default="funny", choices=list(CATEGORY_LABELS),
        help=f"স্ক্রিপ্টের ধরন (ডিফল্ট: funny)। অপশন: {', '.join(CATEGORY_LABELS)}",
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="Gemini না ডেকে স্যাম্পল স্ক্রিপ্ট দিয়ে টেস্ট (ফ্রি কোটা বাঁচায়)",
    )

    args = parser.parse_args()

    if args.schedule:
        schedule_mode(run_hour=args.hour, run_minute=args.minute, category=args.category)
    else:
        try:
            success = execute_daily_reel_pipeline(
                dry_run=args.test, category=args.category, offline=args.offline
            )
        except Exception:
            logger.exception("পাইপলাইন অপ্রত্যাশিতভাবে ব্যর্থ হয়েছে")
            success = False
        # GitHub Actions/CI-এ আসল ব্যর্থতা যেন ধরা পড়ে
        sys.exit(0 if success else 1)
