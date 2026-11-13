const UI = {
  GROUPS: ["Food", "Shopping", "College", "Transport", "Living",
           "Bills", "Fun", "Health", "Other"],

  GROUP_ICONS: {
    Food: "🍽", Shopping: "🛍", College: "🎓", Transport: "🚌", Living: "🏠",
    Bills: "📱", Fun: "🎉", Health: "🏥", Other: "📦"
  },

  money(n) {
    return "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  },

  escape(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  },

  sum(list) {
    return list.reduce((s, x) => s + x.amount, 0);
  },

  groupByCategory(list) {
    return list.reduce((acc, e) => {
      acc[e.category] = (acc[e.category] || 0) + e.amount;
      return acc;
    }, {});
  },

  groupByGroup(list) {
    return list.reduce((acc, e) => {
      acc[e.group] = (acc[e.group] || 0) + e.amount;
      return acc;
    }, {});
  },

  /* ---------- top cards ---------- */
  renderSummary(spentList, incomeList, allSpent, allIncome) {
    const balance = this.sum(allIncome) - this.sum(allSpent);
    const byGroup = this.groupByGroup(spentList);
    const top = Object.entries(byGroup).sort((a, b) => b[1] - a[1])[0];

    document.getElementById("totalSpent").textContent = this.money(this.sum(spentList));
    document.getElementById("incomeMonth").textContent = this.money(this.sum(incomeList));

    const balanceEl = document.getElementById("balance");
    balanceEl.textContent = this.money(balance);
    balanceEl.classList.toggle("warn", balance < 0);

    document.getElementById("topGroup").textContent =
      top ? (this.GROUP_ICONS[top[0]] || "") + " " + top[0] : "-";
  },

  renderBudget(spent, budget) {
    const text = document.getElementById("budgetText");
    const bar = document.getElementById("budgetBar");

    if (!budget) {
      text.textContent = "Not set";
      text.classList.remove("warn");
      bar.style.width = "0%";
      bar.classList.remove("over");
      return;
    }

    const pct = (spent / budget) * 100;
    text.textContent = this.money(spent) + " / " + this.money(budget);
    bar.style.width = Math.min(pct, 100) + "%";
    bar.classList.toggle("over", pct >= 100);
    text.classList.toggle("warn", pct >= 80);
  },

  /* ---------- daily allowance ---------- */
  renderAllowance(month, spentThisMonth, budget, balance) {
    const valueEl = document.getElementById("dailyAllowance");
    const noteEl = document.getElementById("allowanceNote");

    const now = new Date();
    const thisMonth = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0");

    valueEl.classList.remove("warn");

    if (month !== thisMonth) {
      valueEl.textContent = "-";
      noteEl.textContent = "Select the current month to see your daily allowance.";
      return;
    }

    const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    const daysLeft = daysInMonth - now.getDate() + 1; // today counts

    // use the monthly budget if one is set, otherwise the balance
    const useBudget = budget > 0;
    const left = useBudget ? budget - spentThisMonth : balance;
    const basis = useBudget ? "monthly budget" : "balance";
    const dayWord = daysLeft === 1 ? "day" : "days";

    if (left <= 0) {
      valueEl.textContent = "₹0 / day";
      valueEl.classList.add("warn");
      noteEl.textContent = (useBudget ? "Budget used up" : "No balance left") +
        " · " + daysLeft + " " + dayWord + " left in the month";
      return;
    }

    valueEl.textContent = this.money(left / daysLeft) + " / day";
    noteEl.textContent = this.money(left) + " left · " + daysLeft + " " + dayWord +
      " to go · based on " + basis;
  },

  /* ---------- group budgets ---------- */
  renderGroupBudgets(budgets, spentList) {
    const box = document.getElementById("groupBudgetList");
    const spent = this.groupByGroup(spentList);

    box.innerHTML = this.GROUPS.map(g => {
      const limit = budgets[g] || 0;
      const used = spent[g] || 0;
      const pct = limit > 0 ? (used / limit) * 100 : 0;
      const text = limit > 0
        ? this.money(used) + " / " + this.money(limit)
        : this.money(used) + " spent";

      return `
        <div class="gb-row">
          <div class="gb-top">
            <span>${this.GROUP_ICONS[g]} ${g}</span>
            <span class="${limit > 0 && pct >= 80 ? "warn" : ""}">${text}</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill ${pct >= 100 ? "over" : ""}" style="width:${Math.min(pct, 100)}%"></div>
          </div>
          <input type="number" class="gb-input" data-group="${g}" min="0" step="1"
                 placeholder="Monthly limit (₹)" value="${limit || ""}">
        </div>`;
    }).join("");
  },

  /* ---------- by category bars ---------- */
  renderBars(list) {
    const box = document.getElementById("categoryBars");
    const totals = {};
    list.forEach(e => {
      if (!totals[e.category]) totals[e.category] = { amt: 0, icon: e.icon };
      totals[e.category].amt += e.amount;
    });

    const entries = Object.entries(totals).sort((a, b) => b[1].amt - a[1].amt);
    const max = entries.length ? entries[0][1].amt : 1;

    box.innerHTML = entries.length
      ? entries.map(([name, t]) => `
          <div class="bar-row">
            <div class="bar-label"><span>${this.escape(t.icon)} ${this.escape(name)}</span><span>${this.money(t.amt)}</span></div>
            <div class="bar-track"><div class="bar-fill" style="width:${(t.amt / max) * 100}%"></div></div>
          </div>`).join("")
      : '<p class="empty">No data yet.</p>';
  },

  /* ---------- expense list ---------- */
  renderList(list) {
    const ul = document.getElementById("expenseList");
    const empty = document.getElementById("emptyMsg");
    empty.hidden = list.length > 0;

    ul.innerHTML = [...list]
      .sort((a, b) => b.date.localeCompare(a.date))
      .map(e => `
        <li class="item">
          <div class="meta">
            <strong>${this.escape(e.title)}</strong>
            <small>${this.escape(e.icon)} ${this.escape(e.category)} · ${this.escape(e.group)} · ${e.date}</small>
          </div>
          <div class="right">
            <span class="amt">${this.money(e.amount)}</span>
            <button class="edit" data-id="${e.id}">Edit</button>
            <button class="del" data-id="${e.id}">Delete</button>
          </div>
        </li>`).join("");
  },

  /* ---------- income list ---------- */
  renderIncomeList(list) {
    const ul = document.getElementById("incomeList");
    const empty = document.getElementById("incomeEmpty");
    empty.hidden = list.length > 0;

    ul.innerHTML = [...list]
      .sort((a, b) => b.date.localeCompare(a.date))
      .map(i => `
        <li class="item">
          <div class="meta">
            <strong>${this.escape(i.source)}</strong>
            <small>${i.date}</small>
          </div>
          <div class="right">
            <span class="amt plus">+ ${this.money(i.amount)}</span>
            <button class="del del-income" data-id="${i.id}">Delete</button>
          </div>
        </li>`).join("");
  },

  /* ---------- category dropdowns and chips ---------- */
  optionHtml(c) {
    return `<option value="${c.id}">${this.escape(c.icon)} ${this.escape(c.name)}</option>`;
  },

  renderGroupOptions() {
    document.getElementById("catGroup").innerHTML = this.GROUPS
      .map(g => `<option value="${g}">${this.GROUP_ICONS[g]} ${g}</option>`)
      .join("");
  },

  renderCategoryOptions(categories) {
    const select = document.getElementById("category");
    const previous = select.value;
    const mine = categories.filter(c => c.custom);

    let html = "";
    if (mine.length) {
      html += '<optgroup label="⭐ My categories">' +
        mine.map(c => this.optionHtml(c)).join("") + "</optgroup>";
    }
    this.GROUPS.forEach(g => {
      const items = categories.filter(c => !c.custom && c.group === g);
      if (items.length) {
        html += `<optgroup label="${this.GROUP_ICONS[g]} ${g}">` +
          items.map(c => this.optionHtml(c)).join("") + "</optgroup>";
      }
    });

    select.innerHTML = html;
    if (previous && [...select.options].some(o => o.value === previous)) {
      select.value = previous;
    }
  },

  renderCustomCategories(categories) {
    const box = document.getElementById("customCategories");
    const empty = document.getElementById("customEmpty");
    const mine = categories.filter(c => c.custom);
    empty.hidden = mine.length > 0;

    box.innerHTML = mine.map(c => `
      <span class="chip">
        ${this.escape(c.icon)} ${this.escape(c.name)}
        <small>${this.escape(c.group)}</small>
        <button type="button" class="del-cat" data-id="${c.id}" aria-label="Delete category">✕</button>
      </span>`).join("");
  }
};