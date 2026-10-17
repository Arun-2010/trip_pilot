"""Bonus: demo booking of the chosen flight (no real ticket, no payment).

BOOKING_PROVIDER picks the backend:
- "simulated" (default): creates a local booking reference. Real booking APIs need business
  accreditation, so this keeps the demo reliable.
- "duffel": Duffel TEST mode. Its test environment only sells fictional "Duffel Airways"
  flights, so we book the cheapest test offer on the same route and dates.
"""

from __future__ import annotations

import logging
import secrets
import string
import time
from typing import Any

import requests

import config

log = logging.getLogger("trippilot.booking")

DUFFEL_URL = "https://api.duffel.com"
TIMEOUT_S = 60


class BookingError(Exception):
    pass


def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    key = config.require("DUFFEL_API_KEY")
    if not key.startswith("duffel_test_"):
        raise BookingError("Refusing to book: DUFFEL_API_KEY must be a test-mode key (duffel_test_...)")
    try:
        response = requests.post(
            f"{DUFFEL_URL}{path}",
            json={"data": body},
            headers={
                "Authorization": f"Bearer {key}",
                "Duffel-Version": "v2",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as exc:
        raise BookingError(f"Booking service unreachable: {exc.__class__.__name__}") from exc
    data = response.json() if response.content else {}
    if response.status_code >= 400:
        errors = data.get("errors") or [{}]
        raise BookingError(f"Booking failed: {errors[0].get('message', response.status_code)}")
    return data["data"]


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0], parts[0]
    return " ".join(parts[:-1]), parts[-1]


def book_flight(origin: str, destination: str, depart_date: str, return_date: str, passenger_names: list[str]) -> str:
    """Book with the configured provider and return the booking reference."""
    provider = config.get("BOOKING_PROVIDER", "simulated").lower()
    if provider == "duffel":
        return _book_with_duffel(origin, destination, depart_date, return_date, passenger_names)
    return _book_simulated(origin, destination, depart_date, return_date, passenger_names)


def _book_simulated(origin: str, destination: str, depart_date: str, return_date: str, passenger_names: list[str]) -> str:
    alphabet = string.ascii_uppercase + string.digits
    ref = "TP-" + "".join(secrets.choice(alphabet) for _ in range(6))
    log.info("simulated booking %s: %s→%s %s/%s for %s", ref, origin, destination, depart_date, return_date, passenger_names)
    return ref


def _book_with_duffel(origin: str, destination: str, depart_date: str, return_date: str, passenger_names: list[str]) -> str:
    started = time.perf_counter()
    offer_request = _post(
        "/air/offer_requests?return_offers=true",
        {
            "slices": [
                {"origin": origin, "destination": destination, "departure_date": depart_date},
                {"origin": destination, "destination": origin, "departure_date": return_date},
            ],
            "passengers": [{"type": "adult"} for _ in passenger_names],
            "cabin_class": "economy",
        },
    )
    offers = offer_request.get("offers") or []
    if not offers:
        raise BookingError("No test-mode offers for this route")
    offer = min(offers, key=lambda o: float(o["total_amount"]))

    passengers = []
    for i, (slot, name) in enumerate(zip(offer_request["passengers"], passenger_names)):
        given, family = _split_name(name)
        # Test mode needs full passenger details; these placeholders are fine there.
        passengers.append({
            "id": slot["id"],
            "given_name": given,
            "family_name": family,
            "title": "mr",
            "gender": "m",
            "born_on": "1995-01-01",
            "email": f"traveller{i + 1}@example.com",
            "phone_number": "+919999999999",
        })

    order = _post(
        "/air/orders",
        {
            "type": "instant",
            "selected_offers": [offer["id"]],
            "passengers": passengers,
            "payments": [{"type": "balance", "currency": offer["total_currency"], "amount": offer["total_amount"]}],
        },
    )
    log.info("duffel test order %s in %.1fs", order.get("booking_reference"), time.perf_counter() - started)
    return order["booking_reference"]
