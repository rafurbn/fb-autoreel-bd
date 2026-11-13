"""সাবটাইটেল টাইমিং, ASS লেখা ও ffmpeg filter escaping-এর ইউনিট টেস্ট (FFmpeg লাগে না)।"""

from pathlib import Path

from video_editor import (
    build_subtitle_events,
    escape_filter_path,
    format_ass_time,
    format_srt_time,
    write_ass_file,
    write_srt_file,
)


def test_format_srt_time_rounds_down_like_before():
    assert format_srt_time(0) == "00:00:00,000"
    assert format_srt_time(1.5) == "00:00:01,500"
    assert format_srt_time(65.25) == "00:01:05,250"
    assert format_srt_time(3661.999) == "01:01:01,999"


def test_format_ass_time_uses_centiseconds():
    assert format_ass_time(0) == "0:00:00.00"
    assert format_ass_time(2.5) == "0:00:02.50"
    assert format_ass_time(3725.07) == "1:02:05.07"


def test_escape_filter_path_escapes_drive_colon_and_backslashes():
    path = Path(r"C:\Temp\reel's.ass")
    escaped = escape_filter_path(path)
    assert escaped == r"C\:/Temp/reel'\''s.ass"
    assert "\\\\" not in escaped  # backslash নিজে escape হয়ে ডাবল হয় না


def test_escape_filter_path_leaves_posix_path_mostly_intact():
    assert escape_filter_path(Path("/home/runner/out.srt")) == "/home/runner/out.srt"


def test_build_subtitle_events_respects_span_and_length_weights():
    events = build_subtitle_events(
        [{"text": "ছোট"}, {"text": "একটু বড় লাইন যেটা বেশি সময় নেবে"}],
        start=2.0,
        end=12.0,
    )
    assert events[0][0] == 2.0
    assert events[-1][1] <= 12.0
    first_span = events[0][1] - events[0][0]
    second_span = events[1][1] - events[1][0]
    assert second_span > first_span


def test_build_subtitle_events_ignores_empty_lines():
    events = build_subtitle_events([" ", {"text": ""}, {"text": "এক"}, "দুই"], 0.0, 4.0)
    assert [text for _, _, text in events] == ["এক", "দুই"]


def test_write_ass_has_playres_and_bottom_aligned_style(tmp_path):
    out = tmp_path / "subs.ass"
    write_ass_file([(0.0, 2.0, "প্রথম {লাইন}")], out, width=1080, height=1920)
    content = out.read_text(encoding="utf-8")

    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    # Alignment=2 (নিচে), MarginV ফিচারের জন্য নিশ্চিত করি
    style = next(line for line in content.splitlines() if line.startswith("Style:"))
    assert style.split(",")[18] == "2"
    # ffmpeg override ট্যাগ ভাঙতে না পারে
    assert "{লাইন}" not in content
    assert "(লাইন)" in content


def test_write_srt_file_numbers_entries_from_one(tmp_path):
    out = tmp_path / "subs.srt"
    write_srt_file([(0.0, 1.0, "এক"), (1.0, 2.0, "দুই")], out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "1"
    assert lines[4] == "2"
