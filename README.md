# AI Telegram Bot

This repository provides a **unified Telegram bot** that combines general AI chat, multi-role company discussions, autonomous code generation, code review, and **Hong Kong weather reminders** — all powered by [Pollinations AI](https://pollinations.ai).

One `TELEGRAM_TOKEN` is all you need.

For **Railway** deployment (recommended always-on hosting) see **[RAILWAY.md](RAILWAY.md)**.  
For other platforms (Linux/VPS, Docker, macOS, Windows, GitHub Actions) see **[PLATFORM.md](PLATFORM.md)**.

---

## What's New

- **Telegram bot** — replaced the Discord bot; works in direct messages and group chats
- **Live streaming replies** — the bot edits its message as the AI streams tokens
- **Automatic code review** — after `/build` or `/autorun`, a Code Reviewer AI checks for critical issues and auto-regenerates (up to 2 rounds)
- **Universal `/followup`** — context-aware continuation:
  - Active AI stream → cancels it and redirects with your input
  - After `/build` / `/autorun` → build follow-up (amend code, ask questions); supports unlimited chained follow-ups
  - Otherwise → continues the general chat conversation
- **`/weather`** — fetches current Hong Kong weather from the HKO official RSS feed and generates AI-powered clothing suggestions (Traditional Chinese + English); optional auto-reminders

---

## Repository Structure

```
Telegram-bot/
├── bot.py               # ★ Unified Telegram bot — one TELEGRAM_TOKEN, all features
├── requirements.txt     # Python dependencies
├── runtime.txt          # Python version
├── railway.toml         # Railway deployment config
├── README.md
├── RAILWAY.md           # Railway.com deployment guide
├── PLATFORM.md          # All platforms deployment guide
└── APIDOCS.md           # Pollinations AI API reference
```

---

## Quick Start

### 1. Create a Telegram Bot & Get Your Token

1. Open Telegram and start a chat with **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot` and follow the prompts (choose a name and a username ending in `bot`).
3. BotFather will send you the bot token — copy it.  It looks like `7123456789:AAF...`.
4. *(Optional)* Register your bot commands with BotFather:
   ```
   /setcommands
   ```
   Then paste the list from the [Commands section](#all-commands) below.

### 2. Get a Pollinations API Key

Go to <https://enter.pollinations.ai> and copy your `POLLINATIONS_TOKEN`.

### 3. Run Locally

```bash
git clone https://github.com/HugoWong528/Telegram-bot.git
cd Telegram-bot

pip install -r requirements.txt

export TELEGRAM_TOKEN="your_telegram_bot_token"
export POLLINATIONS_TOKEN="your_pollinations_api_key"
# Optional — needed for /build to commit generated code:
# export GITHUB_TOKEN="your_github_pat"
# export GITHUB_REPOSITORY="owner/repo"
# Optional — auto weather reminders (Hong Kong):
# export WEATHER_CHAT_ID="your_telegram_chat_id"
# export WEATHER_REMINDER_HOURS="8,20"   # HKT hours to post (default: 8)

python bot.py
```

### 4. Deploy on Railway (Recommended)

Railway is the easiest way to keep your bot running 24/7.  See **[RAILWAY.md](RAILWAY.md)** for a step-by-step guide.

---

## All Commands

Register these with BotFather via `/setcommands`:

```
start - Show the help guide
about - Show the full help guide
ask - Ask the AI a question (live streaming)
cancel - Cancel your in-progress AI request
models - List all available AI models
settings - View or set your preferred AI model
company - Run a multi-role AI company discussion
build - Developer team discussion + code generation
autorun - Fully autonomous build (AI picks the task)
company_roles - List all available roles
followup - Context-aware continuation
weather - Current HK weather + AI clothing suggestions
```

### General Chat

| Command | Description |
|---|---|
| `/ask <question>` | Ask the AI; response streams live |
| `/ask model:<name> <question>` | Ask with a specific model |
| `/cancel` | Cancel your current in-progress AI request |
| `/models` | List all available AI models |
| `/settings <model>` | Set your preferred AI model |
| `/about` | Show the full help guide |

### AI Company / Build

| Command | Description |
|---|---|
| `/company <task>` | Multi-role AI company discussion |
| `/company <task> roles:CEO,CTO,Designer interactive:true` | Interactive mode |
| `/build <task>` | Developer team discussion + code gen + GitHub commit |
| `/build <task> roles:... interactive:true` | Interactive build |
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
| `/followup <request>` | **Context-aware**: redirects an active stream, continues a build session, or adds to general chat |

---

## How /followup Works

`/followup` is the single command for all "continue the conversation" needs:

1. **If an AI stream is running** → cancels it and redirects with your input
2. **If a `/build` or `/autorun` session exists in this chat** → build follow-up: amend code, ask questions, generate new files and commit them.  You can chain as many follow-ups as you like.
3. **Any other time** → general chat follow-up: adds your message to the conversation history and gets a streaming AI reply

```
/followup Add JWT authentication to the API
/followup Now add rate limiting to the auth routes
/followup Can you write unit tests for the middleware?
/followup Actually, make the tests use pytest-asyncio
```

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
| `WEATHER_CHAT_ID` | Telegram chat ID to post reminders to |
| `WEATHER_REMINDER_HOURS` | Comma-separated hours in HKT to post (default: `8`).  E.g. `8,20` posts at 08:00 and 20:00 HKT. |

To find your chat ID: forward a message to **[@userinfobot](https://t.me/userinfobot)** or use **[@RawDataBot](https://t.me/RawDataBot)**.

---

## Automatic Code Review

After `/build` or `/autorun` generates code, the bot automatically:

1. **Format check** — verifies `### File:` blocks were produced; retries generation up to **3 times** if not
2. **Code review** — a Code Reviewer AI checks for critical issues
3. **Auto-fix loop** — if issues are found, regenerates the code with the reviewer's feedback injected (up to **2 review rounds**)
4. **Upload to GitHub** — commits the verified code to `project/<slug>/` in the repository

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
| `TELEGRAM_TOKEN` | ✅ | Telegram bot token from BotFather |
| `POLLINATIONS_TOKEN` | ✅ | Pollinations AI API key |
| `GITHUB_TOKEN` | optional | GitHub PAT — needed for `/build` to commit files |
| `GITHUB_REPOSITORY` | optional | `owner/repo` — needed for `/build` to commit files |
| `WEATHER_CHAT_ID` | optional | Telegram chat ID for auto weather reminders |
| `WEATHER_REMINDER_HOURS` | optional | HKT hours for auto reminders (default: `8`). E.g. `8,20` |

---

## Notes

- Sessions are stored **in memory** — restart the bot and sessions reset.  Use Railway or a VPS for persistent uptime.
- If all AI models fail: *"Sorry, all AI models are currently unavailable."*
- Responses exceeding Telegram's 4 096-character limit are automatically split into multiple messages.
- Build-session `/followup` calls are **serialised per chat** — if you fire two `/followup` commands rapidly, the second waits for the first to finish.
