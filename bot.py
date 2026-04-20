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
CACHE_INDEX = CACHE_DIR / "index.json"

CACHE_DIR.mkdir(exist_ok=True)
if not CACHE_INDEX.exists():
    with open(CACHE_INDEX, "w") as f: json.dump({}, f)

def wait_for_local_api():
    if not TELEGRAM_TOKEN: return False
    print(f"Menunggu Local API di {LOCAL_API_SERVER}...")
    for i in range(30):
        try:
            resp = requests.get(f"{LOCAL_API_SERVER}/bot{TELEGRAM_TOKEN}/getMe", timeout=5)
            if resp.status_code == 200:
                print(f"✅ Local API sedia!")
                return True
        except:
            pass
        time.sleep(2)
    return False

# Status API
USE_LOCAL_API = False
API_URL = BASE_URL

def tg_api_call(method, data=None, files=None):
    try:
        url = f"{API_URL}/{method}"
        resp = requests.post(url, data=data, files=files, timeout=60)
        return resp.json()
    except Exception as e:
        print(f"TG API Error ({method}): {e}")
        return None

def load_index():
    with open(CACHE_INDEX, "r") as f: return json.load(f)

def save_index(index):
    with open(CACHE_INDEX, "w") as f: json.dump(index, f, indent=4)

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

def upload_to_tempsh(file_path: Path):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        filename = file_path.name
        with file_path.open("rb") as f:
            resp = requests.post(TEMPSH_API, files={'file': (filename, f)}, headers=headers, timeout=600)
            if resp.status_code == 200:
                return resp.text.strip()
        return f"Temp.sh Error: Status {resp.status_code}"
    except Exception as e: return f"Temp.sh Error: {str(e)}"

def sanitize_filename(name: str):
    # Tukar ruang ke underscore, buang simbol pelik, kekalkan titik/underscore
    clean = name.replace(" ", "_")
    clean = re.sub(r'[^a-zA-Z0-9._-]', '', clean)
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_')

async def process_media(message):
    chat_id = message['chat']['id']
    
    attachment = None
    media_types = ['document', 'video', 'audio', 'voice', 'video_note', 'animation', 'photo']
    for mt in media_types:
        if mt in message:
            attachment = message[mt]
            if mt == 'photo': attachment = attachment[-1]
            break
    
    if not attachment: return

    raw_filename = attachment.get('file_name') or f"file_{attachment['file_unique_id']}"
    filename = sanitize_filename(raw_filename)
    
    file_id = attachment['file_id']
    file_size_tg = attachment.get('file_size', 0)
    file_size_tg_mb = file_size_tg / (1024*1024)
    
    msg_text = f"⏳ Memproses `{filename}` (`{file_size_tg_mb:.2f} MB`)..."
    status_resp = tg_api_call("sendMessage", {"chat_id": chat_id, "text": msg_text, "parse_mode": "Markdown"})
    if not status_resp: return
    status_msg_id = status_resp['result']['message_id']
    
    try:
        cached_path = CACHE_DIR / filename
        
        file_info = None
        for _ in range(3):
            file_info = tg_api_call("getFile", {"file_id": file_id})
            if file_info and file_info.get('ok'): break
            time.sleep(2)

        if not file_info or not file_info.get('ok'):
            raise Exception("Gagal mendapatkan maklumat fail.")
        
        server_path = file_info['result']['file_path']
        
        # Download logic
        if USE_LOCAL_API:
            host_file_path = Path(server_path) if server_path.startswith('/') else Path(TELEGRAM_DATA_DIR) / f"bot{TELEGRAM_TOKEN}" / server_path.lstrip('/')
            if host_file_path.exists():
                shutil.copy2(host_file_path, cached_path)
            else:
                resp = requests.get(f"{LOCAL_API_SERVER}/file/bot{TELEGRAM_TOKEN}/{server_path.lstrip('/')}", stream=True)
                with open(cached_path, 'wb') as f: shutil.copyfileobj(resp.raw, f)
        else:
            resp = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{server_path}", stream=True)
            with open(cached_path, 'wb') as f: shutil.copyfileobj(resp.raw, f)

        if not cached_path.exists() or os.path.getsize(cached_path) == 0:
            raise Exception("Fail kosong.")

        tg_api_call("editMessageText", {
            "chat_id": chat_id, "message_id": status_msg_id, 
            "text": f"🚀 Memuat naik `{filename}` ke 2 Cloud...",
            "parse_mode": "Markdown"
        })

        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, upload_to_gofile, cached_path),
            loop.run_in_executor(None, upload_to_tempsh, cached_path)
        ]
        results = await asyncio.gather(*tasks)
        
        # --- PROSES LINK SECARA PAKSA SEBELUM HANTAR (V7) ---
        temp_link = results[1]
        if "temp.sh" in temp_link and "/" in temp_link:
            # Ambil ID unik dari link (cth: gaQsp)
            parts = temp_link.strip().split('/')
            # Jika link penuh cth https://temp.sh/ID/file.zip, parts[3] adalah ID
            if len(parts) >= 4:
                file_id_url = parts[3]
                temp_link = f"https://temp.sh/{file_id_url}/{filename}"
        # --------------------------------------------------

        tg_api_call("editMessageText", {
            "chat_id": chat_id,
            "message_id": status_msg_id,
            "text": (
                f"✅ **Selesai (Versi V7)!**\n\n📁 **Fail:** `{filename}`\n\n"
                f"🌐 **Gofile:** {results[0]}\n⏱ **Temp.sh:** {temp_link}"
            ),
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
    except Exception as e:
        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_msg_id, "text": f"❌ Ralat: {str(e)}"})
    finally:
        if 'cached_path' in locals() and cached_path.exists():
            try: os.remove(cached_path)
            except: pass

async def main():
    global USE_LOCAL_API, API_URL
    USE_LOCAL_API = wait_for_local_api()
    API_URL = f"{LOCAL_API_SERVER}/bot{TELEGRAM_TOKEN}" if USE_LOCAL_API else BASE_URL
    print(f"Bot V7 dimulakan pada {time.ctime()}")
    
    offset = 0
    while True:
        try:
            updates = tg_api_call("getUpdates", {"offset": offset, "timeout": 30})
            if updates and updates.get('ok'):
                for update in updates['result']:
                    offset = update['update_id'] + 1
                    if 'message' in update:
                        msg = update['message']
                        if msg.get('text') == '/start':
                            tg_api_call("sendMessage", {"chat_id": msg['chat']['id'], "text": f"👋 **Multi-Cloud Bot V7 (Final)**\nDikemaskini: `{time.ctime()}`\n\nSila hantar fail." , "parse_mode": "Markdown"})
                        else:
                            asyncio.create_task(process_media(msg))
            await asyncio.sleep(0.5)
        except:
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
