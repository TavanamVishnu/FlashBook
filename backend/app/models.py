import enum

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, UniqueConstraint, Numeric, func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class SeatType(str, enum.Enum):
    standard = "standard"
    premium = "premium"
    vip = "vip"


class SeatStatus(str, enum.Enum):
    available = "available"
    held = "held"
    booked = "booked"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    venue = Column(String, nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    rows = Column(Integer, nullable=False)
    cols = Column(Integer, nullable=False)
    vip_rows = Column(Integer, nullable=False, default=0)
    premium_rows = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    seats = relationship("Seat", back_populates="event", cascade="all, delete-orphan")


class Seat(Base):
    __tablename__ = "seats"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    row = Column(Integer, nullable=False)
    col = Column(Integer, nullable=False)
    label = Column(String, nullable=False)
    seat_type = Column(Enum(SeatType), nullable=False, default=SeatType.standard)
    status = Column(Enum(SeatStatus), nullable=False, default=SeatStatus.available, index=True)
    held_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    hold_expires_at = Column(DateTime(timezone=True), nullable=True)

    event = relationship("Event", back_populates="seats")

    __table_args__ = (
        UniqueConstraint("event_id", "row", "col", name="uq_seat_position_per_event"),
    )


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False, index=True)
    seat_id = Column(Integer, ForeignKey("seats.id"), nullable=False)
    idempotency_key = Column(String, nullable=False)
    status = Column(String, nullable=False, default="confirmed")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_booking_idempotency_key"),
        UniqueConstraint("seat_id", name="uq_booking_seat_id"),
    )


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, unique=True)
    amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String, nullable=False, default="paid")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
