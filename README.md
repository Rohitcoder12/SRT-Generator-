# 🎬 SRT Generator Telegram Bot

Auto-generates `.srt` subtitle files from any video or audio.  
Detects Hindi → asks **Pure Hindi** or **Hinglish (Roman script)**.

---

## 🚀 Deploy on Railway

### Step 1 — Get credentials

| What | Where |
|------|-------|
| `API_ID` + `API_HASH` | https://my.telegram.org → API Development Tools |
| `BOT_TOKEN` | Talk to [@BotFather](https://t.me/BotFather) → /newbot |

### Step 2 — Push to GitHub
```bash
git init
git add .
git commit -m "SRT bot"
git remote add origin https://github.com/YOUR_USERNAME/srt-bot.git
git push -u origin main
```

### Step 3 — Deploy on Railway
1. Go to https://railway.app → **New Project** → **Deploy from GitHub**
2. Select your repo
3. Go to **Variables** tab and add:
   ```
   API_ID      = your_api_id
   API_HASH    = your_api_hash
   BOT_TOKEN   = your_bot_token
   WHISPER_MODEL = small
   ```
4. Railway auto-detects the Dockerfile and deploys ✅

---

## 🤖 Bot Usage

| Action | Result |
|--------|--------|
| Send video/audio | Bot transcribes and returns `.srt` |
| Hindi detected | Bot asks: Pure Hindi or Hinglish? |
| `/start` | Welcome message |
| `/help` | Usage guide |
| `/cancel` | Cancel current job |

## 📦 Supported Formats
- **Video**: mp4, mkv, avi, mov, webm, flv, ts
- **Audio**: mp3, wav, m4a, aac, ogg, flac, wma

## ⚙️ Model Sizes

| Model | Speed | Accuracy | RAM needed |
|-------|-------|----------|------------|
| `tiny` | Fastest | Low | ~1 GB |
| `base` | Fast | OK | ~1 GB |
| `small` | Balanced ✅ | Good | ~2 GB |
| `medium` | Slow | High | ~5 GB |

Change `WHISPER_MODEL` env var to switch.

---

## 📁 File Structure
```
srt-bot/
├── bot.py           # Main bot logic
├── requirements.txt # Python dependencies
├── Dockerfile       # Railway deployment
└── .env.example     # Environment variable template
```