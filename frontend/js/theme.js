const Theme = {
  KEY: "theme_v1",

  current() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  },

  apply(theme, save) {
    document.documentElement.setAttribute("data-theme", theme);

    if (save) {
      try {
        localStorage.setItem(this.KEY, theme);
      } catch {
        // storage not available, the theme just won't be remembered
      }
    }

    const btn = document.getElementById("themeToggle");
    if (btn) {
      btn.textContent = theme === "dark" ? "☀️" : "🌙";
      btn.setAttribute(
        "aria-label",
        theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
      );
    }

    // redraw charts so their colors match the new theme
    if (typeof Reports !== "undefined") Reports.redraw();
  },

  init() {
    this.apply(this.current(), false);
    document.getElementById("themeToggle").addEventListener("click", () => {
      this.apply(this.current() === "dark" ? "light" : "dark", true);
    });
  }
};

Theme.init();