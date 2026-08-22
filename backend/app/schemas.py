from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr, ConfigDict


# ---- auth ----

class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- admin ----

class AdminLoginRequest(BaseModel):
    password: str


class CreateEventRequest(BaseModel):
    name: str
    venue: str
    starts_at: datetime
    rows: int
    cols: int
    vip_rows: int = 0
    premium_rows: int = 0


# ---- events / seats ----

class SeatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    row: int
    col: int
    label: str
    seat_type: str
    status: str


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    venue: str
    starts_at: datetime
    rows: int
    cols: int


class EventDetailOut(EventOut):
    seats: List[SeatOut]


# ---- bookings ----

class ConfirmBookingRequest(BaseModel):
    seat_id: int


class BookingOut(BaseModel):
    id: int
    event_id: int
    event_name: str
    seat_label: str
    seat_type: str
    status: str
    created_at: datetime


# ---- waiting room ----

class QueueStatusOut(BaseModel):
    position: Optional[int]
    admitted: bool
