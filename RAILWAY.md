# Deploying to Railway.com

Railway is the **easiest fully-managed platform** for running these Discord bots 24/7.  
Unlike Vercel (which is serverless), Railway runs a persistent process — the same way you would on a VPS — which means the full Discord Gateway (WebSocket) connection is supported, including `@mention` responses and real-time streaming.

> **No code changes are required.** The bots work out of the box on Railway.

There are three ways to run the bot on Railway:

| Option | Entry point | When to use |
|---|---|---|
| ⭐ **Unified Bot** (recommended) | `bot.py` at repo root | One token, all features (chat + build + weather) |
| **General Chat only** | `general-chat/bot.py` | Lightweight chat-only deployment |
| **AI Company only** | `ai-company/bot.py` | Build/autorun-only deployment |

---

## Table of Contents

- [Why Railway?](#why-railway)
- [Pricing](#pricing)
- [Part 1 — Deploy the Unified Bot (Recommended)](#part-1--deploy-the-unified-bot-recommended)
  - [Step 1 – Fork the repository](#step-1--fork-the-repository)
  - [Step 2 – Create a Railway account](#step-2--create-a-railway-account)
  - [Step 3 – Create a new project](#step-3--create-a-new-project)
  - [Step 4 – Configure the service](#step-4--configure-the-service)
  - [Step 5 – Add environment variables](#step-5--add-environment-variables)
  - [Step 6 – Deploy](#step-6--deploy)
  - [Step 7 – Monitor logs](#step-7--monitor-logs)
- [Part 2 — Deploy the General Chat Bot (standalone)](#part-2--deploy-the-general-chat-bot-standalone)
- [Part 3 — Deploy the AI Company Bot (standalone)](#part-3--deploy-the-ai-company-bot-standalone)
- [Deploying Both Legacy Bots in One Project](#deploying-both-legacy-bots-in-one-project)
- [Environment Variables Reference](#environment-variables-reference)
- [Automatic Restarts and Health](#automatic-restarts-and-health)
- [Updating the Bot](#updating-the-bot)
- [Troubleshooting](#troubleshooting)
- [Comparison with Other Platforms](#comparison-with-other-platforms)

---

## Why Railway?

| Feature | Details |
|---|---|
| **Always-on** | Your bot runs continuously — no sleeping, no 6-hour limit |
| **Gateway support** | Full Discord WebSocket gateway: `@mention`, streaming, DMs all work |
| **Auto-deploy** | Push to GitHub → Railway redeploys automatically |
| **Auto-restart** | If the bot crashes, Railway restarts it immediately |
| **No code changes** | The bots run as-is; Railway detects Python automatically |
| **Log streaming** | View live logs in the Railway dashboard |

---

## Pricing

Railway uses a **credit-based billing** system:

| Plan | Monthly Credit | Notes |
|---|---|---|
| **Hobby** (free) | $5 of compute credit/month | Requires a verified account; sufficient for a single lightweight bot |
| **Pro** | $20/month flat + usage | Best for bots with heavy traffic or multiple services |

A Discord bot running idle on Railway typically uses well under $5/month of compute.  
See [railway.app/pricing](https://railway.app/pricing) for the latest pricing.

> **Tip:** To unlock the free $5 monthly credit you must verify your Railway account with a credit card or GitHub account. The card is **not charged** unless you exceed the free credit.

---

## Part 1 — Deploy the Unified Bot (Recommended)

The **unified bot** (`bot.py` at the repo root) combines the General Chat bot, the AI Company bot, and the Hong Kong weather feature into a **single service with one `DISCORD_TOKEN`**.  This is the easiest way to get everything running on Railway.

### Step 1 – Fork the repository

You must have the repository in your own GitHub account so Railway can access it.

1. Go to [github.com/HugoWong528/AI-discord-bot](https://github.com/HugoWong528/AI-discord-bot).
2. Click **Fork** (top-right) → **Create fork**.

---

### Step 2 – Create a Railway account

1. Go to [railway.app](https://railway.app) and click **Login**.
2. Click **Login with GitHub** (recommended — Railway can access your repositories).
3. Authorise the OAuth application.
4. If prompted to verify your account, follow the on-screen instructions.

---

### Step 3 – Create a new project

1. In the Railway dashboard click **New Project**.
2. Select **Deploy from GitHub repo**.

   ![Deploy from GitHub repo](https://railway.app/brand/logo-dark.svg)
   *(You will see a list of your repositories.)*

3. Search for or scroll to your forked **AI-discord-bot** repository and click it.
4. Railway will ask *"Which branch?"* — choose `main` (or whatever your default branch is).

---

### Step 4 – Configure the service

After Railway creates the initial service:

1. Click on the service card to open its settings.
2. **Leave Root Directory empty** (or set it to `/`).  
   The unified bot's `railway.toml` is at the **repository root**, so Railway picks it up automatically.  There is no need to point to a subdirectory.
3. Verify the **Start Command** field is either empty (Railway reads it from `railway.toml`) or manually set to:
   ```
   python bot.py
   ```
   The root-level `railway.toml` already specifies this command, so no manual entry is required.
4. Leave **Port** empty or set *"No exposed port"* — this is a background worker bot, not a web server.

---

### Step 5 – Add environment variables

1. In the service settings, click the **Variables** tab.
2. Click **New Variable** and add the following:

   | Name | Required | Value |
   |---|:---:|---|
   | `DISCORD_TOKEN` | ✅ | Your Discord bot token (from the [Discord Developer Portal](https://discord.com/developers/applications)) |
   | `POLLINATIONS_TOKEN` | ✅ | Your Pollinations AI API key (from [enter.pollinations.ai](https://enter.pollinations.ai)) |
   | `GITHUB_TOKEN` | ⚠️ `/build` only | GitHub Personal Access Token (PAT) with `repo` write scope |
   | `GITHUB_REPOSITORY` | ⚠️ `/build` only | Your repo in `owner/repo` format, e.g. `YourName/AI-discord-bot` |
   | `WEATHER_CHANNEL_ID` | optional | Discord channel ID to post auto HK weather reminders |
   | `WEATHER_REMINDER_HOURS` | optional | Comma-separated HKT hours to post (default: `8`). E.g. `8,20` |

3. Click **Add** after each variable.  Railway will automatically redeploy when variables change.

> **Security:** Railway encrypts all environment variables at rest. Never paste tokens directly into `bot.py` or commit them to Git.

---

### Step 6 – Deploy

If Railway did not start a deployment automatically:

1. Click **Deploy** (top-right of the service panel).
2. Watch the **Build Logs** tab — you should see nixpacks installing Python dependencies and then starting the bot.

A successful deployment looks like:

```
#1 Building with Nixpacks
...
✅ Build succeeded
Starting service...
2025-01-01 00:00:00,000 [INFO] __main__: Logged in as MyAIBot#1234 (ID: 123456789012345678)
```

---

### Step 7 – Monitor logs

1. In the Railway dashboard, click on your service.
2. Click the **Logs** tab to see live output from the bot.
3. You can filter by log level or search for specific text.

---

## Part 2 — Deploy the General Chat Bot (standalone)

Use this only if you want the General Chat bot running independently without the build/company or weather features.  The deployment steps are identical to Part 1 except for the **Root Directory**.

1. Create a new project (or add a new service to an existing project) and connect your forked repository.
2. Go to **Settings → Source → Root Directory** and set it to:
   ```
   general-chat
   ```
   This tells Railway to treat `general-chat/` as the project root, where `requirements.txt` and the `railway.toml` for this bot live.
3. Verify the **Start Command** is empty or set to `python bot.py`.
4. Add environment variables:

   | Name | Value |
   |---|---|
   | `DISCORD_TOKEN` | Your Discord bot token |
   | `POLLINATIONS_TOKEN` | Your Pollinations AI API key |

> **Note:** `GITHUB_TOKEN` and `GITHUB_REPOSITORY` are not used by the standalone General Chat bot.

---

## Part 3 — Deploy the AI Company Bot (standalone)

Use this only if you want the AI Company bot running independently.

1. In your Railway project, click **New Service → GitHub Repo** and pick your forked repo (or add a new service to an existing project).
2. Set the **Root Directory** to:
   ```
   ai-company
   ```
3. The `ai-company/railway.toml` already sets `startCommand = "python bot.py"`.
4. Add environment variables:

   | Name | Value | Required for |
   |---|---|---|
   | `DISCORD_TOKEN_COMPANY` | Discord bot token for the AI Company bot | Always |
   | `POLLINATIONS_TOKEN` | Pollinations AI API key | Always |
   | `GITHUB_TOKEN` | GitHub Personal Access Token (PAT) with `repo` write scope | `/build` command only |
   | `GITHUB_REPOSITORY` | Your repo in `owner/repo` format, e.g. `YourName/AI-discord-bot` | `/build` command only |

> **Note:** `GITHUB_TOKEN` and `GITHUB_REPOSITORY` are only needed if you want the `/build` command to commit generated code back to your repository. You can skip them initially.

---

## Deploying Both Legacy Bots in One Project

> **Recommendation:** Use the [unified bot (Part 1)](#part-1--deploy-the-unified-bot-recommended) instead — one service, one token, all features combined.

If you still want to run the two legacy bots separately in one Railway project, Railway supports multiple services inside a single project.  Running both bots in one project lets you share variables and view both log streams in the same dashboard.

### Setup

1. Create a new project and connect your repository (as above).
2. For the first service (General Chat), set **Root Directory** → `general-chat`.
3. Click **+ New** (top of the project canvas) → **GitHub Repo** → select the same repository.
4. For the second service (AI Company), set **Root Directory** → `ai-company`.
5. Add variables to each service independently (they have separate variable stores).

### Shared Variables (optional)

If both bots share the same Pollinations key, you can define `POLLINATIONS_TOKEN` as a **shared variable**:

1. Go to the project canvas → **Variables** (project-level, not service-level).
2. Add `POLLINATIONS_TOKEN` there.
3. Railway automatically injects shared variables into all services in the project.

---

## Environment Variables Reference

### Unified bot (`bot.py` — recommended)

| Variable | Required | Description |
|---|:---:|---|
| `DISCORD_TOKEN` | ✅ | Discord bot token from the Developer Portal |
| `POLLINATIONS_TOKEN` | ✅ | Pollinations AI API key |
| `GITHUB_TOKEN` | ⚠️ `/build` only | GitHub Personal Access Token (PAT) with `repo` write scope |
| `GITHUB_REPOSITORY` | ⚠️ `/build` only | Repository in `owner/repo` format |
| `WEATHER_CHANNEL_ID` | optional | Discord channel ID for auto HK weather reminders |
| `WEATHER_REMINDER_HOURS` | optional | HKT hours to post reminders (default `8`). E.g. `8,20` |

### General Chat bot (standalone)

| Variable | Required | Description |
|---|:---:|---|
| `DISCORD_TOKEN` | ✅ | Discord bot token from the Developer Portal |
| `POLLINATIONS_TOKEN` | ✅ | Pollinations AI API key |

### AI Company bot (standalone)

| Variable | Required | Description |
|---|:---:|---|
| `DISCORD_TOKEN_COMPANY` | ✅ | Discord bot token for the AI Company bot |
| `POLLINATIONS_TOKEN` | ✅ | Pollinations AI API key |
| `GITHUB_TOKEN` | ⚠️ `/build` only | GitHub Personal Access Token (PAT) with `repo` write scope |
| `GITHUB_REPOSITORY` | ⚠️ `/build` only | Repository in `owner/repo` format |

---

## Automatic Restarts and Health

The `railway.toml` included in each bot's directory configures:

```toml
[deploy]
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 10
```

This means Railway automatically restarts the bot if it crashes, up to 10 times.  After 10 consecutive failures the service is marked as failed and you will receive an email notification.

To trigger a manual restart at any time:

1. Open the service in the Railway dashboard.
2. Click **⋮ (More)** → **Restart Service**.

---

## Updating the Bot

Railway watches your GitHub repository for new commits.  Every push to the branch you selected triggers a new deployment automatically.

To update the bot:

```bash
# On your local machine
git add .
git commit -m "Update bot"
git push origin main
```

Railway will:

1. Detect the new commit.
2. Build the new image using nixpacks.
3. Gracefully stop the old service and start the new one.
4. Roll back automatically if the new build fails.

You can also **pause auto-deploy** from the service settings and deploy manually by clicking **Deploy** whenever you are ready.

---

## Troubleshooting

### Build fails with "no module named discord"

Railway uses nixpacks to detect and install Python dependencies.  Make sure `requirements.txt` is present in the service's root directory.

- **Unified bot:** leave Root Directory empty; `requirements.txt` is at the repo root.
- **Standalone bots:** verify the Root Directory is set correctly:

```
Service settings → Source → Root Directory → general-chat   (or ai-company)
```

---

### Bot starts but immediately exits

This almost always means a missing environment variable.  Check the **Logs** tab for:

```
KeyError: 'DISCORD_TOKEN'
```

Fix: go to **Variables** → add the missing variable → Railway redeploys.

---

### "Privileged Message Content Intent is missing"

```
discord.ext.commands.bot: Privileged message content intent is missing
```

The General Chat bot needs the **Message Content Intent** enabled in the Discord Developer Portal:

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications).
2. Open your application → **Bot**.
3. Scroll to **Privileged Gateway Intents**.
4. Toggle **Message Content Intent** ON.
5. Click **Save Changes**.

---

### Service keeps restarting / crash loop

1. Open **Logs** and look for the error before the crash.
2. Common causes: invalid token, network error, unhandled exception in bot code.
3. If the error is `discord.errors.LoginFailure: Improper token`, your `DISCORD_TOKEN` is wrong — reset it in the Discord Developer Portal and update the Railway variable.

---

### Slash commands not appearing in Discord

Slash commands are registered globally when the bot first connects.  Propagation can take up to **1 hour**.  If they never appear:

1. Ensure `applications.commands` scope was selected when generating the bot invite URL.
2. Restart the Railway service to force a fresh `tree.sync()` call.

---

### How to view historical logs

Railway retains logs for the current and recent deployments.  Click **Deployments** to see a list of past builds, then click any deployment to inspect its logs.

---

## Comparison with Other Platforms

| Platform | Always-on | Gateway bot | Streaming | Cost | Notes |
|---|:---:|:---:|:---:|---|---|
| **Railway** | ✅ | ✅ | ✅ | ~$0–5/mo | Easiest managed option; this guide |
| **Fly.io** | ✅ | ✅ | ✅ | Free tier available | Docker-based; global regions |
| **Oracle Cloud** | ✅ | ✅ | ✅ | **Free forever** | 2 free VMs; full Linux control |
| **Render** (paid) | ✅ | ✅ | ✅ | ~$7/mo | Free tier sleeps after inactivity |
| **Vercel** | ✅ | ❌ | ❌ | Free | Slash commands only (HTTP Interactions); see [VERCEL.md](VERCEL.md) |
| **GitHub Actions** | ⚠️ 6 h max | ✅ | ✅ | Free | Manual restart after 6 h; see [README.md](README.md) |
| **Linux VPS** | ✅ | ✅ | ✅ | ~$5/mo | Full control; see [PLATFORM.md](PLATFORM.md) |
| **Docker** | ✅ | ✅ | ✅ | Varies | Run anywhere; see [PLATFORM.md](PLATFORM.md) |

---

> For other deployment options (Linux, macOS, Windows, Docker, GitHub Actions) see **[PLATFORM.md](PLATFORM.md)**.  
> For Vercel (slash-command / HTTP Interactions) deployment see **[VERCEL.md](VERCEL.md)**.
