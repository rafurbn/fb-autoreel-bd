# FB AutoReel BD — বাংলা ফেইসবুক রিলস কন্টেন্ট অটোমেশন

প্রতিদিন স্বয়ংক্রিয়ভাবে **AI দিয়ে বাংলা স্ক্রিপ্ট** লেখে, **সাপোর্টেড TTS দিয়ে ভয়েসওভার** যোগ করে,
Pixabay/Pexels-এর **স্টক ভিডিও**কে ৯:১৬ রিলস ফরম্যাটে কাটে, **বাংলা সাবটাইটেল বার্ন** করে
এবং Graph API দিয়ে **আপনার ফেইসবুক পেজে** রিলস হিসেবে পোস্ট করে।

> ⚠️ **সৎ কথা আগে:** এটি একটি অটোমেশন টুল, "মনিটাইজেশন গ্যারান্টি" নয়। স্টক ভিডিও + AI ভয়েস
> দিয়ে বানানো কন্টেন্টকে মেটা যে "Original" ধরবে এমন কোনো প্রতিশ্রুতি এই কোড দিতে পারে না।
> ফেইসবিক ইন-স্ট্রিম/রিলস মনিটাইজেশন পলিসি ও কনটেন্ট-ওনয়ারশিপ নিয়ম নিজে পড়ে নিন।

## বৈশিষ্ট্য

1. **কোনো পেইড ফিল্ড নেই, তবে "১০০% ফ্রি" নয়:** Gemini, Pixabay, Pexels-এর ফ্রি টিয়ার
   ব্যবহার হয় — প্রতিটির **দৈনিক/মাসিক কোটা** আছে এবং কোটা শেষ হলে পাইপলাইন ব্যর্থ হবে।
2. **ক্যাপচা-মুক্ত:** ব্রাউজার অটোমেশন নেই; শুধু অফিসিয়াল Graph API ব্যবহার হয়।
3. **ব্র্যান্ডিং:** `assets/logo.png` ওয়াটারমার্ক + ব্র্যান্ড নাম ব্যানার + বাংলা সাবটাইটেল
   (বাস্তব TTS টাইমিং অনুযায়ী)।
4. **ফ্রি শিডিউলিং:** GitHub Actions-এ প্রতিদিন একবার (UTC ০৩:০০ = ঢাকা সকাল ৯টা)।
   Public রিপোতে সীমা উদার, কিন্তু private রিপোতে monthly minutes সীমা প্রযোজ্য।

## লোকাল সেটআপ

```bash
git clone https://github.com/rafurbn/fb-autoreel-bd.git
cd fb-autoreel-bd
pip install -r requirements.txt
# FFmpeg নিজে ইনস্টল থাকতে হবে (PATH-এ ffmpeg ও ffprobe)
cp .env.example .env    # তারপর .env-এ API কী বসান
python main.py --test   # ভিডিও বানাবে, ফেসবুকে পোস্ট করবে না
python main.py          # তৈরি করে সরাসরি পোস্ট করে
```

প্রয়োজন: **Python 3.10+** এবং **FFmpeg** (Windows: https://www.gyan.dev/ffmpeg/builds/)।

## ফোল্ডার স্ট্রাকচার

```
assets/
  logo.png            # ঐচ্ছিক ব্র্যান্ড ওয়াটারমার্ক
  music/sample_bg.mp3 # ঐচ্ছিক ব্যাকগ্রাউন্ড মিউজিক
  fonts/Kalpurush.ttf # ঐচ্ছিক বাংলা ফন্ট
output/               # তৈরি হওয়া অডিও/ভিডিও (git-এ যায় না)
```

বিস্তারিত: [`assets/README.md`](assets/README.md)

## কমান্ড

| কমান্ড | কাজ |
|--------|-----|
| `python main.py --test` | টেস্ট রান (পোস্ট করবে না) |
| `python main.py` | তৈরি + ফেসবুকে পোস্ট |
| `python main.py --offline --test` | **API কী ছাড়াই** স্যাম্পল স্ক্রিপ্ট দিয়ে সম্পূর্ণ ড্রাই রান |
| `python main.py --category motivation` | স্ক্রিপ্টের ধরন বদলানো |
| `python main.py --schedule --hour 9` | লোকাল শিডিউলার (Asia/Dhaka টাইমজোনে) |

সফল হলে exit code `0`, ব্যর্থ হলে `1` — তাই CI/Actions-এ আসল অবস্থা দেখা যায়।

### ক্যাটাগরি

`funny` (ডিফল্ট), `motivation`, `lifestyle`, `story`, `news` — `--category` দিয়ে বেছে নিন।
Actions-এ `Run workflow` চাপলে ড্রপডাউনে এগুলো পাওয়া যাবে, সাথে `test_only` চেকবক্স।

### টেস্ট

```bash
pip install -r requirements-dev.txt
python -m pytest          # ইউনিট + আসল FFmpeg রেন্ডার টেস্ট
```

FFmpeg ইনস্টল না থাকলে রেন্ডার টেস্টগুলো স্বয়ংক্রিয়ভাবে skip হবে।

## দরকারি কী-গুলো

| কী | কোথায় পাবেন | বাধ্যতামূলক? |
|----|-------------|--------------|
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey | হ্যাঁ |
| `FB_PAGE_ID`, `FB_PAGE_ACCESS_TOKEN` | Meta Business Suite → Graph API | শুধু পোস্ট করতে |
| `PIXABAY_API_KEY` | https://pixabay.com/api/docs/ | একটি ভিডিও-উৎস লাগবেই |
| `PEXELS_API_KEY` | https://www.pexels.com/api/ | বিকল্প |

পেজ টোকেনে `pages_manage_posts` ও `publish_video` পারমিশন লাগবে; না থাকলে পাবলিশ ধাপে
`(#200) Permissions error` আসবে এবং এখন লগে আসল কারণসহ দেখাবে।

### GitHub Actions-এ অটো-পোস্ট

Repo → Settings → Secrets and variables → Actions → উপরের কী-গুলো secret হিসেবে যোগ করুন,
তারপর Actions ট্যাবে `Daily Automated Facebook Reel` workflow **Enable** করুন।
প্রতি রানে প্রথমে টেস্ট চলে; টেস্ট ফেইল হলে পোস্ট হবে না। উৎপাদিত ভিডিও artifact
হিসেবে ৭ দিন থাকে — ফেইল করলেও ডিবাগ করা যাবে।

## সীমাবদ্ধতা (সত্যি কথা)

- **TTS:** `edge-tts` Microsoft-এর অনানুষ্ঠানিক পাবলিক endpoint ব্যবহার করে — SLA নেই,
  IP ব্লক/রেট-লিমিট হতে পারে। ব্যর্থ হলে পাইপলাইন ওই দিন বন্ধ হবে।
- **কনটেন্ট:** সাবটাইটেল ও ভয়েস আসল টাইমিংয়ে মেলে, কিন্তু কোয়েরি দুর্বল হলে ভিডিও-দৃশ্য
  স্ক্রিপ্টের সাথে নাও মিলতে পারে।
- **অরিজিনালিটি:** কালার ফিল্টার কেবল ছবির চেহারা বদলায়; মেটার Used Content ডিটেকশন
  এড়ানোর কোনো নিশ্চয়তা নেই।

## লাইসেন্স

[MIT](LICENSE) — টুলটি ফ্রি, তবে এটি ব্যবহার করে বানানো কন্টেন্টের দায় ও দায়িত্ব আপনার।
