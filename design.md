# Building FlashBook — the story of how this was made

This file explains, in plain simple language, how FlashBook was built — step by
step, in the order it was actually built, including the real problems that came
up along the way and how each one got fixed. Think of it as a diary of the
build, not a technical spec.

## 1. What are we even building?

Imagine a website selling tickets to a concert. There's a seat map. Two
people click the *same* seat at almost the *exact* same time. A bad system
sells that one seat to **both** of them — and now there's a fight at the
door on concert night.

FlashBook's whole job is to make sure that can never happen, no matter how
many people click at once — while still feeling like a normal, friendly
booking website: sign up, browse events, pick a seat, pay, get a
confirmation email, see your booking history.

## 2. Laying the foundation

Before writing any features, we needed a place to put things:

- A `backend/` folder for the FastAPI server (the "brain" of the app).
- A `frontend/` folder for the plain HTML/CSS/JS pages people actually click on.
- A `docker-compose.yml` file that starts two little helper programs in
  containers: **PostgreSQL** (the database — the permanent notebook that
  remembers every user, seat, and booking forever) and **Redis** (a very fast
  temporary scratchpad, used only for quick locks and a waiting-line list —
  nothing in Redis needs to survive forever).

**Difficulty #1 — the parking spot was taken.** When we tried to start the
Postgres container on port 5433, Docker refused: *"port is already
allocated."* Turns out a completely different old project on this same
machine was already using that exact port. We didn't touch that other
project — we just gave FlashBook its own numbered "parking spot" (port 5544
instead) in `docker-compose.yml`. Lesson: always check what's already
running before assuming a port is free.

## 3. Deciding what to remember (the database schema)

Before writing code, we decided what "facts" the app needs to remember
forever. That became 5 tables:

| Table | What it remembers |
|---|---|
| `users` | who signed up (password stored as a scrambled hash, never as plain text) |
| `events` | concerts/shows, and how their seat grid is laid out |
| `seats` | every single seat, and whether it's `available`, `held`, or `booked` |
| `bookings` | confirmed reservations |
| `payments` | a pretend payment record for each booking |

Two small database rules do almost all of the hard safety work later:

- A seat can only appear in `bookings` **once** (`UNIQUE(seat_id)`) — so the
  database itself physically refuses to let one seat be sold twice, even if
  our own code had a bug.
- Each booking has a unique "idempotency key" (`UNIQUE(idempotency_key)`) — so
  if the same "confirm my booking" request accidentally gets sent twice (like
  when your phone's internet blips and it retries), it can never create two
  bookings by accident.

We wrote these tables as SQLAlchemy models (`backend/app/models.py`) and let
the app create them automatically the first time it starts.

## 4. Logging in (authentication)

Next we built signing up and logging in (`backend/app/routers/auth.py`):

- When you sign up, your password is run through `bcrypt`, which turns it
  into scrambled gibberish that can be checked but never reversed back into
  your real password.
- When you log in successfully, the server hands you a **JWT** — think of it
  like a wristband at a festival. You show it on every request, it proves
  who you are, and it naturally expires after 24 hours so you don't have to
  carry it forever, but it also can't be revoked early (a deliberate, small
  trade-off for a project this size).

One shared "bouncer" function (`get_current_user` in `deps.py`) checks that
wristband on every page that needs you to be logged in.

## 5. The admin side — building the venue

Someone has to actually create the concert and its seat map before anyone
can book it. We built a simple admin login (one shared password, not a full
account system — a deliberate simplification, not an oversight) and a
"create event" endpoint (`backend/app/routers/admin.py`) where the admin
just says: how many rows, how many columns, how many of the front rows are
VIP or premium. The server then generates every single seat automatically —
labeled A1, A2, B1, B2, and so on — and colors them by type.

## 6. Browsing events and seeing the seat map

A simple pair of endpoints (`backend/app/routers/events.py`) lets any logged
in user see the list of events, and then see one event's full seat grid —
which seats are free, held, or already booked.

## 7. The heart of the project: holding a seat safely

This is the part the whole project is really about. When you click a seat,
two independent safety nets kick in, one right after the other:

1. **A fast lock in Redis** (`SETNX` with a 5-second expiry). Think of it
   like a tiny "busy" sign someone puts on the seat the instant they touch
   it. Whoever hangs the sign first wins; everyone else immediately sees
   "busy" and is turned away — this happens in microseconds and never even
   has to ask the database.
2. **The database as the real judge.** Even with the lock, we don't just
   *trust* it blindly — we also run an update that only works `WHERE status
   = 'available'`, and we check how many rows it actually changed. If it
   changed 0 rows, someone beat us to it, full stop. This is the safety net
   *underneath* the safety net — if the Redis lock ever failed for any
   reason, the database itself would still refuse to double-book the seat.

We also added a rule: each person can only hold **one** seat per event at a
time, so nobody can grab every seat in a popular show and lock everyone else
out.

## 8. Seats that get abandoned

If someone holds a seat and then closes their laptop and walks away, that
seat shouldn't stay locked forever. So we added a background worker
(`backend/app/worker.py`) using **APScheduler**, which quietly wakes up every
10 seconds and asks the database: "any seat that's been held for more than 5
minutes with nobody confirming? Free it up." No human ever has to do this by
hand.

## 9. Confirming the booking, safely, even if the request repeats itself

Confirming a booking (`backend/app/routers/bookings.py`) requires an
"Idempotency-Key" — a random ID the browser makes up once per attempt. If
the exact same confirm request somehow gets sent twice (flaky wifi, a
double-click, a retry), the server recognizes the repeated key and just
returns the *same* original booking instead of creating a second one. And
because the database itself refuses to allow duplicate keys, this holds even
if two identical requests arrive at literally the same instant — we catch the
database's rejection and hand back whoever actually won.

Right after confirming, we also try to send a confirmation email
(`backend/app/services/email.py`). If email sending fails for any reason —
bad SMTP settings, network hiccup — that failure is only logged. It never
undoes the booking that's already safely saved in the database. A booking
you already paid for should never vanish just because an email server had a
bad day.

## 10. Remembering your past bookings

A simple endpoint (`GET /bookings/history`) lists everything you've ever
booked, most recent first.

## 11. The waiting room for big flash sales

For a very popular event, letting *everyone* hammer the seat map at once is
a recipe for chaos. So we built a waiting room using a Redis **sorted set**
(`backend/app/routers/queue.py`): when you join, you're added with your
join time as your "ticket number." Only the first N people (by ticket
number) are told "go ahead, you're in." When an admitted person finishes or
leaves, we simply remove them from the list — and because everyone's
position is just "how many people are ahead of me," the next person in line
is automatically promoted. Nobody has to manually hand out the freed-up slot.

## 12. The frontend — plain pages, no fancy build tools

We built four simple HTML pages with a bit of vanilla JavaScript, no
frameworks and no build step at all:

- `index.html` — sign up / log in
- `events.html` — browse events
- `seatmap.html` — the actual color-coded seat grid, hold/release/confirm
  buttons, a live countdown of your hold, and a "join waiting room" button
- `admin.html` — admin login and the create-event form
- `bookings.html` — your booking history

Every button just calls the FastAPI backend directly with `fetch()`.

## 13. Proving it actually works — the load test

Talk is cheap. So we wrote a small script
(`backend/tests/load_test.py`) that fires **300 requests at the exact same
seat, all at once**, and counts what happened. A correct system should show
exactly **one** success and 299 rejections. Here's the real result from
running it against this project:

```
Total requests fired:      300
200 (won the seat):        1
409 (correctly rejected):  299
other/errors:              0

PASS - exactly one request won the seat under concurrent load. No double-booking.
```

That's not a made-up number — it's what actually happened when we ran it.

## Difficulties faced during this build, and how they were solved

Real engineering always runs into snags. Here are the ones we actually hit
while building FlashBook, in the order we hit them:

**1. Port 5433 was already taken by a different project.**
Docker refused to start Postgres because something else on the machine
already owned that port. We didn't investigate or kill the other project —
we simply moved FlashBook's Postgres to port 5544 instead, and kept it that
way in `docker-compose.yml`. Small problem, small fix, but a good reminder
to always double-check "is this port really free" before assuming so.

**2. A database driver refused to install because of a conflicting Python
environment.** The very first attempt to install `psycopg2-binary` (the
usual way Python talks to PostgreSQL) failed with a strange, low-level
compiler error. Digging in, the cause was that this machine has an Anaconda
Python installation sitting in the background, and its leftover environment
variables were leaking into the build process, making the compiler look in
the *wrong* place for Python's internal headers. Rather than fight that
environment conflict, we swapped to a newer, actively-maintained database
driver — `psycopg` (version 3) with its `[binary]` option — which ships as a
ready-to-use pre-built package and never needs to compile anything at all.
Problem avoided entirely instead of fought.

**3. The load test looked broken, but the real bug was somewhere else
entirely.** The first real run of the 300-request load test came back with
alarming numbers: only 1 success, 63 rejections, and **236 unexplained
errors**. At first glance that looks like double-booking chaos. But reading
the server's own error log told the real story: it wasn't a booking bug at
all — it was `sqlalchemy.exc.TimeoutError: QueuePool limit ... reached`.
The database connection pool (which defaults to a small number of
connections) was simply too small to serve 300 requests arriving at the same
instant; most of them were just waiting in line for a free database
connection and giving up. The seat-booking logic itself was correct the
whole time — the one seat was never double-sold, even in the "broken" run.
The fix was to give the app a bigger pool of database connections
(`pool_size` and `max_overflow` in `backend/app/database.py`). After that
one-line-ish fix, the exact same test came back clean: 1 success, 299
correct rejections, 0 errors. This was a good reminder that a scary-looking
error doesn't always mean the core logic is wrong — sometimes it's the
plumbing around it.

## What we deliberately kept simple (and why)

- **One shared admin password**, not a full multi-admin permission system —
  this project is about proving booking correctness, not building an admin
  role hierarchy.
- **Payments are pretend.** No real payment processor is wired in; we just
  record a `payments` row so the data model looks realistic.
- **JWTs can't be revoked early.** A 24-hour token that can't be canceled
  mid-life is an accepted trade-off, not an oversight, for a project this
  size.
- **A synchronous backend**, not an async one. FastAPI can do both, but
  since the core trick (a conditional database update, checked by row count)
  is naturally simple with a normal synchronous database session, we didn't
  reach for async/await complexity that this project doesn't need.

## If this had to survive real-world scale one day

These weren't built, but they're the natural next steps: splitting the
database by event so one huge concert doesn't slow down every other event,
swapping the polling-based waiting room for a live push mechanism (like
WebSockets), and moving from a single Redis box to a small Redis cluster so
locking survives even if one Redis server goes down.
