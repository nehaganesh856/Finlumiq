// common.js — Shared utilities for all application pages

const API = window.location.protocol === "https:"
  ? "/api"
  : "http://127.0.0.1:5000/api";

// ---------------------------------------------------------------
// API Helper
// ---------------------------------------------------------------
async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(API + path, {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      ...options
    });
  } catch {
    throw new Error("Cannot reach the server. Is the backend running on port 5000?");
  }
  let body = null;
  try { body = await response.json(); } catch { /* no body */ }
  if (response.status === 503) {
    const err = new Error("Database is unavailable. Please start MySQL from XAMPP and try again.");
    err.status = 503;
    throw err;
  }
  if (!response.ok) {
    const err = new Error((body && body.error) || "Request failed (" + response.status + ")");
    err.status = response.status;
    throw err;
  }
  return body;
} 

const API_CLIENT = {
  get: (path)         => request(path),
  post: (path, data)  => request(path, { method: "POST",   body: JSON.stringify(data) }),
  put: (path, data)   => request(path, { method: "PUT",    body: JSON.stringify(data) }),
  patch: (path, data) => request(path, { method: "PATCH",  body: JSON.stringify(data) }),
  del: (path)         => request(path, { method: "DELETE" }),
};

// ---------------------------------------------------------------
// Auth Guard — call at top of every protected page
// ---------------------------------------------------------------
async function requireAuth() {
  try {
    const user = await API_CLIENT.get("/auth/me");
    return user;
  } catch (err) {
    if (err.status === 401) {
      location.replace("login.html?reason=expired");
    } else {
      location.replace("login.html");
    }
    throw err;
  }
}

// ---------------------------------------------------------------
// Toast Notifications
// ---------------------------------------------------------------
function showToast(message, type = "success", duration = 3500) {
  const container = document.getElementById("toastContainer") || createToastContainer();
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  const icons = { success: "✓", error: "✕", warning: "⚠", info: "ℹ" };
  toast.innerHTML = `<span class="toast-icon">${icons[type] || "ℹ"}</span><span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("toast-show"));
  setTimeout(() => {
    toast.classList.remove("toast-show");
    toast.addEventListener("transitionend", () => toast.remove());
  }, duration);
}

function createToastContainer() {
  const container = document.createElement("div");
  container.id = "toastContainer";
  container.className = "toast-container";
  document.body.appendChild(container);
  return container;
}

// ---------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------
function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = String(str);
  return d.innerHTML;
}

function money(n) {
  return "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function formatDate(isoStr) {
  if (!isoStr) return "—";
  const d = new Date(isoStr + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function todayISO() {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

function daysUntil(isoDate) {
  if (!isoDate) return null;
  const today = new Date(); today.setHours(0,0,0,0);
  const target = new Date(isoDate + "T00:00:00");
  return Math.round((target - today) / 86400000);
}

function confirm2(message, title = "Confirm") {
  return new Promise(resolve => {
    // Use a custom modal if available, otherwise fall back to native confirm
    const modal = document.getElementById("confirmModal");
    if (!modal) return resolve(window.confirm(message));
    document.getElementById("confirmTitle").textContent = title;
    document.getElementById("confirmBody").textContent  = message;
    modal.classList.add("active");
    const yes = document.getElementById("confirmYes");
    const no  = document.getElementById("confirmNo");
    const cleanup = (val) => {
      modal.classList.remove("active");
      yes.replaceWith(yes.cloneNode(true));
      no.replaceWith(no.cloneNode(true));
      resolve(val);
    };
    document.getElementById("confirmYes").addEventListener("click", () => cleanup(true),  { once: true });
    document.getElementById("confirmNo").addEventListener("click",  () => cleanup(false), { once: true });
  });
}

// ---------------------------------------------------------------
// Theme
// ---------------------------------------------------------------
function initTheme() {
  const saved = localStorage.getItem("theme_v1");
  const theme = saved || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(theme, false);
  document.querySelectorAll(".theme-toggle-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(next, true);
    });
  });
}

function applyTheme(theme, save) {
  document.documentElement.setAttribute("data-theme", theme);
  if (save) { try { localStorage.setItem("theme_v1", theme); } catch {} }
  document.querySelectorAll(".theme-toggle-btn").forEach(btn => {
    btn.textContent = theme === "dark" ? "☀️" : "🌙";
    btn.setAttribute("aria-label", theme === "dark" ? "Switch to light mode" : "Switch to dark mode");
  });
}

// ---------------------------------------------------------------
// Reminder badge in nav
// ---------------------------------------------------------------
async function loadReminderBadge() {
  try {
    const data = await API_CLIENT.get("/reminders");
    const count = data.total_alerts || 0;
    document.querySelectorAll(".reminder-badge").forEach(el => {
      el.textContent = count;
      el.hidden = count === 0;
    });
  } catch { /* ignore */ }
}
