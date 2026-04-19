import asyncio
import os
import tempfile
import requests
from pathlib import Path
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# API Endpoints
GOFILE_API = "https://store1.gofile.io/uploadFile" # Note: Gofile often changes stores, this might need dynamic fetching
CATBOX_API = "https://catbox.moe/user/api.php"
TEMPSH_API = "https://temp.sh/upload"

def upload_to_gofile(file_path: Path):
    try:
        # Step 1: Get best server
        server_resp = requests.get("https://api.gofile.io/getServer")
        server = server_resp.json()["data"]["server"]
        url = f"https://{server}.gofile.io/uploadFile"
        
        with file_path.open("rb") as f:
            resp = requests.post(url, files={"file": (file_path.name, f)})
        data = resp.json()
        if data.get("status") == "ok":
            return data["data"]["downloadPage"]
        return "Gofile: Failed"
    except Exception as e:
        return f"Gofile Error: {e}"

def upload_to_catbox(file_path: Path):
    try:
        with file_path.open("rb") as f:
            resp = requests.post(CATBOX_API, data={"req": "upload"}, files={"fileToUpload": (file_path.name, f)})
        if resp.status_code == 200:
            return resp.text.strip()
        return "Catbox: Failed"
    except Exception as e:
        return f"Catbox Error: {e}"

def upload_to_tempsh(file_path: Path):
    try:
        with file_path.open("rb") as f:
            resp = requests.post(TEMPSH_API, files={"file": (file_path.name, f)})
        if resp.status_code == 200:
            return resp.text.strip()
        return "Temp.sh: Failed"
    except Exception as e:
        return f"Temp.sh Error: {e}"

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    file_obj = None
    filename = "file"

    if message.document:
        file_obj = await message.document.get_file()
        filename = message.document.file_name
    elif message.video:
        file_obj = await message.video.get_file()
        filename = message.video.file_name or "video.mp4"
    elif message.audio:
        file_obj = await message.audio.get_file()
        filename = message.audio.file_name or "audio.mp3"
    elif message.photo:
        file_obj = await message.photo[-1].get_file()
        filename = "photo.jpg"
    elif message.voice:
        file_obj = await message.voice.get_file()
        filename = "voice.ogg"
    elif message.video_note:
        file_obj = await message.video_note.get_file()
        filename = "video_note.mp4"
    else:
        return

    status_msg = await message.reply_text("⏳ Downloading from Telegram...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / filename
        await file_obj.download_to_drive(str(local_path))

        await status_msg.edit_text("🚀 Uploading to multiple clouds...")
        await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)

        # Run uploads in parallel
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, upload_to_gofile, local_path),
            loop.run_in_executor(None, upload_to_catbox, local_path),
            loop.run_in_executor(None, upload_to_tempsh, local_path)
        ]
        
        results = await asyncio.gather(*tasks)
        
        response_text = (
            f"✅ **Upload Complete!**\n\n"
            f"📁 **File:** `{filename}`\n\n"
            f"🌐 **Gofile:** {results[0]}\n"
            f"🐱 **Catbox:** {results[1]}\n"
            f"⏱ **Temp.sh:** {results[2]}"
        )
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')

def main():
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN not found in environment.")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Handle all types of media
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE | filters.VIDEO_NOTE, 
        handle_media
    ))
    
    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
