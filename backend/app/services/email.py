import smtplib
import logging
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger("flashbook.email")


def send_booking_confirmation(to_email: str, event_name: str, venue: str, seat_label: str, booking_id: int) -> None:
    """Best-effort email send. A failure here must never affect a booking that
    has already been committed to the database — so every error is caught
    and logged, never raised."""
    if not settings.SMTP_HOST:
        logger.info("SMTP not configured, skipping confirmation email for booking %s", booking_id)
        return

    try:
        msg = EmailMessage()
        msg["Subject"] = f"Booking confirmed: {event_name}"
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to_email
        msg.set_content(
            f"Your seat is booked!\n\n"
            f"Event: {event_name}\n"
            f"Venue: {venue}\n"
            f"Seat: {seat_label}\n"
            f"Booking ID: {booking_id}\n"
        )

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=5) as server:
            server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
    except Exception:
        logger.exception("Failed to send confirmation email for booking %s (booking is still valid)", booking_id)
