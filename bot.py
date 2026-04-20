import asyncio
import os
import requests
import json
import shutil
import time
import re
import mimetypes
from pathlib import Path

# KONFIGURASI API
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
LOCAL_API_SERVER = "http://127.0.0.1:8081"
TELEGRAM_DATA_DIR = os.getenv("TELEGRAM_DATA_DIR", "/home/runner/tg-api-data")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

CACHE_DIR = Path("bot_cache")
CACHE_INDEX = CACHE_DIR / "index.json"
CACHE_DIR.mkdir(exist_ok=True)

if not CACHE_INDEX.exists():
    with open(CACHE_INDEX, "w") as f: json.dump({}, f)

def load_index():
    try:
        with open(CACHE_INDEX, "r") as f: return json.load(f)
    except: return {}

def save_index(index):
    with open(CACHE_INDEX, "w") as f: json.dump(index, f, indent=4)

def wait_for_local_api():
    if not TELEGRAM_TOKEN: return False
    for _ in range(3):
        try:
            resp = requests.get(f"{LOCAL_API_SERVER}/bot{TELEGRAM_TOKEN}/getMe", timeout=2)
            if resp.status_code == 200: return True
        except: pass
        time.sleep(1)
    return False

USE_LOCAL_API = False
API_URL = BASE_URL

def tg_api_call(method, data=None, files=None):
    try:
        url = f"{API_URL}/{method}"
        resp = requests.post(url, data=data, files=files, timeout=60)
        return resp.json()
    except: return None

def upload_to_earlstore(file_path: Path):
    try:
        url = "https://temp.earlstore.online/api/upload"
        filename = file_path.name
        
        # Teka MIME type berdasarkan extension fail
        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type:
            mime_type = "application/octet-stream"

        with file_path.open("rb") as f:
            # Hantar (filename, fileobj, content_type) secara eksplisit
            files = {"file": (filename, f, mime_type)}
            resp = requests.post(url, files=files, timeout=600)
        
        data = resp.json()
        if "url" in data:
            return data["url"]
        return f"Ralat: {json.dumps(data)}"
    except Exception as e:
        return f"EarlStore Error: {str(e)}"

async def process_media(message):
    chat_id = message['chat']['id']
    attachment = None
    for mt in ['document', 'video', 'audio', 'voice', 'video_note', 'animation', 'photo']:
        if mt in message:
            attachment = message[mt]
            if mt == 'photo': attachment = attachment[-1]
            break
    if not attachment: return

    file_id = attachment['file_id']
    file_unique_id = attachment['file_unique_id']
    file_size_str = f"{attachment.get('file_size', 0) / (1024*1024):.2f} MB"

    # Dapatkan maklumat fail untuk tahu extension sebenar
    file_info = tg_api_call("getFile", {"file_id": file_id})
    if not file_info or not file_info.get('ok'):
        tg_api_call("sendMessage", {"chat_id": chat_id, "text": "❌ Gagal mendapatkan maklumat fail daripada Telegram."})
        return
    
    tg_file_path = file_info['result']['file_path']
    # Ambil extension daripada path Telegram (contoh: .jpg)
    ext = os.path.splitext(tg_file_path)[1]
    
    # Jika extension kosong (jarang berlaku), kita cuba teka atau guna .bin
    if not ext:
        ext = ".bin"

    # Guna file_unique_id + extension sebagai nama fail rasmi untuk diupload
    # Ini menjamin format sentiasa ada dalam request ke API
    filename = f"{file_unique_id}{ext}"
    
    index = load_index()
    cached_path = CACHE_DIR / filename
    
    is_cached = False
    if file_unique_id in index:
        potential_path = Path(index[file_unique_id]['path'])
        if potential_path.exists():
            # Jika fail asal tidak mempunyai extension dalam namanya di cache, 
            # kita namakan semula fail cache tersebut supaya ada extension
            if potential_path.suffix != ext:
                new_path = potential_path.with_suffix(ext)
                potential_path.rename(new_path)
                index[file_unique_id]['path'] = str(new_path)
                save_index(index)
                cached_path = new_path
            else:
                cached_path = potential_path
            is_cached = True

    status_text = f"⏳ Memproses `{filename}`..."
    if is_cached: status_text += " (Dari Cache ⚡)"
    
    status = tg_api_call("sendMessage", {"chat_id": chat_id, "text": status_text, "parse_mode": "Markdown"})
    if not status: return
    status_id = status['result']['message_id']
    
    try:
        if not is_cached:
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{tg_file_path}"
            r = requests.get(file_url, stream=True)
            with open(cached_path, 'wb') as f: shutil.copyfileobj(r.raw, f)
            
            index[file_unique_id] = {"path": str(cached_path), "name": filename}
            save_index(index)

        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"🚀 Memuat naik `{filename}` ({file_size_str}) ke EarlStore...", "parse_mode": "Markdown"})

        # Muat naik ke EarlStore secara asinkron (menggunakan run_in_executor untuk requests yang menyekat)
        earl_link = await asyncio.get_event_loop().run_in_executor(None, upload_to_earlstore, cached_path)
        
        tg_api_call("editMessageText", {
            "chat_id": chat_id, "message_id": status_id,
            "text": (
                f"✅ **Selesai!**\n\n"
                f"📁 **Fail:** `{filename}`\n"
                f"📊 **Saiz:** `{file_size_str}`\n\n"
                f"🌐 **Pautan:** {earl_link}"
            ),
            "parse_mode": "Markdown", "disable_web_page_preview": True
        })
    except Exception as e:
        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"❌ Ralat: {str(e)}"})

async def main():
    global USE_LOCAL_API, API_URL
    USE_LOCAL_API = wait_for_local_api()
    API_URL = f"{LOCAL_API_SERVER}/bot{TELEGRAM_TOKEN}" if USE_LOCAL_API else BASE_URL
    print(f"Bot dimulakan.")
    
    offset = 0
    while True:
        try:
            updates = tg_api_call("getUpdates", {"offset": offset, "timeout": 30})
            if updates and updates.get('ok'):
                for u in updates['result']:
                    offset = u['update_id'] + 1
                    if 'message' in u:
                        asyncio.create_task(process_media(u['message']))
            await asyncio.sleep(0.5)
        except: await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
