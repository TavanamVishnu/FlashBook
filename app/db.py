import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    """Opens a new PostgreSQL connection using settings from .env.

    We open a fresh connection per call for now, rather than sharing one
    global connection - simpler to reason about correctness-wise. A real
    production service would switch to a connection pool once this becomes
    a bottleneck, but that's a later optimization, not a day-one concern.
    """
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", 5432)),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        dbname=os.getenv("DB_NAME", "flashbook"),
    )