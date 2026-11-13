
// nav.js — Right-side navigation drawer for Finlumiq.

const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: "📊", href: "/pages/dashboard.html" },
  { id: "expenses", label: "Expenses", icon: "💸", href: "/pages/expenses.html" },
  { id: "income", label: "Income", icon: "💰", href: "/pages/income.html" },
  { id: "budgets", label: "Budgets", icon: "🎯", href: "/pages/budgets.html" },
  { id: "semesters", label: "Semesters", icon: "📅", href: "/pages/semesters.html" },
  { id: "college-fees", label: "College Fees", icon: "🏫", href: "/pages/college-fees.html" },
  { id: "savings-goals", label: "Savings Goals", icon: "🏦", href: "/pages/savings-goals.html" },
  { id: "scholarships", label: "Scholarships", icon: "🎓", href: "/pages/scholarships.html" },
  { id: "split-expenses", label: "Split Expenses", icon: "🤝", href: "/pages/split-expenses.html" },
  { id: "reports", label: "Reports", icon: "📈", href: "/pages/reports.html" },
  { id: "reminders", label: "Financial Alerts", icon: "🔔", href: "/pages/reminders.html", badge: true },
  { id: "phase5-reminders", label: "My Reminders", icon: "🗓️", href: "/pages/phase5-reminders.html" },
  { id: "ai-assistant", label: "AI Financial Assistant", icon: "🤖", href: "/pages/ai-assistant.html" },
  { id: "profile-settings", label: "Profile & Settings", icon: "⚙️", href: "/pages/profile-settings.html" },
  { id: "receipt-scanner", label: "Receipt Scanner", icon: "📷", href: "/pages/receipt-scanner.html" }
];

function buildNav(currentPageId, user) {
  const existing = document.getElementById("appNav");

  if (!existing) return;

  const itemsHtml = NAV_ITEMS.map(item => {
    const isActive = item.id === currentPageId;

    const badgeHtml = item.badge
      ? `<span class="nav-badge reminder-badge" hidden>0</span>`
      : "";

    const soonHtml = item.soon
      ? `<span class="nav-soon">Soon</span>`
      : "";

    return `
      <a href="${item.href}"
         class="nav-item${isActive ? " active" : ""}${item.soon ? " nav-disabled" : ""}"
         ${item.soon ? 'onclick="return false;"' : ""}
         ${isActive ? 'aria-current="page"' : ""}
         data-page="${item.id}">

        <span class="nav-icon">${item.icon}</span>
        <span class="nav-label">${item.label}</span>
        ${badgeHtml}
        ${soonHtml}
      </a>
    `;
  }).join("");

  const userName = user?.name || "Student";
  const userEmail = user?.email || "";

  existing.innerHTML = `
    <div class="nav-overlay" id="navOverlay"></div>

    <aside class="nav-drawer" id="navDrawer" aria-label="Main navigation">

      <div class="nav-header">
        <div class="nav-brand">
          <span class="nav-brand-icon">🎓</span>
          <div>
            <div class="nav-brand-name">Finlumiq</div>
            <div class="nav-brand-sub">Student Tracker</div>
          </div>
        </div>

        <button class="nav-close-btn"
                id="navCloseBtn"
                aria-label="Close menu">
          ✕
        </button>
      </div>

      <div class="nav-user">
        <div class="nav-avatar">
          ${escapeHtml(userName.charAt(0).toUpperCase())}
        </div>

        <div class="nav-user-info">
          <div class="nav-user-name">
            ${escapeHtml(userName)}
          </div>

          <div class="nav-user-email">
            ${escapeHtml(userEmail)}
          </div>
        </div>
      </div>

      <nav class="nav-links" role="navigation" aria-label="Main menu">
        ${itemsHtml}
      </nav>

      <div class="nav-footer">
        <button class="nav-logout-btn" id="navLogoutBtn">
          <span>🚪</span> Log out
        </button>

        <div class="nav-version">
          Smart Student Expense Tracker
        </div>
      </div>

    </aside>
  `;

  document.getElementById("navOverlay")
    .addEventListener("click", closeNav);

  document.getElementById("navCloseBtn")
    .addEventListener("click", closeNav);

  document.getElementById("navLogoutBtn")
    .addEventListener("click", async () => {
      try {
        await API_CLIENT.post("/auth/logout", {});
      } catch (error) {
        console.error("Logout error:", error);
      }

      location.replace("/login.html");
    });

  loadReminderBadge();
}

function openNav() {
  const drawer = document.getElementById("navDrawer");
  const overlay = document.getElementById("navOverlay");

  if (drawer && overlay) {
    drawer.classList.add("open");
    overlay.classList.add("active");
    document.body.style.overflow = "hidden";
  }
}

function closeNav() {
  const drawer = document.getElementById("navDrawer");
  const overlay = document.getElementById("navOverlay");

  if (drawer && overlay) {
    drawer.classList.remove("open");
    overlay.classList.remove("active");
  }

  document.body.style.overflow = "";
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("navOpenBtn");

  if (btn) {
    btn.addEventListener("click", openNav);
  }
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    closeNav();
  }
});
