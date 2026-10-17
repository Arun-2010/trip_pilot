"""Runs the tool layer end to end against fake SerpAPI responses (no API keys needed)."""

from datetime import date, timedelta

import tools.flights
import tools.hotels
from memory import Session
import tools.pdf
from tools import run_tool

DEPART = (date.today() + timedelta(days=30)).isoformat()
RETURN = (date.today() + timedelta(days=33)).isoformat()


def fake_flight(price: int, number: str) -> dict:
    return {
        "flights": [{
            "airline": "IndiGo", "flight_number": number,
            "departure_airport": {"id": "HYD", "time": f"{DEPART} 06:00"},
            "arrival_airport": {"id": "GOI", "time": f"{DEPART} 07:15"},
        }],
        "total_duration": 75, "price": price, "departure_token": f"tok-{number}",
    }


FLIGHTS_RESPONSE = {
    "best_flights": [fake_flight(9000, "6E 2"), fake_flight(7000, "6E 1")],
    "other_flights": [{"flights": [], "price": 1}],  # malformed, should be skipped
    "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights"},
}
HOTELS_RESPONSE = {
    "properties": [
        {"type": "hotel", "name": "Beach Inn", "overall_rating": 4.2, "reviews": 900, "rate_per_night": {"extracted_lowest": 2500},
         "nearby_places": [{"name": "Goa International Airport"}, {"name": "Calangute Beach"}], "link": "https://example.com/inn"},
        {"type": "hotel", "name": "Budget Stay", "overall_rating": 3.8, "reviews": 300, "rate_per_night": {"extracted_lowest": 1500}},
        {"type": "hotel", "name": "No Price Resort", "overall_rating": 4.9, "reviews": 500},
        {"type": "hotel", "name": "Bad Place", "overall_rating": 2.1, "reviews": 500, "rate_per_night": {"extracted_lowest": 500}},
        {"type": "vacation rental", "name": "Some Villa", "overall_rating": 4.8, "reviews": 90, "rate_per_night": {"extracted_lowest": 900}},
        {"type": "hotel", "name": "Brand New Hotel", "overall_rating": 5.0, "reviews": 3, "rate_per_night": {"extracted_lowest": 1000}},
    ]
}


def fake_search(params: dict) -> dict:
    if params["engine"] == "google_hotels":
        return HOTELS_RESPONSE
    if "departure_token" in params:  # return-leg lookup
        return {"best_flights": [fake_flight(7000, "6E 9")]}
    return FLIGHTS_RESPONSE


def test_full_tool_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(tools.pdf, "PDF_DIR", tmp_path)
    monkeypatch.setattr(tools.flights, "search", fake_search)
    monkeypatch.setattr(tools.hotels, "search", fake_search)
    session = Session()

    flights = run_tool(session, "search_flights", {"origin": "hyderabad", "destination": "GOI,GOX",
                                                   "depart_date": DEPART, "return_date": RETURN})
    assert [f["price_per_person"] for f in flights["flights"]] == [7000, 9000]
    assert session.flight_search["departure_id"] == "HYD"

    hotels = run_tool(session, "search_hotels", {"location": "Goa", "check_in": DEPART,
                                                 "check_out": RETURN, "adults": 4, "preference": "near beach"})
    assert [h["name"] for h in hotels["hotels"]] == ["Beach Inn", "Budget Stay"]
    assert hotels["hotels"][0]["location"] == "near Calangute Beach"  # airport skipped

    quote = run_tool(session, "build_quote", {"adults": 4, "budget_inr": 60000})
    assert quote["fits_budget"]
    assert "Option A" in quote["message"]

    itinerary = run_tool(session, "build_itinerary", {"option_label": "a"})
    assert "6E 9" in itinerary["message"]  # return flight fetched via departure_token
    assert session.chosen is not None

    monkeypatch.setenv("BOOKING_PROVIDER", "simulated")
    assert "error" in run_tool(session, "book_flight", {"passenger_names": ["Only One"]})
    booked = run_tool(session, "book_flight", {"passenger_names": ["A B", "C D", "E F", "G H"]})
    assert booked["booking_reference"].startswith("TP-")
    assert session.outbox_files == [f"{booked['booking_reference']}.pdf"]
    assert (tmp_path / session.outbox_files[0]).read_bytes().startswith(b"%PDF")

    session.outbox_files.clear()
    assert "pdf" in run_tool(session, "send_booking_pdf", {})
    assert len(session.outbox_files) == 1


def test_errors_come_back_as_dicts():
    session = Session()
    assert "error" in run_tool(session, "build_quote", {"adults": 2, "budget_inr": 1000})
    assert "error" in run_tool(session, "nope", {})
    assert "error" in run_tool(session, "build_itinerary", {})
