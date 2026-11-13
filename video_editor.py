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

def get_subtitle_font_family() -> str:
    """libass ফন্ট ম্যাচিংয়ের জন্য পরিবার-নাম (ফাইল-পাথ নয়)"""
    return FONT_PATH.stem if FONT_PATH.is_file() else "Noto Sans Bengali"

def escape_filter_path(file_path: Path) -> str:
    """
    FFmpeg filter আর্গুমেন্টে নিরাপদ পাথ:
    ১. প্রথমে backslash নিজেই escape (\\ → \\\\) — আগে না করলে পরে যোগ করা \\: নষ্ট হয়
    ২. তারপর : → \\: আর ' → \\' (Windows ড্রাইভ-letter ও ফাঁকা স্থানসহ পাথ)
    """
    path = str(file_path).replace("\\", "/").replace("\\", "\\\\").replace("$", "\\$")
    path = path.replace("'", "'\\''").replace(":", "\\:")
    return path

def render_final_monetized_reel(
    raw_video_path: Path,
    voice_audio_path: Path,
    subtitles_list: list,
    output_video_path: Path,
    bg_music_path: Path = None,
    logo_path: Path = None,
    subtitle_events: list | None = None,
    subtitle_fallback_span: tuple[float, float] | None = None
) -> bool:
    """
    সবগুলো উপাদান একসাথে করে ফেইসবুক রিলসের জন্য সম্পূর্ণ রেডি ও মনিটাইজেশন-উপযোগী MP4 ভিডিও প্রস্তুত করে

    subtitle_events: TTS থেকে পাওয়া (শুরু, শেষ, লেখা) tuples — থাকলে এগুলোই ব্যবহার হয়
    subtitle_fallback_span: TTS টাইমিং না পেলে সব সাবটাইটেল ভাগ করে বসানোর (শুরু, শেষ) সীমা
    """
    logger.info("FFmpeg এডিটিং পাইপলাইন শুরু হচ্ছে...")

    # অডিও দৈর্ঘ্য নির্ণয় (এটাই ভিডিওর চূড়ান্ত দৈর্ঘ্য)
    duration = get_media_duration(voice_audio_path)
    if duration <= 0:
        duration = 35.0  # ডিফল্ট সময়

    # সাবটাইটেল ফাইল তৈরি: আসল TTS টাইমিং থাকলে সেটি, নাহলে আনুপাতিক ভাগ
    # ASS (নয় SRT) ব্যবহার করছি কারণ এতে PlayRes ও Style স্পষ্টভাবে লেখা যায় —
    # ffmpeg-এর force_style স্ট্রিং Rilis ৭/৮-এ Alignment/MarginV কাজ করে না।
    ass_path = output_video_path.with_suffix(".ass")
    events = subtitle_events or build_subtitle_events(
        subtitles_list,
        start=subtitle_fallback_span[0] if subtitle_fallback_span else 0.0,
        end=subtitle_fallback_span[1] if subtitle_fallback_span else duration,
    )
    write_ass_file(events, ass_path, width=1080, height=1920)

    # ৯:১৬ ক্রপ এবং স্কেলিং (1080x1920) + কালার গ্রেডিং
    video_filters = [
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        COLOR_FILTER
    ]

    # ফেইসবুক রিলস ফ্রেম ও ব্র্যান্ডের নাম যুক্ত করা
    # (সাবটাইটেলের আগে বসে, তাতে স্ক্রিপ্টের লেখা ব্যানারের উপরে না থাকলেও ওয়াটারমার্ক সবসময় দেখা যায়)
    drawtext_font = get_drawtext_font_path()
    if drawtext_font:
        escaped_font = escape_filter_path(drawtext_font)
        safe_brand = BRAND_NAME.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        brand_banner = (
            f"drawtext=fontfile='{escaped_font}':text='{safe_brand}':fontcolor=white:"
            f"fontsize=42:x=(w-text_w)/2:y=120:box=1:boxcolor=black@0.6:boxborderw=15"
        )
        video_filters.append(brand_banner)
    else:
        logger.warning("ব্র্যান্ড ব্যানারের জন্য উপযুক্ত ফন্ট পাওয়া যায়নি; ব্যানার ছাড়া রেন্ডার হবে।")

    # সাবটাইটেল বার্ন — অবশ্যই scale/crop-এর পরে, যাতে ১০৮০×১৯২০ ফ্রেমের সাথে PlayRes মেলে
    if ass_path.exists() and ass_path.stat().st_size > 0:
        escaped_ass = escape_filter_path(ass_path)
        video_filters.append(f"ass=filename='{escaped_ass}'")
    else:
        logger.warning("সাবটাইটেল ফাইল তৈরি হয়নি; সাবটাইটেল ছাড়া রেন্ডার হবে।")

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(raw_video_path),  # [0] ভিডিও
        "-i", str(voice_audio_path),                      # [1] ভয়েস
    ]

    next_input_index = 2
    logo_input_index = None
    if logo_path and Path(logo_path).exists():
        logo_input_index = next_input_index
        next_input_index += 1
        cmd.extend(["-i", str(logo_path)])

    music_input_index = None
    if bg_music_path and Path(bg_music_path).exists():
        music_input_index = next_input_index
        next_input_index += 1
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
        "-t", str(duration),
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

    logger.info(f"রেন্ডারিং শুরু হয়েছে... আনুমানিক সময়: {int(duration)} সেকেন্ড")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info(f"ভিডিও রেন্ডারিং সফলভাবে সম্পন্ন: {output_video_path}")
        return True
    except subprocess.CalledProcessError as err:
        logger.error(f"FFmpeg রেন্ডার ফেইল করেছে: {err.stderr.decode('utf-8', errors='ignore')}")
        return False

def build_subtitle_events(subtitles: list, start: float, end: float) -> list:
    """
    স্ক্রিপ্টের প্রতিটি লাইনকে উপলব্ধ সময়ের (start..end) মধ্যে সমানভাবে ভাগ করে দেয়।
    TTS-এর শব্দ-স্তরের টাইমিং না পাওয়া গেলে এটি ফলব্যাক।
    """
    texts = [sub.get("text", "") if isinstance(sub, dict) else str(sub) for sub in subtitles or []]
    texts = [text.strip() for text in texts if text and text.strip()]
    if not texts:
        return []

    # লাইনের দৈর্ঘ্য অনুযায়ী সময় ভাগ (লম্বা বাক্য বেশি সময় পায়)
    weights = [max(len(text), 8) for text in texts]
    total_weight = sum(weights)
    span = max(end - start, 1.0)

    events = []
    cursor = start
    for text, weight in zip(texts, weights):
        share = span * (weight / total_weight)
        events.append((cursor, min(cursor + share, end), text))
        cursor += share
    return events

def format_ass_time(seconds: float) -> str:
    """ASS টাইম: H:MM:SS.cc (সেন্টিসেকেন্ড)"""
    centis = int(round(max(seconds, 0.0) * 100))
    secs = centis // 100
    return f"{secs // 3600}:{(secs // 60) % 60:02d}:{secs % 60:02d}.{centis % 100:02d}"

def write_ass_file(events: list, ass_file_path: Path, width: int = 1080, height: int = 1920) -> None:
    """
    (শুরু, শেষ, লেখা) tuples থেকে ASS সাবটাইটেল লেখে।
    PlayResX/Y স্পষ্ট দিলে libass লেখার আকার ও নিচের দূরত্ব সঠিকভাবে হিসাব করে
    (SRT + force_style-এ Alignment/MarginV সব ffmpeg বিল্ডে মানা যায় না)।
    রং: PrimaryColour ASS-এ &HAABBGGRR — এখানে সাদা লেখা, কালো আউটলাইন।
    """
    font_name = get_subtitle_font_family()
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Reel,{font_name},64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,4,0,2,60,60,320,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for start, end, text in events:
        safe_text = (
            str(text).replace("\\", "\\\\").replace("{", "(").replace("}", ")")
            .replace("\r", " ").replace("\n", "\\N")
        )
        lines.append(
            f"Dialogue: 0,{format_ass_time(start)},{format_ass_time(max(end, start + 0.3))},"
            f"Reel,,0,0,0,,{safe_text}\n"
        )
    with open(ass_file_path, "w", encoding="utf-8") as f:
        f.write(header + "".join(lines))

def write_srt_file(events: list, srt_file_path: Path) -> None:
    """(শুরু, শেষ, লেখা) tuples থেকে SRT ফাইল লেখে (ডিবাগ/আলাদা ব্যবহারের জন্য)"""
    with open(srt_file_path, "w", encoding="utf-8") as f:
        for idx, (start, end, text) in enumerate(events, 1):
            f.write(
                f"{idx}\n{format_srt_time(max(start, 0.0))} --> {format_srt_time(max(end, start + 0.1))}\n"
                f"{text}\n\n"
            )

def format_srt_time(seconds: float) -> str:
    # আগে (seconds - int(seconds)) * 1000 করলে float precision-এ 3661.999 → 998 হতো;
    # মিলিসেকেন্ডে গোল করে ভাগ করলে এটা হয় না
    total_ms = int(round(max(seconds, 0.0) * 1000))
    secs, millis = divmod(total_ms, 1000)
    mins, secs = divmod(secs, 60)
    hours, mins = divmod(mins, 60)
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
