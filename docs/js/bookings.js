requireLogin();

document.getElementById("logout-link").addEventListener("click", (e) => {
  e.preventDefault();
  clearToken();
  window.location.href = "index.html";
});

async function loadBookings() {
  const listEl = document.getElementById("bookings-list");
  try {
    const bookings = await api("/bookings/history", { token: getToken() });
    if (bookings.length === 0) {
      listEl.textContent = "No bookings yet.";
      return;
    }
    listEl.innerHTML = "";
    bookings.forEach((b) => {
      const row = document.createElement("div");
      row.className = "event-item";
      row.innerHTML = `
        <div>
          <strong>${b.event_name}</strong> — Seat ${b.seat_label} (${b.seat_type})<br>
          <small>Booking #${b.id} · ${b.status} · ${new Date(b.created_at).toLocaleString()}</small>
        </div>
      `;
      listEl.appendChild(row);
    });
  } catch (e) {
    listEl.textContent = `Error: ${e.message}`;
  }
}

loadBookings();
