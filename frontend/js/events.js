requireLogin();

document.getElementById("logout-link").addEventListener("click", (e) => {
  e.preventDefault();
  clearToken();
  window.location.href = "index.html";
});

async function loadEvents() {
  const listEl = document.getElementById("events-list");
  try {
    const events = await api("/events", { token: getToken() });
    if (events.length === 0) {
      listEl.textContent = "No events yet. Ask an admin to create one.";
      return;
    }
    listEl.innerHTML = "";
    events.forEach((ev) => {
      const row = document.createElement("div");
      row.className = "event-item";
      row.innerHTML = `
        <div>
          <strong>${ev.name}</strong><br>
          <small>${ev.venue} — ${new Date(ev.starts_at).toLocaleString()}</small>
        </div>
      `;
      const btn = document.createElement("button");
      btn.textContent = "View seats";
      btn.addEventListener("click", () => {
        window.location.href = `seatmap.html?event_id=${ev.id}`;
      });
      row.appendChild(btn);
      listEl.appendChild(row);
    });
  } catch (e) {
    listEl.textContent = `Error: ${e.message}`;
  }
}

loadEvents();
