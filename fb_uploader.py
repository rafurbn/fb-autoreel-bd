"""
fb_uploader.py - মেটা অফিসিয়াল Graph API (v21.0) দিয়ে সরাসরি ফেইসবুক পেজে রিলস আপলোড
Permanent Page Access Token ব্যবহার করে যাতে মেয়াদ শেষ না হয়
"""

import requests
import json
from pathlib import Path
import logging
from config import FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

def upload_reel_to_facebook(video_path: Path, caption: str, hashtags: list = None) -> bool:
    """
    ফেইসবুক পেজে সম্পূর্ণ ভিডিও রিলস হিসেবে আপলোড করে
    ধাপ ১: ইনিশিয়ালাইজ রিল আপলোড সেশন
    ধাপ ২: বাইনারি ভিডিও ডাটা পাঠানো
    ধাপ ৩: ক্যাপশন সহ পাবলিশ সম্পন্ন করা
    """
    if not FB_PAGE_ID or not FB_PAGE_ACCESS_TOKEN:
        logger.error("ফেইসবুক ক্রেডেনশিয়াল নেই! FB_PAGE_ID ও FB_PAGE_ACCESS_TOKEN .env ফাইলে প্রদান করুন।")
        return False

    tags_str = " ".join(hashtags) if hashtags else "#reelsfb #viral"
    full_description = f"{caption}\n\n{tags_str}"

    file_size = video_path.stat().st_size
    logger.info(f"ফেইসবুক পেজে রিলস আপলোড শুরু... ফাইলের সাইজ: {file_size / (1024*1024):.2f} MB")

    try:
        # ধাপ ১: আপলোড সেশন শুরু
        init_url = f"{BASE_URL}/{FB_PAGE_ID}/video_reels"
        init_payload = {
            "upload_phase": "start",
            "access_token": FB_PAGE_ACCESS_TOKEN
        }
        r_init = requests.post(init_url, data=init_payload, timeout=20)
        r_init.raise_for_status()
        init_data = r_init.json()

        video_id = init_data.get("video_id")
        upload_url = init_data.get("upload_url")

        if not video_id or not upload_url:
            logger.error(f"সেশন ইনিট ফেইল: {init_data}")
            return False

        logger.info(f"আপলোড সেশন অনুমোদিত! Video ID: {video_id}")

        # ধাপ ২: ভিডিও ডাটা স্ট্রিম পাঠানো
        headers = {
            "Authorization": f"OAuth {FB_PAGE_ACCESS_TOKEN}",
            "offset": "0",
            "file_size": str(file_size)
        }
        with open(video_path, "rb") as video_file:
            r_upload = requests.post(upload_url, headers=headers, data=video_file, timeout=120)
            r_upload.raise_for_status()

        logger.info("ভিডিও ফাইল ফেইসবুক সার্ভারে সফলভাবে পৌঁছেছে!")

        # ধাপ ৩: রিলস পাবলিশ করা
        publish_url = f"{BASE_URL}/{FB_PAGE_ID}/video_reels"
        publish_payload = {
            "upload_phase": "finish",
            "access_token": FB_PAGE_ACCESS_TOKEN,
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": full_description
        }
        r_publish = requests.post(publish_url, data=publish_payload, timeout=20)
        r_publish.raise_for_status()
        res_data = r_publish.json()

        if res_data.get("success"):
            logger.info("অভিনন্দন! আপনার ভিডিওটি ফেইসবুকে সফলভাবে রিলস হিসেবে পোস্ট হয়েছে!")
            return True
        else:
            logger.warning(f"পাবলিশ রেসপন্স সন্দেহজনক: {res_data}")
            return True

    except requests.exceptions.RequestException as e:
        logger.error(f"ফেসবুক এপিআই আপলোড ব্যর্থ: {str(e)}")
        if hasattr(e, "response") and e.response:
            logger.error(f"মেটা সার্ভার মেসেজ: {e.response.text}")
        return False
