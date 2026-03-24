# AI Discord Bot

This repository offers a **unified bot** that combines general AI chat, multi-role company discussions, autonomous code generation, code review, and **Hong Kong weather reminders** into a **single Discord bot token**.  The legacy individual bots are kept for backwards compatibility.

| Mode | Entry point | Description |
|---|---|---|
| 🤖 **Unified Bot** (recommended) | [`bot.py`](bot.py) | Single bot — one `DISCORD_TOKEN` covers all features below |
| 🗨️ **General Chat only** | [`general-chat/bot.py`](general-chat/bot.py) | Streaming AI replies to mentions/DMs |
| 🏢 **AI Company only** | [`ai-company/bot.py`](ai-company/bot.py) | Company discussions, `/build`, `/autorun` |

All bots are powered by [Pollinations AI](https://pollinations.ai) and run on Python 3.11.

For platform-specific deployment instructions (Linux/VPS, macOS, Windows, Docker, GitHub Actions, Railway, Render, Fly.io, Heroku, Oracle Cloud) see **[PLATFORM.md](PLATFORM.md)**.  
For Vercel and always-on hosting see **[VERCEL.md](VERCEL.md)**.  
For Railway.com (easiest always-on) see **[RAILWAY.md](RAILWAY.md)**.

---

## What's New

- **Unified single-token bot** — run `bot.py` at the root with one `DISCORD_TOKEN`
- **Automatic code review** — after `/build` or `/autorun` generates code, a Code Reviewer AI checks for critical issues and automatically regenerates if needed (up to 2 rounds)
- **Automatic format retry** — if the AI output doesn't contain `### File:` blocks, the bot retries up to 3 times before giving up
- **Universal `/followup`** — replaces both `/interrupt` and the old `/followup`; it automatically detects context:
  - If an AI stream is in progress → cancels it and redirects with your input
  - If a `/build` or `/autorun` session exists → builds follow-up (amend code, ask questions); **supports unlimited chained follow-ups**, each with full context of all prior exchanges
  - Otherwise → continues the general chat conversation
- **`/weather`** — fetches current Hong Kong weather from the HKO official RSS feed and generates AI-powered clothing suggestions (Traditional Chinese + English); optional auto-reminders to a configured channel

---

## Repository Structure

```
AI-discord-bot/
├── bot.py                  # ★ Unified bot — single DISCORD_TOKEN, all features
├── requirements.txt        # Dependencies for the unified bot
├── runtime.txt             # Python version
├── railway.toml            # Railway deployment config (unified bot)
├── general-chat/
│   ├── bot.py              # General-purpose AI chat bot (standalone)
│   └── requirements.txt
├── ai-company/
│   ├── bot.py              # AI company + build bot (standalone)
│   ├── requirements.txt
│   └── SETUP.md
├── .github/workflows/
│   ├── bot.yml                     # ★ Workflow: Unified bot (DISCORD_TOKEN)
│   ├── discord-bot.yml             # Workflow: General Chat only
│   └── discord-ai-company-bot.yml  # Workflow: AI Company only
├── PLATFORM.md             # All platforms deployment guide
├── VERCEL.md               # Vercel / Render deployment guide
├── RAILWAY.md              # Railway.com deployment guide
└── README.md
```

---

## Quick Start — Unified Bot

### 1. Create a Discord Bot & Get Tokens

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**.
2. In **Bot** → **Reset Token** → copy your `DISCORD_TOKEN`.
3. Enable **Message Content Intent** under **Privileged Gateway Intents**.
4. Go to <https://enter.pollinations.ai> and copy your `POLLINATIONS_TOKEN`.

### 2. Invite the Bot to Your Server

In **OAuth2 → URL Generator**:
- **Scopes:** `bot` + `applications.commands`
- **Bot Permissions:** `Send Messages`, `Read Messages / View Channels`, `Read Message History`, `Create Public Threads`

Copy the URL and invite the bot.

### 3. Run Locally

```bash
git clone https://github.com/HugoWong528/AI-discord-bot.git
cd AI-discord-bot

pip install -r requirements.txt

export DISCORD_TOKEN="your_discord_bot_token"
export POLLINATIONS_TOKEN="your_pollinations_api_key"
# Optional — needed for /build to commit generated code:
# export GITHUB_TOKEN="your_github_pat"
# export GITHUB_REPOSITORY="owner/repo"
# Optional — auto weather reminders (Hong Kong):
# export WEATHER_CHANNEL_ID="your_discord_channel_id"
# export WEATHER_REMINDER_HOURS="8,20"   # HKT hours to post (default: 8)

python bot.py
```

### 4. GitHub Actions (zero infrastructure)

Add repository secrets (Settings → Secrets → Actions):

| Secret | Value |
|---|---|
| `DISCORD_TOKEN` | Your Discord bot token |
| `POLLINATIONS_TOKEN` | Your Pollinations API key |

Then go to **Actions → Unified AI Discord Bot → Run workflow**.

---

## All Slash Commands (Unified Bot)

### General Chat

| Command | Description |
|---|---|
| `/ask question:[…] model:[optional]` | Ask the AI; response streams live to Discord |
| `/cancel` | Cancel your current in-progress AI request |
| `/models` | List all available AI models |
| `/settings model:[optional]` | View or set your preferred AI model |
| `/about` | Show the full help guide |

### AI Company / Build

| Command | Description |
|---|---|
| `/company task:[…]` | Multi-role AI company discussion |
| `/company task:[…] roles:[r1,r2,…] interactive:True` | Customised + interactive |
| `/build task:[…]` | Developer team discussion + code gen + GitHub commit |
| `/build task:[…] roles:[…] interactive:True` | Customised build + interactive |
| `/autorun` | Fully autonomous: AI picks task + builds end-to-end |
| `/autorun stack:python` | Force a specific tech stack |
| `/company_roles` | List all available roles |

### Weather

| Command | Description |
|---|---|
| `/weather` | Current HK weather (HKO RSS) + AI clothing suggestions |

### Universal

| Command | Description |
|---|---|
| `/followup request:[…]` | **Context-aware**: redirects an active stream, continues a build session (chained), or adds to general chat |

---

## How /followup Works

`/followup` is the single command for all "continue the conversation" needs — no need to remember whether to use `/interrupt` or `/followup`:

1. **If an AI stream is running** → cancels it and redirects with your input (like the old `/interrupt`)
2. **If a `/build` or `/autorun` session exists in this channel** → build follow-up: amend code, ask questions, generate new files and commit them.  You can chain as many follow-ups as you like — each one sees the **full history** of all prior exchanges.
3. **Any other time** → general chat follow-up: adds your message to the conversation history and gets a streaming AI reply

```
/followup request:Add JWT authentication to the API
/followup request:Now add rate limiting to the auth routes
/followup request:Can you write unit tests for the middleware?
/followup request:Actually, make the tests use pytest-asyncio
```

Each follow-up builds on every previous one.  You can also **interrupt a follow-up that is mid-stream** by issuing another `/followup` — it cancels the in-progress response and immediately starts the new one.

---

## Hong Kong Weather — /weather

The `/weather` command fetches the current official weather bulletin from the **Hong Kong Observatory** RSS feed:

- **Source:** <https://rss.weather.gov.hk/rss/CurrentWeather_uc.xml>
- **Data shown:** temperature (°C), relative humidity (%), current weather condition
- **AI suggestion:** what to wear today (Traditional Chinese + English)

### Auto Weather Reminders

Set two environment variables to have the bot post a weather report automatically:

| Variable | Description |
|---|---|
| `WEATHER_CHANNEL_ID` | Discord channel ID to post reminders to |
| `WEATHER_REMINDER_HOURS` | Comma-separated hours in HKT to post (default: `8`).  E.g. `8,20` posts at 08:00 and 20:00 HKT. |

Example:
```
WEATHER_CHANNEL_ID=1234567890123456789
WEATHER_REMINDER_HOURS=8,20
```

---

## Automatic Code Review (new)

After `/build` or `/autorun` generates code, the bot automatically:

1. **Format check** — verifies `### File:` blocks were produced; retries generation up to **3 times** if not
2. **Code review** — a Code Reviewer AI checks for critical issues (syntax errors, missing imports, unimplemented placeholders, broken dependencies)
3. **Auto-fix loop** — if issues are found, regenerates the code with the reviewer's feedback injected into the prompt (up to **2 review rounds**)
4. **Upload to GitHub** — commits the verified code to `project/<slug>/` in the repository

---

## How to Use the Bots

### General Chat (mention or `/ask`)

```
@MyAIBot What is quantum computing?
@MyAIBot @gemini-search What's in the news today?
@MyAIBot @deepseek Write a haiku about autumn.
/ask question:Explain async/await in Python model:openai-fast
```

### AI Company Discussion

```
/company task:Build a food delivery app
/company task:Launch a campaign roles:CEO,Marketing Manager,Designer interactive:True
```

### Build & AutoRun

```
/build task:Create a REST API for a todo app in Python
/build task:Build a React todo dashboard interactive:True
/autorun
/autorun stack:python
```

### Multiple Chained Follow-ups After a Build

```
/followup request:Add user authentication with JWT
/followup request:Now add rate limiting to the auth routes
/followup request:Can you write unit tests for the middleware?
/followup request:Fix the import error in test_auth.py
```

### Weather

```
/weather
```

---

## Available AI Models

| Model | Vision | Notes |
|---|:---:|---|
| `openai-fast` | ✅ | Fast OpenAI model; default first choice |
| `openai` | ✅ | Full OpenAI model |
| `gemini-search` | ✅ | Gemini with Google Search grounding |
| `gemini` | ✅ | Standard Gemini model |
| `gemini-fast` | ✅ | Faster Gemini variant |
| `gemini-large` | ✅ | Larger Gemini variant |
| `claude-fast` | ✅ | Fast Claude model |
| `glm` | ❌ | GLM model |
| `qwen-character` | ❌ | Qwen character model |
| `deepseek` | ❌ | DeepSeek model |
| `qwen-safety` | ❌ | Qwen safety model |

---

## Configuration Reference

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | ✅ | Discord bot token (unified bot + general-chat) |
| `DISCORD_TOKEN_COMPANY` | legacy | Only needed when running `ai-company/bot.py` standalone |
| `POLLINATIONS_TOKEN` | ✅ | Pollinations AI API key |
| `GITHUB_TOKEN` | optional | GitHub PAT — needed for `/build` to commit files |
| `GITHUB_REPOSITORY` | optional | `owner/repo` — needed for `/build` to commit files |
| `WEATHER_CHANNEL_ID` | optional | Discord channel ID for auto weather reminders |
| `WEATHER_REMINDER_HOURS` | optional | HKT hours for auto reminders (default: `8`). E.g. `8,20` |

---

## Legacy Standalone Bots

The individual bots still work independently if you prefer them:

```bash
# General Chat only
pip install -r general-chat/requirements.txt
export DISCORD_TOKEN="..."
export POLLINATIONS_TOKEN="..."
python general-chat/bot.py

# AI Company only
pip install -r ai-company/requirements.txt
export DISCORD_TOKEN_COMPANY="..."
export POLLINATIONS_TOKEN="..."
python ai-company/bot.py
```

For the AI Company standalone setup, see **[`ai-company/SETUP.md`](ai-company/SETUP.md)**.

---

## Interactive Mode (builds)

Pass `interactive:True` to `/company` or `/build`. After each role responds, you see:

- **▶ Continue** — let the discussion proceed
- **✏️ Add My Input** — type your perspective (up to 1 000 chars); it becomes **Stakeholder Input** that all subsequent roles can see and react to

`/autorun` always runs interactive with a 90-second auto-continue timer.

---

## Notes

- Sessions are stored **in memory** — restart the bot and sessions reset. Use Railway or a VPS for persistent uptime.
- If all AI models fail: *"Sorry, all AI models are currently unavailable."*
- Responses exceeding Discord's 2 000-character limit are automatically split into multiple messages.
- Code fences (```` ``` ````) are properly opened/closed across splits to preserve Discord's syntax highlighting.
- Build-session `/followup` calls are **serialised per channel** — if you fire two `/followup` commands in rapid succession, the second waits for the first to finish to avoid race conditions.
