import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from psycopg2.errors import UniqueViolation

from app.db import get_connection
from app.redis_client import redis_client

HOLD_DURATION_MINUTES = 5
LOCK_TTL_SECONDS = 5
RELEASE_CHECK_INTERVAL_SECONDS = 10
ADMIT_LIMIT = 2  # small on purpose, so it's easy to demo with just a couple requests

scheduler = BackgroundScheduler()


def release_expired_holds():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE seats SET status = 'available', hold_expires_at = NULL "
        "WHERE status = 'held' AND hold_expires_at < NOW()"
    )
    released = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if released:
        print(f"[worker] released {released} expired hold(s)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(release_expired_holds, "interval", seconds=RELEASE_CHECK_INTERVAL_SECONDS)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="FlashBook API", lifespan=lifespan)


class ConfirmBookingRequest(BaseModel):
    user_email: str
    seat_id: str


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness_check():
    status = {"database": "unknown", "redis": "unknown"}
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.close()
        conn.close()
        status["database"] = "ok"
    except Exception as e:
        status["database"] = f"error: {e}"
    try:
        redis_client.ping()
        status["redis"] = "ok"
    except Exception as e:
        status["redis"] = f"error: {e}"
    all_ok = all(v == "ok" for v in status.values())
    return {"ready": all_ok, "dependencies": status}


@app.get("/events/{event_id}/seats")
def list_seats(event_id: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, seat_label, status, hold_expires_at FROM seats WHERE event_id = %s ORDER BY seat_label",
        (event_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"seat_id": r[0], "seat_label": r[1], "status": r[2], "hold_expires_at": r[3]} for r in rows]


@app.post("/events/{event_id}/seats/{seat_id}/hold")
def hold_seat(event_id: str, seat_id: str):
    lock_key = f"lock:seat:{seat_id}"
    got_lock = redis_client.set(lock_key, "locked", nx=True, ex=LOCK_TTL_SECONDS)
    if not got_lock:
        raise HTTPException(status_code=409, detail="Seat is being processed by another request, try again shortly")
    try:
        conn = get_connection()
        cur = conn.cursor()
        hold_expires_at = datetime.utcnow() + timedelta(minutes=HOLD_DURATION_MINUTES)
        cur.execute(
            "UPDATE seats SET status = 'held', hold_expires_at = %s "
            "WHERE id = %s AND event_id = %s AND status = 'available'",
            (hold_expires_at, seat_id, event_id),
        )
        affected = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if affected == 0:
            raise HTTPException(status_code=409, detail="Seat is not available")
        return {"seat_id": seat_id, "status": "held", "hold_expires_at": hold_expires_at.isoformat()}
    finally:
        redis_client.delete(lock_key)


@app.post("/bookings/confirm")
def confirm_booking(payload: ConfirmBookingRequest, idempotency_key: str = Header(...)):
    """Idempotent by design: retried requests with the same Idempotency-Key
    always return the SAME booking, never create a second one - even if two
    copies of this exact request race each other concurrently. The real
    guarantee here isn't the "check for existing key" query below (that alone
    has a race window); it's the UNIQUE constraint on bookings.idempotency_key
    from schema.sql. The check is just an optimization for the common case;
    the except UniqueViolation block below is what actually makes this safe."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, seat_id, status FROM bookings WHERE idempotency_key = %s",
            (idempotency_key,),
        )
        existing = cur.fetchone()
        if existing:
            return {"booking_id": existing[0], "seat_id": existing[1], "status": existing[2], "replayed": True}

        cur.execute("SELECT id FROM users WHERE email = %s", (payload.user_email,))
        user_row = cur.fetchone()
        if user_row:
            user_id = user_row[0]
        else:
            user_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO users (id, email, password_hash) VALUES (%s, %s, %s)",
                (user_id, payload.user_email, "mock_hash"),
            )

        cur.execute(
            "UPDATE seats SET status = 'booked', hold_expires_at = NULL "
            "WHERE id = %s AND status = 'held'",
            (payload.seat_id,),
        )
        if cur.rowcount == 0:
            conn.rollback()
            raise HTTPException(status_code=409, detail="Seat is not currently held - cannot confirm")

        booking_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO bookings (id, user_id, seat_id, idempotency_key, status) "
            "VALUES (%s, %s, %s, %s, 'confirmed')",
            (booking_id, user_id, payload.seat_id, idempotency_key),
        )
        cur.execute(
            "INSERT INTO payments (id, booking_id, amount, status) VALUES (%s, %s, %s, 'mock_success')",
            (str(uuid.uuid4()), booking_id, 20.00),
        )
        conn.commit()
        return {"booking_id": booking_id, "seat_id": payload.seat_id, "status": "confirmed", "replayed": False}

    except UniqueViolation:
        conn.rollback()
        cur.execute(
            "SELECT id, seat_id, status FROM bookings WHERE idempotency_key = %s",
            (idempotency_key,),
        )
        existing = cur.fetchone()
        return {"booking_id": existing[0], "seat_id": existing[1], "status": existing[2], "replayed": True}
    finally:
        cur.close()
        conn.close()


@app.post("/events/{event_id}/queue/join")
def join_queue(event_id: str):
    """Adds this caller to the back of the line for this event. The sorted
    set is ordered by join time (the score), which is what gives us FIFO
    ordering for free - Redis keeps it sorted, we don't have to."""
    queue_token = str(uuid.uuid4())
    redis_client.zadd(f"queue:{event_id}", {queue_token: time.time()})
    return {"queue_token": queue_token}


@app.get("/events/{event_id}/queue/{queue_token}/status")
def queue_status(event_id: str, queue_token: str):
    rank = redis_client.zrank(f"queue:{event_id}", queue_token)
    if rank is None:
        raise HTTPException(status_code=404, detail="Token not found - you may have already left the queue")
    admitted = rank < ADMIT_LIMIT
    return {"position": rank + 1, "admitted": admitted}


@app.post("/events/{event_id}/queue/{queue_token}/leave")
def leave_queue(event_id: str, queue_token: str):
    """Call this once an admitted user is done (has confirmed a booking, or
    given up) - it frees their slot so the NEXT person in line becomes
    admitted. Without this step, admitted slots would never free up."""
    redis_client.zrem(f"queue:{event_id}", queue_token)
    return {"left": True}