import asyncio
import os
import tempfile
import zipfile
from pathlib import Path

import requests
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

GOFILE_API = "https://api.gofile.io/uploadFile"


def is_zip_file(filename: str) -> bool:
    return filename.lower().endswith(".zip")


def zip_single_file(src_path: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(src_path, arcname=src_path.name)


def upload_to_gofile(file_path: Path) -> str:
    with file_path.open("rb") as f:
        resp = requests.post(GOFILE_API, files={"file": (file_path.name, f)})
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"Upload failed: {data}")
    return data["data"]["downloadPage"]


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    file = None
    filename = None

    if message.document:
        file = await message.document.get_file()
        filename = message.document.file_name
    elif message.photo:
        file = await message.photo[-1].get_file()
        filename = "photo.jpg"
    else:
        await message.reply_text("Hanya media sahaja (document/photo).")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / filename
        await file.download_to_drive(str(local_path))

        if not is_zip_file(filename):
            zip_path = Path(tmpdir) / f"{Path(filename).stem}.zip"
            zip_single_file(local_path, zip_path)
            upload_path = zip_path
        else:
            upload_path = local_path

        await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
        try:
            link = await asyncio.to_thread(upload_to_gofile, upload_path)
            await message.reply_text(f"Selesai upload: {link}")
        except Exception as e:
            await message.reply_text(f"Gagal: {e}")


def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN belum diset.")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_media))
    app.run_polling()


if __name__ == "__main__":
    main()
