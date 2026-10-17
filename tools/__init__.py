"""Tool definitions (what Gemini sees) and handlers (what actually runs).

Search results are stored on the user's Session, so the LLM never has to copy prices around:
build_quote and build_itinerary read them straight from the session.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable

from pydantic import ValidationError

from memory import Session
from models import TripRequest
from tools import booking, flights, hotels, pdf, planner
from tools.serpapi import SearchError

log = logging.getLogger("trippilot.tools")

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_flights",
        "description": "Search live round-trip flight prices on Google Flights. Returns the cheapest few options (price is per person, round trip).",
        "parameters": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "IATA code(s), e.g. HYD. Goa = GOI,GOX"},
                "destination": {"type": "string", "description": "IATA code(s), e.g. GOI,GOX"},
                "depart_date": {"type": "string", "description": "YYYY-MM-DD"},
                "return_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["origin", "destination", "depart_date", "return_date"],
        },
    },
    {
        "name": "search_hotels",
        "description": "Search live hotel prices on Google Hotels. Returns a few options with price per room per night.",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City or area, e.g. 'Goa' or 'Calangute, Goa'"},
                "check_in": {"type": "string", "description": "YYYY-MM-DD"},
                "check_out": {"type": "string", "description": "YYYY-MM-DD"},
                "adults": {"type": "integer", "description": "Total adults in the group"},
                "rooms": {"type": "integer", "description": "Rooms needed; omit to use one room per 2 adults"},
                "preference": {"type": "string", "description": "e.g. 'near beach', 'with pool'"},
            },
            "required": ["location", "check_in", "check_out", "adults"],
        },
    },
    {
        "name": "build_quote",
        "description": "Combine the latest flight and hotel search results into up to 3 options (Cheapest, Best value, Comfort) with exact costs. Call after both searches.",
        "parameters": {
            "type": "object",
            "properties": {
                "adults": {"type": "integer"},
                "children": {"type": "integer"},
                "rooms": {"type": "integer", "description": "Omit to use one room per 2 adults"},
                "budget_inr": {"type": "integer", "description": "Total budget for the whole group in INR"},
                "hotel_preference": {"type": "string"},
            },
            "required": ["adults", "budget_inr"],
        },
    },
    {
        "name": "build_itinerary",
        "description": "Create the final itinerary for the option the customer picked. Returns text to send as-is.",
        "parameters": {
            "type": "object",
            "properties": {"option_label": {"type": "string", "description": "A, B or C"}},
            "required": ["option_label"],
        },
    },
    {
        "name": "book_flight",
        "description": "DEMO booking of the chosen option's flight (no real ticket, no payment). Needs one full name per adult.",
        "parameters": {
            "type": "object",
            "properties": {
                "passenger_names": {"type": "array", "items": {"type": "string"}, "description": "Full name of each traveller"},
            },
            "required": ["passenger_names"],
        },
    },
    {
        "name": "send_booking_pdf",
        "description": "Attach the booking confirmation PDF again (only after book_flight succeeded).",
        "parameters": {"type": "object", "properties": {}},
    },
]


def _search_flights(session: Session, origin: str, destination: str, depart_date: str, return_date: str) -> dict[str, Any]:
    results, params = flights.search_flights(origin, destination, depart_date, return_date)
    session.flights, session.flight_search = results, params
    session.quote = session.chosen = None
    if not results:
        return {"error": "No flights found for these airports and dates."}
    return {"flights": [f.model_dump(exclude={"legs", "departure_token"}) for f in results]}


def _search_hotels(session: Session, location: str, check_in: str, check_out: str, adults: int,
                   rooms: int | None = None, preference: str = "") -> dict[str, Any]:
    rooms = rooms or math.ceil(adults / 2)
    results = hotels.search_hotels(location, check_in, check_out, math.ceil(adults / rooms), preference)
    session.hotels = results
    session.quote = session.chosen = None
    if not results:
        return {"error": "No hotels with prices found. Try a broader location."}
    return {"hotels": [h.model_dump(exclude={"link"}) for h in results]}


def _build_quote(session: Session, adults: int, budget_inr: int, children: int = 0,
                 rooms: int | None = None, hotel_preference: str = "") -> dict[str, Any]:
    if not session.flights or not session.hotels:
        return {"error": "Run search_flights and search_hotels first."}
    params = session.flight_search
    trip = TripRequest(
        origin=params["departure_id"],
        destination=params["arrival_id"],
        depart_date=params["outbound_date"],
        return_date=params["return_date"],
        adults=adults,
        children=children,
        rooms=rooms,
        budget_inr=budget_inr,
        hotel_preference=hotel_preference,
    )
    session.quote = planner.build_options(trip, session.flights, session.hotels)
    return {"message": planner.format_quote(session.quote), "fits_budget": session.quote.fits_budget}


def _build_itinerary(session: Session, option_label: str) -> dict[str, Any]:
    if session.quote is None:
        return {"error": "No quote yet. Build a quote first."}
    label = option_label.strip().upper()[:1]
    option = next((o for o in session.quote.options if o.label == label), None)
    if option is None:
        return {"error": f"There is no option {option_label}. Valid: {[o.label for o in session.quote.options]}"}
    session.chosen = option
    try:
        return_flight = flights.fetch_return_flight(session.flight_search, option.flight)
    except SearchError:
        return_flight = None  # itinerary still works; return details come from the booking link
    session.return_flight = return_flight
    text = planner.format_itinerary(
        session.quote.trip, option, return_flight,
        flights_link=session.flight_search.get("google_flights_url", ""),
        booking_ref=session.booking_ref,
    )
    return {"message": text}


def _book_flight(session: Session, passenger_names: list[str]) -> dict[str, Any]:
    if session.chosen is None or session.quote is None:
        return {"error": "The customer hasn't picked an option yet."}
    trip = session.quote.trip
    if len(passenger_names) != trip.adults:
        return {"error": f"Need exactly {trip.adults} passenger names, got {len(passenger_names)}."}
    # Duffel needs a single airport, so use the airport of the chosen outbound flight.
    legs = session.chosen.flight.legs
    origin = legs[0].from_airport if legs else trip.origin.split(",")[0]
    destination = legs[-1].to_airport if legs else trip.destination.split(",")[0]
    ref = booking.book_flight(origin, destination, trip.depart_date.isoformat(), trip.return_date.isoformat(), passenger_names)
    session.booking_ref = ref
    session.passenger_names = passenger_names
    result: dict[str, Any] = {"booking_reference": ref, "note": "DEMO BOOKING: no real ticket was issued and no payment was taken."}
    try:
        pdf_path = pdf.build_booking_pdf(trip, session.chosen, session.return_flight, ref, passenger_names)
        session.outbox_files.append(pdf_path.name)
        result["pdf"] = "A PDF booking confirmation is attached to your reply automatically. Mention it."
    except Exception as exc:  # the booking itself succeeded; a missing PDF shouldn't hide that
        log.exception("PDF generation failed")
        result["pdf"] = f"PDF could not be created ({exc.__class__.__name__}); don't mention a PDF."
    return result


def _send_booking_pdf(session: Session) -> dict[str, Any]:
    if not session.booking_ref or session.chosen is None or session.quote is None:
        return {"error": "There is no booking yet, so there is no PDF to send."}
    path = pdf.build_booking_pdf(session.quote.trip, session.chosen, session.return_flight,
                                 session.booking_ref, session.passenger_names)
    session.outbox_files.append(path.name)
    return {"pdf": "The booking PDF is attached to your reply automatically."}


HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "send_booking_pdf": _send_booking_pdf,
    "search_flights": _search_flights,
    "search_hotels": _search_hotels,
    "build_quote": _build_quote,
    "build_itinerary": _build_itinerary,
    "book_flight": _book_flight,
}


def run_tool(session: Session, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run one tool. Errors come back as {"error": ...} so the LLM can explain them politely."""
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool {name}"}
    try:
        return handler(session, **args)
    except (SearchError, booking.BookingError, RuntimeError) as exc:  # RuntimeError: missing key in .env
        return {"error": str(exc)}
    except ValidationError as exc:
        return {"error": f"Invalid trip details: {exc.errors()[0]['msg']}"}
    except TypeError as exc:
        return {"error": f"Bad arguments for {name}: {exc}"}
