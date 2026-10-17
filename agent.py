"""The agent loop: history + LLM + tool calls. Used by both cli.py and main.py."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import llm
from memory import get_session
from prompts import system_prompt
from tools import TOOL_DEFINITIONS, run_tool

log = logging.getLogger("trippilot.agent")

MAX_TOOL_ROUNDS = 6
FALLBACK_REPLY = "Sorry, I'm having trouble right now. Please try again in a minute 🙏"
# These tools return a ready-to-send "message"; we send it directly instead of asking
# Gemini to repeat it. Faster, cheaper, and the numbers can't be changed by the LLM.
DIRECT_REPLY_TOOLS = {"build_quote", "build_itinerary"}

_tool_pool = ThreadPoolExecutor(max_workers=4)


def _short(value: object, limit: int = 200) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def _timed_tool(session, name: str, args: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    log.info("→ tool %s %s", name, _short(args))
    result = run_tool(session, name, args)
    log.info("← tool %s in %.1fs: %s", name, time.perf_counter() - started, _short(result))
    return result


def run(user_id: str, text: str) -> str:
    """Handle one customer message and return the reply text."""
    session = get_session(user_id)
    with session.lock:  # one message at a time per user
        history_size = len(session.history)
        session.history.append(llm.user_message(text))
        try:
            return _loop(session)
        except Exception:
            log.exception("agent failed for %s", user_id)
            del session.history[history_size:]  # don't leave half a tool exchange in the history
            return FALLBACK_REPLY


def _loop(session) -> str:
    prompt = system_prompt()
    for _ in range(MAX_TOOL_ROUNDS + 1):
        started = time.perf_counter()
        reply = llm.generate(prompt, session.history, TOOL_DEFINITIONS)
        log.info("gemini replied in %.1fs (%d tool calls)", time.perf_counter() - started, len(reply.tool_calls))
        session.history.append(reply.raw_content)

        if not reply.tool_calls:
            return reply.text.strip() or FALLBACK_REPLY

        # Run this round's tool calls in parallel (e.g. flight + hotel search together).
        results = list(_tool_pool.map(lambda call: (call.name, _timed_tool(session, call.name, call.args)), reply.tool_calls))
        session.history.append(llm.tool_results_message(results))

        direct = [r["message"] for name, r in results if name in DIRECT_REPLY_TOOLS and "message" in r]
        if direct:
            text = "\n\n".join(direct)
            session.history.append(llm.model_message(text))
            return text

    log.warning("hit the %d tool-round cap", MAX_TOOL_ROUNDS)
    return "Sorry, that took longer than expected. Could you send your request again?"
