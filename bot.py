import asyncio
import os
import requests
import json
import shutil
import time
from pathlib import Path

# KONFIGURASI API
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
LOCAL_API_SERVER = "http://127.0.0.1:8081"
TELEGRAM_DATA_DIR = os.getenv("TELEGRAM_DATA_DIR", "/home/runner/work/Multi-Cloud-Uploader/Multi-Cloud-Uploader/telegram-data")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

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
API_URL = f"{LOCAL_API_SERVER}/bot{TELEGRAM_TOKEN}" if USE_LOCAL_API else BASE_URL

def tg_api_call(method, data=None, files=None):
    try:
        resp = requests.post(f"{API_URL}/{method}", data=data, files=files, timeout=30)
        return resp.json()
    except Exception as e:
        print(f"TG API Error ({method}): {e}")
        return None

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

async def process_media(message):
    chat_id = message['chat']['id']
    
    # Kenalpasti jenis media
    attachment = None
    if 'document' in message: attachment = message['document']
    elif 'video' in message: attachment = message['video']
    elif 'audio' in message: attachment = message['audio']
    elif 'photo' in message: attachment = message['photo'][-1]
    elif 'voice' in message: attachment = message['voice']
    elif 'video_note' in message: attachment = message['video_note']
    elif 'animation' in message: attachment = message['animation']
    
    if not attachment: return

    file_id = attachment['file_id']
    filename = attachment.get('file_name') or f"file_{attachment['file_unique_id']}"
    
    status_resp = tg_api_call("sendMessage", {"chat_id": chat_id, "text": f"⏳ Memproses `{filename}`...", "parse_mode": "Markdown"})
    if not status_resp: return
    status_msg_id = status_resp['result']['message_id']
    
    try:
        cached_path = CACHE_DIR / filename
        
        # Dapatkan maklumat fail dari API
        file_info = tg_api_call("getFile", {"file_id": file_id})
        if not file_info or not file_info.get('ok'):
            raise Exception("Gagal mendapatkan maklumat fail dari Telegram.")
        
        server_path = file_info['result']['file_path']
        
        if USE_LOCAL_API:
            container_base = "/var/lib/telegram-bot-api"
            if server_path.startswith(container_base):
                relative_path = server_path[len(container_base):].lstrip('/')
                host_file_path = Path(TELEGRAM_DATA_DIR) / relative_path
            else:
                host_file_path = Path(TELEGRAM_DATA_DIR) / server_path.lstrip('/')

            found = False
            for _ in range(10):
                if host_file_path.exists():
                    found = True
                    break
                time.sleep(1)

            if found:
                shutil.copy2(host_file_path, cached_path)
            else:
                # Sandaran jika fail fizikal tiada
                resp = requests.get(f"{API_URL}/file/bot{TELEGRAM_TOKEN}/{server_path}", stream=True)
                with open(cached_path, 'wb') as f: shutil.copyfileobj(resp.raw, f)
        else:
            # Download biasa (Standard API)
            resp = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{server_path}", stream=True)
            with open(cached_path, 'wb') as f: shutil.copyfileobj(resp.raw, f)

        if not cached_path.exists():
            raise FileNotFoundError("Gagal memproses/memuat turun fail.")

        file_size_mb = os.path.getsize(cached_path) / (1024*1024)
        file_size_str = f"{file_size_mb:.2f} MB"
        
        index = load_index()
        index[filename] = {"size": file_size_str, "id": file_id}
        save_index(index)

        tg_api_call("editMessageText", {
            "chat_id": chat_id, 
            "message_id": status_msg_id, 
            "text": f"🚀 Memuat naik `{filename}` ({file_size_str}) ke 3 Cloud...",
            "parse_mode": "Markdown"
        })
        tg_api_call("sendChatAction", {"chat_id": chat_id, "action": "upload_document"})

        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, upload_to_gofile, cached_path),
            loop.run_in_executor(None, upload_to_catbox, cached_path),
            loop.run_in_executor(None, upload_to_tempsh, cached_path)
        ]
        results = await asyncio.gather(*tasks)
        
        tg_api_call("editMessageText", {
            "chat_id": chat_id,
            "message_id": status_msg_id,
            "text": (
                f"✅ **Selesai!**\n\n📁 **Fail:** `{filename}`\n📊 **Saiz:** `{file_size_str}`\n\n"
                f"🌐 **Gofile:** {results[0]}\n🐱 **Catbox:** {results[1]}\n⏱ **Temp.sh:** {results[2]}"
            ),
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
    except Exception as e:
        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_msg_id, "text": f"❌ Ralat: {str(e)}"})

async def main():
    if not TELEGRAM_TOKEN:
        print("❌ Ralat: TELEGRAM_TOKEN tidak dijumpai!")
        return
    
    print(f"Mod API: {'LOCAL' if USE_LOCAL_API else 'STANDARD'}")
    print("Bot dimulakan.")
    
    offset = 0
    while True:
        try:
            updates = tg_api_call("getUpdates", {"offset": offset, "timeout": 30})
            if updates and updates.get('ok'):
                for update in updates['result']:
                    offset = update['update_id'] + 1
                    if 'message' in update:
                        asyncio.create_task(process_media(update['message']))
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Polling Error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
