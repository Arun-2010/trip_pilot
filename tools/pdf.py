"""Booking confirmation PDF, sent as a WhatsApp attachment after a booking."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fpdf import FPDF

from models import FlightOption, QuoteOption, TripRequest
from tools.planner import inr

PDF_DIR = Path(__file__).resolve().parent.parent / "bookings"
ARIAL = Path("C:/Windows/Fonts/arial.ttf")
ARIAL_BOLD = Path("C:/Windows/Fonts/arialbd.ttf")
BRAND = (16, 94, 140)


class _Doc(FPDF):
    def __init__(self) -> None:
        super().__init__()
        if ARIAL.exists() and ARIAL_BOLD.exists():
            self.add_font("body", "", str(ARIAL))
            self.add_font("body", "B", str(ARIAL_BOLD))
            self.font_name, self.unicode = "body", True
        else:  # core fonts can't print ₹, so money falls back to "Rs."
            self.font_name, self.unicode = "Helvetica", False
        self.set_auto_page_break(True, margin=15)
        self.add_page()

    def money(self, amount: int) -> str:
        text = inr(amount)
        return text if self.unicode else text.replace("₹", "Rs. ")

    def heading(self, text: str) -> None:
        self.ln(4)
        self.set_font(self.font_name, "B", 12)
        self.set_text_color(*BRAND)
        self.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*BRAND)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)
        self.set_text_color(0, 0, 0)

    def row(self, label: str, value: str, bold: bool = False) -> None:
        if not self.unicode:
            value = value.replace("→", "->")
        self.set_font(self.font_name, "", 10)
        self.set_text_color(90, 90, 90)
        self.cell(45, 6, label)
        self.set_text_color(0, 0, 0)
        self.set_font(self.font_name, "B" if bold else "", 10)
        self.multi_cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")


def _flight_rows(doc: _Doc, title: str, flight: FlightOption | None) -> None:
    if flight is None:
        doc.row(title, "See the booking link for details")
        return
    for i, leg in enumerate(flight.legs):
        doc.row(title if i == 0 else "", f"{leg.airline} {leg.flight_number}")
        doc.row("", f"{leg.from_airport} {leg.depart_time}  →  {leg.to_airport} {leg.arrive_time}")


def build_booking_pdf(
    trip: TripRequest,
    option: QuoteOption,
    return_flight: FlightOption | None,
    booking_ref: str,
    passenger_names: list[str],
) -> Path:
    doc = _Doc()

    doc.set_font(doc.font_name, "B", 20)
    doc.set_text_color(*BRAND)
    doc.cell(0, 12, "TripPilot", new_x="LMARGIN", new_y="NEXT")
    doc.set_font(doc.font_name, "", 11)
    doc.set_text_color(0, 0, 0)
    doc.cell(0, 6, "Booking confirmation", new_x="LMARGIN", new_y="NEXT")
    doc.set_font(doc.font_name, "", 9)
    doc.set_text_color(180, 40, 40)
    doc.cell(0, 6, "DEMO BOOKING: no real ticket has been issued and no payment was taken.", new_x="LMARGIN", new_y="NEXT")

    doc.heading("Booking")
    doc.row("Reference", booking_ref, bold=True)
    doc.row("Issued", datetime.now().strftime("%d %b %Y, %H:%M"))
    doc.row("Dates", f"{trip.depart_date:%a %d %b %Y} → {trip.return_date:%a %d %b %Y} ({trip.nights} nights)")

    doc.heading("Travellers")
    for i, name in enumerate(passenger_names, start=1):
        doc.row(f"Traveller {i}", name)

    doc.heading("Flights")
    _flight_rows(doc, "Outbound", option.flight)
    doc.ln(2)
    _flight_rows(doc, "Return", return_flight)

    doc.heading("Hotel")
    doc.row("Hotel", option.hotel.name + (f"  (rated {option.hotel.rating}/5)" if option.hotel.rating else ""))
    if option.hotel.location:
        doc.row("Area", option.hotel.location)
    doc.row("Check-in / out", f"{trip.depart_date:%a %d %b} → {trip.return_date:%a %d %b}")
    doc.row("Rooms", str(trip.rooms))

    doc.heading("Cost breakdown")
    doc.row("Flights", f"{doc.money(option.flight.price_per_person)} × {trip.adults} = {doc.money(option.flight_cost)}")
    doc.row("Hotel", f"{doc.money(option.hotel.price_per_night)} × {trip.nights} nights × {trip.rooms} room(s) = {doc.money(option.hotel_cost)}")
    doc.row("Grand total", doc.money(option.total), bold=True)

    doc.ln(6)
    doc.set_font(doc.font_name, "", 8)
    doc.set_text_color(110, 110, 110)
    doc.multi_cell(0, 4, "Prices were live at the time of quoting (Google Flights / Google Hotels) and may change at booking time.")

    PDF_DIR.mkdir(exist_ok=True)
    path = PDF_DIR / f"{booking_ref}.pdf"
    doc.output(str(path))
    return path
