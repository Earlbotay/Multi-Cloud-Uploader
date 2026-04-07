# Telegram GoFile Bot

Bot Telegram ini akan:
- terima media daripada Telegram
- zip fail jika belum `.zip`
- upload ke GoFile
- jika fail sudah `.zip`, bot terus upload tanpa zip semula

## Fail penting
- `bot.py`
- `requirements.txt`
- `.github/workflows/bot.yml`

## GitHub Secrets
Letak secret berikut:
- `TELEGRAM_TOKEN`

## Cara guna
1. Fork atau upload projek ini ke GitHub.
2. Isi `TELEGRAM_TOKEN` dalam **GitHub Secrets**.
3. Pastikan workflow diaktifkan.
4. Push ke `main` untuk run terus.

## Nota operasi
Workflow diset dengan:
- trigger `push`
- trigger `schedule` setiap 5 jam
- `concurrency` dengan `cancel-in-progress: true` supaya run lama dibatalkan apabila run baru bermula

Ini sesuai untuk sesi polling yang perlu diganti secara berkala.

## Had
GitHub Actions bukan hosting bot 24/7 sebenar. Workflow ini menjalankan long polling sehingga job tamat, kemudian cron/push akan memulakan sesi baharu.
