import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from psycopg2.errors import UniqueViolation

from app.db import get_connection
from app.redis_client import redis_client

HOLD_DURATION_MINUTES = 5
LOCK_TTL_SECONDS = 5
RELEASE_CHECK_INTERVAL_SECONDS = 10
ADMIT_LIMIT = 2
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "devadmin")

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConfirmBookingRequest(BaseModel):
    user_email: str
    seat_id: str


class CreateEventRequest(BaseModel):
    name: str
    venue: str
    event_time: str
    rows: int
    cols: int
    vip_rows: int = 0
    premium_rows: int = 0


def require_admin(x_admin_password: str = Header(...)):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin password")


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


@app.get("/events")
def list_events():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, venue, event_time, total_seats FROM events ORDER BY event_time")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"event_id": r[0], "name": r[1], "venue": r[2], "event_time": r[3].isoformat(), "total_seats": r[4]} for r in rows]


@app.post("/admin/events", dependencies=[Depends(require_admin)])
def create_event(payload: CreateEventRequest):
    conn = get_connection()
    cur = conn.cursor()
    try:
        event_id = str(uuid.uuid4())
        total_seats = payload.rows * payload.cols
        cur.execute(
            "INSERT INTO events (id, name, venue, event_time, total_seats) VALUES (%s, %s, %s, %s, %s)",
            (event_id, payload.name, payload.venue, payload.event_time, total_seats),
        )
        for r in range(1, payload.rows + 1):
            if r <= payload.vip_rows:
                seat_type = "vip"
            elif r <= payload.vip_rows + payload.premium_rows:
                seat_type = "premium"
            else:
                seat_type = "standard"
            row_letter = chr(64 + r)
            for c in range(1, payload.cols + 1):
                seat_id = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO seats (id, event_id, seat_label, seat_type, row_num, col_num) VALUES (%s, %s, %s, %s, %s, %s)",
                    (seat_id, event_id, f"{row_letter}{c}", seat_type, r, c),
                )
        conn.commit()
        return {"event_id": event_id, "total_seats": total_seats}
    finally:
        cur.close()
        conn.close()


@app.get("/events/{event_id}/seats")
def list_seats(event_id: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, seat_label, seat_type, row_num, col_num, status, hold_expires_at FROM seats WHERE event_id = %s ORDER BY row_num, col_num",
        (event_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"seat_id": r[0], "seat_label": r[1], "seat_type": r[2], "row": r[3], "col": r[4], "status": r[5], "hold_expires_at": r[6]} for r in rows]


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
            "UPDATE seats SET status = 'held', hold_expires_at = %s WHERE id = %s AND event_id = %s AND status = 'available'",
            (hold_expires_at, seat_id, event_id),
        )
        affected = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if affected == 0:
            raise HTTPException(status_code=409, detail="Seat is not available")
        return {"seat_id": seat_id, "status": "held", "hold_expires_at": hold_expires_at.isoformat() + "Z"}
    finally:
        redis_client.delete(lock_key)


@app.post("/bookings/confirm")
def confirm_booking(payload: ConfirmBookingRequest, idempotency_key: str = Header(...)):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, seat_id, status FROM bookings WHERE idempotency_key = %s", (idempotency_key,))
        existing = cur.fetchone()
        if existing:
            return {"booking_id": existing[0], "seat_id": existing[1], "status": existing[2], "replayed": True}
        cur.execute("SELECT id FROM users WHERE email = %s", (payload.user_email,))
        user_row = cur.fetchone()
        if user_row:
            user_id = user_row[0]
        else:
            user_id = str(uuid.uuid4())
            cur.execute("INSERT INTO users (id, email, password_hash) VALUES (%s, %s, %s)", (user_id, payload.user_email, "mock_hash"))
        cur.execute("UPDATE seats SET status = 'booked', hold_expires_at = NULL WHERE id = %s AND status = 'held'", (payload.seat_id,))
        if cur.rowcount == 0:
            conn.rollback()
            raise HTTPException(status_code=409, detail="Seat is not currently held - cannot confirm")
        booking_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO bookings (id, user_id, seat_id, idempotency_key, status) VALUES (%s, %s, %s, %s, 'confirmed')",
            (booking_id, user_id, payload.seat_id, idempotency_key),
        )
        cur.execute("INSERT INTO payments (id, booking_id, amount, status) VALUES (%s, %s, %s, 'mock_success')", (str(uuid.uuid4()), booking_id, 20.00))
        conn.commit()
        return {"booking_id": booking_id, "seat_id": payload.seat_id, "status": "confirmed", "replayed": False}
    except UniqueViolation:
        conn.rollback()
        cur.execute("SELECT id, seat_id, status FROM bookings WHERE idempotency_key = %s", (idempotency_key,))
        existing = cur.fetchone()
        return {"booking_id": existing[0], "seat_id": existing[1], "status": existing[2], "replayed": True}
    finally:
        cur.close()
        conn.close()


@app.post("/events/{event_id}/queue/join")
def join_queue(event_id: str):
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
    redis_client.zrem(f"queue:{event_id}", queue_token)
    return {"left": True}
