from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import get_current_user
from app.models import Event
from app.schemas import EventOut, EventDetailOut

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=List[EventOut])
def list_events(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    return db.query(Event).order_by(Event.starts_at).all()


@router.get("/{event_id}", response_model=EventDetailOut)
def get_event(event_id: int, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    event = (
        db.query(Event)
        .options(selectinload(Event.seats))
        .filter(Event.id == event_id)
        .first()
    )
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event
