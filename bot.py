"""
🎬 SRT Generator Telegram Bot
- Send any video/audio → get .srt subtitle file back
- Auto-detects language
- If Hindi detected → asks Hinglish or Pure Hindi
- Deployable on Railway
"""

import os
import re
import uuid
import asyncio
import whisper
from pathlib import Path
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# ── Config ────────────────────────────────────────────────────────────────────
API_ID   = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

DOWNLOAD_DIR = Path("/tmp/srt_downloads")
OUTPUT_DIR   = Path("/tmp/srt_outputs")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Whisper model — "small" is best balance for Railway free tier
# Change to "medium" if you upgrade Railway plan
MODEL_NAME = os.environ.get("WHISPER_MODEL", "small")

print(f"⏳ Loading Whisper model: {MODEL_NAME} ...")
# Use /tmp so model isn't baked into Docker image (keeps image < 4 GB on Railway)
model = whisper.load_model(MODEL_NAME, download_root="/tmp/whisper_models")
print("✅ Whisper model loaded!")

# ── In-memory state: user_id → { file_path, segments, detected_lang } ─────────
pending = {}

app = Client("srt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h = ms // 3_600_000; ms %= 3_600_000
    m = ms // 60_000;    ms %= 60_000
    s = ms // 1_000;     ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = format_timestamp(seg["start"])
        end   = format_timestamp(seg["end"])
        text  = seg["text"].strip()
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


# ── Devanagari → Roman transliteration table ──────────────────────────────────
DEVANAGARI_MAP = {
    "अ":"a","आ":"aa","इ":"i","ई":"ee","उ":"u","ऊ":"oo","ए":"e","ऐ":"ai",
    "ओ":"o","औ":"au","अं":"an","अः":"ah",
    "क":"k","ख":"kh","ग":"g","घ":"gh","ङ":"ng",
    "च":"ch","छ":"chh","ज":"j","झ":"jh","ञ":"n",
    "ट":"t","ठ":"th","ड":"d","ढ":"dh","ण":"n",
    "त":"t","थ":"th","द":"d","ध":"dh","न":"n",
    "प":"p","फ":"ph","ब":"b","भ":"bh","म":"m",
    "य":"y","र":"r","ल":"l","व":"v","श":"sh",
    "ष":"sh","स":"s","ह":"h",
    "ा":"a","ि":"i","ी":"ee","ु":"u","ू":"oo",
    "े":"e","ै":"ai","ो":"o","ौ":"au","ं":"n",
    "्":"","ः":"h","ँ":"n",
    "क्ष":"ksh","त्र":"tr","ज्ञ":"gya",
    "।":"."," ":" ",
}

def hindi_to_hinglish(text: str) -> str:
    """Convert Devanagari script to Roman (Hinglish) transliteration."""
    result = ""
    i = 0
    while i < len(text):
        # Try 3-char, 2-char, 1-char match
        matched = False
        for length in (3, 2, 1):
            chunk = text[i:i+length]
            if chunk in DEVANAGARI_MAP:
                result += DEVANAGARI_MAP[chunk]
                i += length
                matched = True
                break
        if not matched:
            result += text[i]
            i += 1
    # Clean up double spaces
    result = re.sub(r" +", " ", result).strip()
    return result


def apply_hinglish(segments: list) -> list:
    """Return new segments with Hinglish text."""
    return [
        {**seg, "text": hindi_to_hinglish(seg["text"])}
        for seg in segments
    ]


def save_srt(segments: list, output_path: Path) -> Path:
    output_path.write_text(segments_to_srt(segments), encoding="utf-8")
    return output_path


async def transcribe_file(file_path: str) -> dict:
    """Run Whisper transcription in a thread executor (non-blocking)."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: model.transcribe(file_path, verbose=False)
    )
    return result


# ── Bot Handlers ──────────────────────────────────────────────────────────────

@app.on_message(filters.command("start"))
async def start(_, message: Message):
    await message.reply_text(
        "👋 **SRT Generator Bot**\n\n"
        "Send me any **video** or **audio** file and I'll generate an `.srt` subtitle file for it!\n\n"
        "✅ Supports: MP4, MKV, AVI, MOV, MP3, WAV, M4A, AAC and more\n"
        "🌐 Auto-detects language\n"
        "🇮🇳 Hindi → choose **Pure Hindi** or **Hinglish** (Roman script)\n\n"
        "Just send your file to get started! 🎬"
    )


@app.on_message(filters.command("help"))
async def help_cmd(_, message: Message):
    await message.reply_text(
        "📖 **How to use:**\n\n"
        "1. Send any video or audio file\n"
        "2. Wait for transcription (depends on file length)\n"
        "3. If Hindi is detected, choose your script format\n"
        "4. Receive your `.srt` file!\n\n"
        "⚙️ **Commands:**\n"
        "/start — Welcome message\n"
        "/help  — This help message\n"
        "/cancel — Cancel current job\n\n"
        "📦 **Supported formats:**\n"
        "Video: mp4, mkv, avi, mov, webm, flv\n"
        "Audio: mp3, wav, m4a, aac, ogg, flac"
    )


@app.on_message(filters.command("cancel"))
async def cancel(_, message: Message):
    uid = message.from_user.id
    if uid in pending:
        del pending[uid]
        await message.reply_text("❌ Job cancelled.")
    else:
        await message.reply_text("Nothing to cancel.")


@app.on_message(filters.video | filters.audio | filters.voice | filters.document)
async def handle_media(_, message: Message):
    uid = message.from_user.id

    # ── Determine file info ───────────────────────────────────────────────────
    media = message.video or message.audio or message.voice or message.document
    if not media:
        return

    # For documents, check extension
    if message.document:
        fname = message.document.file_name or ""
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
        allowed = {"mp4","mkv","avi","mov","webm","flv","ts","mp3","wav","m4a","aac","ogg","flac","wma"}
        if ext not in allowed:
            await message.reply_text(
                "⚠️ Unsupported file type.\n"
                "Please send a video or audio file (mp4, mkv, mp3, wav, m4a, etc.)"
            )
            return

    file_size_mb = (media.file_size or 0) / (1024 * 1024)
    if file_size_mb > 400:
        await message.reply_text("❌ File too large. Maximum size is 400 MB.")
        return

    # ── Download ──────────────────────────────────────────────────────────────
    status_msg = await message.reply_text("📥 Downloading your file...")

    job_id   = str(uuid.uuid4())[:8]
    file_path = DOWNLOAD_DIR / f"{uid}_{job_id}"

    try:
        downloaded = await message.download(file_name=str(file_path))
    except Exception as e:
        await status_msg.edit_text(f"❌ Download failed: {e}")
        return

    # ── Transcribe ────────────────────────────────────────────────────────────
    await status_msg.edit_text(
        "🎙️ Transcribing audio...\n"
        "_(This may take a few minutes for long files)_"
    )

    try:
        result = await transcribe_file(downloaded)
    except Exception as e:
        await status_msg.edit_text(f"❌ Transcription failed:\n`{e}`")
        return

    segments      = result.get("segments", [])
    detected_lang = result.get("language", "unknown")

    if not segments:
        await status_msg.edit_text("⚠️ No speech detected in this file.")
        return

    # ── Language routing ──────────────────────────────────────────────────────
    if detected_lang == "hi":
        # Store state and ask user
        pending[uid] = {
            "segments": segments,
            "status_msg_id": status_msg.id,
            "job_id": job_id,
        }
        await status_msg.edit_text(
            f"✅ Transcription done!\n"
            f"🌐 Detected language: **Hindi** 🇮🇳\n\n"
            f"Which format do you want for your `.srt`?",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🇮🇳 Pure Hindi (देवनागरी)", callback_data=f"lang_hindi_{uid}"),
                    InlineKeyboardButton("🔤 Hinglish (Roman)", callback_data=f"lang_hinglish_{uid}"),
                ]
            ])
        )
    else:
        # Non-Hindi: send SRT directly
        await status_msg.edit_text(
            f"✅ Transcription done!\n"
            f"🌐 Detected language: **{detected_lang.upper()}**\n\n"
            f"📄 Generating your `.srt` file..."
        )
        await send_srt(message, segments, detected_lang, job_id, status_msg)


async def send_srt(
    message: Message,
    segments: list,
    lang: str,
    job_id: str,
    status_msg=None
):
    """Save and send the SRT file to the user."""
    uid = message.from_user.id
    out_path = OUTPUT_DIR / f"{uid}_{job_id}_{lang}.srt"
    save_srt(segments, out_path)

    original_name = "subtitle"
    if message.video and message.video.file_name:
        original_name = Path(message.video.file_name).stem
    elif message.audio and message.audio.file_name:
        original_name = Path(message.audio.file_name).stem
    elif message.document and message.document.file_name:
        original_name = Path(message.document.file_name).stem

    srt_filename = f"{original_name}_{lang}.srt"

    caption = (
        f"🎉 Here's your `.srt` file!\n"
        f"🌐 Language: `{lang}`\n"
        f"📝 Subtitles: `{len(segments)}` lines\n\n"
        f"_Drop this file into CapCut, Premiere, DaVinci, VLC or any editor!_"
    )

    try:
        await message.reply_document(
            document=str(out_path),
            file_name=srt_filename,
            caption=caption,
        )
        if status_msg:
            await status_msg.delete()
    except Exception as e:
        if status_msg:
            await status_msg.edit_text(f"❌ Failed to send file: {e}")
    finally:
        # Cleanup
        out_path.unlink(missing_ok=True)
        # Clean up download file
        for f in DOWNLOAD_DIR.glob(f"{uid}_*"):
            f.unlink(missing_ok=True)


# ── Callback: Hindi / Hinglish choice ─────────────────────────────────────────

@app.on_callback_query()
async def handle_callback(_, callback_query):
    data = callback_query.data  # e.g. "lang_hindi_123456" or "lang_hinglish_123456"
    await callback_query.answer()

    parts = data.split("_")
    if len(parts) < 3:
        return

    choice = parts[1]        # "hindi" or "hinglish"
    uid    = int(parts[2])

    if uid not in pending:
        await callback_query.message.edit_text("⚠️ Session expired. Please resend your file.")
        return

    state    = pending.pop(uid)
    segments = state["segments"]
    job_id   = state["job_id"]

    await callback_query.message.edit_text("📄 Generating your `.srt` file...")

    if choice == "hinglish":
        segments = apply_hinglish(segments)
        lang_label = "Hinglish"
    else:
        lang_label = "Hindi"

    out_path = OUTPUT_DIR / f"{uid}_{job_id}_{lang_label}.srt"
    save_srt(segments, out_path)

    caption = (
        f"🎉 Here's your `.srt` file!\n"
        f"🌐 Language: `{lang_label}`\n"
        f"📝 Subtitles: `{len(segments)}` lines\n\n"
        f"_Drop this into CapCut, Premiere, DaVinci, or VLC!_"
    )

    try:
        await callback_query.message.reply_document(
            document=str(out_path),
            file_name=f"subtitles_{lang_label}.srt",
            caption=caption,
        )
        await callback_query.message.delete()
    except Exception as e:
        await callback_query.message.edit_text(f"❌ Failed to send: {e}")
    finally:
        out_path.unlink(missing_ok=True)
        for f in DOWNLOAD_DIR.glob(f"{uid}_*"):
            f.unlink(missing_ok=True)


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 SRT Bot is running...")
    app.run()