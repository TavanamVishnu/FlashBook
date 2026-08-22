import string

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_admin
from app.models import Event, Seat, SeatType
from app.schemas import AdminLoginRequest, TokenResponse, CreateEventRequest, EventOut
from app.security import create_access_token
from app.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])


def _row_label(row_index: int) -> str:
    letters = string.ascii_uppercase
    if row_index < len(letters):
        return letters[row_index]
    return f"R{row_index + 1}"  # fallback for venues with more than 26 rows


def _seat_type_for_row(row_index: int, vip_rows: int, premium_rows: int) -> SeatType:
    if row_index < vip_rows:
        return SeatType.vip
    if row_index < vip_rows + premium_rows:
        return SeatType.premium
    return SeatType.standard


@router.post("/login", response_model=TokenResponse)
def admin_login(payload: AdminLoginRequest):
    if payload.password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin password")
    token = create_access_token(subject="admin", role="admin")
    return TokenResponse(access_token=token)


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: CreateEventRequest,
    db: Session = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    if payload.vip_rows + payload.premium_rows > payload.rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="vip_rows + premium_rows cannot exceed total rows",
        )

    event = Event(
        name=payload.name,
        venue=payload.venue,
        starts_at=payload.starts_at,
        rows=payload.rows,
        cols=payload.cols,
        vip_rows=payload.vip_rows,
        premium_rows=payload.premium_rows,
    )
    db.add(event)
    db.flush()  # get event.id before creating seats

    for row_index in range(payload.rows):
        row_label = _row_label(row_index)
        seat_type = _seat_type_for_row(row_index, payload.vip_rows, payload.premium_rows)
        for col_index in range(payload.cols):
            db.add(Seat(
                event_id=event.id,
                row=row_index,
                col=col_index,
                label=f"{row_label}{col_index + 1}",
                seat_type=seat_type,
            ))

    db.commit()
    db.refresh(event)
    return event
