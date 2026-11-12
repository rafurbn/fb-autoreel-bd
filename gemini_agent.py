"""
gemini_agent.py - Google Gemini API দিয়ে ৩০-৪০ সেকেন্ডের ভাইরাল বাংলা স্ক্রিপ্ট তৈরি
সম্পূর্ণ বিনামূল্যে Google GenAI SDK ব্যবহার করে
"""

import json
import logging
from google import genai
from google.genai import types
from config import GEMINI_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_viral_reel_script(category="funny") -> dict:
    """
    ফেইসবুক রিলসের জন্য হাই-রিটেনশন স্ক্রিপ্ট ও ব্যাকগ্রাউন্ড সার্চ কোয়েরি তৈরি করে
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY পাওয়া যায়নি! অনুগ্রহ করে .env ফাইলে কী যুক্ত করুন।")

    client = genai.Client(api_key=GEMINI_API_KEY)

    system_prompt = """
    আপনি বাংলাদেশের ফেইসবুক রিলস ও টিকটক ভিডিও তৈরির একজন অভিজ্ঞ স্ক্রিপ্ট রাইটার।
    আপনাকে ৩০-৪০ সেকেন্ডের একটি নিখুঁত বাংলা স্ক্রিপ্ট তৈরি করতে হবে যা ফেসবুকের মনিটাইজেশন পলিসি মেনে চলে।
    
    শর্তাবলী:
    ১. ভাষা হবে অত্যন্ত আকর্ষণীয়, মজাদার এবং প্রাত্যহিক জীবনের সাথে মানানসই খাঁটি বাংলা।
    ২. কোনো ধরনের ১৮+ বা আপত্তিকর ভাষা থাকবে না (১০০% ফ্যামিলি ফ্রেন্ডলি)।
    ৩. প্রথম ৩ সেকেন্ডেই একটি চমকপ্রদ হুক (Hook) থাকবে যেন দর্শক স্ক্রোল না করে পুরোটা দেখে।
    ৪. স্ক্রিপ্টটি যেন স্বাভাবিক গতিতে পড়লে ৩০ থেকে ৪০ সেকেন্ড সময় নেয়।
    ৫. ব্যাকগ্রাউন্ড ভিডিও খোঁজার জন্য একটি উপযুক্ত ইংরেজি স্টক-ভিডিও সার্চ কোয়েরি দিতে হবে।
    
    আউটপুটটি অবশ্যই নিচে দেওয়া JSON ফরম্যাটে হতে হবে:
    {
      "title": "ছোট মজাদার শিরোনাম",
      "spoken_script": "সম্পূর্ণ বাংলা ভয়েসওভার টেক্সট (৬০-৮০ শব্দ)",
      "subtitles": [
        {"text": "প্রথম ৩-৪ সেকেন্ডের লাইন..."},
        {"text": "পরের লাইনের ডায়নামিক টেক্সট..."}
      ],
      "video_search_prompt": "smiling bengali young man shocked mobile phone vertical video",
      "caption": "ফেইসবুকের জন্য ক্যাপশন ও কল-টু-অ্যাকশন",
      "hashtags": ["#banglareels", "#viralvideo", "#bangladesh", "#funnyreels"]
    }
    """

    user_query = f"আজকের জন্য একটি ট্রেন্ডিং {category} টপিকের ওপর ৩০ সেকেন্ডের বাংলা রিলস স্ক্রিপ্ট তৈরি করো।"

    try:
        logger.info("জেমিনি এআই-এর কাছে নতুন স্ক্রিপ্টের জন্য অনুরোধ পাঠানো হচ্ছে...")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_query,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json"
            )
        )
        data = json.loads(response.text)
        logger.info(f"সফলভাবে স্ক্রিপ্ট তৈরি হয়েছে: {data.get('title')}")
        return data
    except Exception as e:
        logger.error(f"Gemini API ত্রুটি: {str(e)}")
        # সেফ ফলব্যাক টেমপ্লেট
        return {
            "title": "বাঙালির সকালের চা ও রাজনীতি",
            "spoken_script": (
                "সকালে ঘুম থেকে উঠে চায়ের দোকানে না গেলে বাঙালির দিনই শুরু হয় না। "
                "দোকানে গিয়ে এক কাপ লাল চা হাতে পেলেই শুরু হয় বিশ্বরাজনীতি নিয়ে তুমুল তর্ক! "
                "একজন বলে, আজ থেকেই সবকিছু বদলে যাবে; আরেকজন বলে, আগে দোকানের বাকি চা-নাশতার "
                "হিসাবটা মেলাও। পাশের টেবিলের বন্ধু আবার খবর না পড়েই সব খবরের বিশ্লেষক। "
                "চা ঠান্ডা হয়ে যায়, তর্ক কিন্তু থামে না। শেষে সবাই মিলে বলে, কাল সকালে আবার বসব। "
                "অথচ নিজের ঘরে কারেন্ট কেন নেই, সেই খবর কিন্তু কারও কাছে নেই! "
                "তাই চায়ের কাপ হাতে মতামত দেওয়ার আগে বিলটা দিয়ে যেও!"
            ),
            "subtitles": [
                {"text": "সকালের চা ছাড়া বাঙালির দিনই শুরু হয় না!"},
                {"text": "এক কাপ চা, আর শুরু বিশ্বরাজনীতি!"},
                {"text": "একজন বলে—আজ থেকেই সব বদলে যাবে!"},
                {"text": "আগে চা-নাশতার বাকি হিসাবটা মেলাও!"},
                {"text": "বন্ধুটা খবর না পড়েই বিশ্লেষক!"},
                {"text": "চা ঠান্ডা, কিন্তু তর্ক থামে না!"},
                {"text": "কাল আবার বসব—সবার একই কথা!"},
                {"text": "নিজের ঘরের কারেন্টের খবর? কারও জানা নেই!"},
                {"text": "মতামতের আগে চায়ের বিলটা দিয়ে যেও!"}
            ],
            "video_search_prompt": "hot steaming tea glass outdoors vertical smiling man",
            "caption": "চায়ের কাপে ঝড় তোলা সেই পরিচিত বন্ধুদের ট্যাগ করুন! ☕😂",
            "hashtags": ["#banglareels", "#chaaddicts", "#banglafunny", "#reelsfb"]
        }
