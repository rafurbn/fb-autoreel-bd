"""
Gemini retry এবং Groq fallback দিয়ে বাংলা রিলস স্ক্রিপ্ট তৈরি।

Gemini ও Groq দুটোই ব্যর্থ হলে পুরোনো স্ক্রিপ্ট দিয়ে স্বয়ংক্রিয় পোস্ট করা হয় না।
নমুনা স্ক্রিপ্ট শুধু স্পষ্টভাবে --offline মোডে ব্যবহৃত হবে।
"""

import copy
import json
import logging
import re
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

GEMINI_MODELS = [
    "gemini-4-hydrogen",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-3.8-flash",
]

PREFERRED_GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "llama-3.1-8b-instant",
    "qwen/qwen3-32b",
    "openai/gpt-oss-20b",
]

NON_CHAT_GROQ_KEYWORDS = (
    "whisper",
    "tts",
    "guard",
    "safeguard",
    "embed",
    "orpheus",
)

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
    if not text:
        raise ValueError("AI থেকে খালি রেসপন্স পাওয়া গেছে")

    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(text[start : end + 1])

    if not isinstance(data, dict) or not str(data.get("spoken_script", "")).strip():
        raise ValueError("AI JSON-এ spoken_script নেই")

    data.setdefault("title", "বাংলা রিলস")
    data.setdefault(
        "video_search_prompt",
        "Bangladeshi lifestyle vertical stock video",
    )
    data.setdefault("caption", data["title"])

    raw_subtitles = data.get("subtitles")
    if isinstance(raw_subtitles, list):
        normalized_subs = []
        for item in raw_subtitles:
            if isinstance(item, dict) and str(item.get("text", "")).strip():
                normalized_subs.append({"text": str(item["text"]).strip()})
            elif isinstance(item, str) and item.strip():
                normalized_subs.append({"text": item.strip()})
        data["subtitles"] = normalized_subs
    else:
        data["subtitles"] = []

    raw_hashtags = data.get("hashtags")
    if isinstance(raw_hashtags, str):
        data["hashtags"] = [tag for tag in raw_hashtags.split() if tag.strip()]
    elif not isinstance(raw_hashtags, list) or not raw_hashtags:
        data["hashtags"] = ["#banglareels", "#bangladesh"]

    return data


def _gemini_call_once(client, model_name: str, user_query: str) -> dict:
    from google.genai import types

    response = client.models.generate_content(
        model=model_name,
        contents=user_query,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )
    return _parse_json_response(getattr(response, "text", "") or "")


def _get_groq_candidate_models(groq_key: str) -> list[str]:
    """Groq API থেকে বর্তমানে সক্রিয় চ্যাট মডেল তালিকা নিয়ে অগ্রাধিকার ঠিক করে।"""
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {groq_key}"},
            timeout=15,
        )
        if not resp.ok:
            logger.warning(
                "Groq models তালিকা পাওয়া যায়নি (%s): %s",
                resp.status_code,
                resp.text[:300],
            )
            return list(PREFERRED_GROQ_MODELS)

        active_ids = [
            m["id"]
            for m in resp.json().get("data", [])
            if m.get("id")
            and not any(kw in m["id"].lower() for kw in NON_CHAT_GROQ_KEYWORDS)
        ]
        if not active_ids:
            return list(PREFERRED_GROQ_MODELS)

        ordered = [m for m in PREFERRED_GROQ_MODELS if m in active_ids]
        remaining = [m for m in active_ids if m not in ordered]
        return (ordered + remaining)[:5]
    except Exception as exc:
        logger.warning("Groq models তালিকা আনতে ত্রুটি: %s", exc)
        return list(PREFERRED_GROQ_MODELS)


def _groq_call_once(
    groq_key: str,
    model_name: str,
    user_query: str,
    use_json_mode: bool = True,
) -> dict:
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_query},
        ],
        "temperature": 0.7,
    }
    if use_json_mode:
        payload["response_format"] = {"type": "json_object"}

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=45,
    )

    if not response.ok:
        error_body = response.text[:500]
        if (
            response.status_code == 400
            and use_json_mode
            and "response_format" in error_body.lower()
        ):
            logger.info(
                "Groq মডেল %s json_object সমর্থন করে না; সাধারণ টেক্সট মোডে পুনরায় চেষ্টা।",
                model_name,
            )
            return _groq_call_once(
                groq_key, model_name, user_query, use_json_mode=False
            )

        raise requests.HTTPError(
            f"{response.status_code} ({model_name}): {error_body}",
            response=response,
        )

    content = response.json()["choices"][0]["message"]["content"]
    return _parse_json_response(content)


def generate_viral_reel_script(category="funny", offline=False) -> dict:
    """Gemini-তে একাধিক মডেলে চেষ্টা করে; ব্যর্থ হলে Groq fallback করে।"""
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

    gemini_key = (GEMINI_API_KEY or "").strip()
    groq_key = (GROQ_API_KEY or "").strip()

    if gemini_key:
        from google import genai

        client = genai.Client(api_key=gemini_key)
        for index, model_name in enumerate(GEMINI_MODELS, start=1):
            try:
                logger.info(
                    "Gemini অনুরোধ (%s/%s): model=%s",
                    index,
                    len(GEMINI_MODELS),
                    model_name,
                )
                script = _gemini_call_once(client, model_name, user_query)
                logger.info(
                    "Gemini (%s) দিয়ে স্ক্রিপ্ট তৈরি: %s",
                    model_name,
                    script.get("title"),
                )
                return script
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Gemini (%s) ব্যর্থ: %s", model_name, exc
                )
                err_text = str(exc).upper()
                # 404/NOT_FOUND হলে অপেক্ষা না করেই পরের মডেলে যাবে
                if "404" not in err_text and "NOT_FOUND" not in err_text:
                    if index < len(GEMINI_MODELS):
                        time.sleep(3)
    else:
        logger.warning("GEMINI_API_KEY নেই; Groq-তে সরাসরি চেষ্টা করা হবে।")

    if groq_key:
        groq_models = _get_groq_candidate_models(groq_key)
        for index, model_name in enumerate(groq_models, start=1):
            try:
                logger.info(
                    "Groq fallback (%s/%s): model=%s",
                    index,
                    len(groq_models),
                    model_name,
                )
                script = _groq_call_once(groq_key, model_name, user_query)
                logger.info(
                    "Groq (%s) দিয়ে স্ক্রিপ্ট তৈরি: %s",
                    model_name,
                    script.get("title"),
                )
                return script
            except Exception as exc:
                last_error = exc
                logger.warning("Groq (%s) ব্যর্থ: %s", model_name, exc)
                if "404" not in str(exc) and index < len(groq_models):
                    time.sleep(2)

    if last_error:
        raise last_error

    raise ValueError(
        "GEMINI_API_KEY অথবা GROQ_API_KEY—অন্তত একটি সেট করতে হবে।"
    )
