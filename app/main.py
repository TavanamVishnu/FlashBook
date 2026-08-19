import uuid
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException

from app.db import get_connection
from app.redis_client import redis_client

app = FastAPI(title="FlashBook API")

HOLD_DURATION_MINUTES = 5
LOCK_TTL_SECONDS = 5  # short-lived - just guards the critical section itself


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
        "SELECT id, seat_label, status FROM seats WHERE event_id = %s ORDER BY seat_label",
        (event_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"seat_id": r[0], "seat_label": r[1], "status": r[2]} for r in rows]


@app.post("/events/{event_id}/seats/{seat_id}/hold")
def hold_seat(event_id: str, seat_id: str):
    """Two layers of protection against double-booking, on purpose:

    1. A short-lived Redis lock (SETNX) serializes concurrent attempts on the
       SAME seat fast, without every request hitting Postgres.
    2. A conditional UPDATE (WHERE status='available') is the DB-level
       safety net underneath it - checked via rowcount, so even if the Redis
       lock were ever bypassed or expired early, two holds can't both succeed.
    """
    lock_key = f"lock:seat:{seat_id}"

    got_lock = redis_client.set(lock_key, "locked", nx=True, ex=LOCK_TTL_SECONDS)
    if not got_lock:
        raise HTTPException(
            status_code=409,
            detail="Seat is being processed by another request, try again shortly",
        )

    try:
        conn = get_connection()
        cur = conn.cursor()
        hold_expires_at = datetime.utcnow() + timedelta(minutes=HOLD_DURATION_MINUTES)

        cur.execute(
            """
            UPDATE seats SET status = 'held', hold_expires_at = %s
            WHERE id = %s AND event_id = %s AND status = 'available'
            """,
            (hold_expires_at, seat_id, event_id),
        )
        affected = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()

        if affected == 0:
            raise HTTPException(status_code=409, detail="Seat is not available")

        return {
            "seat_id": seat_id,
            "status": "held",
            "hold_expires_at": hold_expires_at.isoformat(),
        }
    finally:
        # Release the lock as soon as we're done with this critical section -
        # don't hold it for the full 5-minute hold duration, only for the
        # brief moment it takes to do the conditional update.
        redis_client.delete(lock_key)