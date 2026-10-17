"""search_hotels via SerpAPI google_hotels, trimmed for the LLM."""

from __future__ import annotations

from typing import Any

from models import HotelOption
from tools.serpapi import search

MAX_RESULTS = 5
MIN_RATING = 3.5
MIN_REVIEWS = 50  # filters out one-off holiday-rental listings


def _location(raw: dict[str, Any]) -> str:
    for place in raw.get("nearby_places") or []:
        name = place.get("name", "")
        if name and "airport" not in name.lower():
            return f"near {name}"
    description = raw.get("description") or ""
    return description if len(description) <= 80 else description[:80].rsplit(" ", 1)[0] + "…"


def _trim(raw: dict[str, Any]) -> HotelOption | None:
    price = (raw.get("rate_per_night") or {}).get("extracted_lowest")
    if not raw.get("name") or not isinstance(price, (int, float)):
        return None
    if raw.get("type", "hotel") != "hotel":
        return None
    if (raw.get("overall_rating") or 0) < MIN_RATING or (raw.get("reviews") or 0) < MIN_REVIEWS:
        return None
    return HotelOption(
        id="",
        name=raw["name"],
        rating=raw.get("overall_rating"),
        reviews=raw.get("reviews"),
        hotel_class=raw.get("hotel_class", ""),
        price_per_night=int(price),
        location=_location(raw),
        link=raw.get("link", ""),
    )


def search_hotels(location: str, check_in: str, check_out: str, adults_per_room: int, preference: str = "") -> list[HotelOption]:
    """Return a few well-rated hotels, price per room per night in INR."""
    query = f"{preference} hotels in {location}".strip() if preference else f"hotels in {location}"
    data = search({
        "engine": "google_hotels",
        "q": query,
        "check_in_date": check_in,
        "check_out_date": check_out,
        "adults": adults_per_room,
        "currency": "INR",
        "gl": "in",
        "hl": "en",
    })
    # Keep the first few that pass the filters (Google's own relevance order).
    hotels = [h for raw in data.get("properties") or [] if (h := _trim(raw)) is not None][:MAX_RESULTS]
    for i, hotel in enumerate(hotels, start=1):
        hotel.id = f"H{i}"
    return hotels
