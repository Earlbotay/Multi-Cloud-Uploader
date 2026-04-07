# Telegram GoFile Bot (Updated)

Bot Telegram ini akan:
- Terima media (document/photo)
- Zip fail jika belum `.zip`
- Upload ke GoFile terus
- Jika fail sudah `.zip`, terus upload

## Fail penting
- `bot.py`
- `requirements.txt`
- `.github/workflows/bot.yml`

## GitHub Secrets
- `TELEGRAM_TOKEN`

## Cara guna
Push ke branch `main` atau tunggu cron setiap 5 jam. Workflow akan batalkan run lama jika ada run baru.

## Nota
GitHub Actions sesuai untuk polling temporari, bukan hosting 24/7.
