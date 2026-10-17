"""Shared SerpAPI caller with on-disk caching (free searches are limited)."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

import config

log = logging.getLogger("trippilot.serpapi")

SERPAPI_URL = "https://serpapi.com/search.json"
TIMEOUT_S = 30
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


class SearchError(Exception):
    """Raised when SerpAPI can't give us results; the message is safe to show the LLM."""


def _cache_path(params: dict[str, Any]) -> Path:
    key = json.dumps(params, sort_keys=True)
    return CACHE_DIR / f"{hashlib.sha256(key.encode()).hexdigest()[:16]}.json"


def search(params: dict[str, Any]) -> dict[str, Any]:
    """Run a SerpAPI search. Reuses a cached response when USE_CACHE=true."""
    path = _cache_path(params)
    if config.use_cache() and path.exists():
        log.info("cache hit  %s (%s)", params.get("engine"), path.name)
        return json.loads(path.read_text(encoding="utf-8"))

    started = time.perf_counter()
    try:
        response = requests.get(
            SERPAPI_URL,
            params={**params, "api_key": config.require("SERPAPI_KEY")},
            timeout=TIMEOUT_S,
        )
        data = response.json()
    except requests.RequestException as exc:
        raise SearchError(f"Price search failed: {exc.__class__.__name__}") from exc
    except ValueError as exc:
        raise SearchError("Price search returned an unreadable response") from exc

    log.info("live search %s in %.1fs", params.get("engine"), time.perf_counter() - started)
    if "error" in data:
        raise SearchError(f"Price search error: {data['error']}")

    if config.use_cache():
        CACHE_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    return data
