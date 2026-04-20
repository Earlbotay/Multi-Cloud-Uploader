import asyncio
import os
import requests
import json
import shutil
import time
import re
from pathlib import Path

# KONFIGURASI API
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
LOCAL_API_SERVER = "http://127.0.0.1:8081"
TELEGRAM_DATA_DIR = os.getenv("TELEGRAM_DATA_DIR", "/home/runner/tg-api-data")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

CACHE_DIR = Path("bot_cache")
CACHE_DIR.mkdir(exist_ok=True)

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

def sanitize_filename(name: str):
    # Hanya tukar ruang ke underscore, buang simbol pelik
    clean = name.replace(" ", "_")
    clean = re.sub(r'[^a-zA-Z0-9._-]', '', clean)
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_')

def upload_to_gofile(file_path: Path):
    try:
        server_resp = requests.get("https://api.gofile.io/servers", timeout=10).json()
        server = server_resp["data"]["servers"][0]["name"]
        with file_path.open("rb") as f:
            resp = requests.post(f"https://{server}.gofile.io/contents/uploadfile", files={"file": (file_path.name, f)}, timeout=600)
        return resp.json()["data"]["downloadPage"]
    except Exception as e: return f"Gofile Error: {str(e)}"

def upload_to_tempsh(file_path: Path):
    try:
        with file_path.open("rb") as f:
            resp = requests.post("https://temp.sh/upload", files={'file': (file_path.name, f)}, timeout=600)
            return resp.text.strip()
    except Exception as e: return f"Temp.sh Error: {str(e)}"

async def process_media(message):
    chat_id = message['chat']['id']
    attachment = None
    for mt in ['document', 'video', 'audio', 'voice', 'video_note', 'animation', 'photo']:
        if mt in message:
            attachment = message[mt]
            if mt == 'photo': attachment = attachment[-1]
            break
    if not attachment: return

    raw_fn = attachment.get('file_name') or f"file_{attachment['file_unique_id']}"
    filename = sanitize_filename(raw_fn)
    file_id = attachment['file_id']
    file_size_str = f"{attachment.get('file_size', 0) / (1024*1024):.2f} MB"
    
    status = tg_api_call("sendMessage", {"chat_id": chat_id, "text": f"⏳ Memproses `{filename}`...", "parse_mode": "Markdown"})
    if not status: return
    status_id = status['result']['message_id']
    
    try:
        cached_path = CACHE_DIR / filename
        file_info = tg_api_call("getFile", {"file_id": file_id})
        if not file_info or not file_info.get('ok'): raise Exception("Gagal info fail")
        
        server_path = file_info['result']['file_path']
        # muat turun fail
        if USE_LOCAL_API:
            h_path = Path(server_path) if server_path.startswith('/') else Path(TELEGRAM_DATA_DIR) / f"bot{TELEGRAM_TOKEN}" / server_path.lstrip('/')
            if h_path.exists(): shutil.copy2(h_path, cached_path)
            else:
                r = requests.get(f"{LOCAL_API_SERVER}/file/bot{TELEGRAM_TOKEN}/{server_path.lstrip('/')}", stream=True)
                with open(cached_path, 'wb') as f: shutil.copyfileobj(r.raw, f)
        else:
            r = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{server_path}", stream=True)
            with open(cached_path, 'wb') as f: shutil.copyfileobj(r.raw, f)

        if not cached_path.exists() or os.path.getsize(cached_path) == 0: raise Exception("Fail kosong")

        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"🚀 Memuat naik `{filename}`...", "parse_mode": "Markdown"})

        loop = asyncio.get_event_loop()
        res = await asyncio.gather(
            loop.run_in_executor(None, upload_to_gofile, cached_path),
            loop.run_in_executor(None, upload_to_tempsh, cached_path)
        )
        
        g_url = res[0]
        t_raw = res[1]
        t_final = t_raw
        
        # --- V11 ULTRA RECONSTRUCTION LOGIC ---
        # Kita bedah apa-apa link temp.sh untuk paksa letak filename asal
        if "temp.sh/" in t_raw:
            # Cari ID guna regex (mencari apa-apa antara / dan / yang bukan temp.sh)
            # Contoh: https://temp.sh/IyqIc/DarkVerseV3.zip -> kita nak 'IyqIc'
            match = re.search(r"temp\.sh/([^/]+)", t_raw)
            if match:
                t_id = match.group(1)
                t_final = f"https://temp.sh/{t_id}/{filename}"
        # ---------------------------------------

        tg_api_call("editMessageText", {
            "chat_id": chat_id, "message_id": status_id,
            "text": (
                f"✅ **Selesai (Versi V11 - Final)!**\n\n"
                f"📁 **Fail:** `{filename}`\n"
                f"📊 **Saiz:** `{file_size_str}`\n\n"
                f"🌐 **Gofile:** {g_url}\n"
                f"⏱ **Temp.sh:** {t_final}"
            ),
            "parse_mode": "Markdown", "disable_web_page_preview": True
        })
    except Exception as e:
        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"❌ Ralat: {str(e)}"})
    finally:
        if 'cached_path' in locals() and cached_path.exists(): os.remove(cached_path)

async def main():
    global USE_LOCAL_API, API_URL
    USE_LOCAL_API = wait_for_local_api()
    API_URL = f"{LOCAL_API_SERVER}/bot{TELEGRAM_TOKEN}" if USE_LOCAL_API else BASE_URL
    print(f"Bot V11 Online")
    
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
                            tg_api_call("sendMessage", {"chat_id": m['chat']['id'], "text": f"👋 **Multi-Cloud Bot V11 (Final)**\n\nStatus: `Ready`\nUjian Masa: `{time.strftime('%H:%M:%S')}`\n\nSila hantar fail." , "parse_mode": "Markdown"})
                        else: asyncio.create_task(process_media(m))
            await asyncio.sleep(0.5)
        except: await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
