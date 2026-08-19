import uuid
from app.db import get_connection


def seed():
    conn = get_connection()
    cur = conn.cursor()

    event_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO events (id, name, venue, event_time, total_seats) "
        "VALUES (%s, %s, %s, %s, %s)",
        (event_id, "Test Concert", "Test Arena", "2026-12-01 19:00:00", 5),
    )

    seat_ids = []
    for i in range(1, 6):
        seat_id = str(uuid.uuid4())
        seat_ids.append(seat_id)
        cur.execute(
            "INSERT INTO seats (id, event_id, seat_label) VALUES (%s, %s, %s)",
            (seat_id, event_id, f"A{i}"),
        )

    conn.commit()
    cur.close()
    conn.close()

    print(f"event_id: {event_id}")
    for i, sid in enumerate(seat_ids, start=1):
        print(f"seat A{i}: {sid}")


if __name__ == "__main__":
    seed()