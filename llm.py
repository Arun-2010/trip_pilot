"""The ONLY file that talks to Gemini. Swap providers by rewriting this file."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import errors, types

import config

log = logging.getLogger("trippilot.llm")

TIMEOUT_MS = 60_000
RATE_LIMIT_RETRIES = 3
MAX_RETRY_WAIT_S = 60

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=config.require("GEMINI_API_KEY"),
            http_options=types.HttpOptions(timeout=TIMEOUT_MS),
        )
    return _client


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class LLMReply:
    text: str
    tool_calls: list[ToolCall]
    raw_content: Any  # the model's turn, appended to history as-is (keeps thought signatures)


def user_message(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def model_message(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text)])


def tool_results_message(results: list[tuple[str, dict[str, Any]]]) -> types.Content:
    parts = [types.Part.from_function_response(name=name, response=result) for name, result in results]
    return types.Content(role="user", parts=parts)


def generate(system_prompt: str, history: list[Any], tools: list[dict[str, Any]]) -> LLMReply:
    """Send the conversation to Gemini and return its text and/or tool calls."""
    declarations = [
        types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters_json_schema=tool["parameters"],
        )
        for tool in tools
    ]
    request_config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[types.Tool(function_declarations=declarations)] if declarations else None,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    response = _call_with_retry(history, request_config)
    calls = [ToolCall(name=c.name or "", args=dict(c.args or {})) for c in (response.function_calls or [])]
    content = response.candidates[0].content if response.candidates else None
    parts = (content.parts if content else None) or []
    text = "".join(p.text for p in parts if p.text and not p.thought)
    if content is None:
        content = types.Content(role="model", parts=[types.Part(text=text)])
    return LLMReply(text=text, tool_calls=calls, raw_content=content)


def _call_with_retry(history: list[Any], request_config: types.GenerateContentConfig) -> types.GenerateContentResponse:
    """Wait and retry on rate limits (the free tier allows only a few calls a minute) and on
    temporary server errors like 503 "high demand"."""
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return _get_client().models.generate_content(
                model=config.require("GEMINI_MODEL"), contents=history, config=request_config,
            )
        except errors.APIError as exc:
            retryable = exc.code == 429 or (exc.code or 0) >= 500
            if not retryable or attempt == RATE_LIMIT_RETRIES:
                raise
            match = re.search(r"'retryDelay': '(\d+)s'", str(exc))
            wait = float(match.group(1)) + 1 if match else 5 * (attempt + 1)
            if wait > MAX_RETRY_WAIT_S:  # e.g. the daily quota is used up: waiting won't help
                raise
            log.warning("Gemini error %s, retrying in %.0fs (attempt %d)", exc.code, wait, attempt + 1)
            time.sleep(wait)
    raise RuntimeError("unreachable")
