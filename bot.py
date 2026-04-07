import asyncio
import mimetypes
import os
import tempfile
import zipfile
from pathlib import Path

import requests
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, ApplicationBuilder, MessageHandler, ContextTypes, filters

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
MAX_UPLOAD_RETRIES = int(os.getenv("MAX_UPLOAD_RETRIES", "3"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))

GOFILE_GET_SERVER = "https://api.gofile.io/getServer"
GOFILE_UPLOAD = "https://{}.gofile.io/uploadFile"


def is_zip_file(filename: str) -> bool:
    return filename.lower().endswith(".zip")


def safe_filename(name: str | None, fallback: str) -> str:
    if not name:
        return fallback
    return Path(name).name or fallback


def zip_single_file(src_path: Path, zip_path: Path, arcname: str) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(src_path, arcname=arcname)


def get_gofile_server() -> str:
    resp = requests.get(GOFILE_GET_SERVER, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"GoFile getServer failed: {data}")
    server = data["data"]["server"]
    if not server:
        raise RuntimeError("GoFile server is empty")
    return server


def upload_to_gofile(file_path: Path) -> str:
    server = get_gofile_server()
    url = GOFILE_UPLOAD.format(server)

    last_error: Exception | None = None
    for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
        try:
            with file_path.open("rb") as fh:
                resp = requests.post(
                    url,
                    files={"file": (file_path.name, fh)},
                    timeout=REQUEST_TIMEOUT,
                )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("status") != "ok":
                raise RuntimeError(f"GoFile upload failed: {payload}")

            data = payload.get("data") or {}
            return (
                data.get("downloadPage")
                or data.get("code")
                or data.get("parentFolder")
                or "Uploaded, but GoFile did not return a download page."
            )
        except Exception as exc:
            last_error = exc
            if attempt < MAX_UPLOAD_RETRIES:
                continue
            raise RuntimeError(f"Upload failed after {MAX_UPLOAD_RETRIES} attempts: {exc}") from exc

    raise RuntimeError(f"Upload failed: {last_error}")


async def process_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    document = message.document
    video = message.video
    audio = message.audio
    voice = message.voice
    animation = message.animation
    photo = message.photo[-1] if message.photo else None

    tg_file = None
    original_name = None

    if document:
        tg_file = await document.get_file()
        original_name = document.file_name or "document.bin"
    elif video:
        tg_file = await video.get_file()
        original_name = video.file_name or "video.mp4"
    elif audio:
        tg_file = await audio.get_file()
        original_name = audio.file_name or "audio.mp3"
    elif voice:
        tg_file = await voice.get_file()
        original_name = "voice.ogg"
    elif animation:
        tg_file = await animation.get_file()
        original_name = animation.file_name or "animation.mp4"
    elif photo:
        tg_file = await photo.get_file()
        original_name = "photo.jpg"
    else:
        await message.reply_text("Media tidak disokong.")
        return

    original_name = safe_filename(original_name, "file.bin")

    await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        downloaded_path = tmpdir_path / original_name
        await tg_file.download_to_drive(custom_path=str(downloaded_path))

        if is_zip_file(original_name):
            upload_path = downloaded_path
        else:
            zip_name = f"{downloaded_path.stem}.zip"
            zip_path = tmpdir_path / zip_name
            zip_single_file(downloaded_path, zip_path, arcname=downloaded_path.name)
            upload_path = zip_path

        try:
            link = await asyncio.to_thread(upload_to_gofile, upload_path)
            await message.reply_text(f"Selesai upload: {link}")
        except Exception as exc:
            await message.reply_text(f"Gagal: {exc}")


def build_app() -> Application:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN belum diset.")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    media_filter = (
        filters.Document.ALL
        | filters.PHOTO
        | filters.VIDEO
        | filters.AUDIO
        | filters.VOICE
        | filters.ANIMATION
    )

    app.add_handler(MessageHandler(media_filter, process_media))
    return app


def main() -> None:
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
