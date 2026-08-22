from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.redis_client import redis_client
from app.models import Seat, SeatStatus, Booking, Payment, Event, User
from app.schemas import ConfirmBookingRequest, BookingOut
from app.services.email import send_booking_confirmation
from app.config import settings

router = APIRouter(tags=["bookings"])

SEAT_PRICES = {"standard": 500, "premium": 1000, "vip": 2000}
LOCK_TTL_SECONDS = 5


@router.post("/seats/{seat_id}/hold", status_code=status.HTTP_200_OK)
def hold_seat(seat_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    seat = db.get(Seat, seat_id)
    if not seat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seat not found")

    # Per-user limit: at most N held seats for this event at a time.
    held_count = (
        db.query(Seat)
        .filter(
            Seat.event_id == seat.event_id,
            Seat.held_by_user_id == user.id,
            Seat.status == SeatStatus.held,
        )
        .count()
    )
    if held_count >= settings.MAX_HELD_SEATS_PER_USER_PER_EVENT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a held seat for this event. Release it before holding another.",
        )

    # Layer 1: short-lived Redis lock so concurrent requests on the same seat
    # don't all pile into the database at once.
    lock_key = f"lock:seat:{seat_id}"
    got_lock = redis_client.set(lock_key, str(user.id), nx=True, ex=LOCK_TTL_SECONDS)
    if not got_lock:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Seat is being processed, try again")

    try:
        # Layer 2: the database itself is the real safety net. The UPDATE only
        # applies if the seat is still 'available' — checked via rowcount, not
        # a separate read-then-write.
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.HOLD_DURATION_MINUTES)
        result = db.execute(
            text(
                "UPDATE seats SET status = 'held', held_by_user_id = :uid, hold_expires_at = :expires_at "
                "WHERE id = :seat_id AND status = 'available'"
            ),
            {"uid": user.id, "expires_at": expires_at, "seat_id": seat_id},
        )
        db.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Seat is no longer available")

        return {"seat_id": seat_id, "status": "held", "hold_expires_at": expires_at.isoformat()}
    finally:
        redis_client.delete(lock_key)


@router.post("/seats/{seat_id}/release", status_code=status.HTTP_200_OK)
def release_seat(seat_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result = db.execute(
        text(
            "UPDATE seats SET status = 'available', held_by_user_id = NULL, hold_expires_at = NULL "
            "WHERE id = :seat_id AND held_by_user_id = :uid AND status = 'held'"
        ),
        {"seat_id": seat_id, "uid": user.id},
    )
    db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You are not holding this seat")

    return {"seat_id": seat_id, "status": "available"}


@router.post("/bookings/confirm", response_model=BookingOut)
def confirm_booking(
    payload: ConfirmBookingRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Idempotent replay: same key seen before -> return the original result.
    existing = db.query(Booking).filter(Booking.idempotency_key == idempotency_key).first()
    if existing:
        return _booking_to_out(db, existing)

    seat = db.get(Seat, payload.seat_id)
    if not seat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seat not found")
    if seat.status != SeatStatus.held or seat.held_by_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You are not holding this seat")
    if seat.hold_expires_at and seat.hold_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Your hold has expired")

    booking = Booking(
        user_id=user.id,
        event_id=seat.event_id,
        seat_id=seat.id,
        idempotency_key=idempotency_key,
        status="confirmed",
    )
    db.add(booking)

    try:
        db.flush()
    except IntegrityError:
        # Two identical requests raced past the check above; the DB's UNIQUE
        # constraint is the real guarantee. Whoever loses the race just reads
        # back whoever won.
        db.rollback()
        winner = db.query(Booking).filter(Booking.idempotency_key == idempotency_key).first()
        if winner:
            return _booking_to_out(db, winner)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Seat was already booked")

    seat.status = SeatStatus.booked
    seat.held_by_user_id = None
    seat.hold_expires_at = None

    db.add(Payment(booking_id=booking.id, amount=SEAT_PRICES.get(seat.seat_type.value, 500), status="paid"))
    db.commit()
    db.refresh(booking)

    event = db.get(Event, booking.event_id)
    send_booking_confirmation(user.email, event.name, event.venue, seat.label, booking.id)

    return _booking_to_out(db, booking)


@router.get("/bookings/history", response_model=list[BookingOut])
def booking_history(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bookings = (
        db.query(Booking)
        .filter(Booking.user_id == user.id)
        .order_by(Booking.created_at.desc())
        .all()
    )
    return [_booking_to_out(db, b) for b in bookings]


def _booking_to_out(db: Session, booking: Booking) -> BookingOut:
    seat = db.get(Seat, booking.seat_id)
    event = db.get(Event, booking.event_id)
    return BookingOut(
        id=booking.id,
        event_id=booking.event_id,
        event_name=event.name if event else "",
        seat_label=seat.label if seat else "",
        seat_type=seat.seat_type.value if seat else "",
        status=booking.status,
        created_at=booking.created_at,
    )
