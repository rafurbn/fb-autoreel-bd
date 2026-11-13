"""পাইপলাইনের ছোট ইউনিট: VTT পার্সিং, বাক্য ভাগ, স্ক্রিপ্ট ফলব্যাক, আপলোড স্ট্যাটাস।"""

import pytest

import main as main_mod
from fb_uploader import upload_reel_to_facebook
from gemini_agent import CATEGORY_LABELS, FALLBACK_SCRIPT, generate_viral_reel_script
from tts_engine import split_sentences


def test_load_vtt_events_parses_timestamps_and_text(tmp_path):
    vtt = tmp_path / "a.vtt"
    vtt.write_text(
        "WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.500\nপ্রথম লাইন\n\n"
        "2\n00:00:02.500 --> 00:00:05.000\nদ্বিতীয় লাইন\n\n",
        encoding="utf-8",
    )
    assert main_mod.load_vtt_events(vtt) == [
        (0.0, 2.5, "প্রথম লাইন"),
        (2.5, 5.0, "দ্বিতীয় লাইন"),
    ]


def test_load_vtt_events_returns_empty_for_missing_file(tmp_path):
    assert main_mod.load_vtt_events(tmp_path / "nope.vtt") == []


def test_split_sentences_handles_bengali_punctuation():
    text = "চা ছাড়া দিন শুরু হয় না। তুমি কি জানো? হ্যাঁ জানি!"
    assert split_sentences(text) == ["চা ছাড়া দিন শুরু হয় না।", "তুমি কি জানো?", "হ্যাঁ জানি!"]


def test_split_sentences_keeps_trailing_text_without_punctuation():
    assert split_sentences("প্রথম বাক্য। শেষ কথা") == ["প্রথম বাক্য।", "শেষ কথা"]


def test_offline_script_does_not_need_api_key(monkeypatch):
    monkeypatch.setattr("gemini_agent.GEMINI_API_KEY", "")
    script = generate_viral_reel_script(category="motivation", offline=True)
    assert script["spoken_script"] == FALLBACK_SCRIPT["spoken_script"]


def test_offline_script_returns_a_copy():
    script = generate_viral_reel_script(category="funny", offline=True)
    script["hashtags"].append("#mutated")
    assert "#mutated" not in FALLBACK_SCRIPT["hashtags"]


def test_unknown_category_is_rejected():
    with pytest.raises(ValueError, match="অসমর্থিত ক্যাটাগরি"):
        generate_viral_reel_script(category="politics", offline=True)


def test_every_category_is_supported():
    for category in CATEGORY_LABELS:
        assert generate_viral_reel_script(category=category, offline=True)["title"]


def test_generate_script_uses_available_gemini_model(monkeypatch):
    from types import SimpleNamespace

    requested_models = []

    class FakeModels:
        def generate_content(self, **kwargs):
            requested_models.append(kwargs["model"])
            return SimpleNamespace(text='{"spoken_script":"নমুনা স্ক্রিপ্ট।"}')

    class FakeClient:
        def __init__(self, api_key):
            self.models = FakeModels()

    monkeypatch.setattr("gemini_agent.GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("google.genai.Client", FakeClient)

    script = generate_viral_reel_script()

    assert script["spoken_script"] == "নমুনা স্ক্রিপ্ট।"
    assert requested_models == ["gemini-3.8-flash"]


def test_fallback_script_has_usable_fields():
    for key in ("title", "spoken_script", "subtitles", "video_search_prompt", "caption", "hashtags"):
        assert FALLBACK_SCRIPT.get(key), key


def test_uploader_refuses_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr("fb_uploader.FB_PAGE_ID", "")
    monkeypatch.setattr("fb_uploader.FB_PAGE_ACCESS_TOKEN", "")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 10)
    assert upload_reel_to_facebook(video, "caption") is False


def test_uploader_returns_false_when_publish_is_not_success(tmp_path, monkeypatch):
    """আগের বাগ: success=False হলেও True রিটার্ন হতো।"""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 10)
    monkeypatch.setattr("fb_uploader.FB_PAGE_ID", "123")
    monkeypatch.setattr("fb_uploader.FB_PAGE_ACCESS_TOKEN", "token")

    class FakeResponse:
        def __init__(self, payload, ok=True, status_code=200):
            self._payload = payload
            self.ok = ok
            self.status_code = status_code
            self.text = str(payload)

        def json(self):
            return self._payload

    class FakeRequests:
        @staticmethod
        def post(url, **kwargs):
            if "video_reels" in url and kwargs.get("data", {}).get("upload_phase") == "start":
                return FakeResponse({"video_id": "v1", "upload_url": "https://upload.example"})
            if url == "https://upload.example":
                return FakeResponse({})
            return FakeResponse({"success": False, "error": {"message": "nope"}})

        @staticmethod
        def get(url, **kwargs):
            return FakeResponse({"status": {"video_status": "ready"}})

    monkeypatch.setattr("fb_uploader.requests", FakeRequests)
    assert upload_reel_to_facebook(video, "caption") is False


@pytest.mark.parametrize("video_status", ["ready", "upload_complete"])
def test_uploader_returns_true_only_on_success(tmp_path, monkeypatch, video_status):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 10)
    monkeypatch.setattr("fb_uploader.FB_PAGE_ID", "123")
    monkeypatch.setattr("fb_uploader.FB_PAGE_ACCESS_TOKEN", "token")

    class FakeResponse:
        ok = True
        status_code = 200
        text = "{}"

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    class FakeRequests:
        @staticmethod
        def post(url, **kwargs):
            if "video_reels" in url and kwargs.get("data", {}).get("upload_phase") == "start":
                return FakeResponse({"video_id": "v1", "upload_url": "https://upload.example"})
            if url == "https://upload.example":
                return FakeResponse({})
            return FakeResponse({"success": True})

        @staticmethod
        def get(url, **kwargs):
            return FakeResponse({"status": {"video_status": video_status}})

    monkeypatch.setattr("fb_uploader.requests", FakeRequests)
    assert upload_reel_to_facebook(video, "caption") is True
