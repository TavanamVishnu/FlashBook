function showCreateEventForm() {
  document.getElementById("login-card").style.display = "none";
  document.getElementById("create-event-card").style.display = "block";
}

if (getAdminToken()) {
  showCreateEventForm();
}

document.getElementById("admin-login-btn").addEventListener("click", async () => {
  const password = document.getElementById("admin-password").value;
  const errorEl = document.getElementById("admin-login-error");
  errorEl.textContent = "";
  try {
    const data = await api("/admin/login", { method: "POST", body: { password } });
    setAdminToken(data.access_token);
    showCreateEventForm();
  } catch (e) {
    errorEl.textContent = e.message;
  }
});

document.getElementById("create-event-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("create-event-error");
  const successEl = document.getElementById("create-event-success");
  errorEl.textContent = "";
  successEl.textContent = "";

  const startsAtLocal = document.getElementById("ev-starts-at").value;
  const body = {
    name: document.getElementById("ev-name").value,
    venue: document.getElementById("ev-venue").value,
    starts_at: startsAtLocal ? new Date(startsAtLocal).toISOString() : null,
    rows: parseInt(document.getElementById("ev-rows").value, 10),
    cols: parseInt(document.getElementById("ev-cols").value, 10),
    vip_rows: parseInt(document.getElementById("ev-vip-rows").value || "0", 10),
    premium_rows: parseInt(document.getElementById("ev-premium-rows").value || "0", 10),
  };

  try {
    const event = await api("/admin/events", { method: "POST", token: getAdminToken(), body });
    successEl.textContent = `Created "${event.name}" with ${event.rows * event.cols} seats.`;
  } catch (e) {
    errorEl.textContent = e.message;
  }
});
