"""
main.py - সম্পূর্ণ স্বয়ংক্রিয় পাইপলাইন নির্বাহক
কমান্ড-লাইন থেকে একবার চালানো বা APScheduler দিয়ে প্রতিদিন নির্দিষ্ট সময়ে রান করার সুবিধা
"""

import sys
import argparse
import datetime
from pathlib import Path
import logging

from config import OUTPUT_DIR, BRAND_LOGO_PATH, MUSIC_DIR
from gemini_agent import generate_viral_reel_script
from tts_engine import make_voiceover_sync
from media_fetcher import fetch_vertical_background_video
from video_editor import render_final_monetized_reel
from fb_uploader import upload_reel_to_facebook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("AutoReelBD")

def execute_daily_reel_pipeline(dry_run=False):
    """এক ক্লিকে সম্পূর্ণ ভিডিও জেনারেশন ও পাবলিশ প্রক্রিয়া সম্পন্ন করে"""
    today_tag = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("==================================================")
    logger.info(f"দৈনিক অটোমেটেড ভিডিও প্রসেস শুরু: {today_tag}")
    logger.info("==================================================")

    # ধাপ ১: স্ক্রিপ্ট তৈরি
    script_data = generate_viral_reel_script(category="funny")
    title = script_data.get("title", "Bangla Funny Reel")
    spoken_text = script_data.get("spoken_script")
    search_prompt = script_data.get("video_search_prompt", "smiling person vertical")
    subtitles = script_data.get("subtitles", [])
    caption = script_data.get("caption", title)
    hashtags = script_data.get("hashtags", [])

    # ফাইল পাথ নির্ধারণ
    audio_path = OUTPUT_DIR / f"voice_{today_tag}.mp3"
    raw_video_path = OUTPUT_DIR / f"raw_video_{today_tag}.mp4"
    final_video_path = OUTPUT_DIR / f"final_reel_{today_tag}.mp4"
    bg_music = MUSIC_DIR / "sample_bg.mp3"

    # ধাপ ২: ভয়েস তৈরি (Edge-TTS)
    logger.info("ধাপ ২: বাংলা ভয়েসওভার প্রস্তুত করা হচ্ছে...")
    tts_success = make_voiceover_sync(spoken_text, audio_path)
    if not tts_success:
        logger.error("TTS সম্পন্ন করা যায়নি, পাইপলাইন স্থগিত!")
        return False

    # ধাপ ৩: ব্যাকগ্রাউন্ড ভিডিও আনা
    logger.info("ধাপ ৩: হাই-কোয়ালিটি ব্যাকগ্রাউন্ড ভিডিও ডাউনলোড...")
    fetch_success = fetch_vertical_background_video(search_prompt, raw_video_path)
    if not fetch_success:
        logger.error("ভিডিও ডাউনলোড ব্যর্থ!")
        return False

    # ধাপ ৪: এডিটিং, সাবটাইটেল ও ব্র্যান্ডিং (FFmpeg)
    logger.info("ধাপ ৪: FFmpeg দিয়ে সাবটাইটেল, ওয়াটারমার্ক ও কালার ফিল্টার রেন্ডারিং...")
    render_success = render_final_monetized_reel(
        raw_video_path=raw_video_path,
        voice_audio_path=audio_path,
        subtitles_list=subtitles,
        output_video_path=final_video_path,
        bg_music_path=bg_music if bg_music.exists() else None,
        logo_path=BRAND_LOGO_PATH if BRAND_LOGO_PATH.exists() else None
    )

    if not render_success:
        logger.error("ভিডিও রেন্ডারিং ফেইল করেছে!")
        return False

    logger.info(f"ইউনিক মনিটাইজেবল ভিডিও রেডি: {final_video_path}")

    # ধাপ ৫: ফেইসবুকে পোস্ট
    if dry_run:
        logger.info("[DRY RUN MODE]: ফেইসবুকে আপলোড স্কিপ করা হলো। ভিডিও আউটপুট ফোল্ডারে দেখতে পারেন।")
        return True

    logger.info("ধাপ ৫: ফেইসবুক পেজে স্বয়ংক্রিয় আপলোড শুরু হচ্ছে...")
    uploaded = upload_reel_to_facebook(final_video_path, caption=caption, hashtags=hashtags)

    if uploaded:
        logger.info("অভিনন্দন! আজকের ভিডিও ফেইসবুকে সফলভাবে লাইভ হয়েছে!")
        return True
    else:
        logger.warning("ফেইসবুক আপলোড সম্পন্ন হয়নি। দয়া করে টোকেন ও পেজ আইডি চেক করুন।")
        return False

def schedule_mode(run_hour=9, run_minute=0):
    """সার্ভারে APScheduler দিয়ে প্রতিদিন নির্দিষ্ট সময়ে রান করার অপশন"""
    from apscheduler.schedulers.blocking import BlockingScheduler
    scheduler = BlockingScheduler()
    logger.info(f"শিডিউলার চালু হয়েছে! প্রতিদিন বাংলাদেশ সময় সকাল {run_hour:02d}:{run_minute:02d}-এ ভিডিও পোস্ট হবে...")
    scheduler.add_job(execute_daily_reel_pipeline, 'cron', hour=run_hour, minute=run_minute)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("শিডিউলার বন্ধ করা হয়েছে।")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FB AutoReel BD Automation Runner")
    parser.add_argument("--test", action="store_true", help="টেস্ট মোড: ভিডিও বানাবে কিন্তু ফেসবুকে পোস্ট করবে না")
    parser.add_argument("--schedule", action="store_true", help="সার্বক্ষণিক শিডিউলার মোডে চালানো")
    parser.add_argument("--hour", type=int, default=9, help="প্রতিদিন পোস্ট করার নির্দিষ্ট ঘণ্টা (0-23)")
    parser.add_argument("--minute", type=int, default=0, help="প্রতিদিন পোস্ট করার মিনিট (0-59)")

    args = parser.parse_args()

    if args.schedule:
        schedule_mode(run_hour=args.hour, run_minute=args.minute)
    else:
        execute_daily_reel_pipeline(dry_run=args.test)
