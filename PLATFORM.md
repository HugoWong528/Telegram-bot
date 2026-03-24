# Platform Deployment Guide

This guide explains how to deploy the Telegram bot on every common platform.  
Pick the section that matches your environment.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Linux / VPS](#linux--vps)
- [macOS](#macos)
- [Windows](#windows)
- [Docker](#docker)
- [GitHub Actions](#github-actions)
- [Railway](#railway)
- [Render](#render)
- [Fly.io](#flyio)
- [Heroku](#heroku)
- [Oracle Cloud Free Tier](#oracle-cloud-free-tier)
- [Environment Variables Reference](#environment-variables-reference)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | Not needed for Docker deployments |
| Telegram bot token | Obtained from [@BotFather](https://t.me/BotFather) |
| Pollinations API key | Obtained from <https://enter.pollinations.ai> |

---

## Linux / VPS

Tested on Ubuntu 22.04 / Debian 12 and compatible distributions.

### 1. Install Python 3.11

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip
```

### 2. Clone and set up the project

```bash
git clone https://github.com/HugoWong528/Telegram-bot.git
cd Telegram-bot
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Set environment variables

```bash
export TELEGRAM_TOKEN="your_telegram_bot_token"
export POLLINATIONS_TOKEN="your_pollinations_api_key"
# Optional:
# export GITHUB_TOKEN="your_github_pat"
# export GITHUB_REPOSITORY="owner/repo"
# export WEATHER_CHAT_ID="your_telegram_chat_id"
# export WEATHER_REMINDER_HOURS="8,20"
```

### 4. Run

```bash
python bot.py
```

### 5. Keep it running with systemd

Create `/etc/systemd/system/telegram-bot.service`:

```ini
[Unit]
Description=AI Telegram Bot
After=network.target

[Service]
User=YOUR_USER
WorkingDirectory=/path/to/Telegram-bot
ExecStart=/path/to/Telegram-bot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=5
Environment=TELEGRAM_TOKEN=your_token
Environment=POLLINATIONS_TOKEN=your_key

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-bot
sudo journalctl -u telegram-bot -f   # view logs
```

---

## macOS

```bash
brew install python@3.11
git clone https://github.com/HugoWong528/Telegram-bot.git
cd Telegram-bot
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
TELEGRAM_TOKEN="..." POLLINATIONS_TOKEN="..." python bot.py
```

---

## Windows

```powershell
# Install Python 3.11 from https://python.org first
git clone https://github.com/HugoWong528/Telegram-bot.git
cd Telegram-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:TELEGRAM_TOKEN="your_token"
$env:POLLINATIONS_TOKEN="your_key"
python bot.py
```

---

## Docker

### Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
CMD ["python", "bot.py"]
```

### Build and run

```bash
docker build -t telegram-bot .
docker run -d \
  -e TELEGRAM_TOKEN="your_token" \
  -e POLLINATIONS_TOKEN="your_key" \
  --name telegram-bot \
  --restart unless-stopped \
  telegram-bot
```

---

## GitHub Actions

> **Note:** GitHub Actions has a 6-hour job limit. The bot will stop after 6 hours unless you restart it.  For always-on hosting, use Railway, Render, Fly.io, or a VPS.

Create `.github/workflows/bot.yml`:

```yaml
name: Telegram Bot
on:
  workflow_dispatch:
  schedule:
    - cron: '0 */5 * * *'   # restart every 5 hours to avoid the 6-hour limit

jobs:
  run-bot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: timeout 5h python bot.py || true
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          POLLINATIONS_TOKEN: ${{ secrets.POLLINATIONS_TOKEN }}
```

Add `TELEGRAM_TOKEN` and `POLLINATIONS_TOKEN` as repository secrets (Settings → Secrets → Actions).

---

## Railway

See the dedicated **[RAILWAY.md](RAILWAY.md)** guide — it is the recommended always-on option.

---

## Render

1. Create a new **Web Service** on [render.com](https://render.com).
2. Connect your forked GitHub repository.
3. Set:
   - **Environment:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
4. Add environment variables under **Environment**.
5. Deploy.

> **Note:** The free tier on Render sleeps after inactivity. Use a paid plan for always-on.

---

## Fly.io

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly auth login
fly launch --name my-telegram-bot --no-deploy
# Edit fly.toml to remove the [[services]] section (no HTTP port needed)
fly secrets set TELEGRAM_TOKEN="..." POLLINATIONS_TOKEN="..."
fly deploy
```

---

## Heroku

```bash
heroku create my-telegram-bot
heroku config:set TELEGRAM_TOKEN="..." POLLINATIONS_TOKEN="..."
# Create a Procfile: worker: python bot.py
echo "worker: python bot.py" > Procfile
git add Procfile && git commit -m "Add Procfile"
git push heroku main
heroku ps:scale worker=1
```

---

## Oracle Cloud Free Tier

Oracle Cloud provides **2 free ARM VMs** forever (Ampere A1 instances).  These are the best free option for always-on bots.

1. Create an account at [cloud.oracle.com](https://cloud.oracle.com).
2. Provision a **VM.Standard.A1.Flex** instance with Ubuntu 22.04 (free tier).
3. SSH in and follow the **[Linux / VPS](#linux--vps)** steps above.

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | ✅ | Telegram bot token from BotFather |
| `POLLINATIONS_TOKEN` | ✅ | Pollinations AI API key |
| `GITHUB_TOKEN` | optional | GitHub PAT — needed for `/build` to commit files |
| `GITHUB_REPOSITORY` | optional | `owner/repo` — needed for `/build` to commit files |
| `WEATHER_CHAT_ID` | optional | Telegram chat ID for auto weather reminders |
| `WEATHER_REMINDER_HOURS` | optional | HKT hours for auto reminders (default: `8`). E.g. `8,20` |

---

## Troubleshooting

### "TELEGRAM_TOKEN is not set"

Add the environment variable and restart the bot.

### Bot is running but doesn't respond

- **Private chats:** send any message directly to your bot.
- **Groups:** the bot only responds when mentioned (`@YourBotUsername`).  
  Make sure you added the bot to the group and it has permission to read messages.

### Commands don't show autocomplete

Register them with BotFather using `/setcommands` (see [RAILWAY.md](RAILWAY.md#step-9--register-commands-with-botfather) for the command list).

### "flood control" / rate limit errors

Telegram limits how often you can edit messages.  The bot waits at least 2 seconds between live edits to stay within limits.  If you see `RetryAfter` errors in the logs, wait a few seconds before sending another message.
