const loginView = document.getElementById("login-view");
const signupView = document.getElementById("signup-view");

function showLoginView() {
  loginView.style.display = "block";
  signupView.style.display = "none";
  document.getElementById("signup-error").textContent = "";
  document.getElementById("signup-success").textContent = "";
}

function showSignupView() {
  loginView.style.display = "none";
  signupView.style.display = "block";
  document.getElementById("login-error").textContent = "";
  document.getElementById("login-success").textContent = "";
}

document.getElementById("show-signup-link").addEventListener("click", (e) => {
  e.preventDefault();
  showSignupView();
});

document.getElementById("show-login-link").addEventListener("click", (e) => {
  e.preventDefault();
  showLoginView();
});

document.getElementById("login-btn").addEventListener("click", async () => {
  const email = document.getElementById("login-email").value;
  const password = document.getElementById("login-password").value;
  const errorEl = document.getElementById("login-error");
  errorEl.textContent = "";
  document.getElementById("login-success").textContent = "";

  try {
    const data = await api("/auth/login", { method: "POST", body: { email, password } });
    setToken(data.access_token);
    window.location.href = "events.html";
  } catch (e) {
    errorEl.textContent = e.message;
  }
});

document.getElementById("signup-btn").addEventListener("click", async () => {
  const email = document.getElementById("signup-email").value;
  const password = document.getElementById("signup-password").value;
  const errorEl = document.getElementById("signup-error");
  const successEl = document.getElementById("signup-success");
  errorEl.textContent = "";
  successEl.textContent = "";

  try {
    await api("/auth/signup", { method: "POST", body: { email, password } });
    // Deliberately no auto-login here: after registering, send the user
    // back to the login form so they log in with their new credentials.
    document.getElementById("login-email").value = email;
    document.getElementById("login-password").value = "";
    showLoginView();
    document.getElementById("login-success").textContent = "Account created! Log in below.";
  } catch (e) {
    errorEl.textContent = e.message;
  }
});
