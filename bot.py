import asyncio
import os
import requests
import json
import shutil
import time
from pathlib import Path
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# KONFIGURASI API
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
LOCAL_API_SERVER = "http://127.0.0.1:8081"
TELEGRAM_DATA_DIR = os.getenv("TELEGRAM_DATA_DIR", "/home/runner/work/Multi-Cloud-Uploader/Multi-Cloud-Uploader/telegram-data")

CACHE_DIR = Path("bot_cache")
CACHE_INDEX = CACHE_DIR / "index.json"

CACHE_DIR.mkdir(exist_ok=True)
if not CACHE_INDEX.exists():
    with open(CACHE_INDEX, "w") as f: json.dump({}, f)

def is_local_api_available():
    if not TELEGRAM_TOKEN: return False
    try:
        resp = requests.get(f"{LOCAL_API_SERVER}/bot{TELEGRAM_TOKEN}/getMe", timeout=2)
        return resp.status_code == 200
    except:
        return False

USE_LOCAL_API = is_local_api_available()

def load_index():
    with open(CACHE_INDEX, "r") as f: return json.load(f)

def save_index(index):
    with open(CACHE_INDEX, "w") as f: json.dump(index, f, indent=4)

CATBOX_API = "https://catbox.moe/user/api.php"
TEMPSH_API = "https://temp.sh/upload"

def upload_to_gofile(file_path: Path):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        server_resp = requests.get("https://api.gofile.io/servers", timeout=15)
        server = server_resp.json()["data"]["servers"][0]["name"]
        url = f"https://{server}.gofile.io/contents/uploadfile"
        with file_path.open("rb") as f:
            resp = requests.post(url, files={"file": (file_path.name, f)}, headers=headers, timeout=600)
        return resp.json()["data"]["downloadPage"]
    except Exception as e: return f"Gofile Error: {str(e)}"

def upload_to_catbox(file_path: Path):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        with file_path.open("rb") as f:
            resp = requests.post(CATBOX_API, data={"req": "upload"}, files={"fileToUpload": (file_path.name, f)}, headers=headers, timeout=600)
        return resp.text.strip()
    except Exception as e: return f"Catbox Error: {str(e)}"

def upload_to_tempsh(file_path: Path):
    try:
        with file_path.open("rb") as f:
            resp = requests.post(TEMPSH_API, files={"file": (file_path.name, f)}, timeout=600)
        return resp.text.strip()
    except Exception as e: return f"Temp.sh Error: {str(e)}"

async def handle_any_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message: return

    attachment = (message.document or message.video or message.audio or 
                  (message.photo[-1] if message.photo else None) or 
                  message.voice or message.video_note or message.animation)
    if not attachment: return

    filename = getattr(attachment, 'file_name', None) or f"file_{attachment.file_unique_id}"
    status_msg = await message.reply_text(f"⏳ Memproses `{filename}`...")
    
    try:
        cached_path = CACHE_DIR / filename
        file_obj = await attachment.get_file()
        
        if USE_LOCAL_API:
            # CARA 1: RETRIEVE (Ambil dari Local API Server)
            server_path = file_obj.file_path
            container_base = "/var/lib/telegram-bot-api"
            
            if server_path.startswith(container_base):
                relative_path = server_path[len(container_base):].lstrip('/')
                host_file_path = Path(TELEGRAM_DATA_DIR) / relative_path
            else:
                host_file_path = Path(TELEGRAM_DATA_DIR) / server_path.lstrip('/')

            # Tunggu fail muncul di cakera
            found = False
            for _ in range(10):
                if host_file_path.exists():
                    found = True
                    break
                time.sleep(1)

            if found:
                shutil.copy2(host_file_path, cached_path)
            else:
                # Sandaran: Cuba muat turun jika fail fizikal tidak dijumpai
                await file_obj.download_to_drive(cached_path)
        else:
            # CARA 2: DOWNLOAD (Guna Standard API)
            await file_obj.download_to_drive(cached_path)

        if not cached_path.exists():
            raise FileNotFoundError("Gagal memproses/memuat turun fail.")

        file_size = f"{os.path.getsize(cached_path) / (1024*1024):.2f} MB"
        index = load_index()
        index[filename] = {"size": file_size, "id": attachment.file_id}
        save_index(index)

        await status_msg.edit_text(f"🚀 Memuat naik `{filename}` ({file_size}) ke 3 Cloud...")
        await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)

        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, upload_to_gofile, cached_path),
            loop.run_in_executor(None, upload_to_catbox, cached_path),
            loop.run_in_executor(None, upload_to_tempsh, cached_path)
        ]
        results = await asyncio.gather(*tasks)
        
        await status_msg.edit_text(
            f"✅ **Selesai!**\n\n📁 **Fail:** `{filename}`\n📊 **Saiz:** `{file_size}`\n\n"
            f"🌐 **Gofile:** {results[0]}\n🐱 **Catbox:** {results[1]}\n⏱ **Temp.sh:** {results[2]}",
            parse_mode='Markdown'
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Ralat: {str(e)}")

def main():
    if not TELEGRAM_TOKEN:
        print("❌ Ralat: TELEGRAM_TOKEN tidak dijumpai dalam persekitaran!")
        return
    
    print(f"Mod API: {'LOCAL' if USE_LOCAL_API else 'STANDARD'}")
    
    if USE_LOCAL_API:
        api_url = f"{LOCAL_API_SERVER}/bot"
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).base_url(api_url).local_mode(True).build()
    else:
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.TEXT, handle_any_media))
    
    print("Bot dimulakan.")
    app.run_polling()

if __name__ == "__main__": main()
