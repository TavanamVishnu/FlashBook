// When running locally this points at your local backend. Once you deploy
// the backend (see README.md), change this to that server's URL.
const API_BASE = "http://127.0.0.1:8000";

function getToken() {
  return localStorage.getItem("flashbook_token");
}

function setToken(token) {
  localStorage.setItem("flashbook_token", token);
}

function clearToken() {
  localStorage.removeItem("flashbook_token");
}

function getAdminToken() {
  return localStorage.getItem("flashbook_admin_token");
}

function setAdminToken(token) {
  localStorage.setItem("flashbook_admin_token", token);
}

async function api(path, { method = "GET", body, token, headers = {} } = {}) {
  const finalHeaders = { "Content-Type": "application/json", ...headers };
  if (token) finalHeaders["Authorization"] = `Bearer ${token}`;

  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    headers: finalHeaders,
    body: body ? JSON.stringify(body) : undefined,
  });

  let data = null;
  try {
    data = await resp.json();
  } catch (e) {
    data = null;
  }

  if (!resp.ok) {
    const detail = data && data.detail ? data.detail : `Request failed (${resp.status})`;
    const err = new Error(detail);
    err.status = resp.status;
    throw err;
  }
  return data;
}

function requireLogin() {
  if (!getToken()) {
    window.location.href = "index.html";
  }
}
