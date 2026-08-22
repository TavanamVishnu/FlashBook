requireLogin();

document.getElementById("logout-link").addEventListener("click", (e) => {
  e.preventDefault();
  clearToken();
  window.location.href = "index.html";
});

const params = new URLSearchParams(window.location.search);
const eventId = params.get("event_id");

let heldSeatId = null;
let heldSeatLabel = null;
let holdExpiresAt = null;
let countdownTimer = null;

async function loadEvent() {
  try {
    const ev = await api(`/events/${eventId}`, { token: getToken() });
    document.getElementById("event-title").textContent = ev.name;
    document.getElementById("event-meta").textContent = `${ev.venue} — ${new Date(ev.starts_at).toLocaleString()}`;

    const grid = document.getElementById("seat-grid");
    grid.style.gridTemplateColumns = `repeat(${ev.cols}, 36px)`;
    grid.innerHTML = "";

    ev.seats
      .sort((a, b) => a.row - b.row || a.col - b.col)
      .forEach((seat) => {
        const div = document.createElement("div");
        const mine = seat.status === "held"; // refined below once we know our own hold
        div.className = `seat ${seat.status} ${seat.seat_type}`;
        div.textContent = seat.label;
        div.title = `${seat.label} (${seat.seat_type})`;
        div.dataset.seatId = seat.id;
        div.dataset.label = seat.label;

        if (seat.id === heldSeatId) {
          div.classList.add("mine");
        }

        if (seat.status === "available" || seat.id === heldSeatId) {
          div.addEventListener("click", () => onSeatClick(seat));
        }
        grid.appendChild(div);
      });
  } catch (e) {
    document.getElementById("event-title").textContent = `Error: ${e.message}`;
  }
}

async function onSeatClick(seat) {
  if (seat.id === heldSeatId) return; // already holding this one
  try {
    const result = await api(`/seats/${seat.id}/hold`, { method: "POST", token: getToken() });
    heldSeatId = seat.id;
    heldSeatLabel = seat.label;
    holdExpiresAt = new Date(result.hold_expires_at);
    showHoldPanel();
    await loadEvent();
  } catch (e) {
    alert(e.message);
  }
}

function showHoldPanel() {
  document.getElementById("hold-panel").style.display = "block";
  document.getElementById("held-seat-label").textContent = heldSeatLabel;
  document.getElementById("hold-error").textContent = "";
  document.getElementById("hold-success").textContent = "";

  if (countdownTimer) clearInterval(countdownTimer);
  countdownTimer = setInterval(() => {
    const secondsLeft = Math.max(0, Math.floor((holdExpiresAt - new Date()) / 1000));
    document.getElementById("countdown").textContent = `${secondsLeft}s remaining`;
    if (secondsLeft === 0) {
      clearInterval(countdownTimer);
      hideHoldPanel();
      loadEvent();
    }
  }, 1000);
}

function hideHoldPanel() {
  heldSeatId = null;
  heldSeatLabel = null;
  document.getElementById("hold-panel").style.display = "none";
}

document.getElementById("confirm-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("hold-error");
  const successEl = document.getElementById("hold-success");
  errorEl.textContent = "";
  try {
    const idempotencyKey = crypto.randomUUID();
    const booking = await api("/bookings/confirm", {
      method: "POST",
      token: getToken(),
      headers: { "Idempotency-Key": idempotencyKey },
      body: { seat_id: heldSeatId },
    });
    successEl.textContent = `Booked! Seat ${booking.seat_label}, booking #${booking.id}. Confirmation email sent (if SMTP is configured).`;
    if (countdownTimer) clearInterval(countdownTimer);
    hideHoldPanel();
    await loadEvent();
  } catch (e) {
    errorEl.textContent = e.message;
  }
});

document.getElementById("release-btn").addEventListener("click", async () => {
  try {
    await api(`/seats/${heldSeatId}/release`, { method: "POST", token: getToken() });
    if (countdownTimer) clearInterval(countdownTimer);
    hideHoldPanel();
    await loadEvent();
  } catch (e) {
    document.getElementById("hold-error").textContent = e.message;
  }
});

document.getElementById("queue-join-btn").addEventListener("click", async () => {
  try {
    const status = await api(`/events/${eventId}/queue/join`, { method: "POST", token: getToken() });
    renderQueueStatus(status);
  } catch (e) {
    document.getElementById("queue-status").textContent = `Error: ${e.message}`;
  }
});

function renderQueueStatus(status) {
  const el = document.getElementById("queue-status");
  if (status.position === null) {
    el.textContent = "Not in the queue.";
  } else if (status.admitted) {
    el.textContent = `You're admitted! Position ${status.position}. Go ahead and book a seat above.`;
  } else {
    el.textContent = `You're in line — position ${status.position}. Please wait.`;
  }
}

loadEvent();
