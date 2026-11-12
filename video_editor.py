"""
video_editor.py - FFmpeg ইঞ্জিন:
১. ইউনিক কালার ফিল্টার যোগ করে মেটাডাটা ও ফিঙ্গারপ্রিন্ট পরিবর্তন (Anti-Reused Content)
২. স্টাইলিশ বাংলা ডায়নামিক সাবটাইটেল বার্ন
৩. পেজের নিজস্ব লোগো ও ওয়াটারমার্ক যুক্ত করা
৪. মৃদু ব্যাকগ্রাউন্ড মিউজিক এবং ভয়েসওভার সঠিক ভলিউমে ব্লেন্ড করা
"""

import subprocess
import os
from pathlib import Path
import logging
from config import COLOR_FILTER, BRAND_NAME, FONT_PATH

logger = logging.getLogger(__name__)

def get_drawtext_font_path() -> Path | None:
    """FFmpeg drawtext-এর জন্য একটি ইনস্টল করা ফন্ট খুঁজে"""
    candidates = [FONT_PATH]
    if os.name == "nt":
        windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        candidates.extend([
            windows_fonts / "NIRMALA.TTF",
            windows_fonts / "ARIALUNI.TTF",
            windows_fonts / "arial.ttf",
        ])
    else:
        candidates.extend([
            Path("/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf"),
            Path("/usr/share/fonts/truetype/noto/NotoSansBengaliUI-Regular.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ])
    return next((path for path in candidates if path.is_file()), None)

def render_final_monetized_reel(
    raw_video_path: Path,
    voice_audio_path: Path,
    subtitles_list: list,
    output_video_path: Path,
    bg_music_path: Path = None,
    logo_path: Path = None
) -> bool:
    """
    সবগুলো উপাদান একসাথে করে ফেইসবুক রিলসের জন্য সম্পূর্ণ রেডি ও মনিটাইজেশন-উপযোগী MP4 ভিডিও প্রস্তুত করে
    """
    logger.info("FFmpeg এডিটিং পাইপলাইন শুরু হচ্ছে...")

    # সাবটাইটেল ASS / SRT ফাইল তৈরি
    srt_path = output_video_path.with_suffix(".srt")
    create_bangla_srt_file(subtitles_list, srt_path)

    # অডিও দৈর্ঘ্য নির্ণয়
    duration = get_media_duration(voice_audio_path)
    if duration <= 0:
        duration = 35.0  # ডিফল্ট সময়

    # ৯:১৬ ক্রপ এবং স্কেলিং (1080x1920) + কালার গ্রেডিং
    video_filters = [
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        COLOR_FILTER
    ]

    # ফেইসবুক রিলস ফ্রেম ও ব্র্যান্ডের নাম যুক্ত করা
    drawtext_font = get_drawtext_font_path()
    if drawtext_font:
        escaped_font = str(drawtext_font).replace("\\", "/").replace(":", "\\:")
        brand_banner = (
            f"drawtext=fontfile='{escaped_font}':text='{BRAND_NAME}':fontcolor=white:"
            f"fontsize=42:x=(w-text_w)/2:y=120:box=1:boxcolor=black@0.6:boxborderw=15"
        )
        video_filters.append(brand_banner)
    else:
        logger.warning("ব্র্যান্ড ব্যানারের জন্য উপযুক্ত ফন্ট পাওয়া যায়নি; ব্যানার ছাড়া রেন্ডার হবে।")

    # সাবটাইটেল বার্ন ফিল্টার
    # লিনাক্সে Noto Sans Bengali অথবা Kalpurush ফন্ট ব্যবহার
    if srt_path.exists():
        escaped_srt = str(srt_path).replace("\\", "/").replace(":", "\\:")
        sub_filter = (
            f"subtitles='{escaped_srt}':force_style='FontSize=26,FontName=Kalpurush,"
            f"PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=3,Outline=2,"
            f"Shadow=1,Alignment=2,MarginV=280'"
        )
        video_filters.append(sub_filter)

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(raw_video_path),  # [0] ভিডিও
        "-i", str(voice_audio_path),                      # [1] ভয়েস
    ]

    logo_input_index = None
    if logo_path and logo_path.exists():
        logo_input_index = 2
        cmd.extend(["-i", str(logo_path)])

    music_input_index = None
    if bg_music_path and bg_music_path.exists():
        music_input_index = 2 + (logo_input_index is not None)
        cmd.extend(["-stream_loop", "-1", "-i", str(bg_music_path)])

    filter_graph = f"[0:v]{','.join(video_filters)}[vbase]"
    if logo_input_index is not None:
        filter_graph += (
            f";[{logo_input_index}:v]scale=200:-1[logo]"
            ";[vbase][logo]overlay=W-w-50:50:format=auto[vout]"
        )
    else:
        filter_graph += ";[vbase]null[vout]"

    if music_input_index is not None:
        filter_graph += (
            f";[1:a]volume=1.0[v_aud];[{music_input_index}:a]volume=0.15[bg_aud]"
            ";[v_aud][bg_aud]amix=inputs=2:duration=first[out_aud]"
        )
        audio_map = "[out_aud]"
    else:
        audio_map = "1:a:0"

    cmd.extend([
        "-filter_complex", filter_graph,
        "-map", "[vout]",
        "-map", audio_map,
    ])

    # ভিডিও এক্সপোর্ট সেটিংস
    cmd.extend([
        "-t", str(duration + 1.0),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        # মেটাডাটা স্ক্র্যাব ও নতুন মেটাডাটা রাইটিং (Avoid detection)
        "-metadata", f"title={BRAND_NAME} Original Reel",
        "-metadata", "artist=AI AutoReel Engine BD",
        str(output_video_path)
    ])

    logger.info(f"রেন্ডারিং শুরু হয়েছে... আনুমানিক সময়: {int(duration)} সেকেন্ড")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info(f"ভিডিও রেন্ডারিং সফলভাবে সম্পন্ন: {output_video_path}")
        return True
    except subprocess.CalledProcessError as err:
        logger.error(f"FFmpeg রেন্ডার ফেইল করেছে: {err.stderr.decode('utf-8', errors='ignore')}")
        return False

def create_bangla_srt_file(subtitles: list, srt_file_path: Path):
    """ডায়নামিক টাইমস্ট্যাম্প সহ SRT ফাইল তৈরি"""
    with open(srt_file_path, "w", encoding="utf-8") as f:
        curr_time = 0.0
        step = 4.5  # প্রতিটি সাবটাইটেলের সময়কাল
        for idx, sub in enumerate(subtitles, 1):
            start = format_srt_time(curr_time)
            end = format_srt_time(curr_time + step)
            text = sub.get("text", "") if isinstance(sub, dict) else str(sub)
            f.write(f"{idx}\n{start} --> {end}\n{text}\n\n")
            curr_time += step

def format_srt_time(seconds: float) -> str:
    millis = int((seconds - int(seconds)) * 1000)
    secs = int(seconds) % 60
    mins = (int(seconds) // 60) % 60
    hours = int(seconds) // 3600
    return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"

def get_media_duration(file_path: Path) -> float:
    """ফাইল থেকে সঠিক সেকেন্ড বের করে"""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path)
        ]
        out = subprocess.check_output(cmd).decode().strip()
        return float(out)
    except Exception:
        return 35.0
