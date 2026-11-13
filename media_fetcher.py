"""Pixabay/Pexels API অথবা ব্যাকআপ থেকে ব্যাকগ্রাউন্ড ভিডিও সংগ্রহ।"""

import requests
import random
import subprocess
from pathlib import Path
import logging
from config import PIXABAY_API_KEY, PEXELS_API_KEY

logger = logging.getLogger(__name__)

def _download_video(url: str, target_path: Path, timeout: int) -> None:
    """ডাউনলোডটি সফল বলার আগে HTTP response ও MP4 ফাইল যাচাই করে"""
    temp_path = target_path.with_name(f"{target_path.name}.part")
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with open(temp_path, "wb") as video_file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        video_file.write(chunk)

        with open(temp_path, "rb") as video_file:
            header = video_file.read(64)
        if len(header) < 12 or b"ftyp" not in header:
            raise ValueError("ডাউনলোড করা ফাইলটি বৈধ MP4 ভিডিও নয়")

        temp_path.replace(target_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

def _select_pixabay_video(hits: list) -> dict | None:
    """Pixabay ফলাফল থেকে portrait-কে অগ্রাধিকার দিয়ে একটি MP4 বেছে নেয়"""
    available_videos = []
    vertical_videos = []
    for hit in hits:
        available = hit.get("videos", {})
        candidates = [
            video for video in available.values()
            if video.get("url")
            and video.get("width", 0) > 0
            and video.get("height", 0) > 0
        ]
        if candidates:
            portrait_candidates = [
                video for video in candidates if video["width"] <= video["height"]
            ]
            best_video = max(
                portrait_candidates or candidates,
                key=lambda video: video["width"] * video["height"]
            )
            available_videos.append(best_video)
            if portrait_candidates:
                vertical_videos.append(best_video)
    preferred_videos = vertical_videos or available_videos
    return random.choice(preferred_videos) if preferred_videos else None

def fetch_vertical_background_video(search_query: str, target_path: Path) -> bool:
    """
    Pixabay অগ্রাধিকার দিয়ে উল্লম্ব ব্যাকগ্রাউন্ড ভিডিও ডাউনলোড করে
    """
    if PIXABAY_API_KEY:
        try:
            for pixabay_query in dict.fromkeys((search_query, "vertical background")):
                logger.info(f"Pixabay-এ উল্লম্ব ব্যাকগ্রাউন্ড ভিডিও খোঁজা হচ্ছে: '{pixabay_query}'")
                response = requests.get(
                    "https://pixabay.com/api/videos/",
                    params={
                        "key": PIXABAY_API_KEY,
                        "q": pixabay_query,
                        "per_page": 20,
                        "safesearch": "true"
                    },
                    timeout=15
                )
                response.raise_for_status()
                video = _select_pixabay_video(response.json().get("hits", []))
                if video:
                    _download_video(video["url"], target_path, timeout=30)
                    logger.info(f"Pixabay ভিডিও সংরক্ষণ সম্পন্ন: {target_path}")
                    return True
            logger.warning("Pixabay-এ portrait ভিডিও পাওয়া যায়নি; অন্য উৎস চেষ্টা করা হচ্ছে।")
        except (requests.RequestException, OSError, ValueError) as e:
            logger.error(f"Pixabay API ত্রুটি: {str(e)}")
    else:
        logger.warning("PIXABAY_API_KEY পাওয়া যায়নি।")

    if not PEXELS_API_KEY:
        logger.warning("PEXELS_API_KEY পাওয়া যায়নি; ব্যাকআপ ভিডিও উৎস চেষ্টা করা হচ্ছে...")
        return download_fallback_video(target_path)

    headers = {
        "Authorization": PEXELS_API_KEY
    }

    params = {
        "query": search_query,
        "orientation": "portrait",
        "per_page": 5,
        "size": "medium"
    }

    try:
        logger.info(f"Pexels-এ উল্লম্ব ব্যাকগ্রাউন্ড ভিডিও খোঁজা হচ্ছে: '{search_query}'")
        res = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=15)
        res.raise_for_status()
        data = res.json()

        videos = data.get("videos", [])
        if not videos:
            logger.warning("নির্দিষ্ট বিষয়ে ভিডিও মেলেনি, সাধারণ ট্রেন্ডিং ভিডিও নেওয়া হচ্ছে...")
            params["query"] = "nature relaxation vertical background"
            res = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=15)
            res.raise_for_status()
            videos = res.json().get("videos", [])

        if not videos:
            return download_fallback_video(target_path)

        chosen_video = random.choice(videos)
        video_files = chosen_video.get("video_files", [])

        # 1080x1920 অথবা 720x1280 vertical ফাইল বাছাই
        hd_file = None
        for vf in video_files:
            if vf.get("width", 0) <= vf.get("height", 0):  # উল্লম্ব রেশিও
                hd_file = vf.get("link")
                if vf.get("quality") == "hd":
                    break

        if not hd_file and video_files:
            hd_file = video_files[0].get("link")

        if not hd_file:
            logger.warning("Pexels ফলাফলে ডাউনলোডযোগ্য ভিডিও পাওয়া যায়নি।")
            return download_fallback_video(target_path)

        logger.info("ভিডিও ফাইল ডাউনলোড হচ্ছে...")
        _download_video(hd_file, target_path, timeout=30)

        logger.info(f"ব্যাকগ্রাউন্ড ভিডিও সংরক্ষণ সম্পন্ন: {target_path}")
        return True

    except (requests.RequestException, OSError, ValueError) as e:
        logger.error(f"Pexels API ত্রুটি: {str(e)}")
        return download_fallback_video(target_path)

# একটাই URL-এর উপরে নির্ভর করা যায় না (অনেক পুরোনো লিঙ্ক এখন 403 দেয়)
FALLBACK_VIDEO_URLS = (
    "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4",
    "https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4",
    "https://download.samplelib.com/mp4/sample-5s.mp4",
)

def download_fallback_video(target_path: Path) -> bool:
    """একাধিক ওপেন-সোর্স ভিডিও চেষ্টা করে; সব ব্যর্থ হলে লোকাল ভিডিও বানায়"""
    for url in FALLBACK_VIDEO_URLS:
        try:
            logger.info(f"ব্যাকআপ ভিডিও ডাউনলোড হচ্ছে: {url.rsplit('/', 1)[-1]}")
            _download_video(url, target_path, timeout=30)
            logger.info(f"ব্যাকআপ ভিডিও সংরক্ষণ সম্পন্ন: {target_path}")
            return True
        except (requests.RequestException, OSError, ValueError) as ex:
            logger.warning(f"এই ফলব্যাক URL কাজ করেনি ({str(ex)[:120]})")

    # শেষ উপায়: ইন্টারনেট ছাড়াও চলবে — FFmpeg দিয়ে একটি সাদামাটা গ্রেডিয়েন্ট ভিডিও
    return generate_offline_video(target_path)

def generate_offline_video(target_path: Path, duration: int = 12) -> bool:
    """দুর্বল কিন্তু বৈধ ৯:১৬ ব্যাকগ্রাউন্ড ভিডিও (FFmpeg lavfi) — শেষ ফলব্যাক"""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"gradients=size=1080x1920:rate=24:duration={duration}:speed=0.05",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        str(target_path),
    ]
    try:
        logger.warning("সব ভিডিও উৎস ব্যর্থ — FFmpeg দিয়ে লোকাল ব্যাকগ্রাউন্ড ভিডিও তৈরি হচ্ছে।")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info(f"লোকাল ব্যাকগ্রাউন্ড ভিডিও তৈরি হয়েছে: {target_path}")
        return True
    except (OSError, subprocess.CalledProcessError) as ex:
        details = ex.stderr.decode("utf-8", errors="ignore")[:300] if hasattr(ex, "stderr") and ex.stderr else str(ex)
        logger.error(f"লোকাল ভিডিও তৈরি ব্যর্থ: {details}")
        return False
