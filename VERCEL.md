# Deploying to Vercel for Always-On Hosting

> **TL;DR** — Vercel is a great choice for the *HTTP Interactions* (slash-command) style of Discord bot, but **cannot run the gateway (WebSocket) bot in this repo as-is**.  This guide explains why, shows you how to convert the General Chat bot to an HTTP-based deployment that runs forever for free on Vercel, and suggests the easiest truly-always-on alternatives.

---

## Table of Contents

- [Why Vercel alone does not work out of the box](#why-vercel-alone-does-not-work-out-of-the-box)
- [Option A — Deploy via Vercel + HTTP Interactions (recommended)](#option-a--deploy-via-vercel--http-interactions-recommended)
  - [1. Create the Vercel project](#1-create-the-vercel-project)
  - [2. Add environment variables](#2-add-environment-variables)
  - [3. Tell Discord where to send interactions](#3-tell-discord-where-to-send-interactions)
  - [4. Deploy and verify](#4-deploy-and-verify)
- [Option B — Keep the gateway bot and use a free always-on service](#option-b--keep-the-gateway-bot-and-use-a-free-always-on-service)
- [Option C — Railway or Render (free tier)](#option-c--railway-or-render-free-tier)
- [Comparison table](#comparison-table)

---

## Why Vercel alone does not work out of the box

The bots in this repository connect to Discord via the **Gateway** (a persistent WebSocket connection).  Vercel runs **serverless functions** that:

- Time out after **10 seconds** (Hobby plan) or **60 seconds** (Pro plan).
- Are spun up on each request and torn down immediately after — there is no persistent process.

A WebSocket bot needs to stay alive indefinitely, which is fundamentally incompatible with serverless execution.

**However**, Discord also supports an **HTTP Interactions** model: instead of maintaining a WebSocket, Discord sends an HTTPS `POST` request to your server each time a slash command is used.  Your function handles the request and responds — no long-lived connection required.  This model works perfectly on Vercel.

> **Limitation:** HTTP Interactions only support **slash commands**.  Responding to `@mentions` in messages (the `on_message` event) requires the Gateway and is **not** supported by Vercel alone.

---

## Option A — Deploy via Vercel + HTTP Interactions (recommended)

This option turns the slash commands (`/ask`, `/interrupt`, `/cancel`, `/models`, `/about`, `/settings`) into a Vercel serverless API endpoint.  The bot will always be online as long as your Vercel project is active.

### Prerequisites

| Requirement | Notes |
|---|---|
| [Vercel account](https://vercel.com) | Free Hobby plan is sufficient |
| Python 3.11+ | Only needed for local testing |
| `DISCORD_TOKEN` | Your bot token from the Discord Developer Portal |
| `DISCORD_PUBLIC_KEY` | Found in your application's **General Information** page |
| `POLLINATIONS_TOKEN` | Your Pollinations AI API key |

> You also need the `discord-interactions` Python package (`pip install discord-interactions`).

### 1. Create the Vercel project

1. **Fork or push** this repository to your own GitHub account.
2. Go to [vercel.com/new](https://vercel.com/new) and import your repository.
3. Set the **Framework Preset** to *Other* and the **Root Directory** to `general-chat/` (or `ai-company/`).
4. Leave the build command blank; Vercel will detect the Python `api/` folder automatically.

Create an `api/` folder inside `general-chat/` with an `interactions.py` file that is the Vercel entry point:

```
general-chat/
├── api/
│   └── interactions.py   ← Vercel serverless handler
├── bot.py
└── requirements.txt
```

**`general-chat/api/interactions.py`** — minimal example:

```python
import json
import os
from http.server import BaseHTTPRequestHandler

from discord_interactions import verify_key, InteractionType, InteractionResponseType

PUBLIC_KEY = os.environ["DISCORD_PUBLIC_KEY"]


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        signature = self.headers.get("X-Signature-Ed25519", "")
        timestamp = self.headers.get("X-Signature-Timestamp", "")

        # Verify the request came from Discord
        if not verify_key(body, signature, timestamp, PUBLIC_KEY):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Bad signature")
            return

        data = json.loads(body)

        # Discord requires us to respond to PING immediately
        if data["type"] == InteractionType.PING:
            self._json({"type": InteractionResponseType.PONG})
            return

        # Handle APPLICATION_COMMAND (slash commands)
        if data["type"] == InteractionType.APPLICATION_COMMAND:
            cmd = data["data"]["name"]
            if cmd == "ask":
                question = data["data"]["options"][0]["value"]
                # For a real implementation, call your AI here (synchronously or
                # via a background task queue such as Inngest or Upstash QStash)
                self._json({
                    "type": InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
                    "data": {"content": f"Your question: {question}\n*(AI reply goes here)*"},
                })
                return

        self.send_response(400)
        self.end_headers()

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
```

> **Note:** A full production handler would call the AI API asynchronously and respond with a deferred response (`DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE`) followed by a follow-up webhook call.  See the [Discord Interactions docs](https://discord.com/developers/docs/interactions/receiving-and-responding) for details.

Add `discord-interactions` to `general-chat/requirements.txt`:

```
discord.py==2.3.2
aiohttp==3.13.3
PyNaCl==1.6.2
discord-interactions
```

### 2. Add environment variables

In your Vercel project go to **Settings → Environment Variables** and add:

| Name | Value |
|---|---|
| `DISCORD_TOKEN` | Your Discord bot token |
| `DISCORD_PUBLIC_KEY` | Found in your app's **General Information** page in the Developer Portal |
| `POLLINATIONS_TOKEN` | Your Pollinations AI API key |

### 3. Tell Discord where to send interactions

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) → your application → **General Information**.
2. Under **Interactions Endpoint URL** enter:
   ```
   https://<your-project>.vercel.app/api/interactions
   ```
3. Click **Save Changes**.  Discord will send a `PING` to verify the URL — make sure your handler returns `PONG`.

### 4. Deploy and verify

```bash
# Push to your main branch — Vercel deploys automatically
git push origin main
```

Check the **Vercel dashboard → Deployments** to confirm the build succeeded.  Then use any slash command in Discord; each invocation creates a new serverless function call and the bot responds instantly.

---

## Option B — Keep the gateway bot and use a free always-on service

If you want to keep the full bot (including `@mention` responses and streaming) without changing the code, the easiest free options are:

### Railway

1. Sign up at [railway.app](https://railway.app) (free starter plan included).
2. Create a new project → **Deploy from GitHub repo**.
3. Set the start command to `python general-chat/bot.py` (or `python ai-company/bot.py`).
4. Add environment variables in the Railway dashboard:
   - `DISCORD_TOKEN`
   - `POLLINATIONS_TOKEN`
5. Deploy — Railway keeps your service running continuously with automatic restarts.

### Render

1. Sign up at [render.com](https://render.com).
2. Create a new **Background Worker** service and connect your GitHub repo.
3. Set the build command to `pip install -r general-chat/requirements.txt` and start command to `python general-chat/bot.py`.
4. Add environment variables (`DISCORD_TOKEN`, `POLLINATIONS_TOKEN`) in the Render dashboard.
5. Deploy — Render keeps the process alive on its free tier (note: free tier services sleep after 15 minutes of inactivity; paid plans run 24/7).

---

## Option C — Railway or Render (free tier)

See [Option B](#option-b--keep-the-gateway-bot-and-use-a-free-always-on-service) above — Railway and Render both have generous free tiers suitable for a Discord bot.

---

## Comparison table

| Platform | Always-on? | Supports gateway bot? | Cost | Notes |
|---|:---:|:---:|---|---|
| **Vercel** (serverless) | ✅ (per request) | ❌ (slash only) | Free | Best for HTTP Interactions |
| **Railway** | ✅ | ✅ | Free starter | Easiest fully-managed option; see [RAILWAY.md](RAILWAY.md) |
| **Fly.io** | ✅ | ✅ | Free tier available | Docker-based; global regions |
| **Oracle Cloud** | ✅ | ✅ | **Free forever** | 2 free VMs; full Linux control |
| **Render** (paid) | ✅ | ✅ | ~$7/mo | Free tier sleeps after inactivity |
| **GitHub Actions** | ⚠️ 6 h max | ✅ | Free | Restarts manually via `workflow_dispatch` |
| **Linux VPS** | ✅ | ✅ | ~$5/mo | Full control; use `systemd` (see PLATFORM.md) |
| **Docker** | ✅ | ✅ | Varies | Run anywhere Docker is available |

---

> For the full list of deployment platforms (Linux, macOS, Windows, Docker, GitHub Actions), see **[PLATFORM.md](PLATFORM.md)**.
