import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://flashbook:flashbook@localhost:5544/flashbook")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")

    JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret-in-production")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

    HOLD_DURATION_MINUTES = int(os.getenv("HOLD_DURATION_MINUTES", "5"))
    HOLD_SWEEP_INTERVAL_SECONDS = int(os.getenv("HOLD_SWEEP_INTERVAL_SECONDS", "10"))
    MAX_HELD_SEATS_PER_USER_PER_EVENT = int(os.getenv("MAX_HELD_SEATS_PER_USER_PER_EVENT", "1"))
    WAITING_ROOM_ADMIT_LIMIT = int(os.getenv("WAITING_ROOM_ADMIT_LIMIT", "50"))

    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "noreply@flashbook.local")


settings = Settings()
