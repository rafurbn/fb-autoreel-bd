"""
fb_uploader.py - মেটা অফিসিয়াল Graph API (v21.0) দিয়ে সরাসরি ফেইসবুক পেজে রিলস আপলোড
Permanent Page Access Token ব্যবহার করে যাতে মেয়াদ শেষ না হয়
"""

import datetime
import json
import logging
from pathlib import Path
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from config import (
    FB_PAGE_ACCESS_TOKEN,
    FB_PAGE_ID,
    FB_SCHEDULE_TIME,
    FB_SCHEDULE_TIMEZONE,
)

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
MIN_SCHEDULE_LEAD_MINUTES = 10
_IMMEDIATE_TOKENS = {"", "now", "off", "none", "false", "0"}


def _resolve_timezone(tz_name: str) -> datetime.tzinfo:
    """টাইমজোন অবজেক্ট তৈরি করে; সিস্টেমে tzdata না থাকলে Asia/Dhaka-র জন্য UTC+6 দেয়।"""
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        if tz_name == "Asia/Dhaka":
            return datetime.timezone(datetime.timedelta(hours=6), name="Asia/Dhaka")
        raise


def compute_next_schedule_timestamp(
    schedule_time: str,
    timezone_name: str = "Asia/Dhaka",
    now: datetime.datetime | None = None,
    min_lead_minutes: int = MIN_SCHEDULE_LEAD_MINUTES,
) -> tuple[int, datetime.datetime]:
    """
    "HH:MM" (২৪-ঘণ্টা) ফরম্যাট থেকে পরবর্তী বৈধ শিডিউল সময়ের Unix timestamp বের করে।
    Meta Graph API অনুযায়ী scheduled_publish_time অন্তত ১০ মিনিট পরের হতে হয়।
    """
    raw = (schedule_time or "").strip()
    parts = raw.split(":")
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
        raise ValueError(f"অবৈধ শিডিউল সময় '{schedule_time}' (সঠিক ফরম্যাট HH:MM, যেমন 07:45)")

    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"অবৈধ ঘণ্টা/মিনিট: '{schedule_time}'")

    tz = _resolve_timezone(timezone_name)
    current = (
        datetime.datetime.now(tz)
        if now is None
        else (now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz))
    )

    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    min_allowed = current + datetime.timedelta(minutes=min_lead_minutes)
    while target < min_allowed:
        target += datetime.timedelta(days=1)

    return int(target.timestamp()), target


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
    """ভিডিও আপলোড সম্পন্ন হওয়া পর্যন্ত অপেক্ষা করে।"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = requests.get(
                f"{BASE_URL}/{video_id}",
                params={"fields": "status", "access_token": FB_PAGE_ACCESS_TOKEN},
                timeout=20,
            )
            if resp.ok:
                status = resp.json().get("status") or {}
                state = status.get("video_status")
                upload_state = (status.get("uploading_phase") or {}).get("status")
                logger.info(
                    f"ভিডিও আপলোড স্টেট: video_status={state}, uploading_phase={upload_state}"
                )

                if state in {"ready", "upload_complete"} or upload_state == "complete":
                    return True
                if state in {"error", "upload_failed", "expired"} or upload_state == "error":
                    logger.error(f"ফেইসবুক ভিডিও আপলোড/প্রসেসিং ফেইল করেছে: {status}")
                    return False
            else:
                _log_graph_error("স্টেট চেক", resp)
                if resp.status_code in (400, 401, 403):
                    return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"ভিডিও স্টেট চেক করা যাচ্ছে না: {e}")

        time.sleep(interval)

    logger.error(f"ভিডিও {timeout} সেকেন্ডেও আপলোড সম্পন্ন হয়নি।")
    return False


def upload_reel_to_facebook(
    video_path: Path,
    caption: str,
    hashtags: list = None,
    schedule_time: str | None = None,
    schedule_timezone: str | None = None,
) -> bool:
    """
    ফেইসবুক পেজে সম্পূর্ণ ভিডিও রিলস হিসেবে আপলোড করে
    ধাপ ১: ইনিশিয়ালাইজ রিল আপলোড সেশন
    ধাপ ২: বাইনারি ভিডিও ডাটা পাঠানো
    ধাপ ৩: ক্যাপশন সহ পাবলিশ বা নির্দিষ্ট সময়ে শিডিউল সম্পন্ন করা
    """
    if not FB_PAGE_ID or not FB_PAGE_ACCESS_TOKEN:
        logger.error("ফেইসবুক ক্রেডেনশিয়াল নেই! FB_PAGE_ID ও FB_PAGE_ACCESS_TOKEN .env ফাইলে প্রদান করুন।")
        return False

    video_path = Path(video_path)
    if not video_path.is_file() or video_path.stat().st_size == 0:
        logger.error(f"আপলোডের জন্য বৈধ ভিডিও ফাইল পাওয়া যায়নি: {video_path}")
        return False

    clean_caption = (caption or "").strip()
    normalized_tags = []
    for tag in (hashtags or []):
        t = str(tag).strip()
        if t:
            normalized_tags.append(t if t.startswith("#") else f"#{t}")
    tags_str = " ".join(normalized_tags) if normalized_tags else "#reelsfb #viral"
    full_description = f"{clean_caption}\n\n{tags_str}".strip()

    effective_schedule = FB_SCHEDULE_TIME if schedule_time is None else schedule_time
    effective_tz = FB_SCHEDULE_TIMEZONE if schedule_timezone is None else schedule_timezone
    normalized_schedule = (effective_schedule or "").strip().lower()

    scheduled_ts = None
    scheduled_dt = None
    if normalized_schedule not in _IMMEDIATE_TOKENS:
        try:
            scheduled_ts, scheduled_dt = compute_next_schedule_timestamp(
                effective_schedule,
                timezone_name=effective_tz,
            )
        except (ValueError, ZoneInfoNotFoundError) as exc:
            logger.warning(f"শিডিউল সেটিং অকার্যকর ({exc}) — সাথে সাথেই পাবলিশ করা হবে।")

    file_size = video_path.stat().st_size
    logger.info(f"ফেইসবুক পেজে রিলস আপলোড শুরু... ফাইলের সাইজ: {file_size / (1024 * 1024):.2f} MB")

    try:
        # ধাপ ১: আপলোড সেশন শুরু
        init_url = f"{BASE_URL}/{FB_PAGE_ID}/video_reels"
        init_payload = {
            "upload_phase": "start",
            "access_token": FB_PAGE_ACCESS_TOKEN,
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
            "file_size": str(file_size),
        }
        # বড় ফাইল হলে রিড টাইমআউট বাড়ান (হিসাব: প্রতি MB-তে প্রায় ২ সেকেন্ড)
        read_timeout = max(120, int(file_size / (512 * 1024)))
        with open(video_path, "rb") as video_file:
            r_upload = requests.post(
                upload_url,
                headers=headers,
                data=video_file,
                timeout=(20, read_timeout),
            )
        if not r_upload.ok:
            _log_graph_error("ভিডিও আপলোড", r_upload)
            return False

        logger.info("ভিডিও ফাইল ফেইসবুক সার্ভারে সফলভাবে পৌঁছেছে!")

        if not _wait_until_uploaded(video_id):
            return False

        # ধাপ ৩: রিলস পাবলিশ বা শিডিউল করা
        publish_url = f"{BASE_URL}/{FB_PAGE_ID}/video_reels"
        publish_payload = {
            "upload_phase": "finish",
            "access_token": FB_PAGE_ACCESS_TOKEN,
            "video_id": video_id,
            "description": full_description,
        }
        if scheduled_ts is not None and scheduled_dt is not None:
            publish_payload["video_state"] = "SCHEDULED"
            publish_payload["scheduled_publish_time"] = scheduled_ts
            logger.info(
                f"রিলসটি {scheduled_dt.strftime('%Y-%m-%d %I:%M %p %Z')} "
                f"(timestamp={scheduled_ts})-এর জন্য শিডিউল করা হচ্ছে..."
            )
        else:
            publish_payload["video_state"] = "PUBLISHED"

        r_publish = requests.post(publish_url, data=publish_payload, timeout=60)
        if not r_publish.ok:
            _log_graph_error("রিলস পাবলিশ", r_publish)
            return False
        res_data = r_publish.json()

        if res_data.get("success") is True:
            if scheduled_ts is not None and scheduled_dt is not None:
                logger.info(
                    f"অভিনন্দন! আপনার রিলসটি {scheduled_dt.strftime('%Y-%m-%d %I:%M %p %Z')}-এ "
                    "প্রকাশের জন্য ফেইসবুকে শিডিউল হয়েছে!"
                )
            else:
                logger.info("অভিনন্দন! আপনার ভিডিওটি ফেইসবুকে সফলভাবে রিলস হিসেবে পোস্ট হয়েছে!")
            return True

        logger.error(f"পাবলিশ সফল হয়নি। রেসপন্স: {json.dumps(res_data, ensure_ascii=False)[:500]}")
        return False

    except requests.exceptions.RequestException as e:
        logger.error(f"ফেসবুক এপিআই আপলোড ব্যর্থ: {str(e)}")
        if e.response is not None:
            _log_graph_error("রিকোয়েস্ট", e.response)
        return False
