"""আসল FFmpeg রেন্ডার টেস্ট — FFmpeg/ffprobe PATH-এ না থাকলে skip হয়।"""

import shutil
import subprocess

import pytest

from video_editor import get_media_duration, render_final_monetized_reel

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe ইনস্টল নেই",
)


def _make_inputs(folder):
    raw = folder / "raw.mp4"
    voice = folder / "voice.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=540x960:rate=24:duration=3",
         "-pix_fmt", "yuv420p", str(raw)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=3", str(voice)],
        check=True, capture_output=True,
    )
    return raw, voice


def test_render_produces_vertical_video_with_audio(tmp_path):
    raw, voice = _make_inputs(tmp_path)
    out = tmp_path / "final.mp4"

    ok = render_final_monetized_reel(
        raw_video_path=raw,
        voice_audio_path=voice,
        subtitles_list=[],
        output_video_path=out,
        subtitle_events=[(0.0, 1.5, "প্রথম বাংলা সাবটাইটেল"), (1.5, 3.0, "দ্বিতীয় লাইন")],
    )

    assert ok is True
    assert out.stat().st_size > 10_000
    assert 2.5 <= get_media_duration(out) <= 3.5

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert probe.stdout.strip().rstrip(",") == "1080,1920"

    audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert "aac" in audio.stdout


def test_render_falls_back_to_subtitles_list_when_no_timing(tmp_path):
    raw, voice = _make_inputs(tmp_path)
    out = tmp_path / "final.mp4"

    ok = render_final_monetized_reel(
        raw_video_path=raw,
        voice_audio_path=voice,
        subtitles_list=["এক", "দুই"],
        output_video_path=out,
        subtitle_fallback_span=(0.0, 3.0),
    )

    assert ok is True
    ass_text = out.with_suffix(".ass").read_text(encoding="utf-8")
    assert "Dialogue: 0" in ass_text


def test_render_reports_failure_for_broken_input(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    voice = tmp_path / "voice.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=1", str(voice)],
        check=True, capture_output=True,
    )

    assert render_final_monetized_reel(
        raw_video_path=broken,
        voice_audio_path=voice,
        subtitles_list=[],
        output_video_path=tmp_path / "out.mp4",
    ) is False
