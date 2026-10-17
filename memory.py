"""Per-user conversation store, kept in memory and keyed by WhatsApp number (or 'cli')."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from models import FlightOption, HotelOption, Quote, QuoteOption


@dataclass
class Session:
    history: list[Any] = field(default_factory=list)  # Gemini Content objects
    flights: list[FlightOption] = field(default_factory=list)
    flight_search: dict[str, Any] = field(default_factory=dict)  # params of the last flight search
    hotels: list[HotelOption] = field(default_factory=list)
    quote: Quote | None = None
    chosen: QuoteOption | None = None
    return_flight: FlightOption | None = None
    booking_ref: str = ""
    passenger_names: list[str] = field(default_factory=list)
    outbox_files: list[str] = field(default_factory=list)  # files to attach to the next reply
    lock: threading.Lock = field(default_factory=threading.Lock)


_sessions: dict[str, Session] = {}
_sessions_lock = threading.Lock()


def get_session(user_id: str) -> Session:
    with _sessions_lock:
        if user_id not in _sessions:
            _sessions[user_id] = Session()
        return _sessions[user_id]


def reset_session(user_id: str) -> None:
    with _sessions_lock:
        _sessions.pop(user_id, None)
