"""
Gemini retry এবং Groq fallback দিয়ে বাংলা রিলস স্ক্রিপ্ট তৈরি।

Gemini ও Groq দুটোই ব্যর্থ হলে পুরোনো স্ক্রিপ্ট দিয়ে স্বয়ংক্রিয় পোস্ট করা হয় না।
নমুনা স্ক্রিপ্ট শুধু স্পষ্টভাবে --offline মোডে ব্যবহৃত হবে।
"""

import copy
import json
import logging
import time

import requests

from config import GEMINI_API_KEY, GROQ_API_KEY

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "funny": "মজা/কৌতুক",
    "motivation": "মোটিভেশন/অনুপ্রেরণা",
    "lifestyle": "দৈনন্দিন জীবনযাত্রা ও টিপস",
    "story": "ছোট গল্প/গল্পকথা",
    "news": "সাম্প্রতিক খবর ও ঘটনা",
}

SYSTEM_PROMPT = """
আপনি বাংলাদেশের ফেইসবুক রিলসের বাংলা স্ক্রিপ্ট লেখক। ৩০-৪০ সেকেন্ডের,
আকর্ষণীয় এবং পরিবারবান্ধব বাংলা স্ক্রিপ্ট তৈরি করুন। প্রথম ৩ সেকেন্ডে একটি
আকর্ষণীয় হুক থাকবে। spoken_script-এ ৪-৮টি স্বাভাবিক বাংলা বাক্য থাকবে।
বাক্যগুলো বাংলা দাঁড়ি (।), প্রশ্নবোধক (?) বা বিস্ময়সূচক (!) দিয়ে শেষ হবে।
ভিডিও খোঁজার জন্য ইংরেজি search prompt দিন। শুধু বৈধ JSON দিন—Markdown
code fence নয়।

JSON schema:
{
  "title": "ছোট বাংলা শিরোনাম",
  "spoken_script": "বাংলা ভয়েসওভার",
  "subtitles": [{"text": "বাংলা সাবটাইটেল"}],
  "video_search_prompt": "English stock video search prompt",
  "caption": "বাংলা Facebook caption",
  "hashtags": ["#banglareels", "#bangladesh"]
}
""".strip()

# শুধু --offline মোডে ব্যবহারের জন্য।
FALLBACK_SCRIPT = {
    "title": "বাঙালির সকালের চা ও রাজনীতি",
    "spoken_script": (
        "সকালে ঘুম থেকে উঠে চায়ের দোকানে না গেলে বাঙালির দিনই শুরু হয় না। "
        "দোকানে গিয়ে এক কাপ লাল চা হাতে পেলেই শুরু হয় বিশ্বরাজনীতি নিয়ে তুমুল আলোচনা। "
        "একজন বলে, আজ থেকেই সবকিছু বদলে যাবে; আরেকজন বলে, আগে দোকানের বাকি চা-নাশতার হিসাবটা মেলাও। "
        "পাশের টেবিলের বন্ধু আবার খবর না পড়েই সব খবরের বিশ্লেষক। "
        "চা ঠান্ডা হয়ে যায়, তর্ক কিন্তু থামে না। "
        "শেষে সবাই মিলে বলে, কাল সকালে আবার বসব। "
        "অথচ নিজের ঘরে কারেন্ট কেন নেই, সেই খবর কিন্তু কারও কাছে নেই! "
        "তাই চায়ের কাপ হাতে মতামত দেওয়ার আগে বিলটা দিয়ে যেও!"
    ),
    "subtitles": [
        {"text": "সকালের চা ছাড়া বাঙালির দিনই শুরু হয় না!"},
        {"text": "এক কাপ চা, আর শুরু বিশ্বরাজনীতি!"},
        {"text": "একজন বলে—আজ থেকেই সব বদলে যাবে!"},
        {"text": "আগে চা-নাশতার বাকি হিসাবটা মেলাও!"},
        {"text": "বন্ধুটা খবর না পড়েই বিশ্লেষক!"},
        {"text": "চা ঠান্ডা, কিন্তু তর্ক থামে না!"},
        {"text": "কাল আবার বসব—সবার একই কথা!"},
        {"text": "নিজের ঘরের কারেন্টের খবর? কারও জানা নেই!"},
        {"text": "মতামতের আগে চায়ের বিলটা দিয়ে যেও!"},
    ],
    "video_search_prompt": "hot steaming tea glass outdoors vertical smiling man",
    "caption": "চায়ের কাপে ঝড় তোলা সেই পরিচিত বন্ধুদের ট্যাগ করুন! ☕😂",
    "hashtags": ["#banglareels", "#chaaddicts", "#banglafunny", "#reelsfb"],
}


def _parse_json_response(response_text: str) -> dict:
    text = (response_text or "").strip()

    if text.startswith("```"):
        text = text[3:].strip()
        if text.startswith("json"):
            text = text[4:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    data = json.loads(text)
    if not isinstance(data, dict) or not str(data.get("spoken_script", "")).strip():
        raise ValueError("AI JSON-এ spoken_script নেই")

    data.setdefault("title", "বাংলা রিলস")
    data.setdefault("subtitles", [])
    data.setdefault(
        "video_search_prompt",
        "Bangladeshi lifestyle vertical stock video",
    )
    data.setdefault("caption", data["title"])
    data.setdefault("hashtags", ["#banglareels", "#bangladesh"])
    return data


def _gemini_call_once(user_query: str) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=user_query,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )
    return _parse_json_response(getattr(response, "text", ""))


def _groq_call_once(user_query: str) -> dict:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY সেট করা নেই")

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_query},
            ],
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        },
        timeout=45,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    return _parse_json_response(content)


def generate_viral_reel_script(category="funny", offline=False) -> dict:
    """Gemini-তে সর্বোচ্চ ৩ বার চেষ্টা করে; ব্যর্থ হলে Groq fallback করে।"""
    category = (category or "funny").strip().lower()

    if category not in CATEGORY_LABELS:
        raise ValueError(
            f"অসমর্থিত ক্যাটাগরি: '{category}'. "
            f"বেছে নিন: {', '.join(CATEGORY_LABELS)}"
        )

    if offline:
        logger.info("[OFFLINE] নমুনা স্ক্রিপ্ট ব্যবহার হচ্ছে।")
        return copy.deepcopy(FALLBACK_SCRIPT)

    user_query = (
        f"আজকের জন্য {CATEGORY_LABELS[category]} ({category}) ক্যাটাগরির "
        "একটি নতুন ৩০-৪০ সেকেন্ডের বাংলা রিলস স্ক্রিপ্ট তৈরি করো। "
        "উপরের JSON schema অনুসরণ করো।"
    )
    last_error = None

    if GEMINI_API_KEY:
        for attempt in range(1, 4):
            try:
                logger.info("Gemini অনুরোধ: চেষ্টা %s/3", attempt)
                script = _gemini_call_once(user_query)
                logger.info("Gemini দিয়ে স্ক্রিপ্ট তৈরি: %s", script.get("title"))
                return script
            except Exception as exc:
                last_error = exc
                logger.warning("Gemini চেষ্টা %s/3 ব্যর্থ: %s", attempt, exc)
                if attempt < 3:
                    time.sleep(2 * attempt)
    else:
        logger.warning("GEMINI_API_KEY নেই; Groq-তে সরাসরি চেষ্টা করা হবে।")

    if GROQ_API_KEY:
        for attempt in range(1, 3):
            try:
                logger.info("Groq fallback: চেষ্টা %s/2", attempt)
                script = _groq_call_once(user_query)
                logger.info("Groq দিয়ে স্ক্রিপ্ট তৈরি: %s", script.get("title"))
                return script
            except Exception as exc:
                last_error = exc
                logger.warning("Groq চেষ্টা %s/2 ব্যর্থ: %s", attempt, exc)
                if attempt < 2:
                    time.sleep(2)

    if last_error:
        raise last_error

    raise ValueError(
        "GEMINI_API_KEY অথবা GROQ_API_KEY—অন্তত একটি সেট করতে হবে।"
    )
