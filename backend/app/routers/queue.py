import time

from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.redis_client import redis_client
from app.schemas import QueueStatusOut
from app.config import settings
from app.models import User

router = APIRouter(prefix="/events/{event_id}/queue", tags=["queue"])


def _queue_key(event_id: int) -> str:
    return f"queue:event:{event_id}"


@router.post("/join", response_model=QueueStatusOut)
def join_queue(event_id: int, user: User = Depends(get_current_user)):
    key = _queue_key(event_id)
    # ZADD NX: only set the score (join time) the first time this user joins;
    # a repeat join call doesn't push them to the back of the line.
    redis_client.zadd(key, {str(user.id): time.time()}, nx=True)
    return _status_for(event_id, user.id)


@router.get("/status", response_model=QueueStatusOut)
def queue_status(event_id: int, user: User = Depends(get_current_user)):
    return _status_for(event_id, user.id)


@router.post("/leave", response_model=QueueStatusOut)
def leave_queue(event_id: int, user: User = Depends(get_current_user)):
    redis_client.zrem(_queue_key(event_id), str(user.id))
    return QueueStatusOut(position=None, admitted=False)


def _status_for(event_id: int, user_id: int) -> QueueStatusOut:
    key = _queue_key(event_id)
    rank = redis_client.zrank(key, str(user_id))
    if rank is None:
        return QueueStatusOut(position=None, admitted=False)
    # Admission is purely rank-based: as soon as someone ahead leaves (zrem),
    # everyone behind them shifts up automatically. No manual slot bookkeeping.
    admitted = rank < settings.WAITING_ROOM_ADMIT_LIMIT
    return QueueStatusOut(position=rank + 1, admitted=admitted)
