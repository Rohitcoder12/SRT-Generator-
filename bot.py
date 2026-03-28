"""
🎬 SRT Generator Telegram Bot
- faster-whisper (no PyTorch) — image stays under 4 GB on Railway
- Auto-detects language
- Hindi detected → asks Hinglish or Pure Hindi
"""

import os
import re
import uuid
import asyncio
from pathlib import Path
from faster_whisper import WhisperModel
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# ── Config ────────────────────────────────────────────────────────────────────
API_ID    = int(os.environ["API_ID"])
API_HASH  = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
MODEL_NAME = os.environ.get("WHISPER_MODEL", "small")

DOWNLOAD_DIR = Path("/tmp/srt_downloads")
OUTPUT_DIR   = Path("/tmp/srt_outputs")
MODEL_DIR    = Path("/tmp/whisper_models")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

print(f"⏳ Loading faster-whisper model: {MODEL_NAME} ...")
# cpu + int8 = smallest RAM footprint, works on Railway free tier
model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", download_root=str(MODEL_DIR))
print("✅ Model loaded!")

# ── Pending state: user_id → { segments, job_id } ────────────────────────────
pending = {}

app = Client("srt_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ── Helpers ───────────────────────────────────────────────────────────────────

def format_ts(seconds: float) -> str:
    ms = round(seconds * 1000)
    h = ms // 3_600_000; ms %= 3_600_000
    m = ms // 60_000;    ms %= 60_000
    s = ms // 1_000;     ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(f"{i}\n{format_ts(seg['start'])} --> {format_ts(seg['end'])}\n{seg['text'].strip()}\n")
    return "\n".join(lines)


DEVANAGARI_MAP = {
    "अ":"a","आ":"aa","इ":"i","ई":"ee","उ":"u","ऊ":"oo","ए":"e","ऐ":"ai",
    "ओ":"o","औ":"au","अं":"an","अः":"ah",
    "क":"k","ख":"kh","ग":"g","घ":"gh","च":"ch","छ":"chh","ज":"j","झ":"jh",
    "ट":"t","ठ":"th","ड":"d","ढ":"dh","ण":"n","त":"t","थ":"th","द":"d",
    "ध":"dh","न":"n","प":"p","फ":"ph","ब":"b","भ":"bh","म":"m","य":"y",
    "र":"r","ल":"l","व":"v","श":"sh","ष":"sh","स":"s","ह":"h",
    "ा":"a","ि":"i","ी":"ee","ु":"u","ू":"oo","े":"e","ै":"ai","ो":"o",
    "ौ":"au","ं":"n","्":"","ः":"h","ँ":"n",
    "क्ष":"ksh","त्र":"tr","ज्ञ":"gya","।":"."," ":" ",
}

def to_hinglish(text: str) -> str:
    result = ""
    i = 0
    while i < len(text):
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
    return re.sub(r" +", " ", result).strip()


def apply_hinglish(segments: list) -> list:
    return [{**s, "text": to_hinglish(s["text"])} for s in segments]


async def transcribe(file_path: str):
    """Run faster-whisper in thread executor (non-blocking)."""
    loop = asyncio.get_event_loop()

    def _run():
        segs, info = model.transcribe(file_path, beam_size=5)
        segments = [{"start": s.start, "end": s.end, "text": s.text} for s in segs]
        return segments, info.language

    return await loop.run_in_executor(None, _run)


# ── Commands ──────────────────────────────────────────────────────────────────

@app.on_message(filters.command("start"))
async def start(_, m: Message):
    await m.reply_text(
        "👋 **SRT Generator Bot**\n\n"
        "Send me any **video** or **audio** file → I'll return a `.srt` subtitle file!\n\n"
        "✅ MP4, MKV, AVI, MOV, MP3, WAV, M4A, AAC and more\n"
        "🌐 Auto language detection\n"
        "🇮🇳 Hindi → choose **Pure Hindi** or **Hinglish**\n\n"
        "Just send your file! 🎬"
    )


@app.on_message(filters.command("help"))
async def help_cmd(_, m: Message):
    await m.reply_text(
        "📖 **How to use:**\n"
        "1. Send any video or audio file\n"
        "2. Wait for transcription\n"
        "3. If Hindi → choose script format\n"
        "4. Get your `.srt` file!\n\n"
        "/start — Welcome\n"
        "/help  — This message\n"
        "/cancel — Cancel current job"
    )


@app.on_message(filters.command("cancel"))
async def cancel(_, m: Message):
    uid = m.from_user.id
    if uid in pending:
        del pending[uid]
        await m.reply_text("❌ Cancelled.")
    else:
        await m.reply_text("Nothing to cancel.")


# ── Media handler ─────────────────────────────────────────────────────────────

@app.on_message(filters.video | filters.audio | filters.voice | filters.document)
async def handle_media(_, m: Message):
    uid = m.from_user.id
    media = m.video or m.audio or m.voice or m.document
    if not media:
        return

    # Check extension for documents
    if m.document:
        fname = m.document.file_name or ""
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
        if ext not in {"mp4","mkv","avi","mov","webm","flv","ts","mp3","wav","m4a","aac","ogg","flac","wma"}:
            await m.reply_text("⚠️ Unsupported file. Send a video or audio file.")
            return

    if (media.file_size or 0) > 400 * 1024 * 1024:
        await m.reply_text("❌ File too large. Max 400 MB.")
        return

    status = await m.reply_text("📥 Downloading...")

    job_id = str(uuid.uuid4())[:8]
    dl_path = DOWNLOAD_DIR / f"{uid}_{job_id}"

    try:
        downloaded = await m.download(file_name=str(dl_path))
    except Exception as e:
        await status.edit_text(f"❌ Download failed: {e}")
        return

    await status.edit_text("🎙️ Transcribing... _(may take a few minutes for long files)_")

    try:
        segments, lang = await transcribe(downloaded)
    except Exception as e:
        await status.edit_text(f"❌ Transcription failed:\n`{e}`")
        return
    finally:
        Path(downloaded).unlink(missing_ok=True)

    if not segments:
        await status.edit_text("⚠️ No speech detected.")
        return

    if lang == "hi":
        pending[uid] = {"segments": segments, "job_id": job_id, "msg": m}
        await status.edit_text(
            f"✅ Done! Detected: **Hindi** 🇮🇳\n\nWhich format for your `.srt`?",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🇮🇳 Pure Hindi", callback_data=f"hindi_{uid}_{job_id}"),
                InlineKeyboardButton("🔤 Hinglish",    callback_data=f"hinglish_{uid}_{job_id}"),
            ]])
        )
    else:
        await status.edit_text(f"✅ Done! Language: **{lang.upper()}** — generating SRT...")
        await send_srt(m, segments, lang, job_id, status)


async def send_srt(m: Message, segments: list, lang: str, job_id: str, status=None):
    uid = m.from_user.id
    out = OUTPUT_DIR / f"{uid}_{job_id}.srt"
    out.write_text(segments_to_srt(segments), encoding="utf-8")

    # Get original filename stem
    stem = "subtitle"
    for attr in (m.video, m.audio, m.document):
        if attr and getattr(attr, "file_name", None):
            stem = Path(attr.file_name).stem
            break

    try:
        await m.reply_document(
            document=str(out),
            file_name=f"{stem}_{lang}.srt",
            caption=(
                f"🎉 Your `.srt` file is ready!\n"
                f"🌐 Language: `{lang}`\n"
                f"📝 Lines: `{len(segments)}`\n\n"
                f"_Import into CapCut, Premiere, DaVinci, or VLC!_"
            )
        )
        if status:
            await status.delete()
    except Exception as e:
        if status:
            await status.edit_text(f"❌ Failed to send: {e}")
    finally:
        out.unlink(missing_ok=True)


# ── Callback: Hindi/Hinglish choice ──────────────────────────────────────────

@app.on_callback_query()
async def on_choice(_, cq):
    await cq.answer()
    parts = cq.data.split("_")  # e.g. ["hindi","123456","abc12345"]
    if len(parts) < 2:
        return

    choice = parts[0]   # "hindi" or "hinglish"
    uid    = int(parts[1])

    if uid not in pending:
        await cq.message.edit_text("⚠️ Session expired. Please resend your file.")
        return

    state    = pending.pop(uid)
    segments = state["segments"]
    job_id   = state["job_id"]
    orig_msg = state["msg"]

    if choice == "hinglish":
        segments   = apply_hinglish(segments)
        lang_label = "Hinglish"
    else:
        lang_label = "Hindi"

    await cq.message.edit_text(f"📄 Generating {lang_label} SRT...")

    out = OUTPUT_DIR / f"{uid}_{job_id}.srt"
    out.write_text(segments_to_srt(segments), encoding="utf-8")

    try:
        await orig_msg.reply_document(
            document=str(out),
            file_name=f"subtitles_{lang_label}.srt",
            caption=(
                f"🎉 Your `.srt` file is ready!\n"
                f"🌐 Format: `{lang_label}`\n"
                f"📝 Lines: `{len(segments)}`\n\n"
                f"_Import into CapCut, Premiere, DaVinci, or VLC!_"
            )
        )
        await cq.message.delete()
    except Exception as e:
        await cq.message.edit_text(f"❌ Failed to send: {e}")
    finally:
        out.unlink(missing_ok=True)


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 SRT Bot is running...")
    app.run()