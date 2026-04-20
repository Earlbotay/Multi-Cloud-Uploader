import asyncio
import os
import json
import shutil
import time
import subprocess
import requests
import math
import uuid
from pathlib import Path

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
LOCAL_API_URL = "http://127.0.0.1:8081"
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

def check_local_api():
    """Semak jika Local API Server sedang berjalan."""
    try:
        resp = requests.get(f"{LOCAL_API_URL}/bot{TELEGRAM_TOKEN}/getMe", timeout=2)
        return resp.status_code == 200
    except:
        return False

IS_LOCAL = check_local_api()
BASE_URL = f"{LOCAL_API_URL}/bot{TELEGRAM_TOKEN}" if IS_LOCAL else f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

print(f"INFO: Menggunakan {'Local API Server' if IS_LOCAL else 'Official Telegram API'}")

def tg_api_call(method, data=None):
    try:
        url = f"{BASE_URL}/{method}"
        resp = requests.post(url, data=data, timeout=60)
        return resp.json()
    except Exception as e:
        print(f"API Error ({method}): {e}")
        return None

def upload_to_earlstore(file_path: Path):
    """Memuat naik ke EarlStore menggunakan chunked upload (5MB per chunk)."""
    try:
        url = "https://temp.earlstore.online/api/upload"

        if not file_path.exists() or file_path.stat().st_size == 0:
            return "❌ Ralat: Fail kosong atau tidak wujud di server."

        file_size = file_path.stat().st_size
        chunk_size = 5 * 1024 * 1024  # 5MB
        total_chunks = math.ceil(file_size / chunk_size)
        upload_id = str(uuid.uuid4())

        final_url = None

        with open(file_path, "rb") as f:
            for i in range(total_chunks):
                chunk_data = f.read(chunk_size)

                payload = {
                    "chunk_index": i,
                    "total_chunks": total_chunks,
                    "upload_id": upload_id
                }
                files = {"file": (file_path.name, chunk_data)}

                # Gunakan timeout yang lebih lama untuk fail besar
                resp = requests.post(url, data=payload, files=files, timeout=120)

                if resp.status_code == 200:
                    data = resp.json()
                    if "url" in data:
                        final_url = data["url"]
                else:
                    return f"❌ EarlStore Error (Part {i+1}): {resp.text}"

        return final_url or "❌ Error: Gagal mendapatkan URL akhir."
    except Exception as e:
        return f"❌ EarlStore Error: {str(e)}"
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
    file_size_mb = attachment.get('file_size', 0) / (1024 * 1024)
    file_size_str = f"{file_size_mb:.2f} MB"

    file_info = tg_api_call("getFile", {"file_id": file_id})
    if not file_info or not file_info.get('ok'):
        tg_api_call("sendMessage", {"chat_id": chat_id, "text": "❌ Gagal mendapatkan info fail."})
        return

    tg_file_path = file_info['result']['file_path']
    ext = os.path.splitext(tg_file_path)[1] or ".bin"
    filename = f"{file_unique_id}{ext}"
    cached_path = CACHE_DIR / filename

    index = load_index()
    is_cached = file_unique_id in index and Path(index[file_unique_id]['path']).exists()
    
    if is_cached:
        cached_path = Path(index[file_unique_id]['path'])
        # Sahkan saiz fail cache
        if cached_path.stat().st_size == 0:
            is_cached = False # Jika 0MB, kita paksa download balik

    status_msg = f"⏳ Memproses {filename}... {'(⚡ Cache)' if is_cached else ''}"
    status = tg_api_call("sendMessage", {"chat_id": chat_id, "text": status_msg})
    if not status: return
    status_id = status['result']['message_id']

    try:
        if not is_cached:
            tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"📥 Menyediakan fail {filename} ({file_size_str})..."})
            
            if IS_LOCAL:
                # Jika Local API, tg_file_path adalah path penuh di disk
                source_path = Path(tg_file_path)
                if source_path.exists():
                    shutil.copy2(source_path, cached_path)
                else:
                    raise Exception(f"Fail tidak dijumpai di disk Local API: {tg_file_path}")
            else:
                # Jika Official API, muat turun melalui HTTP
                file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{tg_file_path}"
                with requests.get(file_url, stream=True) as r:
                    r.raise_for_status()
                    with open(cached_path, 'wb') as f:
                        shutil.copyfileobj(r.raw, f)
            
            # Sahkan saiz selepas muat turun
            if cached_path.stat().st_size == 0:
                raise Exception("Muat turun berjaya tapi fail bersaiz 0MB.")

            index[file_unique_id] = {"path": str(cached_path), "name": filename}
            save_index(index)

        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"🚀 Memuat naik ke EarlStore..."})
        
        loop = asyncio.get_event_loop()
        earl_link = await loop.run_in_executor(None, upload_to_earlstore, cached_path)

        tg_api_call("editMessageText", {
            "chat_id": chat_id, "message_id": status_id,
            "text": (
                f"✅ Selesai!\n\n"
                f"📁 Fail: {filename}\n"
                f"📊 Saiz: {file_size_str}\n\n"
                f"🌐 Pautan: {earl_link}"
            ),
            "disable_web_page_preview": True
        })

    except Exception as e:
        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"❌ Ralat: {str(e)}"})

async def main():
    if not TELEGRAM_TOKEN:
        print("Ralat: TELEGRAM_TOKEN tidak ditetapkan!")
        return
        
    print(f"🤖 Bot EarlStore dimulakan ({'LOCAL' if IS_LOCAL else 'OFFICIAL'})...")
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
        except Exception as e:
            print(f"Loop error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
