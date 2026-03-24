"""Unified AI Discord Bot.

Combines the General Chat bot (streaming AI replies, conversation history,
vision models) and the AI Company bot (multi-role company discussions,
/build, /autorun, code review) into a single process that requires only
**one Discord bot token** (``DISCORD_TOKEN``).

Slash commands
--------------
General chat
    /ask      — ask the AI a question (streaming, model selection)
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
    /followup  — universal context-aware continuation:
                 • cancels an active stream and redirects (if one is running)
                 • build-session follow-up (if a /build or /autorun session exists)
                   supports unlimited chained follow-ups
                 • general chat follow-up (otherwise)
    /about     — show this help guide

Environment variables
---------------------
Required
    DISCORD_TOKEN          Bot token (also accepted as DISCORD_TOKEN_COMPANY
                           for backwards-compatibility with the old layout)
    POLLINATIONS_TOKEN     Pollinations AI API key

Optional (needed for /build GitHub commit)
    GITHUB_TOKEN           GitHub PAT or Actions token with repo write access
    GITHUB_REPOSITORY      Repo in "owner/repo" format

Optional (Hong Kong weather auto-reminders)
    WEATHER_CHANNEL_ID     Discord channel ID to post auto weather reminders
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
import discord
from discord import app_commands
from discord.ext import commands, tasks
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

# Accept DISCORD_TOKEN *or* the legacy DISCORD_TOKEN_COMPANY env var.
DISCORD_TOKEN: str = (
    os.environ.get("DISCORD_TOKEN")
    or os.environ.get("DISCORD_TOKEN_COMPANY", "")
)
POLLINATIONS_TOKEN: str = os.environ.get("POLLINATIONS_TOKEN", "")

# GitHub integration (optional — only needed for /build file commits)
GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY: str = os.environ.get("GITHUB_REPOSITORY", "")
GITHUB_API_BASE = "https://api.github.com"
PROJECT_FOLDER = "project"

# Hong Kong weather auto-reminders (optional)
# WEATHER_CHANNEL_ID  — Discord channel ID to post auto reminders
# WEATHER_REMINDER_HOURS — comma-separated HKT hours, e.g. "8,20"
WEATHER_CHANNEL_ID: int = int(os.environ.get("WEATHER_CHANNEL_ID", "0") or "0")
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

DISCORD_MAX_LENGTH = 2000
STREAM_EDIT_INTERVAL = 1.5   # seconds between live edit updates
STREAM_DISPLAY_LIMIT = 1950  # chars shown in a streaming placeholder
MAX_HISTORY = 20             # max conversation messages per channel

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

MODEL_CHOICES: list[app_commands.Choice[str]] = [
    app_commands.Choice(
        name=f"{model}{' [vision]' if MODEL_INFO.get(model, ('', False))[1] else ''}",
        value=model,
    )
    for model in sorted(MODEL_INFO)
][:25]

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
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True  # needed for on_message mention handling

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

# Per-channel build sessions for /followup continuations.
# Structure: { channel_id: { task, discussion, final_outcome, code_files, ... } }
build_sessions: dict[int, dict] = {}

# Per-channel conversation history for general chat.
# Structure: { channel_id: [ {"role": ..., "content": ...}, ... ] }
conversation_history: dict[int, list[dict]] = {}

# Per-user preferred model (set via /settings).
user_preferred_models: dict[int, str] = {}

# Per-user active streaming tasks (used by /cancel and /followup interrupt mode).
active_requests: dict[int, asyncio.Task] = {}

# Per-channel asyncio locks for build-session follow-ups.
# Prevents two concurrent /followup invocations from racing on the same session.
followup_locks: dict[int, asyncio.Lock] = {}

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


def split_message(text: str, limit: int = DISCORD_MAX_LENGTH) -> list[str]:
    """Split *text* into chunks ≤ *limit* characters.

    Prefers splitting on newlines, then spaces.  Closes and re-opens Markdown
    code fences across splits so Discord formatting stays intact.
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


def get_image_urls(message: discord.Message) -> list[str]:
    return [
        a.url for a in message.attachments
        if a.content_type and a.content_type.startswith("image/")
    ]


def _update_history(channel_id: int, user_text: str, assistant_reply: str) -> None:
    history = conversation_history.setdefault(channel_id, [])
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": assistant_reply})
    if len(history) > MAX_HISTORY:
        conversation_history[channel_id] = history[-MAX_HISTORY:]


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


def _build_weather_message(weather: dict, suggestion: str, *, header: str = "🌤️ **Hong Kong Current Weather**") -> str:
    """Format weather data and clothing suggestion into a Discord message."""
    temp_str = f"{weather['temperature']}°C" if weather.get("temperature") else "N/A"
    humid_str = f"{weather['humidity']}%" if weather.get("humidity") else "N/A"

    lines = [
        header,
        f"📅 {weather['title']}",
        "",
        f"🌡️ 氣溫 / Temperature: **{temp_str}**",
        f"💧 相對濕度 / Humidity: **{humid_str}**",
    ]
    if weather.get("summary"):
        lines.append(f"🌈 天氣 / Condition: {weather['summary']}")
    lines += [
        "",
        "---",
        "👕 **今日穿著建議 / Clothing Suggestion:**",
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
# Thread helper
# ---------------------------------------------------------------------------


async def _create_task_thread(
    msg: discord.WebhookMessage,
    name: str,
    channel: discord.TextChannel | None = None,
) -> discord.Thread | None:
    try:
        if channel is not None:
            full_msg = await channel.fetch_message(msg.id)
            return await full_msg.create_thread(name=name[:100])
        return await msg.create_thread(name=name[:100])
    except (discord.Forbidden, discord.HTTPException, AttributeError, ValueError) as exc:
        logger.warning("Could not create thread: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Discord UI components
# ---------------------------------------------------------------------------


class UserInputModal(discord.ui.Modal, title="Add Your Perspective"):
    perspective = discord.ui.TextInput(
        label="Your input / perspective",
        style=discord.TextStyle.paragraph,
        placeholder="Share your thoughts, redirect the discussion, add constraints…",
        required=True,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()


class InterruptView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=90)
        self.action: str = "continue"
        self.user_input: Optional[str] = None
        self._message: Optional[discord.Message] = None

    @discord.ui.button(label="▶ Continue", style=discord.ButtonStyle.green)
    async def continue_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.action = "continue"
        logger.info("InterruptView: user %s chose Continue", interaction.user)
        for item in self.children:
            item.disabled = True  # type: ignore[union-attr]
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="✏️ Add My Input", style=discord.ButtonStyle.blurple)
    async def input_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        logger.info("InterruptView: user %s opening input modal", interaction.user)
        modal = UserInputModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        self.user_input = modal.perspective.value
        self.action = "input"
        logger.info("InterruptView: user %s submitted input (%d chars)", interaction.user, len(self.user_input or ""))
        for item in self.children:
            item.disabled = True  # type: ignore[union-attr]
        # Attempt to update the message to show disabled buttons after modal submission.
        if self._message is not None:
            try:
                await self._message.edit(view=self)
            except discord.HTTPException as exc:
                logger.warning("InterruptView: could not update message after input: %s", exc)
        self.stop()

    async def on_timeout(self) -> None:
        logger.info("InterruptView: timed out, auto-continuing")
        self.action = "continue"
        for item in self.children:
            item.disabled = True  # type: ignore[union-attr]
        if self._message is not None:
            try:
                await self._message.edit(view=self)
            except discord.HTTPException as exc:
                logger.warning("InterruptView: could not update message on timeout: %s", exc)
        self.stop()


class RoleSelectView(discord.ui.View):
    def __init__(self, defaults: list[str]) -> None:
        super().__init__(timeout=120)
        self.selected_roles: list[str] = list(defaults)
        options = [
            discord.SelectOption(label=role, value=role, default=role in defaults)
            for role in ROLE_PROMPTS
        ]
        visible = options[:25]
        if len(options) > 25:
            logger.warning("ROLE_PROMPTS has %d roles; only first 25 shown.", len(options))
        select = discord.ui.Select(
            placeholder="Choose roles for this build (select any number)…",
            min_values=1,
            max_values=len(visible),
            options=visible,
        )
        select.callback = self._on_select  # type: ignore[method-assign]
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        self.selected_roles = interaction.data["values"]  # type: ignore[index]
        await interaction.response.defer()
        self.stop()

    async def on_timeout(self) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# Bot events
# ---------------------------------------------------------------------------


@bot.event
async def on_ready():
    await bot.tree.sync()
    logger.info("Unified AI Bot logged in as %s (ID: %s)", bot.user, bot.user.id)
    logger.info("General chat active — mention @%s, send a DM, or reply in a bot thread to chat.", bot.user.name)
    if WEATHER_CHANNEL_ID and WEATHER_REMINDER_HOURS:
        if not weather_reminder_task.is_running():
            weather_reminder_task.start()
        logger.info(
            "Weather reminders enabled: channel=%s hours=%s HKT",
            WEATHER_CHANNEL_ID, WEATHER_REMINDER_HOURS,
        )
    else:
        logger.info("Weather reminders disabled (WEATHER_CHANNEL_ID not set).")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    logger.error("Unhandled slash-command error: %s", error, exc_info=True)
    msg = f"⚠️ An unexpected error occurred: {error}"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception as send_exc:
        logger.warning("Could not send error message: %s", send_exc)


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    # Respond when the bot is mentioned, in a DM, OR continuing an existing
    # conversation thread (the user doesn't need to re-mention the bot for
    # every follow-up in a thread the bot already replied to).
    in_conversation_thread = (
        isinstance(message.channel, discord.Thread)
        and message.channel.id in conversation_history
    )
    mentioned = bot.user.mentioned_in(message)

    if mentioned or isinstance(message.channel, discord.DMChannel) or in_conversation_thread:
        logger.info(
            "General chat message from %s (channel %s, thread=%s, mentioned=%s)",
            message.author, message.channel.id, in_conversation_thread, mentioned,
        )
        content = message.content
        for mention in message.mentions:
            content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
        content = content.strip()

        token, content = parse_model_prefix(content)

        if token == "about":
            await message.reply(_build_about_message())
            return

        preferred_model: str | None = token if token is not None else user_preferred_models.get(message.author.id)
        image_urls = get_image_urls(message)

        if image_urls and preferred_model and preferred_model not in VISION_MODELS:
            await message.reply(
                f"⚠️ **{preferred_model}** doesn't support image input. "
                "Switching to a vision-capable model automatically."
            )
            preferred_model = None

        if not content and not image_urls:
            await message.reply(
                "Please send a message (or attach an image) for me to reply to!\n"
                "Use `/ask` for a slash-command interface, or `/about` for help."
            )
            return

        if not content:
            content = "Describe this image."

        reply_channel: discord.abc.Messageable = message.channel
        if isinstance(message.channel, discord.TextChannel):
            try:
                thread_name = f"AI Chat — {message.author.display_name}"[:100]
                reply_channel = await message.create_thread(name=thread_name, auto_archive_duration=60)
            except discord.HTTPException as exc:
                logger.warning("Could not create thread: %s", exc)

        history_key = reply_channel.id
        history = conversation_history.get(history_key, [])

        if isinstance(reply_channel, discord.Thread):
            placeholder_msg = await reply_channel.send("▌")
        else:
            placeholder_msg = await message.reply("▌")

        async def _on_progress(text: str) -> None:
            display = text[-STREAM_DISPLAY_LIMIT:] + "▌" if len(text) > STREAM_DISPLAY_LIMIT else text + "▌"
            try:
                await placeholder_msg.edit(content=display)
            except discord.HTTPException:
                pass

        task = asyncio.create_task(
            get_ai_reply_streaming(content, preferred_model, image_urls, history, _on_progress)
        )
        active_requests[message.author.id] = task
        try:
            reply, model_used, is_fallback = await task
        except asyncio.CancelledError:
            await placeholder_msg.edit(content="⛔ Your in-progress request has been cancelled.")
            return
        finally:
            active_requests.pop(message.author.id, None)

        display_reply = reply + _fallback_footer(model_used, preferred_model, is_fallback)
        if model_used:
            _update_history(history_key, content, reply)

        chunks = split_message(display_reply)
        await placeholder_msg.edit(content=chunks[0])
        for chunk in chunks[1:]:
            await reply_channel.send(chunk)

    await bot.process_commands(message)


# ---------------------------------------------------------------------------
# General chat slash commands
# ---------------------------------------------------------------------------


@bot.tree.command(name="ask", description="Ask the AI a question with optional model selection")
@app_commands.describe(
    question="Your question or prompt for the AI",
    model="AI model to use (leave blank for automatic selection)",
)
@app_commands.choices(model=MODEL_CHOICES)
async def ask_slash(interaction: discord.Interaction, question: str, model: str | None = None):
    preferred_model = model or None
    await interaction.response.defer(thinking=True)

    history_key = interaction.channel_id if interaction.channel_id is not None else interaction.user.id
    history = conversation_history.get(history_key, [])

    placeholder_msg = await interaction.followup.send("▌")

    async def _on_progress(text: str) -> None:
        display = text[-STREAM_DISPLAY_LIMIT:] + "▌" if len(text) > STREAM_DISPLAY_LIMIT else text + "▌"
        try:
            await placeholder_msg.edit(content=display)
        except discord.HTTPException:
            pass

    t = asyncio.create_task(
        get_ai_reply_streaming(question, preferred_model, history=history, progress_cb=_on_progress)
    )
    active_requests[interaction.user.id] = t
    try:
        reply, model_used, is_fallback = await t
    except asyncio.CancelledError:
        await placeholder_msg.edit(content="⛔ Your in-progress request has been cancelled.")
        return
    finally:
        active_requests.pop(interaction.user.id, None)

    if model_used:
        _update_history(history_key, question, reply)

    display_reply = reply + _fallback_footer(model_used, preferred_model, is_fallback)
    chunks = split_message(display_reply)
    await placeholder_msg.edit(content=chunks[0])
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk)


@bot.tree.command(name="cancel", description="Hard-cancel your current in-progress AI request")
async def cancel_slash(interaction: discord.Interaction):
    task = active_requests.pop(interaction.user.id, None)
    if task and not task.done():
        task.cancel()
        await interaction.response.send_message("⛔ Your in-progress request has been cancelled.")
    else:
        await interaction.response.send_message("You don't have an active request to cancel.")


@bot.tree.command(name="models", description="List all available AI models with their capabilities")
async def models_slash(interaction: discord.Interaction):
    lines = ["**📋 Available AI Models**", ""]
    for model in sorted(MODEL_INFO):
        desc, vision = MODEL_INFO[model]
        vision_mark = "✅" if vision else "❌"
        lines.append(f"**`{model}`** {vision_mark} — {desc}")
    lines += ["", "*Tip: Use `/ask` and pick a model from the dropdown.*"]
    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="settings", description="View or set your preferred AI model")
@app_commands.describe(model="Your preferred AI model (leave blank to view current setting)")
@app_commands.choices(model=MODEL_CHOICES)
async def settings_slash(interaction: discord.Interaction, model: str | None = None):
    if model is None:
        current = user_preferred_models.get(interaction.user.id)
        if current:
            desc, vision = MODEL_INFO.get(current, ("Unknown model", False))
            vision_tag = " [vision]" if vision else ""
            await interaction.response.send_message(
                f"Your preferred model is **{current}**{vision_tag} — {desc}.\n"
                "Use `/settings model:...` to change it."
            )
        else:
            await interaction.response.send_message(
                "No preferred model set — using automatic model selection.\n"
                "Use `/settings model:...` to set one."
            )
    else:
        user_preferred_models[interaction.user.id] = model
        desc, vision = MODEL_INFO.get(model, ("Unknown model", False))
        vision_tag = " [vision]" if vision else ""
        await interaction.response.send_message(
            f"✅ Preferred model set to **{model}**{vision_tag} — {desc}."
        )


# ---------------------------------------------------------------------------
# AI Company slash commands
# ---------------------------------------------------------------------------


@bot.tree.command(name="company", description="Run an AI company discussion on a task")
@app_commands.describe(
    task="The task or project for the company to discuss",
    roles="Comma-separated roles (e.g. 'CEO,CTO,Designer'). Leave blank for defaults.",
    interactive="Pause after each role so you can add your own perspective. Default: False.",
)
async def company_slash(
    interaction: discord.Interaction,
    task: str,
    roles: str | None = None,
    interactive: bool = False,
):
    await interaction.response.defer(thinking=True)

    role_list = [r.strip() for r in roles.split(",") if r.strip()] if roles else list(DEFAULT_ROLES)

    logger.info("Company discussion | task=%r | roles=%s | interactive=%s", task, role_list, interactive)

    roles_display = ", ".join(role_list)
    mode_note = " *(interactive)*" if interactive else ""
    header = (
        f"🏢 **AI Company Discussion**{mode_note}\n"
        f"📋 **Task:** {task}\n"
        f"👥 **Participants:** {roles_display}\n"
        f"📡 *Each role reads all prior contributions before responding.*\n\n"
        "*Starting discussion… this may take a moment.*"
    )
    header_msg = await interaction.followup.send(header)
    thread = await _create_task_thread(header_msg, f"🏢 {task}"[:100], interaction.channel)
    send = thread.send if thread else interaction.followup.send

    role_done_cb: Optional[Callable] = None
    posts_done_in_cb = False

    if interactive:
        posts_done_in_cb = True

        async def _company_role_cb(role: str, reply: str) -> Optional[str]:
            logger.info("Company interactive: posting role %r response", role)
            prior_count = role_list.index(role)
            msg = f"👤 **{role}** {_prior_context_note(prior_count)}\n{reply}"
            for chunk in split_message(msg):
                await send(chunk)
            remaining = role_list[role_list.index(role) + 1:]
            if remaining:
                view = InterruptView()
                prompt_msg = await send(
                    f"*Next up: **{remaining[0]}**.*  "
                    "Would you like to add your perspective first?",
                    view=view,
                )
                view._message = prompt_msg
                logger.info("Company interactive: waiting for user input before %r", remaining[0])
                await view.wait()
                if view.action == "input" and view.user_input:
                    preview = view.user_input[:80] + "…" if len(view.user_input) > 80 else view.user_input
                    await send(f"✅ *Your input noted: \"{preview}\"*")
                    return view.user_input
            return None

        role_done_cb = _company_role_cb

    discussion, final_outcome = await run_company_discussion(task, role_list, role_done_cb=role_done_cb)

    if not posts_done_in_cb:
        for idx, (role, reply) in enumerate(discussion):
            msg = f"👤 **{role}** {_prior_context_note(idx)}\n{reply}"
            for chunk in split_message(msg):
                await send(chunk)

    for chunk in split_message(f"---\n✅ **Final Outcome**\n\n{final_outcome}"):
        await send(chunk)


@bot.tree.command(
    name="build",
    description="Developer team discussion + code generation saved to project/",
)
@app_commands.describe(
    task="Describe what to build",
    roles="Comma-separated developer roles. Leave blank to pick from a dropdown.",
    interactive="Pause after each role so you can add your perspective. Default: False.",
)
async def build_slash(
    interaction: discord.Interaction,
    task: str,
    roles: str | None = None,
    interactive: bool = False,
):
    await interaction.response.defer(thinking=True)

    if roles:
        role_list = [r.strip() for r in roles.split(",") if r.strip()]
    else:
        role_view = RoleSelectView(list(DEFAULT_BUILD_ROLES))
        await interaction.followup.send(
            "👥 **Select team roles** *(choose any number, or wait 2 min to use defaults):*",
            view=role_view,
            ephemeral=True,
        )
        await role_view.wait()
        role_list = role_view.selected_roles

    async with aiohttp.ClientSession() as _name_session:
        project_slug = await generate_project_name(_name_session, task)

    logger.info("Build | task=%r | project=%s | roles=%s", task, project_slug, role_list)

    roles_display = ", ".join(role_list)
    mode_note = " *(interactive)*" if interactive else ""
    header = (
        f"🛠️ **AI Developer Team — Build Session**{mode_note}\n"
        f"📋 **Task:** {task}\n"
        f"📁 **Project:** `{project_slug}`\n"
        f"👥 **Team:** {roles_display}\n"
        f"📡 *Each team member reads all prior contributions before responding.*\n\n"
        "*Team discussion starting… this may take a moment.*"
    )
    header_msg = await interaction.followup.send(header)
    thread = await _create_task_thread(header_msg, f"🛠️ {project_slug}"[:100], interaction.channel)
    send = thread.send if thread else interaction.followup.send

    role_done_cb: Optional[Callable] = None
    posts_done_in_cb = False

    if interactive:
        posts_done_in_cb = True

        async def _build_role_cb(role: str, reply: str) -> Optional[str]:
            logger.info("Build interactive: posting role %r response", role)
            prior_count = role_list.index(role)
            msg = f"👤 **{role}** {_prior_context_note(prior_count)}\n{reply}"
            for chunk in split_message(msg):
                await send(chunk)
            remaining = role_list[role_list.index(role) + 1:]
            if remaining:
                view = InterruptView()
                prompt_msg = await send(
                    f"*Next up: **{remaining[0]}**.*  "
                    "Would you like to add your perspective first?",
                    view=view,
                )
                view._message = prompt_msg
                logger.info("Build interactive: waiting for user input before %r", remaining[0])
                await view.wait()
                if view.action == "input" and view.user_input:
                    preview = view.user_input[:80] + "…" if len(view.user_input) > 80 else view.user_input
                    await send(f"✅ *Your input noted: \"{preview}\"*")
                    return view.user_input
            return None

        role_done_cb = _build_role_cb

    discussion, final_outcome = await run_company_discussion(task, role_list, role_done_cb=role_done_cb)

    if not posts_done_in_cb:
        for idx, (role, reply) in enumerate(discussion):
            msg = f"👤 **{role}** {_prior_context_note(idx)}\n{reply}"
            for chunk in split_message(msg):
                await send(chunk)

    for chunk in split_message(f"---\n✅ **Final Plan**\n\n{final_outcome}"):
        await send(chunk)

    # Generate code with format-retry + code review
    code_files, raw_output = await generate_verified_code_files(
        task, discussion, final_outcome, send
    )

    def _store_session(code: list[tuple[str, str]]) -> None:
        session_dict: dict = {
            "task": task,
            "discussion": discussion,
            "final_outcome": final_outcome,
            "code_files": code,
            "project_slug": project_slug,
            "thread_id": thread.id if thread else None,
            "followup_history": [],
        }
        channel_id = interaction.channel_id or 0
        build_sessions[channel_id] = session_dict
        if thread:
            build_sessions[thread.id] = session_dict

    if not code_files:
        await send(
            "⚠️ No structured code files were detected in the AI output. "
            "The raw output follows:"
        )
        for chunk in split_message(raw_output or "*No output.*"):
            await send(chunk)
        _store_session([])
        await send("💬 *Use `/followup` to ask questions or request a retry.*")
        return

    files_list = "\n".join(f"• `{fn}`" for fn, _ in code_files)
    await send(f"📦 **{len(code_files)} file(s) generated:**\n{files_list}\n\n*Saving to GitHub…*")

    committed_urls, folder_url = await commit_project(project_slug, task, final_outcome, code_files)

    if committed_urls:
        url_lines = "\n".join(f"• {u}" for u in committed_urls[:20])
        extra = f"\n*(and {len(committed_urls) - 20} more)*" if len(committed_urls) > 20 else ""
        folder_line = f"\n\n📂 **Project folder:** {folder_url}" if folder_url else ""
        await send(f"✅ **Project saved to GitHub!**\n{url_lines}{extra}{folder_line}")
    elif GITHUB_TOKEN and GITHUB_REPOSITORY:
        await send("⚠️ Could not commit files to GitHub. Check the bot logs for details.")
    else:
        await send(
            "ℹ️ GitHub integration not configured — files were not saved.\n"
            "Set `GITHUB_TOKEN` and `GITHUB_REPOSITORY` to enable saving."
        )

    _store_session(code_files)
    await send("💬 *Session saved. Use `/followup` to ask questions or request amendments.*")


_STACK_EMOJI: dict[str, str] = {"python": "🐍", "php": "🐘", "actions": "⚙️"}


@bot.tree.command(
    name="autorun",
    description="AI picks a task and builds it autonomously; you can steer after each role",
)
@app_commands.describe(stack="Preferred tech stack. Leave blank for AI to choose.")
@app_commands.choices(stack=[
    app_commands.Choice(name="Python (Flask / FastAPI / CLI)", value="python"),
    app_commands.Choice(name="PHP + HTML (web app / API)", value="php"),
    app_commands.Choice(name="GitHub Actions workflow (CI/CD)", value="actions"),
])
async def autorun_slash(
    interaction: discord.Interaction,
    stack: app_commands.Choice[str] | None = None,
):
    await interaction.response.defer(thinking=True)

    try:
        stack_value = stack.value if stack else None

        async with aiohttp.ClientSession() as _setup_session:
            task, chosen_stack = await generate_auto_task(_setup_session, stack_value)
            project_slug = await generate_project_name(_setup_session, task)

        role_list = list(DEFAULT_BUILD_ROLES)
        stack_emoji = _STACK_EMOJI.get(chosen_stack, "💻")

        role_view = RoleSelectView(role_list)
        await interaction.followup.send(
            "👥 **Select team roles** *(choose any number, or wait 2 min to use defaults):*",
            view=role_view,
            ephemeral=True,
        )
        await role_view.wait()
        role_list = role_view.selected_roles

        logger.info("AutoRun | task=%r | project=%s | stack=%s", task, project_slug, chosen_stack)

        header = (
            f"🤖 **AI AutoRun — Autonomous Build Session**\n"
            f"📋 **Task:** {task}\n"
            f"📁 **Project:** `{project_slug}`\n"
            f"🛠️ **Stack:** {stack_emoji} `{chosen_stack}`\n"
            f"👥 **Team:** {', '.join(role_list)}\n"
            f"📡 *Click **✏️ Add My Input** after any role to steer the discussion.*\n\n"
            "*Team discussion starting… this may take a moment.*"
        )
        header_msg = await interaction.followup.send(header)
        thread = await _create_task_thread(header_msg, f"🤖 {project_slug}"[:100], interaction.channel)
        send = thread.send if thread else interaction.followup.send

        async def _autorun_role_cb(role: str, reply: str) -> Optional[str]:
            logger.info("AutoRun interactive: posting role %r response", role)
            role_idx = role_list.index(role)
            msg = f"👤 **{role}** {_prior_context_note(role_idx)}\n{reply}"
            for chunk in split_message(msg):
                await send(chunk)
            remaining = role_list[role_idx + 1:]
            if remaining:
                view = InterruptView()
                prompt_msg = await send(
                    f"*Next: **{remaining[0]}** — continuing in 90 s…*  "
                    "Want to add your input first?",
                    view=view,
                )
                view._message = prompt_msg
                logger.info("AutoRun interactive: waiting for user input before %r", remaining[0])
                await view.wait()
                if view.action == "input" and view.user_input:
                    preview = view.user_input[:80] + "…" if len(view.user_input) > 80 else view.user_input
                    await send(f"✅ *Your input noted: \"{preview}\"*")
                    return view.user_input
            return None

        discussion, final_outcome = await run_company_discussion(task, role_list, role_done_cb=_autorun_role_cb)

        for chunk in split_message(f"---\n✅ **Final Plan**\n\n{final_outcome}"):
            await send(chunk)

        # Generate code with format-retry + code review
        code_files, raw_output = await generate_verified_code_files(
            task, discussion, final_outcome, send
        )

        def _store_session(code: list[tuple[str, str]]) -> None:
            session_obj: dict = {
                "task": task,
                "discussion": discussion,
                "final_outcome": final_outcome,
                "code_files": code,
                "project_slug": project_slug,
                "thread_id": thread.id if thread else None,
                "followup_history": [],
            }
            channel_id = interaction.channel_id or 0
            build_sessions[channel_id] = session_obj
            if thread:
                build_sessions[thread.id] = session_obj

        if not code_files:
            await send("⚠️ No structured code files detected. The raw output follows:")
            for chunk in split_message(raw_output or "*No output.*"):
                await send(chunk)
            _store_session([])
            await send("💬 *Use `/followup` to ask questions or request a retry.*")
            return

        files_list = "\n".join(f"• `{fn}`" for fn, _ in code_files)
        await send(f"📦 **{len(code_files)} file(s) generated:**\n{files_list}\n\n*Saving to GitHub…*")

        committed_urls, folder_url = await commit_project(project_slug, task, final_outcome, code_files)

        if committed_urls:
            url_lines = "\n".join(f"• {u}" for u in committed_urls[:20])
            extra = f"\n*(and {len(committed_urls) - 20} more)*" if len(committed_urls) > 20 else ""
            folder_line = f"\n\n📂 **Project folder:** {folder_url}" if folder_url else ""
            await send(f"✅ **Project saved to GitHub!**\n{url_lines}{extra}{folder_line}")
        elif GITHUB_TOKEN and GITHUB_REPOSITORY:
            await send("⚠️ Could not commit files to GitHub. Check bot logs for details.")
        else:
            await send(
                "ℹ️ GitHub integration not configured — files were not saved.\n"
                "Set `GITHUB_TOKEN` and `GITHUB_REPOSITORY` to enable saving."
            )

        _store_session(code_files)
        await send("💬 *AutoRun session saved. Use `/followup` to ask questions or request amendments.*")

    except Exception as exc:
        logger.error("AutoRun failed: %s", exc, exc_info=True)
        try:
            await interaction.followup.send(f"❌ AutoRun encountered an error: {exc}")
        except Exception:
            pass


@bot.tree.command(name="company_roles", description="List all available roles for /company and /build")
async def company_roles_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    lines = ["**🏢 Available Company Roles**", "", "**Default roles** (for `/company`):"]
    for role in DEFAULT_ROLES:
        lines.append(f"• `{role}`")
    lines += ["", "**Default developer team** (for `/build` and `/autorun`):"]
    for role in DEFAULT_BUILD_ROLES:
        lines.append(f"• `{role}`")
    lines += ["", "**All built-in roles:**"]
    for role, prompt in ROLE_PROMPTS.items():
        sentences = prompt.split(". ")
        focus = sentences[1].lstrip("Focus on ") if len(sentences) > 1 else ""
        lines.append(f"• `{role}` — {focus}")
    lines += [
        "",
        "**Custom roles** — supply any role name not in the list above.",
        "The bot generates a suitable system prompt automatically.",
    ]
    content = "\n".join(lines)
    for chunk in split_message(content):
        await interaction.followup.send(chunk)


# ---------------------------------------------------------------------------
# Universal /followup — context-aware continuation command
# ---------------------------------------------------------------------------


async def _do_build_followup(
    interaction: discord.Interaction,
    request: str,
    session_data: dict,
) -> None:
    """Perform a build-session follow-up.

    Uses a per-channel asyncio.Lock so that rapid successive /followup
    invocations are serialised rather than racing on the shared session.
    """
    channel_key = interaction.channel_id or 0
    lock = followup_locks.setdefault(channel_key, asyncio.Lock())

    async with lock:
        task = session_data["task"]
        discussion: list[tuple[str, str]] = session_data["discussion"]
        final_outcome: str = session_data["final_outcome"]
        code_files: list[tuple[str, str]] = session_data.get("code_files", [])
        project_slug: str = session_data.get("project_slug", "project")
        followup_history: list[dict] = session_data.setdefault("followup_history", [])

        logger.info(
            "Build follow-up #%d | project=%s | request=%r",
            len(followup_history) + 1, project_slug, request,
        )

        context = f"**Original Task:** {task}\n\n**Developer Team Discussion:**\n"
        for role, reply in discussion:
            context += f"\n**{role}:** {reply}\n"
        context += f"\n**Final Plan:**\n{final_outcome}\n"

        if code_files:
            context += "\n**Previously Generated Files:**\n"
            for filename, content in code_files:
                preview = content[:600] + "\n…(truncated)" if len(content) > 600 else content
                context += f"\n### File: {filename}\n```\n{preview}\n```\n"

        if followup_history:
            context += "\n**Previous Follow-up Conversation:**\n"
            # Include up to the last 10 exchanges for richer context
            for i, exchange in enumerate(followup_history[-10:], 1):
                context += f"\nQ{i}: {exchange['request']}\n"
                reply_preview = exchange["reply"][:500]
                if len(exchange["reply"]) > 500:
                    reply_preview += "\n…(truncated)"
                context += f"A{i}: {reply_preview}\n"

        followup_prompt = (
            f"{context}\n\n"
            f"**Follow-up Request #{len(followup_history) + 1}:** {request}\n\n"
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
                await interaction.followup.send("⚠️ AI request failed. Please try again.")
                return

        # Route to build thread when available
        thread_id = session_data.get("thread_id")
        send = interaction.followup.send
        if thread_id:
            try:
                thread_channel = bot.get_channel(thread_id) or await bot.fetch_channel(thread_id)
                # Only redirect when we know the user is in a different channel.
                # If interaction.channel_id is None (edge case), stay with followup.send.
                if interaction.channel_id is not None and interaction.channel_id != thread_channel.id:
                    send = thread_channel.send  # type: ignore[assignment]
                    await interaction.followup.send(
                        "💬 *Responding in the build thread…*", ephemeral=True
                    )
            except Exception as exc:
                logger.warning("Could not retrieve build thread %s: %s", thread_id, exc)

        followup_num = len(followup_history) + 1
        await send(f"💬 **Follow-up #{followup_num}:** {request[:120]}")
        for chunk in split_message(reply):
            await send(chunk)

        followup_history.append({"request": request, "reply": reply})

        amended_files = parse_code_files(reply)
        if amended_files:
            existing = dict(code_files)
            for fn, content in amended_files:
                existing[fn] = content
            session_data["code_files"] = list(existing.items())

            if GITHUB_TOKEN and GITHUB_REPOSITORY:
                await send(f"📝 *{len(amended_files)} file(s) amended. Saving to GitHub…*")
                committed_urls, _ = await commit_project(project_slug, task, final_outcome, amended_files)
                if committed_urls:
                    url_lines = "\n".join(f"• {u}" for u in committed_urls[:10])
                    extra = f"\n*(and {len(committed_urls) - 10} more)*" if len(committed_urls) > 10 else ""
                    await send(f"✅ **Amendments saved to GitHub:**\n{url_lines}{extra}")
                else:
                    await send("⚠️ Could not commit amended files to GitHub.")
            else:
                files_list = "\n".join(f"• `{fn}`" for fn, _ in amended_files)
                await send(
                    f"📝 *{len(amended_files)} file(s) included above:*\n{files_list}\n"
                    "*(GitHub integration not configured — files not saved automatically.)*"
                )


@bot.tree.command(
    name="followup",
    description="Steer an active AI stream, amend a build session, or continue the chat conversation",
)
@app_commands.describe(
    request="Your question, amendment request, or perspective for the AI"
)
async def followup_slash(interaction: discord.Interaction, request: str):
    await interaction.response.defer(thinking=True)

    # ── Priority 1: cancel any active streaming request and redirect it ────
    existing_task = active_requests.pop(interaction.user.id, None)
    if existing_task and not existing_task.done():
        existing_task.cancel()

        history_key = interaction.channel_id if interaction.channel_id is not None else interaction.user.id
        history = conversation_history.get(history_key, [])
        preferred = user_preferred_models.get(interaction.user.id)

        if len(request) > 80:
            cut = request[:80].rsplit(None, 1)[0] if " " in request[:80] else request[:80]
            preview = cut + "…"
        else:
            preview = request

        placeholder_msg = await interaction.followup.send(
            f"✏️ *Previous request cancelled — redirecting: \"{preview}\"…* ▌"
        )

        async def _progress_redirect(text: str) -> None:
            display = text[-STREAM_DISPLAY_LIMIT:] + "▌" if len(text) > STREAM_DISPLAY_LIMIT else text + "▌"
            try:
                await placeholder_msg.edit(content=display)
            except discord.HTTPException:
                pass

        new_task = asyncio.create_task(
            get_ai_reply_streaming(request, preferred, history=history, progress_cb=_progress_redirect)
        )
        active_requests[interaction.user.id] = new_task
        try:
            reply, model_used, is_fallback = await new_task
        except asyncio.CancelledError:
            await placeholder_msg.edit(content="⛔ Interrupted.")
            return
        finally:
            active_requests.pop(interaction.user.id, None)

        if model_used:
            _update_history(history_key, request, reply)
        display_reply = reply + _fallback_footer(model_used, preferred, is_fallback)
        header = f"✏️ *Redirected based on: \"{preview}\"*\n\n"
        chunks = split_message(header + display_reply)
        await placeholder_msg.edit(content=chunks[0])
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)
        return

    # ── Priority 2: active build session → build follow-up ─────────────────
    channel_id = interaction.channel_id or 0
    session_data = build_sessions.get(channel_id)
    if not session_data:
        ch = interaction.channel
        if isinstance(ch, discord.Thread) and ch.parent_id:
            session_data = build_sessions.get(ch.parent_id)

    if session_data:
        await _do_build_followup(interaction, request, session_data)
        return

    # ── Priority 3: no active request, no build session → general chat ─────
    history_key = interaction.channel_id if interaction.channel_id is not None else interaction.user.id
    history = conversation_history.get(history_key, [])
    preferred = user_preferred_models.get(interaction.user.id)

    placeholder_msg = await interaction.followup.send("▌")

    async def _on_progress(text: str) -> None:
        display = text[-STREAM_DISPLAY_LIMIT:] + "▌" if len(text) > STREAM_DISPLAY_LIMIT else text + "▌"
        try:
            await placeholder_msg.edit(content=display)
        except discord.HTTPException:
            pass

    t = asyncio.create_task(
        get_ai_reply_streaming(request, preferred, history=history, progress_cb=_on_progress)
    )
    active_requests[interaction.user.id] = t
    try:
        reply, model_used, is_fallback = await t
    except asyncio.CancelledError:
        await placeholder_msg.edit(content="⛔ Request cancelled.")
        return
    finally:
        active_requests.pop(interaction.user.id, None)

    if model_used:
        _update_history(history_key, request, reply)
    display_reply = reply + _fallback_footer(model_used, preferred, is_fallback)
    chunks = split_message(display_reply)
    await placeholder_msg.edit(content=chunks[0])
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk)


# ---------------------------------------------------------------------------
# Weather slash command
# ---------------------------------------------------------------------------


@bot.tree.command(
    name="weather",
    description="Get current Hong Kong weather and AI clothing suggestions",
)
async def weather_slash(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    weather = await fetch_hk_weather()
    if not weather:
        await interaction.followup.send(
            "⚠️ Could not fetch current weather data from HKO. Please try again later.\n"
            f"*(Source: <{HKO_RSS_URL}>)*"
        )
        return

    suggestion = await get_weather_clothing_suggestion(weather)
    msg = _build_weather_message(weather, suggestion)
    for chunk in split_message(msg):
        await interaction.followup.send(chunk)


# ---------------------------------------------------------------------------
# Unified /about
# ---------------------------------------------------------------------------


def _build_about_message() -> str:
    default_roles_str = ", ".join(DEFAULT_ROLES)
    build_roles_str = ", ".join(DEFAULT_BUILD_ROLES)
    return (
        "**🤖 Unified AI Bot — How to Use**\n\n"
        "**💬 General Chat**\n"
        "Mention me in any channel, send a DM, or just reply in a thread I started — "
        "no need to re-mention me for follow-up messages.\n"
        "Prefix with `@<model>` to pick a model, or `@about` to show this guide.\n\n"
        "**⚡ Chat Slash Commands**\n"
        "• `/ask question:[…] model:[optional]` — Ask a question with streaming\n"
        "• `/cancel` — Cancel your in-progress request\n"
        "• `/models` — List available AI models\n"
        "• `/settings model:[optional]` — View or set your preferred model\n\n"
        "**🏢 AI Company / Build**\n"
        "• `/company task:[…]` — Multi-role company discussion\n"
        "• `/company task:[…] roles:[CEO,CTO,…] interactive:True` — Interactive mode\n"
        "• `/build task:[…]` — Dev team discussion + code gen → saved to `project/`\n"
        "• `/build task:[…] roles:[…] interactive:True` — Interactive build\n"
        "• `/autorun` — AI picks a task and builds it end-to-end\n"
        "• `/company_roles` — List available roles\n\n"
        "**🔄 Code Review** (automatic after `/build`/`/autorun`)\n"
        "A reviewer AI checks code and regenerates with feedback (up to 2 rounds). "
        "Output not using `### File:` format is retried up to 3 times.\n\n"
        "**🌤️ Weather**\n"
        "• `/weather` — Current HK weather (HKO) + AI clothing suggestions\n"
        "Auto-reminders: set `WEATHER_CHANNEL_ID` and `WEATHER_REMINDER_HOURS` env vars.\n\n"
        "**🔗 `/followup`** — works in any context:\n"
        "1. Active stream → cancel & redirect to new topic\n"
        "2. After `/build`/`/autorun` → amend code or ask questions "
        "(supports unlimited chained follow-ups; each one has full prior context)\n"
        "3. Otherwise → continue general chat conversation\n\n"
        f"**👥 Default Company Roles:** {default_roles_str}\n"
        f"**🛠️ Default Dev Team:** {build_roles_str}\n\n"
        "**💡 Examples**\n"
        "```\n"
        "/ask question:Explain async/await in Python\n"
        "/company task:Build a food delivery app\n"
        "/build task:REST API for a todo app interactive:True\n"
        "/autorun stack:python\n"
        "/followup request:Add JWT authentication\n"
        "/followup request:Now add rate limiting\n"
        "/followup request:Can you write unit tests?\n"
        "/weather\n"
        "```"
    )


@bot.tree.command(name="about", description="Show a guide for all bot features")
async def about_slash(interaction: discord.Interaction):
    msg = _build_about_message()
    chunks = split_message(msg)
    await interaction.response.send_message(chunks[0])
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk)


# ---------------------------------------------------------------------------
# Weather auto-reminder background task
# ---------------------------------------------------------------------------


@tasks.loop(minutes=30)
async def weather_reminder_task() -> None:
    """Post an auto weather reminder to the configured channel.

    Runs every 30 minutes; sends at most once per configured HKT hour to avoid
    double-posting when the 30-minute tick straddles an hour boundary.
    """
    if not WEATHER_CHANNEL_ID or not WEATHER_REMINDER_HOURS:
        return

    hkt_now = datetime.datetime.now(_HKT)
    if hkt_now.hour not in WEATHER_REMINDER_HOURS:
        return

    current_key = (hkt_now.toordinal(), hkt_now.hour)
    if current_key in _weather_sent_hours:
        return

    # Mark as sent *before* the network call to avoid a second post if the
    # task fires again while the API request is still in flight.
    _weather_sent_hours.add(current_key)

    # Prune entries older than 2 days to avoid unbounded growth.
    cutoff = hkt_now.toordinal() - 2
    for key in list(_weather_sent_hours):
        if key[0] < cutoff:
            _weather_sent_hours.discard(key)

    channel = bot.get_channel(WEATHER_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(WEATHER_CHANNEL_ID)
        except Exception as exc:
            logger.warning("Weather reminder: channel %s not found: %s", WEATHER_CHANNEL_ID, exc)
            return

    weather = await fetch_hk_weather()
    if not weather:
        logger.warning("Weather reminder: could not fetch HKO data — skipping this round")
        return

    suggestion = await get_weather_clothing_suggestion(weather)
    header = f"⏰ **今日天氣提醒 / Weather Reminder — Hong Kong** ({hkt_now.strftime('%H:%M')} HKT)"
    msg = _build_weather_message(weather, suggestion, header=header)

    try:
        for chunk in split_message(msg):
            await channel.send(chunk)
        logger.info("Weather reminder sent to channel %s", WEATHER_CHANNEL_ID)
    except Exception as exc:
        logger.warning("Weather reminder: failed to send message: %s", exc)


@weather_reminder_task.before_loop
async def before_weather_reminder():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    if not DISCORD_TOKEN:
        logger.error(
            "DISCORD_TOKEN (or DISCORD_TOKEN_COMPANY) is not set. "
            "Add it as an environment variable before starting the bot."
        )
        raise SystemExit(1)
    if not POLLINATIONS_TOKEN:
        logger.error(
            "POLLINATIONS_TOKEN is not set. "
            "Add it as an environment variable before starting the bot."
        )
        raise SystemExit(1)
    try:
        bot.run(DISCORD_TOKEN)
    except discord.errors.LoginFailure as exc:
        logger.error("Failed to log in to Discord: %s", exc)
        raise SystemExit(1) from exc
    except discord.errors.PrivilegedIntentsRequired as exc:
        logger.error(
            "The bot requires the 'Message Content' privileged intent, which has not been "
            "enabled in the Discord Developer Portal. "
            "Go to https://discord.com/developers/applications/, open your application, "
            "navigate to the 'Bot' page, and enable 'Message Content Intent' under "
            "'Privileged Gateway Intents', then restart the bot."
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
