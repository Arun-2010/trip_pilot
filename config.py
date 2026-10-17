"""Loads settings from .env once, so every module reads config the same way."""

import os

from dotenv import load_dotenv

load_dotenv()


def get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def require(name: str) -> str:
    value = get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to your .env file (see .env.example).")
    return value


def use_cache() -> bool:
    return get("USE_CACHE", "true").lower() in ("1", "true", "yes")
