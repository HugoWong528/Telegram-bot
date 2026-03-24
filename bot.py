"""Unified AI Telegram Bot.

Combines general AI chat (streaming replies, conversation history, vision
models) and the AI Company bot (multi-role company discussions, /build,
/autorun, code review) into a single process that requires only one
``TELEGRAM_TOKEN``.

Commands
--------
General chat
    /ask      — ask the AI a question (streaming live updates)
    /cancel   — cancel your current in-progress request
    /models   — list available AI models
    /settings — view / set your preferred AI model

AI company / build
    /company       — multi-role company discussion
    /build         — developer team discussion + code generation + GitHub commit
    /autorun       — fully autonomous build (AI picks the task)
    /company_roles — list available roles

Weather
    /weather   — current Hong Kong weather + AI clothing suggestions

Universal
    /followup  — context-aware continuation:
                 • cancels an active stream and redirects (if one is running)
                 • build-session follow-up (if a /build or /autorun session exists)
                   supports unlimited chained follow-ups
                 • general chat follow-up (otherwise)
    /about     — show this help guide

Environment variables
---------------------
Required
    TELEGRAM_TOKEN         Telegram bot token from BotFather
    POLLINATIONS_TOKEN     Pollinations AI API key

Optional (needed for /build GitHub commit)
    GITHUB_TOKEN           GitHub PAT or Actions token with repo write access
    GITHUB_REPOSITORY      Repo in "owner/repo" format

Optional (Hong Kong weather auto-reminders)
    WEATHER_CHAT_ID        Telegram chat ID to post auto weather reminders
    WEATHER_REMINDER_HOURS Comma-separated HKT hours to send reminders (default: 8)
                           Example: "8,20" sends at 08:00 and 20:00 HKT
"""

import asyncio
import base64
import datetime
import json
import logging
import os
import posixpath
import re
import xml.etree.ElementTree as ET
from typing import AsyncGenerator, Callable, Optional

import aiohttp
from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from zoneinfo import ZoneInfo

_HKT = ZoneInfo("Asia/Hong_Kong")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN: str = os.environ.get("TELEGRAM_TOKEN", "")
POLLINATIONS_TOKEN: str = os.environ.get("POLLINATIONS_TOKEN", "")

# GitHub integration (optional — only needed for /build file commits)
GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY: str = os.environ.get("GITHUB_REPOSITORY", "")
GITHUB_API_BASE = "https://api.github.com"
PROJECT_FOLDER = "project"

# Hong Kong weather auto-reminders (optional)
# WEATHER_CHAT_ID  — Telegram chat ID to post auto reminders
# WEATHER_REMINDER_HOURS — comma-separated HKT hours, e.g. "8,20"
WEATHER_CHAT_ID: int = int(os.environ.get("WEATHER_CHAT_ID", "0") or "0")
_raw_hours = os.environ.get("WEATHER_REMINDER_HOURS", "8")
WEATHER_REMINDER_HOURS: list[int] = [
    int(h.strip()) for h in _raw_hours.split(",") if h.strip().isdigit()
]
HKO_RSS_URL = "https://rss.weather.gov.hk/rss/CurrentWeather_uc.xml"

AI_API_URL = "https://gen.pollinations.ai/v1/chat/completions"

# Model fallback chain — tried in order; next model used on any error.
MODEL_CHAIN = [
    "openai-fast",
    "gemini-search",
    "openai",
    "glm",
    "claude-fast",
    "qwen-character",
    "deepseek",
    "qwen-safety",
]

TELEGRAM_MAX_LENGTH = 4096
STREAM_EDIT_INTERVAL = 2.0   # seconds between live edit updates
STREAM_DISPLAY_LIMIT = 4000  # chars shown in a streaming placeholder
MAX_HISTORY = 20             # max conversation messages per chat

# Weather parsing constants
_HKO_TEMP_RE = re.compile(r"氣溫\s*[：:]\s*(\d+(?:\.\d+)?)")
_HKO_HUMID_RE = re.compile(r"相對濕度\s*[：:]\s*(\d+)")
_HKO_SUMMARY_RE = re.compile(r"天氣\s*[：:]\s*([^\n。.]+)")

# Relative humidity at or above this level triggers an umbrella suggestion.
HIGH_HUMIDITY_THRESHOLD = 85

# ---------------------------------------------------------------------------
# Model metadata (general chat)
# ---------------------------------------------------------------------------

VISION_MODELS: set[str] = {
    "openai",
    "openai-fast",
    "gemini",
    "gemini-fast",
    "gemini-large",
    "gemini-search",
    "claude-fast",
}

ALL_MODELS: set[str] = set(MODEL_CHAIN)

MODEL_INFO: dict[str, tuple[str, bool]] = {
    "openai-fast": ("Fast OpenAI model — default first choice", True),
    "openai": ("Full OpenAI model", True),
    "gemini-search": ("Gemini with Google Search grounding", True),
    "gemini": ("Standard Gemini model", True),
    "gemini-fast": ("Faster Gemini variant", True),
    "gemini-large": ("Larger Gemini variant", True),
    "claude-fast": ("Fast Claude model", True),
    "glm": ("GLM model", False),
    "qwen-character": ("Qwen character model", False),
    "deepseek": ("DeepSeek model", False),
    "qwen-safety": ("Qwen safety-focused model", False),
}

# ---------------------------------------------------------------------------
# AI Company role configuration
# ---------------------------------------------------------------------------

DEFAULT_ROLES = [
    "CEO", "CTO", "Product Manager", "Designer", "Engineer", "Marketing Manager",
]
DEFAULT_BUILD_ROLES = [
    "CTO", "Backend Developer", "Frontend Developer", "QA Engineer", "DevOps Engineer",
]

ROLE_PROMPTS: dict[str, str] = {
    "CEO": (
        "You are the CEO of a technology company. "
        "Focus on business strategy, return on investment, market opportunity, and high-level vision. "
        "Be concise and decisive."
    ),
    "CTO": (
        "You are the CTO of a technology company. "
        "Focus on technical architecture, feasibility, scalability, security, and technology stack choices. "
        "Be precise and practical."
    ),
    "Product Manager": (
        "You are the Product Manager. "
        "Focus on user needs, product requirements, prioritization, success metrics, and the product roadmap. "
        "Be user-centric and data-driven."
    ),
    "Designer": (
        "You are the Lead UX/UI Designer. "
        "Focus on user experience, interface design, accessibility, visual identity, and usability. "
        "Be creative and empathetic."
    ),
    "Engineer": (
        "You are the Lead Software Engineer. "
        "Focus on implementation details, technical challenges, development timelines, testing, and code quality. "
        "Be realistic and thorough."
    ),
    "Marketing Manager": (
        "You are the Marketing Manager. "
        "Focus on target audience, brand positioning, growth strategies, content, and messaging. "
        "Be persuasive and market-aware."
    ),
    "Data Scientist": (
        "You are the Data Scientist. "
        "Focus on data requirements, machine learning models, analytics, insights, and data-driven decisions. "
        "Be analytical and evidence-based."
    ),
    "Legal Counsel": (
        "You are the Legal Counsel. "
        "Focus on legal risks, regulatory compliance, intellectual property, privacy laws, and contracts. "
        "Be cautious and thorough."
    ),
    "Finance Manager": (
        "You are the Finance Manager. "
        "Focus on budget planning, cost estimation, revenue projections, financial risks, and ROI analysis. "
        "Be precise and conservative."
    ),
    "HR Manager": (
        "You are the HR Manager. "
        "Focus on team structure, talent requirements, company culture, onboarding, and people management. "
        "Be people-focused and empathetic."
    ),
    "Frontend Developer": (
        "You are the Frontend Developer. "
        "Focus on UI implementation with React/Vue/HTML/CSS/JavaScript, component design, "
        "responsiveness, and browser compatibility. "
        "Propose concrete frontend architecture and the key components to build."
    ),
    "Backend Developer": (
        "You are the Backend Developer. "
        "Focus on server-side logic, REST/GraphQL API design, database schemas, authentication, "
        "and backend performance. "
        "Propose concrete API endpoints, data models, and backend architecture."
    ),
    "Full Stack Developer": (
        "You are the Full Stack Developer. "
        "Focus on end-to-end implementation, bridging frontend and backend, data flow, "
        "and integration points. "
        "Provide a holistic view of the implementation."
    ),
    "QA Engineer": (
        "You are the QA Engineer. "
        "Focus on testing strategies, unit tests, integration tests, edge cases, "
        "bug prevention, and quality standards. "
        "Outline the key test scenarios and quality gates for the project."
    ),
    "DevOps Engineer": (
        "You are the DevOps Engineer. "
        "Focus on CI/CD pipelines, Docker/containerization, deployment strategies, "
        "monitoring, and infrastructure as code. "
        "Propose the deployment setup and toolchain."
    ),
}

# ---------------------------------------------------------------------------
# Bot application (set up after handlers are defined)
# ---------------------------------------------------------------------------

# Built at the bottom of this file via _build_application()
_app: Optional[Application] = None

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

# Per-chat build sessions for /followup continuations.
# Structure: { chat_id: { task, discussion, final_outcome, code_files, ... } }
build_sessions: dict[int, dict] = {}

# Per-chat conversation history for general chat.
# Structure: { chat_id: [ {"role": ..., "content": ...}, ... ] }
conversation_history: dict[int, list[dict]] = {}

# Per-user preferred model (set via /settings).
user_preferred_models: dict[int, str] = {}

# Per-user active streaming tasks (used by /cancel and /followup interrupt mode).
active_requests: dict[int, asyncio.Task] = {}

# Per-chat asyncio locks for build-session follow-ups.
# Prevents two concurrent /followup invocations from racing on the same session.
followup_locks: dict[int, asyncio.Lock] = {}

# Pending interactive callbacks: maps a unique key → asyncio.Future
# Used to pass user replies (text or button presses) back to running handlers.
_interactive_futures: dict[str, "asyncio.Future[Optional[str]]"] = {}

# Tracks (date_ordinal, hour) tuples for which a weather reminder was already sent.
_weather_sent_hours: set[tuple[int, int]] = set()

# ---------------------------------------------------------------------------
# Shared text utilities
# ---------------------------------------------------------------------------


def _open_fence(text: str) -> str | None:
    """Return the opening fence token if *text* ends with an unclosed Markdown
    code fence, otherwise ``None``."""
    open_token: str | None = None
    pos = 0
    while True:
        idx = text.find("```", pos)
        if idx == -1:
            break
        if open_token is None:
            rest = text[idx + 3:]
            nl = rest.find("\n")
            lang = rest[:nl].strip() if nl != -1 else rest.strip()
            open_token = "```" + lang
        else:
            open_token = None
        pos = idx + 3
    return open_token


def split_message(text: str, limit: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """Split *text* into chunks ≤ *limit* characters.

    Prefers splitting on newlines, then spaces.  Closes and re-opens Markdown
    code fences across splits so formatting stays intact.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while len(text) > limit:
        split_pos = text.rfind("\n", 0, limit)
        if split_pos == -1:
            split_pos = text.rfind(" ", 0, limit)
        if split_pos == -1:
            split_pos = limit

        chunk = text[:split_pos]
        fence = _open_fence(chunk)
        if fence is not None:
            chunk += "\n```"
            text = fence + "\n" + text[split_pos:].lstrip("\n")
        else:
            text = text[split_pos:].lstrip("\n")
        chunks.append(chunk)

    if text:
        chunks.append(text)
    return chunks


def slugify(text: str) -> str:
    """Convert *text* to a filesystem/URL-safe slug (max 50 chars)."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = text.strip("-")
    return text[:50] or "project"


def parse_code_files(text: str) -> list[tuple[str, str]]:
    """Extract ``(filename, content)`` pairs from AI output using the
    ``### File: <name>`` / ``` format."""
    pattern = r"### File:\s*([^\n]+)\n```[^\n]*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    return [(fn.strip(), code.rstrip()) for fn, code in matches]


def _prior_context_note(prior_count: int) -> str:
    if prior_count == 0:
        return "*(first to speak)*"
    return f"*(read {prior_count} prior response{'s' if prior_count != 1 else ''})*"


# ---------------------------------------------------------------------------
# General chat AI helpers
# ---------------------------------------------------------------------------


def build_model_chain(preferred_model: str | None) -> list[str]:
    if preferred_model is None:
        return MODEL_CHAIN
    rest = [m for m in MODEL_CHAIN if m != preferred_model]
    return [preferred_model] + rest


def parse_model_prefix(content: str) -> tuple[str | None, str]:
    """Detect an optional ``@<model-name>``, ``@ai``, or ``@about`` prefix."""
    stripped = content.strip()
    candidate = stripped[1:] if stripped.startswith("@") else stripped
    parts = candidate.split(None, 1)
    if not parts:
        return None, content
    first_word = parts[0].lower()
    remainder = parts[1].strip() if len(parts) > 1 else ""
    if first_word == "about":
        return "about", remainder
    if first_word == "ai":
        return None, remainder
    if first_word in ALL_MODELS:
        return first_word, remainder
    return None, content


def _fallback_footer(
    model_used: str | None, preferred_model: str | None, is_fallback: bool
) -> str:
    if not model_used:
        return ""
    if is_fallback:
        return f"\n\n*— Response generated by **{model_used}** (fallback)*"
    if preferred_model and model_used != preferred_model:
        return f"\n\n*— Response generated by **{model_used}** (fallback from {preferred_model})*"
    return ""


def get_image_urls_from_tg(message: Message) -> list[str]:
    """Return image file IDs from a Telegram message (photos or image documents)."""
    urls: list[str] = []
    if message.photo:
        # message.photo is a list of PhotoSize (smallest → largest); take the largest
        largest = message.photo[-1]
        urls.append(f"tg://{largest.file_id}")
    if message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        urls.append(f"tg://{message.document.file_id}")
    return urls


def _update_history(chat_id: int, user_text: str, assistant_reply: str) -> None:
    history = conversation_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": assistant_reply})
    if len(history) > MAX_HISTORY:
        conversation_history[chat_id] = history[-MAX_HISTORY:]


async def _single_model_call(
    session: aiohttp.ClientSession,
    model: str,
    user_message: str,
    image_urls: list[str] | None = None,
    history: list[dict] | None = None,
) -> str:
    """Make a single non-streaming call to one specific model."""
    headers = {
        "Authorization": f"Bearer {POLLINATIONS_TOKEN}",
        "Content-Type": "application/json",
    }
    if image_urls and model in VISION_MODELS:
        message_content: list[dict] | str = [{"type": "text", "text": user_message}]
        for url in image_urls:
            message_content.append({"type": "image_url", "image_url": {"url": url}})
    else:
        message_content = user_message

    messages: list[dict] = list(history) if history else []
    messages.append({"role": "user", "content": message_content})
    payload = {"model": model, "messages": messages}
    async with session.post(
        AI_API_URL, json=payload, headers=headers,
        timeout=aiohttp.ClientTimeout(total=30),
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data["choices"][0]["message"]["content"]


async def _iter_stream_chunks(
    session: aiohttp.ClientSession,
    model: str,
    user_message: str,
    image_urls: list[str] | None = None,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """Yield text tokens from the AI using SSE streaming."""
    headers = {
        "Authorization": f"Bearer {POLLINATIONS_TOKEN}",
        "Content-Type": "application/json",
    }
    if image_urls and model in VISION_MODELS:
        message_content: list[dict] | str = [{"type": "text", "text": user_message}]
        for url in image_urls:
            message_content.append({"type": "image_url", "image_url": {"url": url}})
    else:
        message_content = user_message

    messages_list: list[dict] = list(history) if history else []
    messages_list.append({"role": "user", "content": message_content})
    payload = {"model": model, "messages": messages_list, "stream": True}
    async with session.post(
        AI_API_URL, json=payload, headers=headers,
        timeout=aiohttp.ClientTimeout(total=120),
    ) as resp:
        resp.raise_for_status()
        pending = ""
        async for raw in resp.content.iter_any():
            pending += raw.decode("utf-8", errors="replace")
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    return
                try:
                    obj = json.loads(data_str)
                    delta = obj["choices"][0]["delta"].get("content") or ""
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass


async def get_ai_reply_streaming(
    user_message: str,
    preferred_model: str | None = None,
    image_urls: list[str] | None = None,
    history: list[dict] | None = None,
    progress_cb: Callable | None = None,
) -> tuple[str, str | None, bool]:
    """Stream the AI reply.  Returns ``(reply_text, model_used, is_fallback)``."""
    chain = build_model_chain(preferred_model)
    if image_urls:
        chain = [m for m in chain if m in VISION_MODELS]
        if not chain:
            return (
                "⚠️ No vision-capable models are available right now.",
                None, False,
            )

    first_model = chain[0]
    last_progress = 0.0

    async with aiohttp.ClientSession() as session:
        for model in chain:
            accumulated = ""
            try:
                async for chunk in _iter_stream_chunks(session, model, user_message, image_urls, history):
                    accumulated += chunk
                    if progress_cb is not None:
                        now = asyncio.get_running_loop().time()
                        if now - last_progress >= STREAM_EDIT_INTERVAL:
                            try:
                                await progress_cb(accumulated)
                                last_progress = now
                            except Exception:
                                pass

                if accumulated:
                    return accumulated, model, (model != first_model)

                # SSE returned nothing — fall back to non-streaming
                accumulated = await _single_model_call(session, model, user_message, image_urls, history)
                return accumulated, model, (model != first_model)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Model %s failed (streaming): %s. Trying next…", model, exc)

    return "Sorry, all AI models are currently unavailable. Please try again later.", None, False


# ---------------------------------------------------------------------------
# AI Company helpers
# ---------------------------------------------------------------------------


async def call_ai(
    session: aiohttp.ClientSession,
    messages: list[dict],
) -> str:
    """Call the AI API with a messages list, trying each model in MODEL_CHAIN."""
    headers = {
        "Authorization": f"Bearer {POLLINATIONS_TOKEN}",
        "Content-Type": "application/json",
    }
    for model in MODEL_CHAIN:
        payload = {"model": model, "messages": messages}
        try:
            async with session.post(
                AI_API_URL, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                logger.info("Got reply from model %s", model)
                return data["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("Model %s failed: %s. Trying next…", model, exc)
    raise RuntimeError("All AI models failed.")


async def generate_project_name(session: aiohttp.ClientSession, task: str) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "You generate concise, filesystem-safe project names. "
                "Reply with ONLY the project name: lowercase letters, digits, and hyphens, "
                "2–4 words maximum, no spaces, no punctuation, no extra text. "
                "Example: 'todo-rest-api'."
            ),
        },
        {"role": "user", "content": f"Generate a project name for: {task}"},
    ]
    try:
        raw = await call_ai(session, messages)
        first_token = raw.strip().split()[0] if raw.strip() else ""
        slug = slugify(first_token)
        if slug and slug != "project":
            return slug
    except Exception as exc:
        logger.warning("Project name generation failed: %s", exc)
    return slugify(task)


_AUTO_STACKS: dict[str, str] = {
    "python": "Python (Flask, FastAPI, or a standalone CLI/script)",
    "php": "PHP + HTML (a dynamic web page or small PHP web API)",
    "actions": "GitHub Actions (a YAML workflow for CI/CD or automation)",
}

_STACK_EMOJI: dict[str, str] = {"python": "🐍", "php": "🐘", "actions": "⚙️"}


async def generate_auto_task(
    session: aiohttp.ClientSession,
    stack: str | None = None,
) -> tuple[str, str]:
    if stack and stack in _AUTO_STACKS:
        stack_hint = f"The project MUST use this tech stack: {_AUTO_STACKS[stack]}."
    else:
        options = " | ".join(f"{k}: {v}" for k, v in _AUTO_STACKS.items())
        stack_hint = f"Choose ONE of these stacks: {options}."

    messages = [
        {
            "role": "system",
            "content": (
                "You are a creative software architect who invents interesting, "
                "self-contained programming projects that a small team can build in one sprint."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Invent a concrete, buildable programming project. {stack_hint}\n"
                "Reply in EXACTLY this format — no extra text:\n"
                "TASK: <one clear sentence describing what to build>\n"
                "STACK: <python | php | actions>"
            ),
        },
    ]
    try:
        raw = await call_ai(session, messages)
        task_match = re.search(r"TASK:\s*(.+)", raw)
        stack_match = re.search(r"STACK:\s*(\w+)", raw)
        task = task_match.group(1).strip() if task_match else raw.strip()[:200]
        chosen = stack_match.group(1).strip().lower() if stack_match else (stack or "python")
        if chosen not in _AUTO_STACKS:
            chosen = stack or "python"
        return task, chosen
    except Exception as exc:
        logger.warning("Auto-task generation failed: %s", exc)
    fallback_stack = stack if stack in _AUTO_STACKS else "python"
    return "Build a simple Python CLI tool that converts CSV files to JSON", fallback_stack


async def run_company_discussion(
    task: str,
    roles: list[str],
    role_done_cb: Optional[Callable] = None,
) -> tuple[list[tuple[str, str]], str]:
    """Run a multi-role AI company discussion.  Returns ``(discussion, final_outcome)``."""
    discussion: list[tuple[str, str]] = []
    injected_inputs: list[str] = []

    async with aiohttp.ClientSession() as session:
        for role in roles:
            system_prompt = ROLE_PROMPTS.get(
                role,
                f"You are the {role} of a technology company. Share your professional perspective.",
            )
            user_content = f"**Task:** {task}\n"
            if injected_inputs:
                user_content += "\n**Stakeholder Input (from the human in the room):**\n"
                for idx, inp in enumerate(injected_inputs, 1):
                    user_content += f"> [{idx}] {inp}\n"
            if discussion:
                user_content += "\n**Discussion so far:**\n"
                for prev_role, prev_reply in discussion:
                    truncated = prev_reply[:500] + "…" if len(prev_reply) > 500 else prev_reply
                    user_content += f"\n**{prev_role}:** {truncated}\n"
                user_content += (
                    f"\nNow, as the **{role}**, respond to this task building on the "
                    "discussion above. Acknowledge specific points raised by other roles. "
                    "Be concise (2–4 sentences)."
                )
            else:
                user_content += (
                    f"\nAs the **{role}**, what is your initial take on this task? "
                    "Be concise (2–4 sentences)."
                )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
            try:
                reply = await call_ai(session, messages)
                discussion.append((role, reply))
            except Exception as exc:
                logger.error("Role %s failed: %s", role, exc)
                reply = "*[No response available]*"
                discussion.append((role, reply))

            if role_done_cb is not None:
                user_input = await role_done_cb(role, reply)
                if user_input:
                    injected_inputs.append(user_input)

        # Facilitator synthesis
        synthesis_context = f"**Task:** {task}\n\n**Company Discussion:**\n"
        for role, reply in discussion:
            synthesis_context += f"\n**{role}:** {reply}\n"
        if injected_inputs:
            synthesis_context += "\n**Stakeholder Interjections:**\n"
            for idx, inp in enumerate(injected_inputs, 1):
                synthesis_context += f"> [{idx}] {inp}\n"
        synthesis_context += (
            "\nAs the meeting **Facilitator**, synthesise all perspectives into a "
            "clear, structured **Final Outcome** with:\n"
            "1. Key decisions made\n"
            "2. Recommended next steps (prioritised)\n"
            "3. Important risks or considerations\n"
            "Be actionable and concise."
        )
        facilitator_messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert meeting facilitator who synthesises company "
                    "discussions into clear, actionable outcomes."
                ),
            },
            {"role": "user", "content": synthesis_context},
        ]
        try:
            final_outcome = await call_ai(session, facilitator_messages)
        except Exception as exc:
            logger.error("Final synthesis failed: %s", exc)
            final_outcome = "*Unable to generate the final outcome. Please try again.*"

    return discussion, final_outcome


async def generate_code_files(
    task: str,
    discussion: list[tuple[str, str]],
    final_outcome: str,
    feedback: str | None = None,
) -> tuple[list[tuple[str, str]], str]:
    """Generate code files from the team discussion.

    When *feedback* is provided (from a code review) it is injected into the
    prompt so the AI fixes those issues in this new attempt.
    """
    discussion_context = f"**Task:** {task}\n\n**Developer Team Discussion:**\n"
    for role, reply in discussion:
        discussion_context += f"\n**{role}:** {reply}\n"
    discussion_context += f"\n**Final Plan:**\n{final_outcome}"

    feedback_section = (
        "\n\n**⚠️ Code Reviewer Feedback — ALL issues below MUST be fixed in this generation:**\n"
        f"{feedback}\n\n"
        "Fix every issue listed above. Do not leave any TODO, placeholder, or "
        "unimplemented section in the output."
        if feedback else ""
    )

    _model_list = "\n".join(f"  {i}. {m}" for i, m in enumerate(MODEL_CHAIN, 1))
    code_gen_prompt = (
        f"{discussion_context}{feedback_section}\n\n"
        "Based on the plan above, generate a complete, working codebase.\n\n"
        "For EACH file, use EXACTLY this format:\n\n"
        "### File: <filename with extension and any sub-path>\n"
        "```<language>\n"
        "<complete file content>\n"
        "```\n\n"
        "Include ALL necessary files: source code, configuration files "
        "(e.g. package.json, requirements.txt), a Dockerfile if appropriate, "
        "and a README.md. Make all code complete and functional — not just placeholders."
    )
    code_gen_messages = [
        {
            "role": "system",
            "content": (
                "You are an expert senior software engineer who writes complete, "
                "production-quality code. Generate every file needed for the project. "
                "Use exactly the `### File:` / ``` format so the output can be parsed "
                "and committed to a repository automatically.\n\n"
                "**AI integration — IMPORTANT:**\n"
                "If the project uses AI/LLM features, use the Pollinations AI API:\n"
                "  POST https://gen.pollinations.ai/v1/chat/completions\n"
                f"  Authorization: Bearer {POLLINATIONS_TOKEN}\n\n"
                f"Try models in order: {_model_list}\n"
                "Implement the fallback loop so it retries on HTTP errors."
            ),
        },
        {"role": "user", "content": code_gen_prompt},
    ]
    async with aiohttp.ClientSession() as session:
        try:
            raw_output = await call_ai(session, code_gen_messages)
        except Exception as exc:
            logger.error("Code generation failed: %s", exc)
            return [], ""

    code_files = parse_code_files(raw_output)
    logger.info("Generated %d code file(s)", len(code_files))
    return code_files, raw_output


async def review_code_files(
    task: str,
    code_files: list[tuple[str, str]],
    final_outcome: str,
) -> str:
    """Ask a Code Reviewer AI to check generated code for critical issues.

    Returns a non-empty string with issue descriptions when critical problems
    are found, or an empty string when the code passes review (LGTM).
    """
    if not code_files:
        return ""

    file_content = ""
    for filename, content in code_files[:8]:
        preview = content[:800] + "\n…(truncated)" if len(content) > 800 else content
        file_content += f"\n### File: {filename}\n```\n{preview}\n```\n"

    review_prompt = (
        f"**Task:** {task}\n\n"
        f"**Final Plan (summary):**\n{final_outcome[:400]}\n\n"
        f"**Generated Code Files:**\n{file_content}\n\n"
        "Review the code above. Identify ONLY critical issues that would prevent "
        "the code from running or fulfilling the task:\n"
        "• Syntax errors or obvious runtime bugs\n"
        "• Missing required imports or undefined names (ImportError/NameError)\n"
        "• Placeholder code left unimplemented (TODO, pass, raise NotImplementedError)\n"
        "• Broken inter-file dependencies\n\n"
        "If the code is complete and runnable, respond with exactly: LGTM\n"
        "Otherwise list up to 5 specific critical issues. "
        "Do NOT suggest style improvements or optional enhancements."
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a strict senior code reviewer. "
                "Find only critical bugs that would prevent the code from running. "
                "If there are no critical issues, respond with exactly: LGTM"
            ),
        },
        {"role": "user", "content": review_prompt},
    ]
    async with aiohttp.ClientSession() as session:
        try:
            review_output = await call_ai(session, messages)
        except Exception as exc:
            logger.warning("Code review call failed: %s — skipping review", exc)
            return ""

    review_text = review_output.strip()
    lower = review_text.lower()
    if (
        review_text.upper().startswith("LGTM")
        or lower.startswith("no critical")
        or lower.startswith("looks good")
        or lower.startswith("the code looks")
        or lower.startswith("code looks good")
    ):
        logger.info("Code review passed (LGTM)")
        return ""
    logger.info("Code review found issues: %.200s", review_text)
    return review_text


async def generate_verified_code_files(
    task: str,
    discussion: list[tuple[str, str]],
    final_outcome: str,
    send_fn,
    max_format_retries: int = 3,
    max_review_rounds: int = 2,
) -> tuple[list[tuple[str, str]], str]:
    """Generate code with automatic format-retry and code-review loop.

    1. Try to generate code up to *max_format_retries* times until ``### File:``
       blocks are found.
    2. Ask a Code Reviewer AI to check.  If critical issues are found,
       regenerate with reviewer feedback injected (up to *max_review_rounds*).
    """
    review_feedback: str | None = None

    for review_round in range(max_review_rounds + 1):
        code_files: list[tuple[str, str]] = []
        raw_output: str = ""

        for fmt_try in range(1, max_format_retries + 1):
            if review_round == 0 and fmt_try == 1:
                await send_fn("💻 *Generating code files…*")
            elif fmt_try > 1:
                await send_fn(
                    f"🔄 *No `### File:` blocks found — retrying generation "
                    f"(attempt {fmt_try}/{max_format_retries})…*"
                )

            code_files, raw_output = await generate_code_files(
                task, discussion, final_outcome, feedback=review_feedback
            )
            if code_files:
                break

        if not code_files:
            return [], raw_output

        is_last_round = review_round >= max_review_rounds
        await send_fn(f"🔍 *Code Reviewer examining {len(code_files)} file(s)…*")
        issues = await review_code_files(task, code_files, final_outcome)

        if not issues:
            await send_fn("✅ *Code review passed — no critical issues found.*")
            return code_files, raw_output

        if is_last_round:
            await send_fn(
                "⚠️ *Code Reviewer found issues but max retries reached — "
                "proceeding with best available code:*\n"
                f"```\n{issues[:500]}\n```"
            )
            return code_files, raw_output

        await send_fn(
            f"⚠️ *Code Reviewer found issues (round {review_round + 1}/{max_review_rounds}) "
            "— regenerating with fixes applied:*\n"
            f"```\n{issues[:400]}\n```"
        )
        review_feedback = issues

    return code_files, raw_output


# ---------------------------------------------------------------------------
# Hong Kong weather helpers
# ---------------------------------------------------------------------------


async def fetch_hk_weather() -> dict | None:
    """Fetch and parse the current HK weather report from the HKO RSS feed.

    Returns a dict with keys: title, description, temperature, humidity, summary.
    Returns None on any network or parsing error.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                HKO_RSS_URL,
                timeout=aiohttp.ClientTimeout(total=15),
                headers={"User-Agent": "Mozilla/5.0"},
            ) as resp:
                resp.raise_for_status()
                xml_bytes = await resp.read()

        root = ET.fromstring(xml_bytes)

        # Standard RSS 2.0: <rss><channel><item>…</item></channel></rss>
        item = root.find(".//item")
        if item is None:
            logger.warning("HKO RSS: no <item> element found")
            return None

        title = (item.findtext("title") or "").strip()
        description_raw = (item.findtext("description") or "").strip()

        # Strip HTML tags and decode common HTML entities
        description = re.sub(r"<[^>]+>", " ", description_raw)
        description = re.sub(r"&lt;", "<", description)
        description = re.sub(r"&gt;", ">", description)
        description = re.sub(r"&amp;", "&", description)
        description = re.sub(r"&nbsp;", " ", description)
        description = re.sub(r"&#\d+;", " ", description)
        description = re.sub(r"&[a-z]+;", " ", description)
        description = re.sub(r"\s+", " ", description).strip()

        # Extract temperature, humidity, and weather summary using module-level patterns
        temp_match = _HKO_TEMP_RE.search(description)
        temperature = temp_match.group(1) if temp_match else None

        humid_match = _HKO_HUMID_RE.search(description)
        humidity = humid_match.group(1) if humid_match else None

        summary_match = _HKO_SUMMARY_RE.search(description)
        summary = summary_match.group(1).strip() if summary_match else ""

        return {
            "title": title,
            "description": description,
            "temperature": temperature,
            "humidity": humidity,
            "summary": summary,
        }
    except Exception as exc:
        logger.warning("HK weather fetch failed: %s", exc)
        return None


def _clothing_fallback(temperature: str | None, humidity: str | None) -> str:
    """Rule-based clothing suggestion when AI is unavailable."""
    try:
        temp = float(temperature) if temperature else 22.0
    except ValueError:
        temp = 22.0
    try:
        humid = int(humidity) if humidity else 70
    except ValueError:
        humid = 70

    rain_note = "☔ 考慮攜帶雨傘。/ Consider bringing an umbrella." if humid >= HIGH_HUMIDITY_THRESHOLD else ""

    if temp < 12:
        base = (
            "🧥 今日天氣寒冷，建議穿著厚外套、保暖內衣及圍巾。\n"
            "It's cold today. Wear a heavy coat, warm layers, and a scarf."
        )
    elif temp < 17:
        base = (
            "🧣 今日天氣涼爽，建議穿著輕便外套或毛衣。\n"
            "It's cool today. A light jacket or sweater is recommended."
        )
    elif temp < 23:
        base = (
            "👕 今日天氣溫和，長袖衫已足夠，可備輕薄外套。\n"
            "Mild weather today. Long sleeves are comfortable; bring a light layer."
        )
    elif temp < 28:
        base = (
            "🌤️ 今日天氣舒適，穿著輕薄衣物即可。\n"
            "Pleasant weather. Light clothing is perfect."
        )
    else:
        base = (
            "☀️ 今日天氣炎熱，建議穿著輕薄透氣的夏季衣物並注意防曬。\n"
            "It's hot today. Wear light, breathable summer clothes and apply sunscreen."
        )

    return f"{base}\n{rain_note}".strip()


async def get_weather_clothing_suggestion(weather: dict) -> str:
    """Ask the AI for clothing suggestions based on current HK weather.

    Falls back to rule-based suggestions if the AI call fails.
    """
    desc = weather.get("description", "")[:500]
    temp = weather.get("temperature") or "unknown"
    humid = weather.get("humidity") or "unknown"

    prompt = (
        f"Current Hong Kong weather:\n"
        f"• Temperature: {temp}°C\n"
        f"• Relative Humidity: {humid}%\n"
        f"• Weather report excerpt: {desc}\n\n"
        "Based on the above, suggest what to wear today in Hong Kong. "
        "Include practical clothing items and any relevant accessories (umbrella, sunscreen, etc.). "
        "Reply in Traditional Chinese first, then English. Keep it to 3–5 sentences total."
    )

    async with aiohttp.ClientSession() as session:
        try:
            suggestion = await _single_model_call(session, "openai-fast", prompt)
            return suggestion.strip()
        except Exception as exc:
            logger.warning("AI clothing suggestion failed: %s — using fallback", exc)
            return _clothing_fallback(weather.get("temperature"), weather.get("humidity"))


def _build_weather_message(weather: dict, suggestion: str, *, header: str = "🌤️ *Hong Kong Current Weather*") -> str:
    """Format weather data and clothing suggestion into a Telegram message."""
    temp_str = f"{weather['temperature']}°C" if weather.get("temperature") else "N/A"
    humid_str = f"{weather['humidity']}%" if weather.get("humidity") else "N/A"

    lines = [
        header,
        f"📅 {weather['title']}",
        "",
        f"🌡️ 氣溫 / Temperature: *{temp_str}*",
        f"💧 相對濕度 / Humidity: *{humid_str}*",
    ]
    if weather.get("summary"):
        lines.append(f"🌈 天氣 / Condition: {weather['summary']}")
    lines += [
        "",
        "---",
        "👕 *今日穿著建議 / Clothing Suggestion:*",
        suggestion,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------


async def _get_file_sha(
    session: aiohttp.ClientSession, repo: str, path: str
) -> str | None:
    url = f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return (await resp.json()).get("sha")
    except Exception:
        pass
    return None


async def _commit_file(
    session: aiohttp.ClientSession,
    path: str,
    content: str,
    commit_message: str,
) -> str | None:
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPOSITORY}/contents/{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    sha = await _get_file_sha(session, GITHUB_REPOSITORY, path)
    payload: dict = {
        "message": commit_message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    try:
        async with session.put(url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            return (await resp.json())["content"]["html_url"]
    except Exception as exc:
        logger.error("GitHub commit failed for %s: %s", path, exc)
        return None


def _safe_project_path(folder: str, filename: str) -> str | None:
    normalized = posixpath.normpath(filename.replace("\\", "/"))
    if posixpath.isabs(normalized) or normalized.startswith(".."):
        logger.warning("Rejecting unsafe filename: %r", filename)
        return None
    if ".." in normalized.split("/"):
        logger.warning("Rejecting unsafe filename (contains '..'): %r", filename)
        return None
    return f"{folder}/{normalized}"


async def commit_project(
    project_slug: str,
    task: str,
    final_outcome: str,
    code_files: list[tuple[str, str]],
) -> tuple[list[str], str | None]:
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        logger.warning("GitHub commit skipped: token or repository not set.")
        return [], None

    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    folder = f"{PROJECT_FOLDER}/{project_slug}"
    commit_msg = f"Add project: {project_slug}"

    readme_lines = [
        f"# {project_slug}", "",
        f"**Task:** {task}", "",
        f"*Generated by AI Bot on {timestamp}*", "",
        "---", "", "## Final Outcome", "", final_outcome,
    ]
    if code_files:
        readme_lines += ["", "---", "", "## Generated Files", ""]
        for filename, _ in code_files:
            readme_lines.append(f"- `{filename}`")
    readme_content = "\n".join(readme_lines) + "\n"

    all_files: list[tuple[str, str]] = [("README.md", readme_content)] + list(code_files)
    committed_urls: list[str] = []
    async with aiohttp.ClientSession() as session:
        for filename, content in all_files:
            path = _safe_project_path(folder, filename)
            if path is None:
                continue
            file_url = await _commit_file(session, path, content, commit_msg)
            if file_url:
                committed_urls.append(file_url)
            else:
                logger.warning("Failed to commit: %s", path)

    folder_url = (
        f"https://github.com/{GITHUB_REPOSITORY}/tree/main/{folder}"
        if GITHUB_REPOSITORY else None
    )
    return committed_urls, folder_url


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------


async def _safe_edit_text(msg: Message, text: str) -> None:
    """Edit a Telegram message, ignoring 'message is not modified' errors."""
    try:
        await msg.edit_text(text)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            logger.debug("edit_text failed: %s", exc)
    except TelegramError as exc:
        logger.debug("edit_text failed: %s", exc)


async def _send_chunks(
    chat_id: int,
    text: str,
    bot: Bot,
    reply_to: int | None = None,
) -> None:
    """Send *text* split into chunks ≤ TELEGRAM_MAX_LENGTH."""
    chunks = split_message(text)
    for i, chunk in enumerate(chunks):
        if i == 0 and reply_to:
            await bot.send_message(chat_id=chat_id, text=chunk, reply_to_message_id=reply_to)
        else:
            await bot.send_message(chat_id=chat_id, text=chunk)


async def _stream_to_message(
    user_message: str,
    chat_id: int,
    bot: Bot,
    preferred_model: str | None,
    history: list[dict] | None,
    reply_to_id: int | None,
) -> tuple[str, str | None, bool]:
    """Stream an AI reply, editing a placeholder message live.

    Returns (reply_text, model_used, is_fallback).
    """
    # Send placeholder
    placeholder_msg = await bot.send_message(
        chat_id=chat_id,
        text="▌",
        reply_to_message_id=reply_to_id,
    )

    accumulated = ""
    last_edit = 0.0

    async def _progress(text: str) -> None:
        nonlocal last_edit
        now = asyncio.get_running_loop().time()
        if now - last_edit >= STREAM_EDIT_INTERVAL:
            display = text[-STREAM_DISPLAY_LIMIT:] + "▌" if len(text) > STREAM_DISPLAY_LIMIT else text + "▌"
            await _safe_edit_text(placeholder_msg, display)
            last_edit = now

    reply, model_used, is_fallback = await get_ai_reply_streaming(
        user_message, preferred_model, history=history, progress_cb=_progress
    )

    # Final update — split if needed
    display = reply + _fallback_footer(model_used, preferred_model, is_fallback)
    chunks = split_message(display)
    await _safe_edit_text(placeholder_msg, chunks[0])
    for chunk in chunks[1:]:
        await bot.send_message(chat_id=chat_id, text=chunk)

    return reply, model_used, is_fallback


# ---------------------------------------------------------------------------
# Interactive helper: wait for user to press a button or type an input
# ---------------------------------------------------------------------------


async def _wait_for_user_choice(
    chat_id: int,
    bot: Bot,
    next_role: str,
) -> Optional[str]:
    """Send Continue / Add Input buttons and wait for user selection.

    Returns the user's typed input string, or None for "continue".
    """
    key = f"interactive:{chat_id}"
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[Optional[str]] = loop.create_future()
    _interactive_futures[key] = fut

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶ Continue", callback_data=f"interactive_continue:{chat_id}"),
            InlineKeyboardButton("✏️ Add My Input", callback_data=f"interactive_input:{chat_id}"),
        ]
    ])
    await bot.send_message(
        chat_id=chat_id,
        text=f"*Next up: {next_role}.*  Would you like to add your perspective first?",
        reply_markup=keyboard,
    )

    try:
        result = await asyncio.wait_for(fut, timeout=90)
    except asyncio.TimeoutError:
        result = None
        logger.info("Interactive wait timed out for chat %s — auto-continuing", chat_id)
    finally:
        _interactive_futures.pop(key, None)

    return result


# ---------------------------------------------------------------------------
# Bot event handlers
# ---------------------------------------------------------------------------


async def _on_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text and photo messages — only responds in private chats or when mentioned."""
    msg = update.effective_message
    if msg is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return

    # In groups: only respond when the bot is mentioned
    if chat.type != "private":
        bot_username = (await context.bot.get_me()).username
        if msg.text and f"@{bot_username}" not in (msg.text or ""):
            return
        # Strip the mention
        content = (msg.text or "").replace(f"@{bot_username}", "").strip()
    else:
        content = (msg.text or msg.caption or "").strip()

    # Collect image file IDs if photos are attached
    image_file_ids = get_image_urls_from_tg(msg)
    if image_file_ids:
        if not content:
            content = "Describe this image."
    elif not content:
        await msg.reply_text(
            "Please send me a message to chat!\nUse /ask for a command interface, or /about for help."
        )
        return

    chat_id = chat.id
    history = conversation_history.get(chat_id, [])
    preferred = user_preferred_models.get(user.id)

    # Note: Telegram file IDs are not direct URLs; vision support requires
    # downloading the file first. For now we pass the content text only.
    # Image-aware responses will note the image was received.
    if image_file_ids and not content.startswith("Describe"):
        content = f"[Image attached] {content}"

    task = asyncio.create_task(
        _stream_to_message(content, chat_id, context.bot, preferred, history, msg.message_id)
    )
    active_requests[user.id] = task
    try:
        reply, model_used, _ = await task
    except asyncio.CancelledError:
        await context.bot.send_message(chat_id=chat_id, text="⛔ Your in-progress request has been cancelled.")
        return
    finally:
        active_requests.pop(user.id, None)

    if model_used:
        _update_history(chat_id, content, reply)


# ---------------------------------------------------------------------------
# General chat commands
# ---------------------------------------------------------------------------


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ask <question> [model:<model>]"""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if msg is None or user is None or chat is None:
        return

    # Parse: /ask <question>  or  /ask model:<model> <question>
    args = context.args or []
    text = " ".join(args).strip()
    if not text:
        await msg.reply_text("Usage: /ask <your question>\nOptionally prefix with model:<model_name>")
        return

    preferred_model: str | None = None
    if text.lower().startswith("model:"):
        parts = text.split(None, 1)
        model_part = parts[0][6:]
        if model_part in ALL_MODELS:
            preferred_model = model_part
            text = parts[1].strip() if len(parts) > 1 else ""
        if not text:
            await msg.reply_text("Please provide a question after model:<name>")
            return

    chat_id = chat.id
    history = conversation_history.get(chat_id, [])
    if preferred_model is None:
        preferred_model = user_preferred_models.get(user.id)

    task = asyncio.create_task(
        _stream_to_message(text, chat_id, context.bot, preferred_model, history, msg.message_id)
    )
    active_requests[user.id] = task
    try:
        reply, model_used, _ = await task
    except asyncio.CancelledError:
        await context.bot.send_message(chat_id=chat_id, text="⛔ Your in-progress request has been cancelled.")
        return
    finally:
        active_requests.pop(user.id, None)

    if model_used:
        _update_history(chat_id, text, reply)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cancel — cancel an in-progress AI request."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    task = active_requests.pop(user.id, None)
    if task and not task.done():
        task.cancel()
        await msg.reply_text("⛔ Your in-progress request has been cancelled.")
    else:
        await msg.reply_text("You don't have an active request to cancel.")


async def models_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/models — list available AI models."""
    msg = update.effective_message
    if msg is None:
        return
    lines = ["📋 *Available AI Models*", ""]
    for model in sorted(MODEL_INFO):
        desc, vision = MODEL_INFO[model]
        vision_mark = "✅" if vision else "❌"
        lines.append(f"• `{model}` {vision_mark} — {desc}")
    lines += ["", "_Tip: Use /ask model:<name> <question> to pick a model._"]
    await msg.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/settings [model:<model>] — view or set preferred AI model."""
    msg = update.effective_message
    user = update.effective_user
    if msg is None or user is None:
        return
    args = context.args or []
    if not args:
        current = user_preferred_models.get(user.id)
        if current:
            desc, vision = MODEL_INFO.get(current, ("Unknown model", False))
            vtag = " [vision]" if vision else ""
            await msg.reply_text(
                f"Your preferred model is *{current}*{vtag} — {desc}.\n"
                "Use `/settings <model_name>` to change it.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await msg.reply_text(
                "No preferred model set — using automatic model selection.\n"
                "Use `/settings <model_name>` to set one."
            )
        return

    model = args[0].strip()
    if model not in ALL_MODELS:
        model_list = ", ".join(sorted(ALL_MODELS))
        await msg.reply_text(f"Unknown model `{model}`.\nAvailable: {model_list}", parse_mode=ParseMode.MARKDOWN)
        return

    user_preferred_models[user.id] = model
    desc, vision = MODEL_INFO.get(model, ("Unknown model", False))
    vtag = " [vision]" if vision else ""
    await msg.reply_text(
        f"✅ Preferred model set to *{model}*{vtag} — {desc}.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# AI Company / Build commands
# ---------------------------------------------------------------------------


async def company_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/company <task> [roles:CEO,CTO,...] [interactive:true]"""
    msg = update.effective_message
    chat = update.effective_chat
    if msg is None or chat is None:
        return

    args_text = " ".join(context.args or "").strip() if context.args else ""
    if not args_text:
        await msg.reply_text("Usage: /company <task description>\nOptional: roles:CEO,CTO,... interactive:true")
        return

    task, role_list, interactive = _parse_company_args(args_text, DEFAULT_ROLES)

    chat_id = chat.id
    roles_display = ", ".join(role_list)
    mode_note = " _(interactive)_" if interactive else ""

    header = (
        f"🏢 *AI Company Discussion*{mode_note}\n"
        f"📋 *Task:* {task}\n"
        f"👥 *Participants:* {roles_display}\n\n"
        "_Starting discussion…_"
    )
    await msg.reply_text(header, parse_mode=ParseMode.MARKDOWN)

    async def _send(text: str) -> None:
        await _send_chunks(chat_id, text, context.bot)

    role_done_cb: Optional[Callable] = None
    posts_done_in_cb = False

    if interactive:
        posts_done_in_cb = True

        async def _company_role_cb(role: str, reply: str) -> Optional[str]:
            prior_count = role_list.index(role)
            role_msg = f"👤 *{role}* {_prior_context_note(prior_count)}\n{reply}"
            await _send(role_msg)
            remaining = role_list[role_list.index(role) + 1:]
            if remaining:
                return await _wait_for_user_choice(chat_id, context.bot, remaining[0])
            return None

        role_done_cb = _company_role_cb

    discussion, final_outcome = await run_company_discussion(task, role_list, role_done_cb=role_done_cb)

    if not posts_done_in_cb:
        for idx, (role, reply) in enumerate(discussion):
            await _send(f"👤 *{role}* {_prior_context_note(idx)}\n{reply}")

    await _send(f"---\n✅ *Final Outcome*\n\n{final_outcome}")


async def build_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/build <task> [roles:CTO,...] [interactive:true]"""
    msg = update.effective_message
    chat = update.effective_chat
    if msg is None or chat is None:
        return

    args_text = " ".join(context.args or "").strip() if context.args else ""
    if not args_text:
        await msg.reply_text("Usage: /build <task description>\nOptional: roles:CTO,BackendDev,... interactive:true")
        return

    task, role_list, interactive = _parse_company_args(args_text, DEFAULT_BUILD_ROLES)
    chat_id = chat.id

    async with aiohttp.ClientSession() as _name_session:
        project_slug = await generate_project_name(_name_session, task)

    roles_display = ", ".join(role_list)
    mode_note = " _(interactive)_" if interactive else ""
    header = (
        f"🛠️ *AI Developer Team — Build Session*{mode_note}\n"
        f"📋 *Task:* {task}\n"
        f"📁 *Project:* `{project_slug}`\n"
        f"👥 *Team:* {roles_display}\n\n"
        "_Team discussion starting…_"
    )
    await msg.reply_text(header, parse_mode=ParseMode.MARKDOWN)

    async def _send(text: str) -> None:
        await _send_chunks(chat_id, text, context.bot)

    role_done_cb: Optional[Callable] = None
    posts_done_in_cb = False

    if interactive:
        posts_done_in_cb = True

        async def _build_role_cb(role: str, reply: str) -> Optional[str]:
            prior_count = role_list.index(role)
            role_msg = f"👤 *{role}* {_prior_context_note(prior_count)}\n{reply}"
            await _send(role_msg)
            remaining = role_list[role_list.index(role) + 1:]
            if remaining:
                return await _wait_for_user_choice(chat_id, context.bot, remaining[0])
            return None

        role_done_cb = _build_role_cb

    discussion, final_outcome = await run_company_discussion(task, role_list, role_done_cb=role_done_cb)

    if not posts_done_in_cb:
        for idx, (role, reply) in enumerate(discussion):
            await _send(f"👤 *{role}* {_prior_context_note(idx)}\n{reply}")

    await _send(f"---\n✅ *Final Plan*\n\n{final_outcome}")

    code_files, raw_output = await generate_verified_code_files(task, discussion, final_outcome, _send)

    def _store_session(code: list[tuple[str, str]]) -> None:
        build_sessions[chat_id] = {
            "task": task,
            "discussion": discussion,
            "final_outcome": final_outcome,
            "code_files": code,
            "project_slug": project_slug,
            "followup_history": [],
        }

    if not code_files:
        await _send(
            "⚠️ No structured code files were detected in the AI output.\n"
            "The raw output follows:"
        )
        await _send(raw_output or "_No output._")
        _store_session([])
        await _send("💬 _Use /followup to ask questions or request a retry._")
        return

    files_list = "\n".join(f"• `{fn}`" for fn, _ in code_files)
    await _send(f"📦 *{len(code_files)} file(s) generated:*\n{files_list}\n\n_Saving to GitHub…_")

    committed_urls, folder_url = await commit_project(project_slug, task, final_outcome, code_files)

    if committed_urls:
        url_lines = "\n".join(f"• {u}" for u in committed_urls[:20])
        extra = f"\n_(and {len(committed_urls) - 20} more)_" if len(committed_urls) > 20 else ""
        folder_line = f"\n\n📂 *Project folder:* {folder_url}" if folder_url else ""
        await _send(f"✅ *Project saved to GitHub!*\n{url_lines}{extra}{folder_line}")
    elif GITHUB_TOKEN and GITHUB_REPOSITORY:
        await _send("⚠️ Could not commit files to GitHub. Check the bot logs for details.")
    else:
        await _send(
            "ℹ️ GitHub integration not configured — files were not saved.\n"
            "Set `GITHUB_TOKEN` and `GITHUB_REPOSITORY` to enable saving."
        )

    _store_session(code_files)
    await _send("💬 _Session saved. Use /followup to ask questions or request amendments._")


async def autorun_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/autorun [stack:python|php|actions]"""
    msg = update.effective_message
    chat = update.effective_chat
    if msg is None or chat is None:
        return

    chat_id = chat.id
    args_text = " ".join(context.args or "").strip() if context.args else ""
    stack_value: str | None = None
    if args_text.lower().startswith("stack:"):
        candidate = args_text[6:].strip().lower()
        if candidate in _AUTO_STACKS:
            stack_value = candidate

    await msg.reply_text("🤖 *AI AutoRun* — generating task…", parse_mode=ParseMode.MARKDOWN)

    try:
        async with aiohttp.ClientSession() as _setup_session:
            task, chosen_stack = await generate_auto_task(_setup_session, stack_value)
            project_slug = await generate_project_name(_setup_session, task)

        role_list = list(DEFAULT_BUILD_ROLES)
        stack_emoji = _STACK_EMOJI.get(chosen_stack, "💻")

        header = (
            f"🤖 *AI AutoRun — Autonomous Build Session*\n"
            f"📋 *Task:* {task}\n"
            f"📁 *Project:* `{project_slug}`\n"
            f"🛠️ *Stack:* {stack_emoji} `{chosen_stack}`\n"
            f"👥 *Team:* {', '.join(role_list)}\n\n"
            "_Team discussion starting…_"
        )
        await context.bot.send_message(chat_id=chat_id, text=header, parse_mode=ParseMode.MARKDOWN)

        async def _send(text: str) -> None:
            await _send_chunks(chat_id, text, context.bot)

        async def _autorun_role_cb(role: str, reply: str) -> Optional[str]:
            role_idx = role_list.index(role)
            role_msg = f"👤 *{role}* {_prior_context_note(role_idx)}\n{reply}"
            await _send(role_msg)
            remaining = role_list[role_idx + 1:]
            if remaining:
                return await _wait_for_user_choice(chat_id, context.bot, remaining[0])
            return None

        discussion, final_outcome = await run_company_discussion(task, role_list, role_done_cb=_autorun_role_cb)

        await _send(f"---\n✅ *Final Plan*\n\n{final_outcome}")

        code_files, raw_output = await generate_verified_code_files(task, discussion, final_outcome, _send)

        def _store_session(code: list[tuple[str, str]]) -> None:
            build_sessions[chat_id] = {
                "task": task,
                "discussion": discussion,
                "final_outcome": final_outcome,
                "code_files": code,
                "project_slug": project_slug,
                "followup_history": [],
            }

        if not code_files:
            await _send("⚠️ No structured code files detected. The raw output follows:")
            await _send(raw_output or "_No output._")
            _store_session([])
            await _send("💬 _Use /followup to ask questions or request a retry._")
            return

        files_list = "\n".join(f"• `{fn}`" for fn, _ in code_files)
        await _send(f"📦 *{len(code_files)} file(s) generated:*\n{files_list}\n\n_Saving to GitHub…_")

        committed_urls, folder_url = await commit_project(project_slug, task, final_outcome, code_files)

        if committed_urls:
            url_lines = "\n".join(f"• {u}" for u in committed_urls[:20])
            extra = f"\n_(and {len(committed_urls) - 20} more)_" if len(committed_urls) > 20 else ""
            folder_line = f"\n\n📂 *Project folder:* {folder_url}" if folder_url else ""
            await _send(f"✅ *Project saved to GitHub!*\n{url_lines}{extra}{folder_line}")
        elif GITHUB_TOKEN and GITHUB_REPOSITORY:
            await _send("⚠️ Could not commit files to GitHub. Check bot logs for details.")
        else:
            await _send(
                "ℹ️ GitHub integration not configured — files were not saved.\n"
                "Set `GITHUB_TOKEN` and `GITHUB_REPOSITORY` to enable saving."
            )

        _store_session(code_files)
        await _send("💬 _AutoRun session saved. Use /followup to ask questions or request amendments._")

    except Exception as exc:
        logger.error("AutoRun failed: %s", exc, exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text=f"❌ AutoRun encountered an error: {exc}")


async def company_roles_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/company_roles — list available roles."""
    msg = update.effective_message
    if msg is None:
        return
    lines = ["🏢 *Available Company Roles*", "", "*Default roles* (for /company):"]
    for role in DEFAULT_ROLES:
        lines.append(f"• `{role}`")
    lines += ["", "*Default developer team* (for /build and /autorun):"]
    for role in DEFAULT_BUILD_ROLES:
        lines.append(f"• `{role}`")
    lines += ["", "*All built-in roles:*"]
    for role, prompt in ROLE_PROMPTS.items():
        sentences = prompt.split(". ")
        focus = sentences[1].lstrip("Focus on ") if len(sentences) > 1 else ""
        lines.append(f"• `{role}` — {focus}")
    lines += [
        "",
        "*Custom roles* — supply any role name not in the list above.",
        "The bot generates a suitable system prompt automatically.",
    ]
    content = "\n".join(lines)
    chat = update.effective_chat
    if chat is None:
        return
    await _send_chunks(chat.id, content, context.bot)


# ---------------------------------------------------------------------------
# /followup — context-aware continuation
# ---------------------------------------------------------------------------


async def followup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/followup <request> — steer active stream, amend build session, or continue chat."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if msg is None or user is None or chat is None:
        return

    request = " ".join(context.args or "").strip() if context.args else ""
    if not request:
        await msg.reply_text("Usage: /followup <your request or question>")
        return

    chat_id = chat.id

    # ── Priority 1: cancel any active streaming request and redirect it ────
    existing_task = active_requests.pop(user.id, None)
    if existing_task and not existing_task.done():
        existing_task.cancel()
        history = conversation_history.get(chat_id, [])
        preferred = user_preferred_models.get(user.id)

        preview = request[:80] + "…" if len(request) > 80 else request
        await msg.reply_text(f"✏️ _Previous request cancelled — redirecting: \"{preview}\"…_", parse_mode=ParseMode.MARKDOWN)

        task = asyncio.create_task(
            _stream_to_message(request, chat_id, context.bot, preferred, history, None)
        )
        active_requests[user.id] = task
        try:
            reply, model_used, is_fallback = await task
        except asyncio.CancelledError:
            await context.bot.send_message(chat_id=chat_id, text="⛔ Interrupted.")
            return
        finally:
            active_requests.pop(user.id, None)

        if model_used:
            _update_history(chat_id, request, reply)
        return

    # ── Priority 2: active build session → build follow-up ─────────────────
    session_data = build_sessions.get(chat_id)
    if session_data:
        await _do_build_followup(chat_id, request, session_data, context.bot)
        return

    # ── Priority 3: no active request, no build session → general chat ─────
    history = conversation_history.get(chat_id, [])
    preferred = user_preferred_models.get(user.id)

    task = asyncio.create_task(
        _stream_to_message(request, chat_id, context.bot, preferred, history, msg.message_id)
    )
    active_requests[user.id] = task
    try:
        reply, model_used, _ = await task
    except asyncio.CancelledError:
        await context.bot.send_message(chat_id=chat_id, text="⛔ Request cancelled.")
        return
    finally:
        active_requests.pop(user.id, None)

    if model_used:
        _update_history(chat_id, request, reply)


async def _do_build_followup(
    chat_id: int,
    request: str,
    session_data: dict,
    bot: Bot,
) -> None:
    """Perform a build-session follow-up (serialised per chat)."""
    lock = followup_locks.setdefault(chat_id, asyncio.Lock())

    async with lock:
        task_desc = session_data["task"]
        discussion: list[tuple[str, str]] = session_data["discussion"]
        final_outcome: str = session_data["final_outcome"]
        code_files: list[tuple[str, str]] = session_data.get("code_files", [])
        project_slug: str = session_data.get("project_slug", "project")
        followup_history: list[dict] = session_data.setdefault("followup_history", [])

        logger.info(
            "Build follow-up #%d | project=%s | request=%r",
            len(followup_history) + 1, project_slug, request,
        )

        context_str = f"*Original Task:* {task_desc}\n\n*Developer Team Discussion:*\n"
        for role, reply in discussion:
            context_str += f"\n*{role}:* {reply}\n"
        context_str += f"\n*Final Plan:*\n{final_outcome}\n"

        if code_files:
            context_str += "\n*Previously Generated Files:*\n"
            for filename, content in code_files:
                preview = content[:600] + "\n…(truncated)" if len(content) > 600 else content
                context_str += f"\n### File: {filename}\n```\n{preview}\n```\n"

        if followup_history:
            context_str += "\n*Previous Follow-up Conversation:*\n"
            for i, exchange in enumerate(followup_history[-10:], 1):
                context_str += f"\nQ{i}: {exchange['request']}\n"
                reply_preview = exchange["reply"][:500]
                if len(exchange["reply"]) > 500:
                    reply_preview += "\n…(truncated)"
                context_str += f"A{i}: {reply_preview}\n"

        followup_prompt = (
            f"{context_str}\n\n"
            f"*Follow-up Request #{len(followup_history) + 1}:* {request}\n\n"
            "Answer clearly. If modifying code use the `### File: <filename>` / ``` format."
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a senior software engineer helping to refine and extend a "
                    "previously generated project. You have full context of every prior "
                    "follow-up exchange above. Use the `### File:` / ``` format for code."
                ),
            },
            {"role": "user", "content": followup_prompt},
        ]

        async with aiohttp.ClientSession() as http_session:
            try:
                reply = await call_ai(http_session, messages)
            except Exception as exc:
                logger.error("Follow-up AI call failed: %s", exc)
                await bot.send_message(chat_id=chat_id, text="⚠️ AI request failed. Please try again.")
                return

        followup_num = len(followup_history) + 1
        await bot.send_message(chat_id=chat_id, text=f"💬 *Follow-up #{followup_num}:* {request[:120]}", parse_mode=ParseMode.MARKDOWN)
        await _send_chunks(chat_id, reply, bot)

        followup_history.append({"request": request, "reply": reply})

        amended_files = parse_code_files(reply)
        if amended_files:
            existing = dict(code_files)
            for fn, content in amended_files:
                existing[fn] = content
            session_data["code_files"] = list(existing.items())

            if GITHUB_TOKEN and GITHUB_REPOSITORY:
                await bot.send_message(chat_id=chat_id, text=f"📝 _{len(amended_files)} file(s) amended. Saving to GitHub…_", parse_mode=ParseMode.MARKDOWN)
                committed_urls, _ = await commit_project(project_slug, task_desc, final_outcome, amended_files)
                if committed_urls:
                    url_lines = "\n".join(f"• {u}" for u in committed_urls[:10])
                    extra = f"\n_(and {len(committed_urls) - 10} more)_" if len(committed_urls) > 10 else ""
                    await bot.send_message(chat_id=chat_id, text=f"✅ *Amendments saved to GitHub:*\n{url_lines}{extra}", parse_mode=ParseMode.MARKDOWN)
                else:
                    await bot.send_message(chat_id=chat_id, text="⚠️ Could not commit amended files to GitHub.")
            else:
                files_list = "\n".join(f"• `{fn}`" for fn, _ in amended_files)
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"📝 _{len(amended_files)} file(s) included above:_\n{files_list}\n"
                        "_(GitHub integration not configured — files not saved automatically.)_"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )


# ---------------------------------------------------------------------------
# Interactive callback query handler
# ---------------------------------------------------------------------------


async def interactive_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Continue / Add Input button presses during interactive sessions."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    data = query.data or ""
    if data.startswith("interactive_continue:"):
        chat_id = int(data.split(":")[1])
        key = f"interactive:{chat_id}"
        fut = _interactive_futures.get(key)
        if fut and not fut.done():
            fut.set_result(None)
        await query.edit_message_text("▶ Continuing…")

    elif data.startswith("interactive_input:"):
        chat_id = int(data.split(":")[1])
        key = f"interactive:{chat_id}"
        fut = _interactive_futures.get(key)
        if fut:
            # Ask user to type their input as a reply in the chat
            await query.edit_message_text(
                "✏️ Please type your input/perspective and send it as a reply. "
                "I'll include it in the discussion."
            )
            # Register a one-time text listener for this chat
            context.chat_data["awaiting_interactive_input"] = key  # type: ignore[index]


async def interactive_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture text input typed by user during interactive sessions.

    Runs in handler group 0 (higher priority).  Raises ApplicationHandlerStop
    when it consumes the message so the general chat handler in group 1 is skipped.
    """
    msg = update.effective_message
    if msg is None:
        return
    key = context.chat_data.get("awaiting_interactive_input")  # type: ignore[union-attr]
    if not key:
        return  # not waiting for input — let group 1 handle it normally
    del context.chat_data["awaiting_interactive_input"]  # type: ignore[union-attr]

    fut = _interactive_futures.get(key)
    if fut and not fut.done():
        fut.set_result(msg.text or "")
        await msg.reply_text(f"✅ _Your input noted: \"{(msg.text or '')[:80]}\"_", parse_mode=ParseMode.MARKDOWN)
    raise ApplicationHandlerStop  # prevent the general chat handler from also firing


# ---------------------------------------------------------------------------
# Weather command
# ---------------------------------------------------------------------------


async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/weather — current HK weather + AI clothing suggestions."""
    msg = update.effective_message
    chat = update.effective_chat
    if msg is None or chat is None:
        return

    await msg.reply_text("🌤️ Fetching Hong Kong weather…")

    weather = await fetch_hk_weather()
    if not weather:
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "⚠️ Could not fetch current weather data from HKO. Please try again later.\n"
                f"_(Source: {HKO_RSS_URL})_"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    suggestion = await get_weather_clothing_suggestion(weather)
    weather_msg = _build_weather_message(weather, suggestion)
    await _send_chunks(chat.id, weather_msg, context.bot)


# ---------------------------------------------------------------------------
# /about
# ---------------------------------------------------------------------------


def _build_about_message() -> str:
    default_roles_str = ", ".join(DEFAULT_ROLES)
    build_roles_str = ", ".join(DEFAULT_BUILD_ROLES)
    return (
        "🤖 *Unified AI Telegram Bot — How to Use*\n\n"
        "💬 *General Chat*\n"
        "• Message me directly (DM) and I'll reply with AI.\n"
        "• In groups: mention me with @username to chat.\n\n"
        "⚡ *Chat Commands*\n"
        "• `/ask <question>` — Ask a question (live streaming)\n"
        "• `/ask model:<name> <question>` — Use a specific model\n"
        "• `/cancel` — Cancel your in-progress request\n"
        "• `/models` — List available AI models\n"
        "• `/settings <model>` — Set your preferred model\n\n"
        "🏢 *AI Company / Build*\n"
        "• `/company <task>` — Multi-role company discussion\n"
        "• `/company <task> roles:CEO,CTO,... interactive:true` — Interactive mode\n"
        "• `/build <task>` — Dev team discussion + code gen → saved to `project/`\n"
        "• `/build <task> roles:... interactive:true` — Interactive build\n"
        "• `/autorun` — AI picks a task and builds it end-to-end\n"
        "• `/autorun stack:python` — Force a stack (python / php / actions)\n"
        "• `/company_roles` — List available roles\n\n"
        "🔄 *Code Review* (automatic after /build / /autorun)\n"
        "A reviewer AI checks code and regenerates with feedback (up to 2 rounds).\n\n"
        "🌤️ *Weather*\n"
        "• `/weather` — Current HK weather (HKO) + AI clothing suggestions\n"
        "Auto-reminders: set `WEATHER_CHAT_ID` and `WEATHER_REMINDER_HOURS` env vars.\n\n"
        "🔗 */followup <request>* — context-aware:\n"
        "1. Active stream → cancel & redirect to new topic\n"
        "2. After /build / /autorun → amend code or ask questions\n"
        "   (supports unlimited chained follow-ups with full prior context)\n"
        "3. Otherwise → continue general chat conversation\n\n"
        f"👥 *Default Company Roles:* {default_roles_str}\n"
        f"🛠️ *Default Dev Team:* {build_roles_str}\n\n"
        "💡 *Examples*\n"
        "```\n"
        "/ask Explain async/await in Python\n"
        "/company Build a food delivery app\n"
        "/build Create a REST API for a todo app interactive:true\n"
        "/autorun stack:python\n"
        "/followup Add JWT authentication\n"
        "/followup Now add rate limiting\n"
        "/weather\n"
        "```"
    )


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/about — show bot help guide."""
    msg = update.effective_message
    chat = update.effective_chat
    if msg is None or chat is None:
        return
    await _send_chunks(chat.id, _build_about_message(), context.bot)


# ---------------------------------------------------------------------------
# Argument parser for /company and /build
# ---------------------------------------------------------------------------


def _parse_company_args(
    text: str,
    default_roles: list[str],
) -> tuple[str, list[str], bool]:
    """Parse shared argument format for /company and /build.

    Supported format:
        <task text> [roles:<r1,r2,...>] [interactive:true]
    """
    interactive = False
    role_list = list(default_roles)

    # Extract interactive flag
    m = re.search(r"\binteractive\s*:\s*(true|yes|1)\b", text, re.IGNORECASE)
    if m:
        interactive = True
        text = (text[:m.start()] + text[m.end():]).strip()

    # Extract roles
    m = re.search(r"\broles\s*:\s*([^\s]+)", text, re.IGNORECASE)
    if m:
        roles_str = m.group(1)
        parsed = [r.strip() for r in roles_str.split(",") if r.strip()]
        if parsed:
            role_list = parsed
        text = (text[:m.start()] + text[m.end():]).strip()

    return text.strip(), role_list, interactive


# ---------------------------------------------------------------------------
# Weather auto-reminder background task
# ---------------------------------------------------------------------------


async def _weather_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Post an auto weather reminder to the configured chat.

    Scheduled every 30 minutes; sends at most once per configured HKT hour.
    """
    if not WEATHER_CHAT_ID or not WEATHER_REMINDER_HOURS:
        return

    hkt_now = datetime.datetime.now(_HKT)
    if hkt_now.hour not in WEATHER_REMINDER_HOURS:
        return

    current_key = (hkt_now.toordinal(), hkt_now.hour)
    if current_key in _weather_sent_hours:
        return

    _weather_sent_hours.add(current_key)

    cutoff = hkt_now.toordinal() - 2
    for key in list(_weather_sent_hours):
        if key[0] < cutoff:
            _weather_sent_hours.discard(key)

    weather = await fetch_hk_weather()
    if not weather:
        logger.warning("Weather reminder: could not fetch HKO data — skipping this round")
        return

    suggestion = await get_weather_clothing_suggestion(weather)
    header = f"⏰ *今日天氣提醒 / Weather Reminder — Hong Kong* ({hkt_now.strftime('%H:%M')} HKT)"
    weather_msg = _build_weather_message(weather, suggestion, header=header)

    try:
        await _send_chunks(WEATHER_CHAT_ID, weather_msg, context.bot)
        logger.info("Weather reminder sent to chat %s", WEATHER_CHAT_ID)
    except Exception as exc:
        logger.warning("Weather reminder: failed to send message: %s", exc)


# ---------------------------------------------------------------------------
# Build the Application
# ---------------------------------------------------------------------------


def _build_application() -> Application:
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("models", models_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("company", company_command))
    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CommandHandler("autorun", autorun_command))
    app.add_handler(CommandHandler("company_roles", company_roles_command))
    app.add_handler(CommandHandler("followup", followup_command))
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("start", about_command))

    # Callback queries for interactive mode
    app.add_handler(CallbackQueryHandler(interactive_callback_handler, pattern=r"^interactive_"))

    # Interactive input capture (group 0 — higher priority).
    # Raises ApplicationHandlerStop when it consumes the message, preventing
    # the general chat handler in group 1 from also firing.
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, interactive_text_handler),
        group=0,
    )

    # General chat — DMs and group @mentions (group 1).
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND,
            _on_message_handler,
        ),
        group=1,
    )

    # Weather reminder job (every 30 minutes)
    if WEATHER_CHAT_ID and WEATHER_REMINDER_HOURS:
        app.job_queue.run_repeating(  # type: ignore[union-attr]
            _weather_reminder_job,
            interval=1800,
            first=60,
        )
        logger.info(
            "Weather reminders enabled: chat=%s hours=%s HKT",
            WEATHER_CHAT_ID, WEATHER_REMINDER_HOURS,
        )
    else:
        logger.info("Weather reminders disabled (WEATHER_CHAT_ID not set).")

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    if not TELEGRAM_TOKEN:
        logger.error(
            "TELEGRAM_TOKEN is not set. "
            "Create a bot via @BotFather on Telegram and set the token as an environment variable."
        )
        raise SystemExit(1)
    if not POLLINATIONS_TOKEN:
        logger.error(
            "POLLINATIONS_TOKEN is not set. "
            "Get your key from https://enter.pollinations.ai and set it as an environment variable."
        )
        raise SystemExit(1)

    app = _build_application()
    logger.info("Starting Telegram bot (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
