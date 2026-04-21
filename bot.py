import asyncio
import os
import json
import shutil
import time
import subprocess
import requests
import math
import uuid
import html
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DOMAIN = os.getenv("DOMAIN", "temp.earlstore.online")
UPLOAD_URL = f"https://{DOMAIN}/api/upload"
WEB_URL = f"https://{DOMAIN}"
LOCAL_API_URL = "http://127.0.0.1:8081"
BASE_URL = f"{LOCAL_API_URL}/bot{TELEGRAM_TOKEN}"

CACHE_DIR = Path("bot_cache")
CACHE_INDEX = CACHE_DIR / "index.json"

executor = ThreadPoolExecutor(max_workers=999)
main_loop = None

CACHE_DIR.mkdir(exist_ok=True)
if not CACHE_INDEX.exists():
    with open(CACHE_INDEX, "w") as f: json.dump({}, f)

index_lock = asyncio.Lock()

def load_index():
    try:
        if not CACHE_INDEX.exists(): return {}
        with open(CACHE_INDEX, "r") as f: return json.load(f)
    except: return {}

async def save_index_async(index):
    async with index_lock:
        with open(CACHE_INDEX, "w") as f: json.dump(index, f, indent=4)

def check_local_api():
    try:
        resp = requests.get(f"{BASE_URL}/getMe", timeout=5)
        return resp.status_code == 200
    except Exception as e:
        return False

async def wait_for_local_api(timeout=60):
    start_time = time.time()
    print(f"⏳ Menunggu Local Bot API Server sedia (Timeout: {timeout}s)...")
    while time.time() - start_time < timeout:
        if check_local_api():
            print("✅ Local Bot API Server dikesan dan sedia!")
            return True
        await asyncio.sleep(2)
    return False

def tg_api_call(method, data=None):
    try:
        url = f"{BASE_URL}/{method}"
        if data and "reply_markup" in data and isinstance(data["reply_markup"], dict):
            data["reply_markup"] = json.dumps(data["reply_markup"])
        resp = requests.post(url, data=data, timeout=1000)
        return resp.json()
    except Exception as e:
        print(f"API Error ({method}): {e}")
        return None

async def tg_api_call_async(method, data=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, tg_api_call, method, data)

def download_file_sync(url, dest):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f: shutil.copyfileobj(r.raw, f)

async def safe_edit_message(chat_id, message_id, text):
    res = await tg_api_call_async("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"})
    if not res or not res.get("ok"):
        return await tg_api_call_async("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    return res

def upload_to_earlstore(file_path: Path, chat_id=None, status_id=None):
    try:
        if not file_path.exists() or file_path.stat().st_size == 0:
            return "❌ Ralat: Fail kosong atau tidak wujud."

        file_size = file_path.stat().st_size
        chunk_size = 5 * 1024 * 1024
        total_chunks = math.ceil(file_size / chunk_size)
        upload_id = str(uuid.uuid4())
        final_url = None

        with open(file_path, "rb") as f:
            for i in range(total_chunks):
                chunk_data = f.read(chunk_size)
                payload = {"chunk_index": i, "total_chunks": total_chunks, "upload_id": upload_id}
                files = {"file": (file_path.name, chunk_data)}
                resp = requests.post(UPLOAD_URL, data=payload, files=files, timeout=120)
                
                if resp.status_code == 200:
                    data = resp.json()
                    if "url" in data: final_url = data["url"]
                    if chat_id and status_id and total_chunks > 1 and (i % 2 == 0 or i == total_chunks - 1):
                        percent = int(((i + 1) / total_chunks) * 100)
                        bar = "█" * (percent // 10) + "░" * (10 - (percent // 10))
                        progress_text = (
                            f"<blockquote>🚀 <b>Earl File...</b>\n\n"
                            f"<code>{bar}</code> {percent}%\n"
                            f"<b>Bahagian {i+1}/{total_chunks}</b></blockquote>"
                        )
                        if main_loop:
                            asyncio.run_coroutine_threadsafe(safe_edit_message(chat_id, status_id, progress_text), main_loop)
                        time.sleep(1)
                else: return f"❌ Error API (Part {i+1}): {resp.text}"

        return final_url or "❌ Gagal mendapatkan URL akhir."
    except Exception as e: return f"❌ Earl File Error: {str(e)}"

async def process_media(message):
    chat_id = message['chat']['id']
    
    # Handle /start command
    if 'text' in message and message['text'].startswith('/start'):
        welcome_text = (
            "<blockquote><b>👋 Selamat Datang ke Earl File Bot!</b>\n\n"
            "Saya dioptimumkan untuk memproses fail sehingga <b>2GB</b> melalui Local Bot API.\n\n"
            "<b>Cara Guna:</b>\n"
            "1. Hantar sebarang media ke sini.\n"
            "2. Tunggu bot memproses muat naik.\n"
            "3. Bot akan memberikan pautan hasil muat turun.\n\n"
            "<i>Dibina untuk kelajuan tinggi. Selamat mencuba!</i></blockquote>"
        )
        markup = {"inline_keyboard": [[{"text": "🌐 LINK WEB", "url": WEB_URL, "style": "danger"}]]}
        await tg_api_call_async("sendMessage", {"chat_id": chat_id, "text": welcome_text, "parse_mode": "HTML", "reply_markup": markup})
        return

    attachment = None
    for mt in ['document', 'video', 'audio', 'voice', 'video_note', 'animation', 'photo']:
        if mt in message:
            attachment = message[mt]
            if mt == 'photo': attachment = attachment[-1]
            break
    if not attachment: return

    initial_msg = "<blockquote>⚡ <b>Tugasan diterima!</b>\nMenghubungi Telegram API untuk mendapatkan info fail...</blockquote>"
    status = await tg_api_call_async("sendMessage", {"chat_id": chat_id, "text": initial_msg, "parse_mode": "HTML"})
    if not status: return
    status_id = status['result']['message_id']

    file_id = attachment['file_id']
    file_unique_id = attachment['file_unique_id']
    file_size_mb = attachment.get('file_size', 0) / (1024 * 1024)
    file_size_str = f"{file_size_mb:.2f} MB"

    file_info = await tg_api_call_async("getFile", {"file_id": file_id})
    if not file_info or not file_info.get('ok'):
        desc = file_info.get('description', 'Tiada respon / Timeout') if file_info else 'Timeout'
        await safe_edit_message(chat_id, status_id, f"<blockquote>❌ <b>Gagal mendapatkan info fail.</b>\nRespon: <code>{html.escape(desc)}</code></blockquote>")
        return

    tg_file_path = file_info['result']['file_path']
    ext = os.path.splitext(tg_file_path)[1] or ".bin"
    safe_filename = html.escape(attachment.get('file_name', f"{file_unique_id}{ext}"))
    
    task_id = str(uuid.uuid4())[:8]
    task_dir = CACHE_DIR / task_id
    task_dir.mkdir(exist_ok=True)
    cached_path = task_dir / f"{file_unique_id}{ext}"

    index = load_index()
    is_cached = file_unique_id in index and Path(index[file_unique_id]['path']).exists()
    if is_cached:
        cached_path = Path(index[file_unique_id]['path'])
        if cached_path.stat().st_size == 0: is_cached = False

    try:
        if not is_cached:
            await safe_edit_message(chat_id, status_id, f"<blockquote>📥 <b>Menyediakan fail:</b>\n<code>{safe_filename}</code> ({file_size_str})...</blockquote>")
            source_path = Path(tg_file_path)
            if source_path.exists():
                await asyncio.get_event_loop().run_in_executor(executor, shutil.copy2, source_path, cached_path)
            else:
                raise Exception(f"Fail tidak dijumpai di disk: {tg_file_path}")
            
            if cached_path.stat().st_size == 0: raise Exception("Fail bersaiz 0MB.")
            index = load_index()
            index[file_unique_id] = {"path": str(cached_path), "name": safe_filename}
            await save_index_async(index)

        await safe_edit_message(chat_id, status_id, f"<blockquote>🚀 <b>Earl File...</b></blockquote>")
        earl_link = await asyncio.get_event_loop().run_in_executor(executor, upload_to_earlstore, cached_path, chat_id, status_id)

        if earl_link and "http" in str(earl_link):
            await safe_edit_message(chat_id, status_id, f"<blockquote>✅ <b>Muat naik selesai!</b>\nSila semak mesej di bawah.</blockquote>")
            final_caption = (
                f"<blockquote>🔗 <b>Earl File Berjaya Dicipta!</b>\n\n"
                f"📁 <b>Fail:</b> <code>{safe_filename}</code>\n"
                f"📊 <b>Saiz:</b> {file_size_str}\n\n"
                f"🌐 <b>Pautan:</b> {earl_link}</blockquote>"
            )
            await tg_api_call_async("sendMessage", {"chat_id": chat_id, "text": final_caption, "parse_mode": "HTML"})
        else:
            await safe_edit_message(chat_id, status_id, f"<blockquote>❌ <b>Gagal:</b> API tidak memulangkan link sah.\nRespon API: <code>{html.escape(str(earl_link))}</code></blockquote>")
    except Exception as e:
        await safe_edit_message(chat_id, status_id, f"<blockquote>❌ <b>Ralat:</b> {html.escape(str(e))}</blockquote>")
    finally:
        try:
            if task_dir.exists(): shutil.rmtree(task_dir)
        except: pass

async def main():
    global main_loop
    if not TELEGRAM_TOKEN:
        print("❌ Ralat: TELEGRAM_TOKEN tidak ditetapkan!")
        sys.exit(1)
    
    print(f"🤖 Bot Earl File dimulakan (Strict Local API)...")
    
    # Tunggu sehingga Local API sedia
    if not await wait_for_local_api(timeout=60):
        print("❌ KRITIKAL: Local Bot API Server tidak dikesan selepas 60 saat!")
        sys.exit(1)
        
    main_loop = asyncio.get_running_loop()
    offset = 0
    print("✅ Bot sedang mendengar pesanan...")
    while True:
        try:
            updates = await tg_api_call_async("getUpdates", {"offset": offset, "timeout": 30})
            if updates and updates.get('ok'):
                for u in updates['result']:
                    offset = u['update_id'] + 1
                    if 'message' in u: asyncio.create_task(process_media(u['message']))
            await asyncio.sleep(0.5)
        except Exception as e: 
            print(f"⚠️ Warning: Ralat semasa getUpdates: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
