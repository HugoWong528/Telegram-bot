# Deploying to Railway.com

Railway is the **easiest fully-managed platform** for running this Telegram bot 24/7.  
Unlike Vercel (which is serverless), Railway runs a persistent process — which means the full Telegram polling connection stays alive, including real-time streaming replies.

> **No code changes are required.** The bot works out of the box on Railway.

---

## Table of Contents

- [Why Railway?](#why-railway)
- [Pricing](#pricing)
- [Step 1 – Create a Telegram Bot Token](#step-1--create-a-telegram-bot-token)
- [Step 2 – Fork the Repository](#step-2--fork-the-repository)
- [Step 3 – Create a Railway Account](#step-3--create-a-railway-account)
- [Step 4 – Create a New Project](#step-4--create-a-new-project)
- [Step 5 – Configure the Service](#step-5--configure-the-service)
- [Step 6 – Add Environment Variables](#step-6--add-environment-variables)
- [Step 7 – Deploy](#step-7--deploy)
- [Step 8 – Monitor Logs](#step-8--monitor-logs)
- [Step 9 – Register Commands with BotFather](#step-9--register-commands-with-botfather)
- [Environment Variables Reference](#environment-variables-reference)
- [Automatic Restarts and Health](#automatic-restarts-and-health)
- [Updating the Bot](#updating-the-bot)
- [Troubleshooting](#troubleshooting)

---

## Why Railway?

| Feature | Details |
|---|---|
| **Always-on** | Your bot runs continuously — no sleeping, no 6-hour limit |
| **Polling support** | Full Telegram Bot API long-polling: real-time messages |
| **Auto-deploy** | Push to GitHub → Railway redeploys automatically |
| **Auto-restart** | If the bot crashes, Railway restarts it immediately |
| **No code changes** | The bot runs as-is; Railway detects Python automatically |
| **Log streaming** | View live logs in the Railway dashboard |

---

## Pricing

Railway uses a **credit-based billing** system:

| Plan | Monthly Credit | Notes |
|---|---|---|
| **Hobby** (free) | $5 of compute credit/month | Requires a verified account; sufficient for a single lightweight bot |
| **Pro** | $20/month flat + usage | Best for bots with heavy traffic or multiple services |

A Telegram bot running idle on Railway typically uses well under $5/month of compute.  
See [railway.app/pricing](https://railway.app/pricing) for the latest pricing.

> **Tip:** To unlock the free $5 monthly credit you must verify your Railway account with a credit card or GitHub account. The card is **not charged** unless you exceed the free credit.

---

## Step 1 – Create a Telegram Bot Token

1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`.
3. Follow the prompts — choose a **display name** and a **username** (must end in `bot`, e.g. `MyAIAssistantBot`).
4. BotFather will reply with your **bot token** — it looks like:
   ```
   7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
   **Copy this token.** You will need it in Step 6.

5. *(Optional but recommended)* Register commands with BotFather so users see autocomplete:
   ```
   /setcommands
   ```
   Then select your bot and paste:
   ```
   start - Show the help guide
   about - Show the full help guide
   ask - Ask the AI a question
   cancel - Cancel your in-progress request
   models - List all available AI models
   settings - Set your preferred AI model
   company - Run a multi-role AI company discussion
   build - Developer team discussion + code generation
   autorun - Fully autonomous build (AI picks the task)
   company_roles - List all available roles
   followup - Context-aware continuation
   weather - Current HK weather + AI suggestions
   ```

---

## Step 2 – Fork the Repository

You must have the repository in your own GitHub account so Railway can access it.

1. Go to [github.com/HugoWong528/Telegram-bot](https://github.com/HugoWong528/Telegram-bot).
2. Click **Fork** (top-right) → **Create fork**.

---

## Step 3 – Create a Railway Account

1. Go to [railway.app](https://railway.app) and click **Login**.
2. Click **Login with GitHub** (recommended — Railway can access your repositories).
3. Authorise the OAuth application.
4. If prompted to verify your account, follow the on-screen instructions.

---

## Step 4 – Create a New Project

1. In the Railway dashboard click **New Project**.
2. Select **Deploy from GitHub repo**.
3. Search for or scroll to your forked **Telegram-bot** repository and click it.
4. Railway will ask *"Which branch?"* — choose `main` (or your default branch).

---

## Step 5 – Configure the Service

After Railway creates the initial service:

1. Click on the service card to open its settings.
2. **Leave Root Directory empty** (or set it to `/`).  
   The `railway.toml` is at the **repository root**, so Railway picks it up automatically.
3. Verify the **Start Command** field is either empty (Railway reads it from `railway.toml`) or manually set to:
   ```
   python bot.py
   ```
4. Leave **Port** empty or set *"No exposed port"* — this is a long-polling background worker, not a web server.

---

## Step 6 – Add Environment Variables

1. In the service settings, click the **Variables** tab.
2. Click **New Variable** and add the following:

   | Name | Required | Value |
   |---|:---:|---|
   | `TELEGRAM_TOKEN` | ✅ | Your Telegram bot token from BotFather (Step 1) |
   | `POLLINATIONS_TOKEN` | ✅ | Your Pollinations AI API key from [enter.pollinations.ai](https://enter.pollinations.ai) |
   | `GITHUB_TOKEN` | ⚠️ `/build` only | GitHub Personal Access Token (PAT) with `repo` write scope |
   | `GITHUB_REPOSITORY` | ⚠️ `/build` only | Your repo in `owner/repo` format, e.g. `YourName/Telegram-bot` |
   | `WEATHER_CHAT_ID` | optional | Telegram chat ID to post auto HK weather reminders |
   | `WEATHER_REMINDER_HOURS` | optional | Comma-separated HKT hours to post (default: `8`). E.g. `8,20` |

3. Click **Add** after each variable.  Railway will automatically redeploy when variables change.

> **Security:** Railway encrypts all environment variables at rest. Never paste tokens directly into `bot.py` or commit them to Git.

---

## Step 7 – Deploy

If Railway did not start a deployment automatically:

1. Click **Deploy** (top-right of the service panel).
2. Watch the **Build Logs** tab — you should see nixpacks installing Python dependencies and then starting the bot.

A successful deployment looks like:

```
#1 Building with Nixpacks
...
✅ Build succeeded
Starting service...
2025-01-01 00:00:00,000 [INFO] __main__: Starting Telegram bot (polling)…
```

---

## Step 8 – Monitor Logs

1. In the Railway dashboard, click on your service.
2. Click the **Logs** tab to see live output from the bot.
3. You can filter by log level or search for specific text.

---

## Step 9 – Register Commands with BotFather

To get command autocomplete in Telegram:

1. Open [@BotFather](https://t.me/BotFather) in Telegram.
2. Send `/setcommands`.
3. Select your bot from the list.
4. Paste the command list from [Step 1](#step-1--create-a-telegram-bot-token).

---

## Environment Variables Reference

| Variable | Required | Description |
|---|:---:|---|
| `TELEGRAM_TOKEN` | ✅ | Telegram bot token from BotFather |
| `POLLINATIONS_TOKEN` | ✅ | Pollinations AI API key |
| `GITHUB_TOKEN` | ⚠️ `/build` only | GitHub Personal Access Token (PAT) with `repo` write scope |
| `GITHUB_REPOSITORY` | ⚠️ `/build` only | Repository in `owner/repo` format |
| `WEATHER_CHAT_ID` | optional | Telegram chat ID for auto HK weather reminders |
| `WEATHER_REMINDER_HOURS` | optional | HKT hours to post reminders (default `8`). E.g. `8,20` |

---

## Automatic Restarts and Health

The `railway.toml` at the repo root configures:

```toml
[deploy]
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 10
```

Railway automatically restarts the bot if it crashes, up to 10 times.  After 10 consecutive failures the service is marked as failed and you will receive an email notification.

To trigger a manual restart:

1. Open the service in the Railway dashboard.
2. Click **⋮ (More)** → **Restart Service**.

---

## Updating the Bot

Railway watches your GitHub repository for new commits.  Every push to the branch you selected triggers a new deployment automatically.

```bash
git add .
git commit -m "Update bot"
git push origin main
```

Railway will:

1. Detect the new commit.
2. Build the new image using nixpacks.
3. Gracefully stop the old service and start the new one.
4. Roll back automatically if the new build fails.

---

## Troubleshooting

### Build fails with "no module named telegram"

Make sure `requirements.txt` is present at the repository root and contains:

```
python-telegram-bot[job-queue]==22.7
aiohttp==3.13.3
```

### Bot starts but immediately exits

This almost always means a missing environment variable.  Check the **Logs** tab for:

```
TELEGRAM_TOKEN is not set.
```

Fix: go to **Variables** → add the missing variable → Railway redeploys.

### Bot is running but not responding

1. Verify the token is correct — copy it fresh from BotFather (`/mybots` → select bot → *API Token*).
2. Make sure you are messaging the correct bot (search by the username you gave it).
3. In groups: the bot only responds when **mentioned** (`@YourBotUsername`). In private chats it responds to every message.

### Commands not appearing in Telegram

Run `/setcommands` in BotFather as described in [Step 9](#step-9--register-commands-with-botfather).  Commands registered with BotFather appear in the autocomplete menu immediately.

### How to find your Chat ID (for WEATHER_CHAT_ID)

- **Private chat:** forward any message to [@userinfobot](https://t.me/userinfobot) — it replies with your user/chat ID.
- **Group chat:** add [@RawDataBot](https://t.me/RawDataBot) to the group temporarily; it sends a JSON dump of every message including `chat.id`.
- The group/channel chat ID is typically a negative number like `-1001234567890`.

---

> For other deployment options (Linux/VPS, Docker, GitHub Actions) see **[PLATFORM.md](PLATFORM.md)**.
