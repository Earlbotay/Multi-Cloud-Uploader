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
CATBOX_API = "https://catbox.moe/user/api.php"
TEMPSH_API = "https://temp.sh/upload"

def upload_to_gofile(file_path: Path):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # Step 1: Get best server (Updated API)
        server_resp = requests.get("https://api.gofile.io/servers", headers=headers, timeout=10)
        if server_resp.status_code != 200:
            return f"Gofile: Server list error ({server_resp.status_code})"
        
        server_data = server_resp.json()
        if server_data.get("status") != "ok":
            return f"Gofile: {server_data.get('status')}"
            
        server = server_data["data"]["servers"][0]["name"]
        url = f"https://{server}.gofile.io/contents/uploadfile"
        
        with file_path.open("rb") as f:
            resp = requests.post(url, files={"file": (file_path.name, f)}, headers=headers, timeout=60)
            
        if resp.status_code != 200:
            return f"Gofile: Upload error ({resp.status_code})"
            
        data = resp.json()
        if data.get("status") == "ok":
            return data["data"]["downloadPage"]
        return f"Gofile: {data.get('status', 'Upload failed')}"
    except Exception as e:
        return f"Gofile Error: {str(e)}"

def upload_to_catbox(file_path: Path):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with file_path.open("rb") as f:
            resp = requests.post(
                CATBOX_API, 
                data={"req": "upload"}, 
                files={"fileToUpload": (file_path.name, f)},
                headers=headers,
                timeout=60
            )
        if resp.status_code == 200:
            return resp.text.strip()
        return f"Catbox: Failed ({resp.status_code})"
    except Exception as e:
        return f"Catbox Error: {str(e)}"

def upload_to_tempsh(file_path: Path):
    try:
        with file_path.open("rb") as f:
            resp = requests.post(TEMPSH_API, files={"file": (file_path.name, f)}, timeout=60)
        if resp.status_code == 200:
            return resp.text.strip()
        return f"Temp.sh: Failed ({resp.status_code})"
    except Exception as e:
        return f"Temp.sh Error: {str(e)}"

async def handle_any_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    # Detect any attachment type
    attachment = (
        message.document or 
        message.video or 
        message.audio or 
        (message.photo[-1] if message.photo else None) or 
        message.voice or 
        message.video_note or
        message.animation
    )

    if not attachment:
        return

    # Determine filename
    filename = getattr(attachment, 'file_name', None)
    if not filename:
        if message.photo: filename = "photo.jpg"
        elif message.voice: filename = "voice.ogg"
        elif message.video_note: filename = "video_note.mp4"
        elif message.animation: filename = "animation.gif"
        else: filename = "file"

    status_msg = await message.reply_text(f"⏳ Sedang memproses `{filename}`...")
    
    try:
        file_obj = await attachment.get_file()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / filename
            await file_obj.download_to_drive(str(local_path))

            await status_msg.edit_text(f"🚀 Memuat naik `{filename}` ke 3 Cloud...")
            await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)

            # Parallel uploads
            loop = asyncio.get_event_loop()
            tasks = [
                loop.run_in_executor(None, upload_to_gofile, local_path),
                loop.run_in_executor(None, upload_to_catbox, local_path),
                loop.run_in_executor(None, upload_to_tempsh, local_path)
            ]
            
            results = await asyncio.gather(*tasks)
            
            response_text = (
                f"✅ **Muat Naik Selesai!**\n\n"
                f"📁 **Fail:** `{filename}`\n\n"
                f"🌐 **Gofile:** {results[0]}\n"
                f"🐱 **Catbox:** {results[1]}\n"
                f"⏱ **Temp.sh:** {results[2]}"
            )
            
            await status_msg.edit_text(response_text, parse_mode='Markdown')
    except Exception as e:
        await status_msg.edit_text(f"❌ Ralat: {str(e)}")

def main():
    if not TELEGRAM_TOKEN:
        print("Ralat: TELEGRAM_TOKEN tidak dijumpai.")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Handle all media except commands and text
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.TEXT, handle_any_media))
    
    print("Bot dimulakan...")
    app.run_polling()

if __name__ == "__main__":
    main()
