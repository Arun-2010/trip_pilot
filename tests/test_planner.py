from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from models import FlightOption, HotelOption, TripRequest
from tools.planner import build_options, format_itinerary, format_quote, inr, split_message

START = date.today() + timedelta(days=30)


def trip(budget: int = 60000, adults: int = 4) -> TripRequest:
    return TripRequest(origin="HYD", destination="GOI,GOX", depart_date=START,
                       return_date=START + timedelta(days=3), adults=adults, budget_inr=budget)


def flight(fid: str, price: int, stops: int = 0) -> FlightOption:
    return FlightOption(id=fid, airline="IndiGo", flight_numbers="6E 123", depart_time="06:00",
                        arrive_time="07:15", duration_min=75, stops=stops, price_per_person=price)


def hotel(hid: str, price: int, rating: float) -> HotelOption:
    return HotelOption(id=hid, name=f"Hotel {hid}", rating=rating, price_per_night=price)


def test_inr_uses_indian_grouping():
    assert inr(58400) == "₹58,400"
    assert inr(158400) == "₹1,58,400"
    assert inr(950) == "₹950"


def test_trip_defaults_rooms_and_nights():
    t = trip(adults=5)
    assert t.rooms == 3
    assert t.nights == 3


def test_trip_rejects_past_dates():
    with pytest.raises(ValidationError):
        TripRequest(origin="HYD", destination="GOI", depart_date=date(2020, 1, 1),
                    return_date=date(2020, 1, 4), adults=2, budget_inr=10000)


def test_costs_are_computed_in_python():
    quote = build_options(trip(), [flight("F1", 8000)], [hotel("H1", 2000, 4.1)])
    opt = quote.options[0]
    assert opt.flight_cost == 32000  # 8000 x 4 adults
    assert opt.hotel_cost == 12000  # 2000 x 3 nights x 2 rooms
    assert opt.total == 44000
    assert opt.within_budget


def test_builds_three_distinct_options_within_budget():
    flights = [flight("F1", 7000), flight("F2", 9000, stops=1)]
    hotels = [hotel("H1", 1500, 3.6), hotel("H2", 2000, 4.3), hotel("H3", 2500, 4.7)]
    quote = build_options(trip(60000), flights, hotels)
    assert quote.fits_budget
    assert [o.label for o in quote.options] == ["A", "B", "C"]
    assert {o.kind for o in quote.options} == {"Cheapest", "Best value", "Comfort"}
    assert len({o.hotel.id for o in quote.options}) == 3
    assert all(o.total <= 60000 for o in quote.options)


def test_over_budget_returns_closest_with_gap():
    quote = build_options(trip(20000), [flight("F1", 7000)], [hotel("H1", 2000, 4.0)])
    assert not quote.fits_budget
    (opt,) = quote.options
    assert opt.kind == "Closest"
    assert opt.over_by == 40000 - 20000
    assert "over budget" in format_quote(quote)


def test_itinerary_contains_required_parts():
    t = trip()
    opt = build_options(t, [flight("F1", 7000)], [hotel("H1", 2000, 4.5)]).options[0]
    text = format_itinerary(t, opt, None, flights_link="https://example.com")
    for part in ("4 adult", "Hotel H1", "Grand total", "₹40,000", "may change"):
        assert part in text


def test_split_message_keeps_chunks_under_limit():
    text = "\n\n".join(["x" * 400] * 6)
    chunks = split_message(text, limit=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
