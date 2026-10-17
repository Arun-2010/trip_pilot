"""Budget check, option building and message formatting. All money maths lives here."""

from __future__ import annotations

from datetime import date

from models import FlightOption, HotelOption, Quote, QuoteOption, TripRequest

GOOD_RATING = 4.0
MAX_MESSAGE_CHARS = 1500
LABELS = "ABC"


def inr(amount: int) -> str:
    """Indian digit grouping: 158400 -> ₹1,58,400."""
    digits = str(abs(int(amount)))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    return f"{'-' if amount < 0 else ''}₹{digits}"


def _make_option(trip: TripRequest, flight: FlightOption, hotel: HotelOption, kind: str) -> QuoteOption:
    flight_cost = flight.price_per_person * trip.adults
    hotel_cost = hotel.price_per_night * trip.nights * (trip.rooms or 1)
    total = flight_cost + hotel_cost
    return QuoteOption(
        label="",
        kind=kind,
        flight=flight,
        hotel=hotel,
        flight_cost=flight_cost,
        hotel_cost=hotel_cost,
        total=total,
        within_budget=total <= trip.budget_inr,
        over_by=max(0, total - trip.budget_inr),
    )


def build_options(trip: TripRequest, flights: list[FlightOption], hotels: list[HotelOption]) -> Quote:
    """Pick up to 3 options: Cheapest, Best value, Comfort. Falls back to the closest one."""
    combos = [_make_option(trip, f, h, "") for f in flights for h in hotels]
    if not combos:
        return Quote(trip=trip, options=[], fits_budget=False)

    within = [c for c in combos if c.within_budget]
    if not within:
        closest = min(combos, key=lambda c: c.total).model_copy(update={"kind": "Closest", "label": "A"})
        return Quote(trip=trip, options=[closest], fits_budget=False)

    picked: list[QuoteOption] = []

    def add(candidates: list[QuoteOption], kind: str) -> None:
        used_hotels = {p.hotel.id for p in picked}
        fresh = [c for c in candidates if c.hotel.id not in used_hotels]
        if fresh:
            picked.append(fresh[0].model_copy(update={"kind": kind}))

    by_total = sorted(within, key=lambda c: c.total)
    add(by_total, "Cheapest")
    well_rated = [c for c in by_total if (c.hotel.rating or 0) >= GOOD_RATING]
    add(well_rated, "Best value")
    comfort = sorted(within, key=lambda c: (-(c.hotel.rating or 0), c.flight.stops, -c.total))
    add(comfort, "Comfort")

    picked.sort(key=lambda c: c.total)
    for label, option in zip(LABELS, picked):
        option.label = label
    return Quote(trip=trip, options=picked, fits_budget=True)


def _duration(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes else ""


def _stops(stops: int) -> str:
    return "non-stop" if stops == 0 else f"{stops} stop" + ("s" if stops > 1 else "")


def _nice_date(d: date) -> str:
    return d.strftime("%a %d %b")


def format_quote(quote: Quote) -> str:
    trip = quote.trip
    header = (
        f"{trip.adults} traveller{'s' if trip.adults > 1 else ''} · "
        f"{_nice_date(trip.depart_date)} → {_nice_date(trip.return_date)} ({trip.nights} nights) · "
        f"{trip.rooms} room{'s' if (trip.rooms or 1) > 1 else ''}\n"
        f"Budget: {inr(trip.budget_inr)}"
    )
    if not quote.options:
        return header + "\n\nSorry, I couldn't find flight + hotel combinations for these dates."

    blocks = []
    for opt in quote.options:
        rating = f"{opt.hotel.rating}★" if opt.hotel.rating else "unrated"
        blocks.append(
            f"Option {opt.label}: {opt.kind}\n"
            f"✈️ {opt.flight.airline} {opt.flight.flight_numbers}, {_stops(opt.flight.stops)}, "
            f"{_duration(opt.flight.duration_min)}\n"
            f"   Departs {opt.flight.depart_time}\n"
            f"   {inr(opt.flight.price_per_person)} × {trip.adults} = {inr(opt.flight_cost)}\n"
            f"🏨 {opt.hotel.name} ({rating})\n"
            f"   {inr(opt.hotel.price_per_night)}/night × {trip.nights} nights × {trip.rooms} room(s) = {inr(opt.hotel_cost)}\n"
            f"💰 Total: {inr(opt.total)}"
            + ("" if opt.within_budget else f" ({inr(opt.over_by)} over budget)")
        )

    note = "" if quote.fits_budget else "\n\nNothing fits the budget, so here is the closest option."
    footer = "\n\nPrices are live and may change at booking time. Reply with the option letter to continue."
    return header + note + "\n\n" + "\n\n".join(blocks) + footer


def _leg_lines(flight: FlightOption | None) -> list[str]:
    if flight is None:
        return ["   Details on the booking link below"]
    return [
        f"   {leg.airline} {leg.flight_number}: {leg.from_airport} {leg.depart_time} → {leg.to_airport} {leg.arrive_time}"
        for leg in flight.legs
    ]


def format_itinerary(
    trip: TripRequest,
    option: QuoteOption,
    return_flight: FlightOption | None,
    flights_link: str = "",
    booking_ref: str = "",
) -> str:
    lines = [
        "🧳 Your TripPilot itinerary",
        f"Travellers: {trip.adults} adult(s)" + (f", {trip.children} child(ren)" if trip.children else ""),
        f"Dates: {_nice_date(trip.depart_date)} → {_nice_date(trip.return_date)} ({trip.nights} nights)",
        "",
        "✈️ Outbound",
        *_leg_lines(option.flight),
        "✈️ Return",
        *_leg_lines(return_flight),
        "",
        f"🏨 {option.hotel.name}" + (f" ({option.hotel.rating}★)" if option.hotel.rating else ""),
    ]
    if option.hotel.location:
        lines.append(f"   {option.hotel.location}")
    lines += [
        f"   Check-in {_nice_date(trip.depart_date)}, check-out {_nice_date(trip.return_date)}, {trip.rooms} room(s)",
        "",
        "💰 Cost breakdown",
        f"   Flights: {inr(option.flight.price_per_person)} × {trip.adults} = {inr(option.flight_cost)}",
        f"   Hotel: {inr(option.hotel.price_per_night)} × {trip.nights} nights × {trip.rooms} room(s) = {inr(option.hotel_cost)}",
        f"   Grand total: {inr(option.total)}",
        "",
    ]
    if booking_ref:
        lines.append(f"✅ Demo booking reference: {booking_ref} (no real ticket, no payment)")
    else:
        if flights_link:
            lines.append(f"Book flights: {flights_link}")
        if option.hotel.link:
            lines.append(f"Book hotel: {option.hotel.link}")
        lines.append("Reply \"book it\" and I can make a demo booking.")
    lines.append("Prices are live and may change at booking time.")
    return "\n".join(lines)


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Split on blank lines so each WhatsApp message stays under the limit."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(block) > limit:  # a single huge block: hard-split it
            chunks.append(block[:limit])
            block = block[limit:]
        current = block
    if current:
        chunks.append(current)
    return chunks
