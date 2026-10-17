"""Pydantic models shared by the tools, planner and agent."""

from __future__ import annotations

import math
from datetime import date

from pydantic import BaseModel, Field, model_validator


class TripRequest(BaseModel):
    origin: str = Field(description="Origin airport code(s), e.g. HYD")
    destination: str = Field(description="Destination airport code(s), e.g. GOI,GOX")
    depart_date: date
    return_date: date
    adults: int = Field(ge=1, le=9)
    budget_inr: int = Field(gt=0)
    children: int = Field(default=0, ge=0)
    rooms: int | None = Field(default=None, ge=1)
    hotel_preference: str = ""

    @model_validator(mode="after")
    def check_dates_and_rooms(self) -> TripRequest:
        if self.depart_date <= date.today():
            raise ValueError("depart_date must be in the future")
        if self.return_date <= self.depart_date:
            raise ValueError("return_date must be after depart_date")
        if self.rooms is None:
            self.rooms = math.ceil(self.adults / 2)
        return self

    @property
    def nights(self) -> int:
        return (self.return_date - self.depart_date).days


class FlightLeg(BaseModel):
    airline: str
    flight_number: str
    from_airport: str
    to_airport: str
    depart_time: str
    arrive_time: str


class FlightOption(BaseModel):
    id: str
    airline: str
    flight_numbers: str
    depart_time: str
    arrive_time: str
    duration_min: int
    stops: int
    price_per_person: int  # round-trip, INR
    legs: list[FlightLeg] = []
    departure_token: str = ""  # used to fetch the return flight details


class HotelOption(BaseModel):
    id: str
    name: str
    rating: float | None = None
    reviews: int | None = None
    hotel_class: str = ""
    price_per_night: int  # INR, per room
    location: str = ""
    link: str = ""


class QuoteOption(BaseModel):
    label: str  # "A", "B", "C"
    kind: str  # "Cheapest", "Best value", "Comfort", "Closest"
    flight: FlightOption
    hotel: HotelOption
    flight_cost: int
    hotel_cost: int
    total: int
    within_budget: bool
    over_by: int = 0


class Quote(BaseModel):
    trip: TripRequest
    options: list[QuoteOption]
    fits_budget: bool
