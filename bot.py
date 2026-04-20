import asyncio
import os
import requests
import json
import shutil
import time
import re
from pathlib import Path
from pyppeteer import launch

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

async def upload_to_litterbox(file_path: Path):
    browser = None
    try:
        browser = await launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox'],
            executablePath='/usr/bin/google-chrome' if os.path.exists('/usr/bin/google-chrome') else None
        )
        page = await browser.newPage()
        await page.goto('https://litterbox.catbox.moe/', {'timeout': 60000})
        input_file = await page.querySelector('input[type=file]')
        await input_file.uploadFile(str(file_path.absolute()))
        await page.click('#threeDays')
        await page.click('#uploadButton')
        await page.waitForSelector('#upload-link', {'timeout': 600000})
        link = await page.evaluate('() => document.querySelector("#upload-link").innerText')
        return link.strip()
    except Exception as e:
        return f"Litterbox Error: {str(e)}"
    finally:
        if browser: await browser.close()

async def process_media(message):
    chat_id = message['chat']['id']
    attachment = None
    for mt in ['document', 'video', 'audio', 'voice', 'video_note', 'animation', 'photo']:
        if mt in message:
            attachment = message[mt]
            if mt == 'photo': attachment = attachment[-1]
            break
    if not attachment: return

    file_unique_id = attachment['file_unique_id']
    raw_fn = attachment.get('file_name') or f"file_{file_unique_id}"
    filename = sanitize_filename(raw_fn)
    file_id = attachment['file_id']
    file_size_str = f"{attachment.get('file_size', 0) / (1024*1024):.2f} MB"
    
    # SEMAK CACHE DAHULU
    index = load_index()
    cached_path = CACHE_DIR / filename
    
    is_cached = False
    if file_unique_id in index:
        potential_path = Path(index[file_unique_id]['path'])
        if potential_path.exists():
            cached_path = potential_path
            is_cached = True

    status_text = f"⏳ Memproses `{filename}`..."
    if is_cached: status_text += " (Dari Cache ⚡)"
    
    status = tg_api_call("sendMessage", {"chat_id": chat_id, "text": status_text, "parse_mode": "Markdown"})
    if not status: return
    status_id = status['result']['message_id']
    
    try:
        if not is_cached:
            file_info = tg_api_call("getFile", {"file_id": file_id})
            if not file_info or not file_info.get('ok'): raise Exception("Gagal info fail")
            
            # Download Logic
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
            
            # Simpan ke Index
            index[file_unique_id] = {"path": str(cached_path), "name": filename}
            save_index(index)

        if not cached_path.exists() or os.path.getsize(cached_path) == 0: raise Exception("Fail kosong")

        tg_api_call("editMessageText", {"chat_id": chat_id, "message_id": status_id, "text": f"🚀 Memuat naik `{filename}` ({file_size_str})...", "parse_mode": "Markdown"})

        # Muat naik
        gofile_link = await asyncio.get_event_loop().run_in_executor(None, upload_to_gofile, cached_path)
        litter_link = await upload_to_litterbox(cached_path)
        
        tg_api_call("editMessageText", {
            "chat_id": chat_id, "message_id": status_id,
            "text": (
                f"✅ **Selesai!**\n\n"
                f"📁 **Fail:** `{filename}`\n"
                f"📊 **Saiz:** `{file_size_str}`\n\n"
                f"🌐 **Gofile:** {gofile_link}\n"
                f"🐱 **Litterbox (72h):** {litter_link}"
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
