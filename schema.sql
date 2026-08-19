-- FlashBook schema (PostgreSQL)
-- Designed around the query patterns in DESIGN.md sections 5-6, not just the entities.

CREATE TYPE seat_status AS ENUM ('available', 'held', 'booked');
CREATE TYPE booking_status AS ENUM ('pending', 'confirmed', 'cancelled');
CREATE TYPE payment_status AS ENUM ('mock_success', 'mock_failed');

CREATE TABLE users (
    id              CHAR(36)     PRIMARY KEY,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE events (
    id              CHAR(36)     PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    venue           VARCHAR(255) NOT NULL,
    event_time      TIMESTAMP    NOT NULL,
    total_seats     INT          NOT NULL,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE seats (
    id                 CHAR(36)     PRIMARY KEY,
    event_id           CHAR(36)     NOT NULL REFERENCES events(id),
    seat_label         VARCHAR(20)  NOT NULL,          -- e.g. "A12"
    status             seat_status  NOT NULL DEFAULT 'available',
    hold_expires_at    TIMESTAMP    NULL,
    created_at         TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Query 1: "available seats for this event" - the most frequent read.
CREATE INDEX idx_event_status ON seats (event_id, status);

-- Query 3: background worker scanning for expired holds.
CREATE INDEX idx_status_expiry ON seats (status, hold_expires_at);

CREATE TABLE bookings (
    id                CHAR(36)        PRIMARY KEY,
    user_id           CHAR(36)        NOT NULL REFERENCES users(id),
    seat_id           CHAR(36)        NOT NULL REFERENCES seats(id),
    idempotency_key   VARCHAR(255)    NOT NULL UNIQUE,   -- Query 4: instant idempotent-replay lookup
    status            booking_status  NOT NULL DEFAULT 'pending',
    created_at        TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Defense in depth: even if the Redis lock and app logic both had a bug,
    -- the DB itself refuses to let one seat have two active bookings.
    UNIQUE (seat_id)
);

CREATE TABLE payments (
    id           CHAR(36)        PRIMARY KEY,
    booking_id   CHAR(36)        NOT NULL REFERENCES bookings(id),
    amount       DECIMAL(10,2)   NOT NULL,
    status       payment_status  NOT NULL,
    created_at   TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- The hold-flip itself (Query 2) doesn't need a special index - it's a lookup
-- by primary key - but its correctness depends on this exact pattern:
--
--   UPDATE seats SET status = 'held', hold_expires_at = %s
--   WHERE id = %s AND status = 'available';
--
-- Check the driver's rowcount after this statement. If it's 0, someone else
-- already got the seat - that's your DB-level confirmation sitting underneath
-- the Redis lock, not a replacement for it.