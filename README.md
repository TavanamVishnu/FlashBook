# FlashBook — Concurrent Seat Booking Engine

A FastAPI + PostgreSQL + Redis booking system that guarantees a seat is never
double-booked, even under heavy concurrent load — the same class of problem
behind real ticketing systems (BookMyShow, Ticketmaster, IRCTC).

Full design reasoning, requirements, and rejected alternatives live in
[`DESIGN.md`](./DESIGN.md).

## What it actually does

- Holds a seat for 5 minutes using a **Redis distributed lock** for speed and
  a **conditional PostgreSQL update** as a DB-level safety net underneath it.
- Auto-releases abandoned holds via a **background worker** (APScheduler)
  polling every 10s.
- Confirms bookings through an **idempotent** endpoint — retried requests
  with the same `Idempotency-Key` always return the same result, protected
  by a `UNIQUE` constraint at the database level, not just an app-side check.
- Throttles flash-sale traffic with a **Redis sorted-set waiting room**,
  admitting a limited number of users at a time and freeing slots as people
  finish.

## Proof it works — not just a claim

```
Total requests fired:      300
200 (won the seat):        1
409 (correctly rejected):  299
other/errors:              0

PASS - exactly one request won the seat under concurrent load. No double-booking.
```

300 simultaneous requests targeting the *same* seat, run via
[`load_test.py`](./load_test.py). Exactly one succeeds, every other request
is correctly rejected with a 409, and nothing errors. This is what actually
backs up the concurrency design, rather than trusting the code by inspection.

## Tech stack

FastAPI · PostgreSQL · Redis · APScheduler · Docker · pytest/httpx

## Architecture

```
Client -> FastAPI booking API -> PostgreSQL (source of truth: seats, bookings, users)
                               -> Redis (locks, hold TTL guard, waiting-room queue)
Background worker -> polls Redis-adjacent DB state -> releases expired holds in PostgreSQL
```

## Running it locally

1. `docker run --name flashbook-postgres -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=flashbook -p 5433:5432 -d postgres:16`
2. `docker run --name flashbook-redis -p 6379:6379 -d redis:7`
3. `docker exec -i flashbook-postgres psql -U postgres -d flashbook < schema.sql`
4. `python3 -m venv project && source project/bin/activate`
5. `python3 -m pip install -r requirements.txt`
6. Create `.env` (see `DESIGN.md` for the values used)
7. `PYTHONPATH=. python3 seed.py` — creates a test event with 5 seats
8. `PYTHONPATH=. uvicorn app.main:app --reload`
9. Visit `http://127.0.0.1:8000/docs`

## API

| Method & path | Purpose |
|---|---|
| `GET /health` | Liveness check |
| `GET /health/ready` | Readiness check — confirms DB and Redis are actually reachable |
| `GET /events/{event_id}/seats` | List seat availability |
| `POST /events/{event_id}/seats/{seat_id}/hold` | Hold a seat for 5 minutes |
| `POST /bookings/confirm` (header: `Idempotency-Key`) | Confirm a booking |
| `POST /events/{event_id}/queue/join` | Join the flash-sale waiting room |
| `GET /events/{event_id}/queue/{token}/status` | Check queue position / admission |
| `POST /events/{event_id}/queue/{token}/leave` | Leave the queue, freeing a slot |

## What I'd change at scale

Covered in detail in `DESIGN.md` §10 — short version: shard PostgreSQL by
`event_id`, replace the polling queue with a message broker or WebSocket
push, and move to Redis Cluster / Redlock for highly-available locking.

## Notable real-world detour

Local development hit a genuine, non-obvious MySQL/Docker authentication bug
on macOS that persisted across account recreation and container rebuilds.
Rather than lose more time to a driver-specific issue unrelated to the
system design, the project switched to PostgreSQL — logged as a decision in
`DESIGN.md`'s ADR table, alternatives and all. Debugging that blind, in the
order it actually happened, was as much a part of building this as the code.
