import asyncio
import os
import requests
import json
import shutil
import time
import re
from pathlib import Path
from urllib.parse import urlparse

# KONFIGURASI API
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
LOCAL_API_SERVER = "http://127.0.0.1:8081"
TELEGRAM_DATA_DIR = os.getenv("TELEGRAM_DATA_DIR", "/home/runner/tg-api-data")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

CACHE_DIR = Path("bot_cache")
CACHE_DIR.mkdir(exist_ok=True)

def tg_api_call(method, data=None, files=None):
    try:
        resp = requests.post(f"{BASE_URL}/{method}", data=data, files=files, timeout=60)
        return resp.json()
    except: return None

def sanitize_filename(name: str):
    # Ganti ruang ke underscore, buang simbol pelik
    clean = name.replace(" ", "_")
    clean = re.sub(r'[^a-zA-Z0-9._-]', '', clean)
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_')

def upload_to_gofile(file_path: Path):
    try:
        s_resp = requests.get("https://api.gofile.io/servers").json()
        s = s_resp["data"]["servers"][0]["name"]
        with file_path.open("rb") as f:
            r = requests.post(f"https://{s}.gofile.io/contents/uploadfile", files={"file": (file_path.name, f)})
        return r.json()["data"]["downloadPage"]
    except: return "Gofile Error"

def upload_to_tempsh(file_path: Path, target_name: str):
    try:
        with file_path.open("rb") as f:
            # Muat naik fail
            r = requests.post("https://temp.sh/upload", files={'file': (target_name, f)})
            raw_url = r.text.strip()
            
            # --- V13 OMEGA ULTIMATE RECONSTRUCTION ---
            # Kita bedah URL secara manual untuk paksa nama fail asal
            # Contoh: https://temp.sh/abcde/NamaSalah.zip
            if "temp.sh" in raw_url:
                parsed = urlparse(raw_url)
                path_parts = parsed.path.strip('/').split('/')
                if len(path_parts) >= 1:
                    file_id = path_parts[0] # Ambil 'abcde'
                    return f"https://temp.sh/{file_id}/{target_name}"
            return raw_url
    except: return "Temp.sh Error"

async def process_media(message):
    chat_id = message['chat']['id']
    att = None
    for mt in ['document', 'video', 'audio', 'photo', 'video_note', 'animation']:
        if mt in message:
            att = message[mt]
            if mt == 'photo': att = att[-1]
            break
    if not att: return

    # FIX NAMA FAIL SEAWAL MUNGKIN
    raw_fn = att.get('file_name') or f"file_{att['file_unique_id']}"
    filename = sanitize_filename(raw_fn)
    
    status = tg_api_call("sendMessage", {"chat_id": chat_id, "text": f"⏳ Memproses `{filename}`..."})
    if not status: return
    status_id = status['result']['message_id']
    
    try:
        cached_path = CACHE_DIR / filename
        file_info = tg_api_call("getFile", {"file_id": att['file_id']})
        if not file_info or not file_info.get('ok'): raise Exception("Info fail gagal")
        
        # Download fail
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info['result']['file_path']}"
        with requests.get(file_url, stream=True) as r:
            r.raise_for_status()
            with open(cached_path, 'wb') as f:
                shutil.copyfileobj(r.raw, f)

        if not cached_path.exists() or os.path.getsize(cached_path) == 0:
            raise Exception("Fail kosong")

        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"🚀 Memuat naik `{filename}`..."})

        loop = asyncio.get_event_loop()
        # Jalankan muat naik secara serentak
        res = await asyncio.gather(
            loop.run_in_executor(None, upload_to_gofile, cached_path),
            loop.run_in_executor(None, upload_to_tempsh, cached_path, filename)
        )
        
        tg_api_call("editMessageText", {
            "chat_id": chat_id, "message_id": status_id,
            "text": (
                f"✅ **Selesai (Versi V13 - Omega Ultimate)!**\n\n"
                f"📁 **Fail:** `{filename}`\n\n"
                f"🌐 **Gofile:** {res[0]}\n"
                f"⏱ **Temp.sh:** {res[1]}"
            ),
            "parse_mode": "Markdown", "disable_web_page_preview": True
        })
    except Exception as e:
        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"❌ Ralat: {str(e)}"})
    finally:
        if 'cached_path' in locals() and cached_path.exists():
            os.remove(cached_path)

async def main():
    print(f"Bot V13 Omega Ultimate Online")
    offset = 0
    while True:
        try:
            updates = tg_api_call("getUpdates", {"offset": offset, "timeout": 30})
            if updates and updates.get('ok'):
                for u in updates['result']:
                    offset = u['update_id'] + 1
                    if 'message' in u:
                        m = u['message']
                        if m.get('text') == '/start':
                            tg_api_call("sendMessage", {"chat_id": m['chat']['id'], "text": f"👋 **Multi-Cloud Bot V13 (Omega Ultimate)**\nKemas kini: `{time.ctime()}`\n\nSila hantar fail anda."})
                        else:
                            asyncio.create_task(process_media(m))
            await asyncio.sleep(0.5)
        except:
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
