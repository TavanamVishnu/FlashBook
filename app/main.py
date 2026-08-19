import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException

from app.db import get_connection
from app.redis_client import redis_client

HOLD_DURATION_MINUTES = 5
LOCK_TTL_SECONDS = 5
RELEASE_CHECK_INTERVAL_SECONDS = 10

scheduler = BackgroundScheduler()


def release_expired_holds():
    """Background job: finds seats whose hold has expired and puts them back
    to 'available'. This is what actually enforces the 5-minute hold limit -
    without this running, a seat someone abandoned mid-checkout would stay
    locked forever."""
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
    return [
        {"seat_id": r[0], "seat_label": r[1], "status": r[2], "hold_expires_at": r[3]}
        for r in rows
    ]


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