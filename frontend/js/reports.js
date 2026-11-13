const Reports = {
  pie: null,
  line: null,
  last: null, // remembers the last data so charts can be redrawn on theme change
  COLORS: ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#64748b"],

  // read the current theme colors from the CSS variables
  palette() {
    const css = getComputedStyle(document.documentElement);
    const get = (name) => css.getPropertyValue(name).trim();
    return {
      text: get("--text"),
      muted: get("--muted"),
      grid: get("--border"),
      surface: get("--surface"),
      primary: get("--primary")
    };
  },

  renderCharts(list, all) {
    this.last = { list, all };
    if (typeof Chart === "undefined") return; // Chart.js did not load (offline?)
    this.renderPie(list);
    this.renderTrend(all);
  },

  redraw() {
    if (this.last) this.renderCharts(this.last.list, this.last.all);
  },

  renderPie(list) {
    const p = this.palette();
    const byCat = UI.groupByGroup(list);

    if (this.pie) this.pie.destroy();
    this.pie = new Chart(document.getElementById("pieChart"), {
      type: "pie",
      data: {
        labels: Object.keys(byCat),
        datasets: [{
          data: Object.values(byCat),
          backgroundColor: this.COLORS,
          borderColor: p.surface,
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { color: p.text } },
          tooltip: {
            callbacks: { label: (c) => c.label + ": " + UI.money(c.parsed) }
          }
        }
      }
    });
  },

  renderTrend(all) {
    const p = this.palette();
    const byMonth = {};
    all.forEach(e => {
      const key = e.date.slice(0, 7);
      byMonth[key] = (byMonth[key] || 0) + e.amount;
    });

    const keys = Object.keys(byMonth).sort().slice(-12);
    const labels = keys.map(k => {
      const [y, m] = k.split("-");
      return new Date(y, m - 1).toLocaleString("en-IN", { month: "short", year: "numeric" });
    });
    const data = keys.map(k => byMonth[k]);

    if (this.line) this.line.destroy();
    this.line = new Chart(document.getElementById("trendChart"), {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: "Total spent",
          data,
          borderColor: p.primary,
          backgroundColor: p.primary + "26", // same color, transparent
          fill: true,
          tension: 0.3
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: { label: (c) => UI.money(c.parsed.y) }
          }
        },
        scales: {
          x: { ticks: { color: p.muted }, grid: { color: p.grid } },
          y: { beginAtZero: true, ticks: { color: p.muted }, grid: { color: p.grid } }
        }
      }
    });
  },

  exportCsv(list, month) {
    if (!list.length) return false;

    const text = (value) => {
      let s = String(value);
      if (/^[=+\-@]/.test(s)) s = "'" + s;
      return '"' + s.replace(/"/g, '""') + '"';
    };

    const rows = [...list]
      .sort((a, b) => a.date.localeCompare(b.date))
      .map(e => [e.date, text(e.title), text(e.category), e.amount.toFixed(2)].join(","));

    const csv = "\uFEFF" + ["Date,Title,Category,Amount", ...rows].join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");
    link.href = url;
    link.download = "expenses-" + (month || "all") + ".csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return true;
  }
};