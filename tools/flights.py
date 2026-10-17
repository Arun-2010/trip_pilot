"""search_flights via SerpAPI google_flights, trimmed for the LLM."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from models import FlightLeg, FlightOption
from tools.serpapi import search

MAX_RESULTS = 5

# Fallback for when the LLM passes a city name instead of an IATA code.
CITY_TO_AIRPORT = {
    "hyderabad": "HYD", "bangalore": "BLR", "bengaluru": "BLR", "mumbai": "BOM",
    "bombay": "BOM", "delhi": "DEL", "new delhi": "DEL", "chennai": "MAA",
    "kolkata": "CCU", "pune": "PNQ", "ahmedabad": "AMD", "kochi": "COK",
    "cochin": "COK", "jaipur": "JAI", "goa": "GOI,GOX", "lucknow": "LKO",
    "chandigarh": "IXC", "visakhapatnam": "VTZ", "vizag": "VTZ", "srinagar": "SXR",
    "port blair": "IXZ", "andaman": "IXZ", "udaipur": "UDR", "varanasi": "VNS",
}


def to_airport_code(place: str) -> str:
    cleaned = place.strip()
    return CITY_TO_AIRPORT.get(cleaned.lower(), cleaned.upper().replace(" ", ""))


def _base_params(origin: str, destination: str, depart_date: str, return_date: str) -> dict[str, Any]:
    # adults=1 so the price is unambiguously per person; planner multiplies by group size.
    return {
        "engine": "google_flights",
        "departure_id": to_airport_code(origin),
        "arrival_id": to_airport_code(destination),
        "outbound_date": depart_date,
        "return_date": return_date,
        "type": "1",  # round trip
        "adults": 1,
        "currency": "INR",
        "gl": "in",
        "hl": "en",
    }


def _clock(timestamp: str) -> str:
    # SerpAPI gives "2025-11-14 06:05"; turn it into "Fri 14 Nov, 06:05".
    try:
        return datetime.strptime(timestamp, "%Y-%m-%d %H:%M").strftime("%a %d %b, %H:%M")
    except ValueError:
        return timestamp


def _trim(raw: dict[str, Any], index: int) -> FlightOption | None:
    legs = raw.get("flights") or []
    price = raw.get("price")
    if not legs or not isinstance(price, (int, float)):
        return None
    first, last = legs[0], legs[-1]
    trimmed_legs = [
        FlightLeg(
            airline=leg.get("airline", ""),
            flight_number=leg.get("flight_number", ""),
            from_airport=leg.get("departure_airport", {}).get("id", ""),
            to_airport=leg.get("arrival_airport", {}).get("id", ""),
            depart_time=_clock(leg.get("departure_airport", {}).get("time", "")),
            arrive_time=_clock(leg.get("arrival_airport", {}).get("time", "")),
        )
        for leg in legs
    ]
    airlines = sorted({leg.airline for leg in trimmed_legs if leg.airline})
    return FlightOption(
        id=f"F{index}",
        airline=" + ".join(airlines),
        flight_numbers=", ".join(leg.flight_number for leg in trimmed_legs),
        depart_time=_clock(first.get("departure_airport", {}).get("time", "")),
        arrive_time=_clock(last.get("arrival_airport", {}).get("time", "")),
        duration_min=int(raw.get("total_duration") or 0),
        stops=len(legs) - 1,
        price_per_person=int(price),
        legs=trimmed_legs,
        departure_token=raw.get("departure_token", ""),
    )


def search_flights(origin: str, destination: str, depart_date: str, return_date: str) -> tuple[list[FlightOption], dict[str, Any]]:
    """Return the cheapest few round-trip options (outbound details) and the search params used."""
    params = _base_params(origin, destination, depart_date, return_date)
    data = search(params)
    raw_options = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    options = [opt for i, raw in enumerate(raw_options) if (opt := _trim(raw, i)) is not None]
    options.sort(key=lambda f: f.price_per_person)
    for i, option in enumerate(options[:MAX_RESULTS], start=1):
        option.id = f"F{i}"
    params["google_flights_url"] = data.get("search_metadata", {}).get("google_flights_url", "")
    return options[:MAX_RESULTS], params


def fetch_return_flight(search_params: dict[str, Any], outbound: FlightOption) -> FlightOption | None:
    """Google Flights shows the return leg only after an outbound is chosen (departure_token)."""
    if not outbound.departure_token:
        return None
    params = {k: v for k, v in search_params.items() if k != "google_flights_url"}
    params["departure_token"] = outbound.departure_token
    data = search(params)
    raw_options = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    options = [opt for i, raw in enumerate(raw_options) if (opt := _trim(raw, i)) is not None]
    if not options:
        return None
    # Prefer the return flight that matches the quoted round-trip price.
    same_price = [o for o in options if o.price_per_person == outbound.price_per_person]
    return (same_price or sorted(options, key=lambda o: o.price_per_person))[0]
