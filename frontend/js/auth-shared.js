// auth-shared.js — Shared utilities for all Finlumiq auth pages


const API = (
  window.location.hostname === "localhost" ||
  window.location.hostname === "127.0.0.1"
)
  ? "http://127.0.0.1:5000/api"
  : "https://finlumiq-2.onrender.com/api";

// ----------------------------------------------------------------
// Theme
// ----------------------------------------------------------------
(function initTheme() {
  const saved = localStorage.getItem("theme_v1") || "light";
  document.documentElement.dataset.theme = saved;
  const btn = document.getElementById("themeBtn");
  if (btn) {
    btn.textContent = saved === "dark" ? "☀️ Light" : "🌙 Dark";
    btn.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      localStorage.setItem("theme_v1", next);
      btn.textContent = next === "dark" ? "☀️ Light" : "🌙 Dark";
    });
  }
})();

// ----------------------------------------------------------------
// API helpers
// ----------------------------------------------------------------
async function apiPost(path, body) {
  let res;
  try {
    res = await fetch(API + path, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Cannot reach the server. Make sure the Flask backend is running on port 5000.");
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 503) {
    throw new Error("Database is not running. Please start MySQL from XAMPP Control Panel and try again.");
  }
  if (!res.ok) throw new Error(data.error || "Request failed. Please try again.");
  return data;
}

async function apiGet(path) {
  const res = await fetch(API + path, { credentials: "include" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Request failed.");
  return data;
}

// ----------------------------------------------------------------
// Alert box
// ----------------------------------------------------------------
function showAlert(containerId, message, type = "error") {
  const el = document.getElementById(containerId);
  if (!el) return;
  const icons = { error: "❌", success: "✅", info: "ℹ️", warning: "⚠️" };
  el.innerHTML = `
    <div class="auth-alert ${type}">
      <span class="alert-icon">${icons[type] || "ℹ️"}</span>
      <span>${message}</span>
    </div>`;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function clearAlert(containerId) {
  const el = document.getElementById(containerId);
  if (el) el.innerHTML = "";
}

// ----------------------------------------------------------------
// Button loading state
// ----------------------------------------------------------------
function setButtonLoading(btn, loading, originalText) {
  btn.disabled = loading;
  if (loading) {
    btn.innerHTML = `<span class="btn-spinner"></span> Please wait…`;
  } else {
    btn.textContent = originalText;
  }
}

// ----------------------------------------------------------------
// Password visibility toggle
// ----------------------------------------------------------------
function setupPasswordToggle(inputId, toggleId) {
  const input  = document.getElementById(inputId);
  const toggle = document.getElementById(toggleId);
  if (!input || !toggle) return;
  toggle.addEventListener("click", () => {
    const show = input.type === "password";
    input.type   = show ? "text" : "password";
    toggle.textContent = show ? "🙈" : "👁️";
    toggle.title = show ? "Hide password" : "Show password";
  });
}

// ----------------------------------------------------------------
// Password strength meter
// ----------------------------------------------------------------
function setupStrengthMeter(inputId, fillId, labelId) {
  const input = document.getElementById(inputId);
  const fill  = document.getElementById(fillId);
  const label = document.getElementById(labelId);
  if (!input || !fill || !label) return;

  input.addEventListener("input", () => {
    const v = input.value;
    let score = 0;
    if (v.length >= 8)             score++;
    if (v.length >= 12)            score++;
    if (/[A-Z]/.test(v))           score++;
    if (/[0-9]/.test(v))           score++;
    if (/[^A-Za-z0-9]/.test(v))   score++;

    const labels = ["", "Very Weak", "Weak", "Fair", "Strong", "Very Strong"];
    const colors = ["", "#ef4444", "#f97316", "#eab308", "#22c55e", "#16a34a"];

    fill.style.width      = (score * 20) + "%";
    fill.style.background = colors[score] || "#e2e8f0";
    label.textContent     = labels[score] || "";
    label.style.color     = colors[score] || "var(--muted)";
  });
}

// ----------------------------------------------------------------
// Field-level validation helpers
// ----------------------------------------------------------------
function showFieldError(inputEl, errorEl, message) {
  inputEl.classList.add("error");
  errorEl.textContent = message;
  errorEl.classList.add("visible");
}

function clearFieldError(inputEl, errorEl) {
  inputEl.classList.remove("error");
  errorEl.classList.remove("visible");
  errorEl.textContent = "";
}

// ----------------------------------------------------------------
// Email format validation
// ----------------------------------------------------------------
function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

// ----------------------------------------------------------------
// Auto-redirect if already logged in (for login/register pages only)
// ----------------------------------------------------------------
async function redirectIfLoggedIn() {
  try {
    const res = await fetch(API + "/auth/me", { credentials: "include" });
    if (res.ok) {
      location.replace("dashboard.html");
    }
  } catch {
    // Not logged in or offline — stay on page
  }
}
