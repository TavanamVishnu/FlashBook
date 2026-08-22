import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text

from app.database import SessionLocal
from app.config import settings

logger = logging.getLogger("flashbook.worker")


def release_expired_holds() -> None:
    db = SessionLocal()
    try:
        result = db.execute(
            text(
                "UPDATE seats SET status = 'available', held_by_user_id = NULL, hold_expires_at = NULL "
                "WHERE status = 'held' AND hold_expires_at < now()"
            )
        )
        db.commit()
        if result.rowcount:
            logger.info("Released %s expired seat hold(s)", result.rowcount)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        release_expired_holds,
        "interval",
        seconds=settings.HOLD_SWEEP_INTERVAL_SECONDS,
        id="release_expired_holds",
    )
    scheduler.start()
    return scheduler
