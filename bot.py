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
                print(f"✅ Local API sedia selepas {i*2} saat!")
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
        # Nama fail tanpa ruang untuk Temp.sh
        clean_name = file_path.name.replace(" ", "_")
        with file_path.open("rb") as f:
            # Menggunakan format multipart standard
            files = {'file': (clean_name, f)}
            resp = requests.post(TEMPSH_API, files=files, timeout=600)
            
            if resp.status_code == 200:
                link = resp.text.strip()
                # Pastikan link bermula dengan http
                if link.startswith("http"): return link
                return f"Temp.sh Error: Respons tidak sah ({link})"
            else:
                return f"Temp.sh Error: Status {resp.status_code}"
    except Exception as e: return f"Temp.sh Error: {str(e)}"

def sanitize_filename(name: str):
    # Ganti ruang dan simbol pelik dengan underscore
    # Hanya benarkan alphanumeric, titik, dan dash
    import re
    clean = re.sub(r'[^a-zA-Z0-9._-]', '_', name)
    # Elakkan underscore bertindih (___)
    return re.sub(r'_+', '_', clean).strip('_')

async def process_media(message):
    chat_id = message['chat']['id']
    
    # Kenalpasti sebarang jenis media
    attachment = None
    media_types = ['document', 'video', 'audio', 'voice', 'video_note', 'animation', 'photo']
    for mt in media_types:
        if mt in message:
            attachment = message[mt]
            if mt == 'photo': attachment = attachment[-1]
            break
    
    if not attachment: return

    raw_filename = attachment.get('file_name') or f"file_{attachment['file_unique_id']}"
    # AUTO PEMBETULAN NAMA FAIL
    filename = sanitize_filename(raw_filename)
    
    file_id = attachment['file_id']
    file_size_tg = attachment.get('file_size', 0)
    file_size_tg_mb = file_size_tg / (1024*1024)
    
    msg_text = f"⏳ Memproses `{filename}` (`{file_size_tg_mb:.2f} MB`)..."
    if not USE_LOCAL_API and file_size_tg_mb > 20:
        msg_text += "\n\n⚠️ **Amaran:** Fail > 20MB mungkin gagal tanpa Local API Server!"
    
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
            error_desc = file_info.get('description', 'Ralat tidak diketahui') if file_info else 'Tiada respons'
            raise Exception(f"Gagal mendapatkan maklumat fail: {error_desc}")
        
        server_path = file_info['result']['file_path']
        
        if USE_LOCAL_API:
            if server_path.startswith('/'):
                host_file_path = Path(server_path)
            else:
                host_file_path = Path(TELEGRAM_DATA_DIR) / f"bot{TELEGRAM_TOKEN}" / server_path.lstrip('/')

            if host_file_path.exists():
                shutil.copy2(host_file_path, cached_path)
            else:
                clean_path = server_path.lstrip('/')
                file_download_url = f"{LOCAL_API_SERVER}/file/bot{TELEGRAM_TOKEN}/{clean_path}"
                with requests.get(file_download_url, stream=True, timeout=600) as resp:
                    resp.raise_for_status()
                    with open(cached_path, 'wb') as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk: f.write(chunk)
        else:
            file_download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{server_path}"
            with requests.get(file_download_url, stream=True, timeout=600) as resp:
                resp.raise_for_status()
                with open(cached_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk: f.write(chunk)

        if not cached_path.exists() or os.path.getsize(cached_path) == 0:
            raise Exception("Fail tidak berjaya diproses atau saiznya 0 bait.")

        file_size_bytes = os.path.getsize(cached_path)
        file_size_mb = file_size_bytes / (1024*1024)
        file_size_str = f"{file_size_mb:.2f} MB"
        
        index = load_index()
        index[filename] = {"size": file_size_str, "id": file_id}
        save_index(index)

        tg_api_call("editMessageText", {
            "chat_id": chat_id, 
            "message_id": status_msg_id, 
            "text": f"🚀 Memuat naik `{filename}` ({file_size_str}) ke 2 Cloud...",
            "parse_mode": "Markdown"
        })
        tg_api_call("sendChatAction", {"chat_id": chat_id, "action": "upload_document"})

        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, upload_to_gofile, cached_path),
            loop.run_in_executor(None, upload_to_tempsh, cached_path)
        ]
        results = await asyncio.gather(*tasks)
        
        tg_api_call("editMessageText", {
            "chat_id": chat_id,
            "message_id": status_msg_id,
            "text": (
                f"✅ **Selesai!**\n\n📁 **Fail:** `{filename}`\n📊 **Saiz:** `{file_size_str}`\n\n"
                f"🌐 **Gofile:** {results[0]}\n⏱ **Temp.sh:** {results[1]}"
            ),
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        })
    except Exception as e:
        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_msg_id, "text": f"❌ Ralat: {str(e)}"})
    finally:
        # Padam fail dari cache untuk jimat ruang
        if 'cached_path' in locals() and cached_path.exists():
            try: os.remove(cached_path)
            except: pass

async def main():
    global USE_LOCAL_API, API_URL
    if not TELEGRAM_TOKEN:
        print("❌ Ralat: TELEGRAM_TOKEN tidak dijumpai!")
        return
    
    USE_LOCAL_API = wait_for_local_api()
    API_URL = f"{LOCAL_API_SERVER}/bot{TELEGRAM_TOKEN}" if USE_LOCAL_API else BASE_URL
    
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
