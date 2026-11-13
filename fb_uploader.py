"""
fb_uploader.py - মেটা অফিসিয়াল Graph API (v21.0) দিয়ে সরাসরি ফেইসবুক পেজে রিলস আপলোড
Permanent Page Access Token ব্যবহার করে যাতে মেয়াদ শেষ না হয়
"""

import requests
import json
import time
from pathlib import Path
import logging
from config import FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

def _graph_error(resp: requests.Response) -> dict:
    """মেটা সার্ভারের আসল error message/code বের করে"""
    try:
        return resp.json().get("error", {}) or {}
    except ValueError:
        return {"message": resp.text[:500]}

def _log_graph_error(step: str, resp: requests.Response) -> None:
    error = _graph_error(resp)
    logger.error(
        f"ফেইসবুক {step} ব্যর্থ (HTTP {resp.status_code}) | "
        f"code={error.get('code')} subcode={error.get('error_subcode')} "
        f"type={error.get('type')} | {error.get('message')}"
    )

def _wait_until_uploaded(video_id: str, timeout: int = 300, interval: int = 5) -> bool:
    """ভিডিও আপলোড সম্পন্ন হওয়া পর্যন্ত অপেক্ষা করে; Meta-র upload_complete অবস্থাও সম্পন্ন।"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = requests.get(
                f"{BASE_URL}/{video_id}",
                params={"fields": "status", "access_token": FB_PAGE_ACCESS_TOKEN},
                timeout=20,
            )
            if resp.ok:
                status = (resp.json().get("status") or {})
                state = status.get("video_status")
                logger.info(f"ভিডিও আপলোড স্টেট: {state}")
                if state in {"ready", "upload_complete"}:
                    return True
                if state in {"error", "upload_failed", "expired"}:
                    logger.error(f"ফেইসবুক ভিডিও আপলোড/প্রসেসিং ফেইল করেছে: {status}")
                    return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"ভিডিও স্টেট চেক করা যাচ্ছে না: {e}")
        time.sleep(interval)
    logger.error(f"ভিডিও {timeout} সেকেন্ডেও আপলোড সম্পন্ন হয়নি।")
    return False

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
        if not r_init.ok:
            _log_graph_error("সেশন ইনিট", r_init)
            return False
        init_data = r_init.json()

        video_id = init_data.get("video_id")
        upload_url = init_data.get("upload_url")

        if not video_id or not upload_url:
            logger.error(f"সেশন ইনিট ফেইল (video_id/upload_url নেই): {init_data}")
            return False

        logger.info(f"আপলোড সেশন অনুমোদিত! Video ID: {video_id}")

        # ধাপ ২: ভিডিও ডাটা স্ট্রিম পাঠানো
        headers = {
            "Authorization": f"OAuth {FB_PAGE_ACCESS_TOKEN}",
            "offset": "0",
            "file_size": str(file_size)
        }
        # বড় ফাইল হলে রিড টাইমআউট বাড়ান (হিসাব: প্রতি MB-তে প্রায় ২ সেকেন্ড)
        read_timeout = max(120, int(file_size / (512 * 1024)))
        with open(video_path, "rb") as video_file:
            r_upload = requests.post(upload_url, headers=headers, data=video_file, timeout=(20, read_timeout))
        if not r_upload.ok:
            _log_graph_error("ভিডিও আপলোড", r_upload)
            return False

        logger.info("ভিডিও ফাইল ফেইসবুক সার্ভারে সফলভাবে পৌঁছেছে!")

        # Meta upload_complete-কে upload শেষ হিসেবে জানায়; এরপর finish ধাপ প্রকাশনা শুরু করে।
        if not _wait_until_uploaded(video_id):
            return False

        # ধাপ ৩: রিলস পাবলিশ করা
        publish_url = f"{BASE_URL}/{FB_PAGE_ID}/video_reels"
        publish_payload = {
            "upload_phase": "finish",
            "access_token": FB_PAGE_ACCESS_TOKEN,
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": full_description
        }
        r_publish = requests.post(publish_url, data=publish_payload, timeout=60)
        if not r_publish.ok:
            _log_graph_error("রিলস পাবলিশ", r_publish)
            return False
        res_data = r_publish.json()

        if res_data.get("success") is True:
            logger.info("অভিনন্দন! আপনার ভিডিওটি ফেইসবুকে সফলভাবে রিলস হিসেবে পোস্ট হয়েছে!")
            return True

        # success না পেলে এটা ফেইলিউরই — আগে ভুল করে True রিটার্ন করত
        logger.error(f"পাবলিশ সফল হয়নি। রেসপন্স: {json.dumps(res_data, ensure_ascii=False)[:500]}")
        return False

    except requests.exceptions.RequestException as e:
        logger.error(f"ফেসবুক এপিআই আপলোড ব্যর্থ: {str(e)}")
        if e.response is not None:
            _log_graph_error("রিকোয়েস্ট", e.response)
        return False
