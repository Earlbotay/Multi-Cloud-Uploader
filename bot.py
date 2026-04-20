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
    clean = name.replace(" ", "_")
    clean = re.sub(r'[^a-zA-Z0-9._-]', '', clean)
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_')

def upload_to_gofile(file_path: Path):
    try:
        s_resp = requests.get("https://api.gofile.io/servers", timeout=10).json()
        server = s_resp["data"]["servers"][0]["name"]
        with file_path.open("rb") as f:
            resp = requests.post(f"https://{server}.gofile.io/contents/uploadfile", files={"file": (file_path.name, f)}, timeout=600)
        return resp.json()["data"]["downloadPage"]
    except: return "Gofile Error"

def upload_to_tempsh(file_path: Path):
    try:
        filename = file_path.name
        with file_path.open("rb") as f:
            resp = requests.post("https://temp.sh/upload", files={'file': (filename, f)}, timeout=600)
            if resp.status_code == 200:
                raw_link = resp.text.strip()
                # Betulkan link secara automatik jika underscore hilang
                if "temp.sh/" in raw_link:
                    parts = raw_link.split('/')
                    if len(parts) >= 4:
                        file_id = parts[3]
                        return f"https://temp.sh/{file_id}/{filename}"
                return raw_link
        return "Temp.sh Error"
    except: return "Temp.sh Error"

def upload_to_litterbox(file_path: Path):
    try:
        with file_path.open("rb") as f:
            # Litterbox API: 72 jam simpanan
            data = {"req": "fileupload", "time": "72h"}
            files = {"fileToUpload": (file_path.name, f)}
            resp = requests.post("https://litterbox.catbox.moe/resources/internals/api.php", data=data, files=files, timeout=600)
            return resp.text.strip()
    except Exception as e:
        return f"Litterbox Error: {str(e)}"

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
        
        # Download
        if USE_LOCAL_API:
            server_path = file_info['result']['file_path']
            host_path = Path(server_path) if server_path.startswith('/') else Path(TELEGRAM_DATA_DIR) / f"bot{TELEGRAM_TOKEN}" / server_path.lstrip('/')
            if host_path.exists(): shutil.copy2(host_path, cached_path)
            else:
                r = requests.get(f"{LOCAL_API_SERVER}/file/bot{TELEGRAM_TOKEN}/{server_path.lstrip('/')}", stream=True)
                with open(cached_path, 'wb') as f: shutil.copyfileobj(r.raw, f)
        else:
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info['result']['file_path']}"
            r = requests.get(file_url, stream=True)
            with open(cached_path, 'wb') as f: shutil.copyfileobj(r.raw, f)

        if not cached_path.exists() or os.path.getsize(cached_path) == 0: raise Exception("Fail kosong")

        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"🚀 Memuat naik `{filename}` ({file_size_str}) ke 3 Cloud...", "parse_mode": "Markdown"})

        loop = asyncio.get_event_loop()
        res = await asyncio.gather(
            loop.run_in_executor(None, upload_to_gofile, cached_path),
            loop.run_in_executor(None, upload_to_tempsh, cached_path),
            loop.run_in_executor(None, upload_to_litterbox, cached_path)
        )
        
        tg_api_call("editMessageText", {
            "chat_id": chat_id, "message_id": status_id,
            "text": (
                f"✅ **Selesai!**\n\n"
                f"📁 **Fail:** `{filename}`\n"
                f"📊 **Saiz:** `{file_size_str}`\n\n"
                f"🌐 **Gofile:** {res[0]}\n"
                f"⏱ **Temp.sh:** {res[1]}\n"
                f"🐱 **Litterbox (72h):** {res[2]}"
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
    print(f"Bot dimulakan.")
    
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
                            tg_api_call("sendMessage", {"chat_id": m['chat']['id'], "text": "👋 **Multi-Cloud Uploader Online**\n\nSila hantar fail anda."})
                        else:
                            asyncio.create_task(process_media(m))
            await asyncio.sleep(0.5)
        except: await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
