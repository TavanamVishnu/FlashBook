from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    # Sync endpoints run in FastAPI's threadpool, so under concurrent load many
    # requests want a DB connection at once. The default pool (5 + 10 overflow)
    # is too small for a load test firing hundreds of requests at once and
    # causes healthy requests to time out waiting for a connection.
    pool_size=30,
    max_overflow=50,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
