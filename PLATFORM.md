# Platform Deployment Guide

This guide explains how to deploy either Discord bot on every common platform.  
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
| Python 3.11+ | Not needed for Docker or GitHub Actions deployments |
| Discord bot token | Obtained from the [Discord Developer Portal](https://discord.com/developers/applications) |
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
git clone https://github.com/HugoWong528/AI-discord-bot.git
cd AI-discord-bot
```

### 3. Create a virtual environment and install dependencies

**Unified bot (recommended — all features, one token):**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**General Chat bot (standalone):**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r general-chat/requirements.txt
```

**AI Company bot (standalone):**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r ai-company/requirements.txt
```

### 4. Set environment variables

**Unified bot:**

```bash
export DISCORD_TOKEN="your_discord_bot_token"
export POLLINATIONS_TOKEN="your_pollinations_api_key"
# Optional — needed for /build to commit generated code:
# export GITHUB_TOKEN="your_github_pat"
# export GITHUB_REPOSITORY="owner/repo"
# Optional — HK weather auto-reminders:
# export WEATHER_CHANNEL_ID="your_discord_channel_id"
# export WEATHER_REMINDER_HOURS="8,20"
```

**Standalone legacy bots:**

```bash
export DISCORD_TOKEN="your_discord_bot_token"          # General Chat
export POLLINATIONS_TOKEN="your_pollinations_api_key"
# AI Company bot uses a different token variable:
# export DISCORD_TOKEN_COMPANY="your_company_bot_token"
```

### 5. Run the bot

```bash
# Unified bot (recommended)
python bot.py

# General Chat bot (standalone)
python general-chat/bot.py

# AI Company bot (standalone)
python ai-company/bot.py
```

### 6. (Optional) Run as a systemd service

Create `/etc/systemd/system/ai-discord-bot.service`:

```ini
[Unit]
Description=AI Discord Bot
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/path/to/AI-discord-bot
EnvironmentFile=/path/to/AI-discord-bot/.env
ExecStart=/path/to/AI-discord-bot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Create `.env` (never commit this file):

```
DISCORD_TOKEN=your_token_here
POLLINATIONS_TOKEN=your_key_here
# GITHUB_TOKEN=your_github_pat
# GITHUB_REPOSITORY=owner/repo
# WEATHER_CHANNEL_ID=your_channel_id
# WEATHER_REMINDER_HOURS=8,20
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-discord-bot
sudo systemctl start ai-discord-bot
sudo systemctl status ai-discord-bot   # verify it is running
```

---

## macOS

Tested on macOS 13 (Ventura) and later.

### 1. Install Python 3.11 via Homebrew

```bash
brew install python@3.11
```

### 2. Clone and set up the project

```bash
git clone https://github.com/HugoWong528/AI-discord-bot.git
cd AI-discord-bot
```

### 3. Create a virtual environment and install dependencies

**Unified bot (recommended):**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**General Chat bot (standalone):**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r general-chat/requirements.txt
```

**AI Company bot (standalone):**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r ai-company/requirements.txt
```

### 4. Set environment variables and run

```bash
export DISCORD_TOKEN="your_discord_bot_token"
export POLLINATIONS_TOKEN="your_pollinations_api_key"

python bot.py   # unified bot (recommended)
# or: python general-chat/bot.py
# or: python ai-company/bot.py
```

### 5. (Optional) Run as a launchd service

Create `~/Library/LaunchAgents/com.ai-discord-bot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ai-discord-bot</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/AI-discord-bot/.venv/bin/python</string>
    <string>/path/to/AI-discord-bot/bot.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>DISCORD_TOKEN</key>
    <string>your_token_here</string>
    <key>POLLINATIONS_TOKEN</key>
    <string>your_key_here</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/ai-discord-bot.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/ai-discord-bot.err</string>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.ai-discord-bot.plist
```

---

## Windows

Tested on Windows 10 and Windows 11.

### 1. Install Python 3.11

Download the installer from <https://www.python.org/downloads/> and run it.  
**Important:** Check **"Add Python to PATH"** during installation.

### 2. Clone and set up the project

```cmd
git clone https://github.com/HugoWong528/AI-discord-bot.git
cd AI-discord-bot
```

If you do not have Git installed, download it from <https://git-scm.com/download/win>.

### 3. Create a virtual environment and install dependencies

Open **Command Prompt** or **PowerShell**:

```cmd
python -m venv .venv
.venv\Scripts\activate
```

**Unified bot (recommended):**

```cmd
pip install -r requirements.txt
```

**General Chat bot (standalone):**

```cmd
pip install -r general-chat\requirements.txt
```

**AI Company bot (standalone):**

```cmd
pip install -r ai-company\requirements.txt
```

### 4. Set environment variables and run

**Command Prompt:**

```cmd
set DISCORD_TOKEN=your_discord_bot_token
set POLLINATIONS_TOKEN=your_pollinations_api_key
python bot.py
```

**PowerShell:**

```powershell
$env:DISCORD_TOKEN = "your_discord_bot_token"
$env:POLLINATIONS_TOKEN = "your_pollinations_api_key"
python bot.py
```

### 5. (Optional) Run on startup using Task Scheduler

The easiest approach is to create a small batch file that sets environment variables and launches the bot, then schedule that batch file.

1. Create `run-bot.bat` (e.g. in `C:\bots\AI-discord-bot\`):

   ```bat
   @echo off
   set DISCORD_TOKEN=your_discord_bot_token
   set POLLINATIONS_TOKEN=your_pollinations_api_key
   C:\bots\AI-discord-bot\.venv\Scripts\python.exe C:\bots\AI-discord-bot\bot.py
   ```

2. Open **Task Scheduler** → **Create Basic Task**.
3. Set **Trigger** to *When the computer starts* (or *At log on*).
4. Set **Action** to *Start a program* and enter the full path to `run-bot.bat`.
5. Click **Finish**. Right-click the new task → **Properties** → **General** → enable **Run whether user is logged on or not** if you want it to run in the background.

---

## Docker

All three bot options share the same Dockerfile pattern.

### Unified bot (recommended — all features, one token)

Create a `Dockerfile` at the **repository root**:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

CMD ["python", "bot.py"]
```

Build and run (from the repository root):

```bash
docker build -t ai-discord-bot .
docker run -d \
  -e DISCORD_TOKEN="your_token" \
  -e POLLINATIONS_TOKEN="your_key" \
  --name ai-discord-bot \
  ai-discord-bot
```

### General Chat bot (standalone)

Create `general-chat/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

CMD ["python", "bot.py"]
```

Build and run (from the repository root):

```bash
docker build -t ai-discord-bot ./general-chat
docker run -d \
  -e DISCORD_TOKEN="your_token" \
  -e POLLINATIONS_TOKEN="your_key" \
  --name ai-discord-bot \
  ai-discord-bot
```

### AI Company bot (standalone)

Create `ai-company/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

CMD ["python", "bot.py"]
```

```bash
docker build -t ai-company-bot ./ai-company
docker run -d \
  -e DISCORD_TOKEN_COMPANY="your_token" \
  -e POLLINATIONS_TOKEN="your_key" \
  --name ai-company-bot \
  ai-company-bot
```

### Docker Compose — unified bot (recommended)

Add a `docker-compose.yml` to the repository root:

```yaml
services:
  ai-discord-bot:
    build:
      context: .
    environment:
      DISCORD_TOKEN: "${DISCORD_TOKEN}"
      POLLINATIONS_TOKEN: "${POLLINATIONS_TOKEN}"
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
      GITHUB_REPOSITORY: "${GITHUB_REPOSITORY}"
      WEATHER_CHANNEL_ID: "${WEATHER_CHANNEL_ID}"
      WEATHER_REMINDER_HOURS: "${WEATHER_REMINDER_HOURS}"
    restart: unless-stopped
```

Create a `.env` file (never commit it):

```
DISCORD_TOKEN=your_discord_bot_token
POLLINATIONS_TOKEN=your_pollinations_key
# GITHUB_TOKEN=your_github_pat
# GITHUB_REPOSITORY=owner/repo
# WEATHER_CHANNEL_ID=your_channel_id
# WEATHER_REMINDER_HOURS=8,20
```

Start the unified bot:

```bash
docker compose up -d
```

### Docker Compose — both legacy bots

Using the Dockerfiles created above, add a `docker-compose.yml` to the repository root:

```yaml
services:
  general-chat:
    build:
      context: ./general-chat
    environment:
      DISCORD_TOKEN: "${DISCORD_TOKEN}"
      POLLINATIONS_TOKEN: "${POLLINATIONS_TOKEN}"
    restart: unless-stopped

  ai-company:
    build:
      context: ./ai-company
    environment:
      DISCORD_TOKEN_COMPANY: "${DISCORD_TOKEN_COMPANY}"
      POLLINATIONS_TOKEN: "${POLLINATIONS_TOKEN}"
    restart: unless-stopped
```

Create a `.env` file (never commit it):

```
DISCORD_TOKEN=your_general_chat_token
DISCORD_TOKEN_COMPANY=your_company_token
POLLINATIONS_TOKEN=your_pollinations_key
```

Start both bots:

```bash
docker compose up -d
```

---

## GitHub Actions

GitHub Actions is a free way to keep the bots running with **zero infrastructure cost**.  
There is a workflow for the unified bot and individual workflows for each legacy bot.

> **6-hour limit:** GitHub Actions jobs run for a maximum of 6 hours. Sessions stored in memory are lost when the job ends. For continuous uptime use Railway, Render, Fly.io, or a VPS.

### How it works

- Each workflow starts the corresponding bot and keeps it running for up to 6 hours (GitHub's job time limit).
- The `workflow_dispatch` trigger lets you start or restart the bot manually from the **Actions** tab at any time.
- The automatic `cron` schedule has been **disabled** (commented out in the workflow files). For continuous 24/7 uptime, use Railway, Render, or a VPS.
- Logs are visible in real time from the **Actions** tab.

### Setup

1. **Fork or push** this repository to your own GitHub account.

2. **Add Secrets** — go to **Settings → Secrets and variables → Actions → New repository secret** and add:

   | Secret name | Bot | Description |
   |---|---|---|
   | `DISCORD_TOKEN` | Unified / General Chat | Token for the unified bot or standalone general chat bot |
   | `DISCORD_TOKEN_COMPANY` | AI Company (standalone) | Token for the standalone AI company bot |
   | `POLLINATIONS_TOKEN` | All | Your Pollinations AI API key |

   > `GITHUB_TOKEN` is provided automatically by GitHub Actions — you do not need to add it.

3. **Enable workflows** — go to the **Actions** tab and click **I understand my workflows, go ahead and enable them** if prompted.

4. **Run a workflow** — click the desired workflow in the left sidebar, then click **Run workflow → Run workflow**.

### Workflow files

| File | Bot |
|---|---|
| `.github/workflows/bot.yml` | ⭐ **Unified bot** (recommended — all features, one token) |
| `.github/workflows/discord-bot.yml` | General Chat bot (standalone) |
| `.github/workflows/discord-ai-company-bot.yml` | AI Company bot (standalone) |

All workflows are independent and can be started or stopped separately.

---

## Railway

Railway is the **easiest fully-managed platform** for running these bots 24/7.  
For a complete step-by-step guide see **[RAILWAY.md](RAILWAY.md)**.

**Quick start — Unified Bot (recommended):**

1. Fork this repository to your GitHub account.
2. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**.
3. Select your forked repository.
4. **Leave Root Directory empty** — the root-level `railway.toml` is picked up automatically.
5. Add environment variables:
   - `DISCORD_TOKEN` — your Discord bot token
   - `POLLINATIONS_TOKEN` — your Pollinations API key
   - *(optional)* `GITHUB_TOKEN`, `GITHUB_REPOSITORY` — needed for `/build` to commit files
   - *(optional)* `WEATHER_CHANNEL_ID`, `WEATHER_REMINDER_HOURS` — HK weather auto-reminders
6. Click **Deploy**.

The unified bot runs `bot.py` at the repo root and covers all features (general chat, AI company/build, Hong Kong weather) with a single `DISCORD_TOKEN`.

**Quick start — standalone bots (legacy):**

If you prefer to run only the General Chat or only the AI Company bot, set the **Root Directory** to `general-chat` or `ai-company` respectively, then add the matching environment variables.  See [RAILWAY.md](RAILWAY.md) for the full walkthrough.

Railway detects Python automatically, installs dependencies from `requirements.txt`, and starts the bot using the command in `railway.toml`.

---

## Render

Render is a cloud platform with a free tier for background services.

> **Free-tier note:** Render's free tier suspends background workers after periods of inactivity, which will disconnect the bot. Use a paid instance or Railway for guaranteed uptime.

### Deploy

1. Sign up at [render.com](https://render.com).
2. Click **New → Background Worker**.
3. Connect your GitHub repository.
4. Configure the service:
   - **Root Directory**: `general-chat` (or `ai-company`)
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
5. Under **Environment**, add:
   - `DISCORD_TOKEN` — your Discord bot token
   - `POLLINATIONS_TOKEN` — your Pollinations API key
6. Click **Create Background Worker**.

Render will build and deploy the bot.  Each push to your GitHub branch triggers an automatic redeploy.

---

## Fly.io

Fly.io runs Docker containers globally and has a generous free allowance.

### Prerequisites

- [Install `flyctl`](https://fly.io/docs/hands-on/install-flyctl/) — the Fly.io CLI
- A Fly.io account (`fly auth login`)

### Deploy — General Chat bot

1. Create a `general-chat/Dockerfile` (see the [Docker section](#docker) above).

2. From the repository root:

   ```bash
   cd general-chat
   fly launch --no-deploy
   ```

   Follow the prompts: choose a region close to your Discord server.

3. Set secrets:

   ```bash
   fly secrets set DISCORD_TOKEN="your_token" POLLINATIONS_TOKEN="your_key"
   ```

4. Deploy:

   ```bash
   fly deploy
   ```

5. Monitor logs:

   ```bash
   fly logs
   ```

### Deploy — AI Company bot

Repeat the same steps from the `ai-company/` directory, using the appropriate environment variables:

```bash
cd ai-company
fly launch --no-deploy
fly secrets set DISCORD_TOKEN_COMPANY="your_token" POLLINATIONS_TOKEN="your_key"
fly deploy
```

Fly.io keeps the container running continuously with automatic restarts.

---

## Heroku

Heroku supports Python worker dynos suitable for Discord bots.

> **Pricing note:** Heroku removed its free tier in 2022. The cheapest paid plan (Eco dynos) starts at ~$5/month.

### Prerequisites

- [Install the Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli)
- A Heroku account

### Deploy — General Chat bot

1. Create a `general-chat/Procfile`:

   ```
   worker: python bot.py
   ```

2. From the repository root, create a new Heroku app:

   ```bash
   heroku create my-discord-bot
   ```

3. Set the stack and buildpack:

   ```bash
   heroku buildpacks:set heroku/python --app my-discord-bot
   ```

4. Set config vars:

   ```bash
   heroku config:set DISCORD_TOKEN="your_token" --app my-discord-bot
   heroku config:set POLLINATIONS_TOKEN="your_key" --app my-discord-bot
   ```

5. Push to Heroku:

   ```bash
   git subtree push --prefix general-chat heroku main
   ```

6. Scale the worker:

   ```bash
   heroku ps:scale worker=1 --app my-discord-bot
   ```

7. View logs:

   ```bash
   heroku logs --tail --app my-discord-bot
   ```

### Deploy — AI Company bot

Create a separate Heroku app following the same steps, using `ai-company/` as the prefix and `DISCORD_TOKEN_COMPANY` as the environment variable.

---

## Oracle Cloud Free Tier

Oracle Cloud offers a **permanently free** tier that includes 2 AMD-based Compute VMs (1 GB RAM each) — enough to run both Discord bots indefinitely at no cost.

### Prerequisites

- An [Oracle Cloud](https://cloud.oracle.com) account (free tier; credit card required for verification but not charged)

### Steps

1. **Create a VM instance**
   - Go to **Compute → Instances → Create Instance**.
   - Choose **Always Free Eligible** shape (e.g. `VM.Standard.E2.1.Micro`).
   - Use an Ubuntu 22.04 image.
   - Download or provide your SSH public key.
   - Click **Create**.

2. **Open port 22** (SSH) in the Security List if it is not already open.

3. **SSH into the VM:**

   ```bash
   ssh -i <your-private-key> ubuntu@<instance-public-ip>
   ```

4. **Follow the [Linux / VPS](#linux--vps) instructions** above to install Python, clone the repository, and run the bot as a `systemd` service for automatic startup and restart.

The Oracle free-tier VMs provide a full-time persistent process, so both bots run 24/7 without any cron jobs or restarts.

---

## Environment Variables Reference

### General Chat bot (`general-chat/bot.py`)

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | ✅ | Discord bot token |
| `POLLINATIONS_TOKEN` | ✅ | Pollinations AI API key |

### AI Company bot (`ai-company/bot.py`)

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN_COMPANY` | ✅ | Discord bot token |
| `POLLINATIONS_TOKEN` | ✅ | Pollinations AI API key |
| `GITHUB_TOKEN` | Required for `/build` | GitHub token with repo write access. Provided automatically in GitHub Actions. |
| `GITHUB_REPOSITORY` | Required for `/build` | Repository in `owner/repo` format. Set automatically in GitHub Actions. |

### Unified bot (`bot.py`) — all of the above plus:

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | ✅ | Discord bot token |
| `POLLINATIONS_TOKEN` | ✅ | Pollinations AI API key |
| `GITHUB_TOKEN` | optional | GitHub PAT — needed for `/build` to commit files |
| `GITHUB_REPOSITORY` | optional | `owner/repo` — needed for `/build` to commit files |
| `WEATHER_CHANNEL_ID` | optional | Discord channel ID for auto HK weather reminders |
| `WEATHER_REMINDER_HOURS` | optional | HKT hours to post reminders (default `8`). E.g. `8,20` |

---

## Platform Comparison

| Platform | Always-on | Gateway bot | Streaming | Cost | Notes |
|---|:---:|:---:|:---:|---|---|
| **Railway** | ✅ | ✅ | ✅ | ~$0–5/mo | Easiest managed option; see [RAILWAY.md](RAILWAY.md) |
| **Fly.io** | ✅ | ✅ | ✅ | Free tier available | Docker-based; global regions |
| **Oracle Cloud** | ✅ | ✅ | ✅ | **Free forever** | 2 free VMs; full Linux control |
| **Render** (paid) | ✅ | ✅ | ✅ | ~$7/mo | Free tier sleeps; not suitable for bots |
| **Heroku** | ✅ | ✅ | ✅ | ~$5/mo | No free tier; well-established platform |
| **Vercel** | ✅ | ❌ | ❌ | Free | Slash commands only; see [VERCEL.md](VERCEL.md) |
| **GitHub Actions** | ⚠️ 6 h max | ✅ | ✅ | Free | Manual restart after 6 h |
| **Linux VPS / Docker** | ✅ | ✅ | ✅ | ~$5/mo | Full control; use `systemd` |

---

## Troubleshooting

### `DISCORD_TOKEN` / `DISCORD_TOKEN_COMPANY` not set

```
KeyError: 'DISCORD_TOKEN'
```

Make sure the environment variable is exported before running the bot.  
On Linux/macOS: `export DISCORD_TOKEN="..."` — on Windows: `set DISCORD_TOKEN=...`

### Message Content Intent warning

```
discord.ext.commands.bot: Privileged message content intent is missing, commands may not work as expected.
```

This warning only affects the **General Chat** bot, which reads message content to respond to mentions.  
Fix: in the [Discord Developer Portal](https://discord.com/developers/applications) open your bot → **Bot** → scroll to **Privileged Gateway Intents** → enable **Message Content Intent** → **Save Changes**.

> The **AI Company** bot uses slash commands only and does **not** require the Message Content Intent.

### PyNaCl / voice warning

```
discord.client: PyNaCl is not installed, voice will NOT be supported
```

This warning is suppressed once you install dependencies with `pip install -r requirements.txt` (PyNaCl is included).  
Neither bot uses voice, so this has no functional impact.

### Slash commands not appearing in Discord

Slash commands are registered globally when the bot first comes online.  
It can take up to **1 hour** for them to propagate to all servers. If they never appear:

1. Ensure `applications.commands` scope was checked when generating the invite URL.
2. Restart the bot to force a fresh `tree.sync()` call.

### Bot goes offline after ~6 hours on GitHub Actions

This is expected — GitHub Actions jobs have a maximum runtime.  
The automatic cron restart has been **disabled** in the workflow files.  
To restart the bot, go to the **Actions** tab → click the workflow → **Run workflow**.  
For continuous uptime, use Railway, Fly.io, Oracle Cloud Free Tier, or a dedicated Linux server.
