# FlashBook — Concurrent Seat Booking Engine

## Design Doc v1

---

## 1. Problem statement

Ticket/seat booking systems must guarantee that a single seat is never sold to two
people, even when hundreds of users try to book it in the same instant (e.g. a
flash sale). This project builds a booking engine that solves this correctness
problem under realistic concurrent load, and documents the trade-offs behind the
chosen design instead of just implementing it.

---

## 2. Goals / Non-goals

**Goals**
- No seat is ever double-booked, even under concurrent access.
- Seats held but not paid for are automatically released.
- Payment confirmation is idempotent — retries never double-charge or double-book.
- The system stays responsive when many users attempt to book simultaneously
  during a flash sale.

**Non-goals**
- Real payment processing (mocked).
- Multi-tenant admin dashboard / venue management UI.
- Horizontal scaling implementation (discussed in §10, not built).

---

## 3. Functional requirements

| ID | Requirement |
|----|-------------|
| FR1 | User can view seat availability for an event. |
| FR2 | User can place a temporary hold on a seat. |
| FR3 | A held seat auto-releases after the hold duration if not confirmed. |
| FR4 | User can confirm a booking with payment; confirmation is idempotent via an `Idempotency-Key` header. |
| FR5 | During high-demand events, users enter a queue instead of hitting the booking endpoints directly. |

---

## 4. Non-functional requirements

| ID | Requirement |
|----|-------------|
| NFR1 — Concurrency | Correctly handle **200–500 concurrent hold requests** against the same/overlapping seats without double-booking. |
| NFR2 — Hold duration | **5 minutes**, after which the seat is auto-released. |
| NFR3 — Latency | Hold-request should respond well under 1s even at peak concurrency (target: p99 < 300ms) so the flow feels interactive. |
| NFR4 — Consistency | Seat state (available / held / booked) must be strongly consistent — no state where two confirmations succeed for one seat. |
| NFR5 — Idempotency | Retried confirm requests with the same key return the original result, not a new booking. |

---

## 5. High-level architecture

```
Client
  │
  ▼
FastAPI booking API  (hold / confirm / queue endpoints)
  │                              │
  ▼                              ▼
MySQL                          Redis
(seats, bookings,        (distributed locks, hold TTL,
 users — source of truth)  waiting-room queue, availability cache)
                                  │
                                  ▼
                          Background worker
                    (polls for expired holds, releases seats in MySQL)
```

See the architecture diagram shared in chat for the visual version of this flow.

---

## 6. Concurrency strategy

**Chosen approach:** Redis distributed lock (`SETNX` + TTL) for the hold step,
MySQL transaction for the final confirm step.

**Why:** At 200–500 concurrent requests targeting the same seat, DB row locks
alone would serialize behind the row for the full transaction duration, hurting
latency (violates NFR3). Optimistic locking would cause heavy retry storms since
contention here is *high*, not low — most retries would fail again immediately.
A Redis lock gives fast lock acquisition/rejection, keeping the "hold" step
responsive, while MySQL still owns the final source of truth at confirm time.

**Alternatives considered:**

| Approach | Rejected because |
|----------|-------------------|
| Pure DB row-level locking (`SELECT ... FOR UPDATE`) | Lock held for full transaction duration under contention → latency spikes at 200-500 concurrent (violates NFR3). |
| Optimistic locking (version column) | High retry-storm rate under high contention — most competing requests fail and retry immediately, wasting work. |
| Queue-based serialization for every request | Correct, but adds unnecessary latency/infra for the common case; reserved instead for the flash-sale *admission* queue (FR5), not every hold request. |

---

## 7. API contract (draft)

| Method & path | Purpose |
|---|---|
| `GET /events/{id}/seats` | List seat availability for an event. |
| `POST /events/{id}/seats/{seat_id}/hold` | Hold a seat for 5 minutes. Returns `hold_id`. |
| `POST /bookings/confirm` (header: `Idempotency-Key`) | Confirm a booking. Returns `booking_id`. |
| `POST /events/{id}/queue/join` | Join the waiting room for a flash-sale event. Returns queue token. |
| `GET /queue/{token}/status` | Poll queue position / admitted status. |

---

## 8. Testing strategy

- **Unit tests** — hold logic, expiry logic, idempotency-key handling.
- **Integration tests** — full hold → confirm flow against a test DB.
- **Concurrency/load test** — N=200–500 simultaneous hold requests on the same
  seat; assert exactly one succeeds. This is the test that actually proves NFR1
  and NFR4, not just the happy path.

---

## 9. Observability

- Structured logs for: hold attempt, hold success/failure, expiry release,
  confirm attempt, confirm idempotent-replay.
- Simple counters exposed at `/metrics`: total holds, total expired, total
  confirmed, total idempotent replays.

---

## 10. What I'd change at scale (not built, but documented)

- Single MySQL instance is the eventual bottleneck — would shard bookings by
  `event_id` and add read replicas for availability reads.
- The waiting-room queue is currently polling-based — would move to a message
  broker (Kafka/RabbitMQ) or WebSocket push for real-time admission instead.
- Redis becomes a single point of failure at very high scale — would consider
  Redis Cluster or the Redlock algorithm for highly-available locking.

---

## 11. Alternatives log (ADR-style)

*Keep appending one entry per significant decision as the project evolves.*

| Decision | Alternatives considered | Why this one |
|---|---|---|
| Redis lock + TTL for holds | DB row lock, optimistic locking | See §6 |
| 5-minute hold duration | 2 min (tighter), 10 min (looser) | Standard middle ground between UX friction and inventory lock-up time |
