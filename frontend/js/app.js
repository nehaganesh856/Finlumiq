const form = document.getElementById("expenseForm");
const monthFilter = document.getElementById("monthFilter");
const list = document.getElementById("expenseList");
const editId = document.getElementById("editId");
const submitBtn = document.getElementById("submitBtn");
const cancelBtn = document.getElementById("cancelBtn");
const errorBox = document.getElementById("errorBox");

const authView = document.getElementById("authView");
const appView = document.getElementById("appView");
const sessionControls = document.getElementById("sessionControls");
const userName = document.getElementById("userName");
const authError = document.getElementById("authError");
const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const tabLogin = document.getElementById("tabLogin");
const tabRegister = document.getElementById("tabRegister");

const incomeForm = document.getElementById("incomeForm");
const incomeList = document.getElementById("incomeList");
const categoryForm = document.getElementById("categoryForm");
const customCategories = document.getElementById("customCategories");
const groupBudgetForm = document.getElementById("groupBudgetForm");

let allItems = [];      // every expense of the logged-in user
let currentItems = [];  // expenses for the selected month
let allIncome = [];     // every income entry
let currentIncome = []; // income for the selected month
let categories = [];    // default + custom categories
let currentBudget = 0;  // overall monthly budget
let groupBudgets = {};  // monthly limit per group

// today's date in the user's own time zone (not UTC)
function todayISO() {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

/* ---------- messages ---------- */
function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
}

function setAuthError(message) {
  authError.textContent = message || "";
  authError.hidden = !message;
}

function handleError(err, prefix) {
  if (err.status === 401) {
    showAuth("Your session ended. Please log in again.");
    return;
  }
  showError(prefix + err.message);
}

/* ---------- switching screens ---------- */
function setAuthMode(mode) {
  const isLogin = mode === "login";
  loginForm.hidden = !isLogin;
  registerForm.hidden = isLogin;
  tabLogin.classList.toggle("active", isLogin);
  tabRegister.classList.toggle("active", !isLogin);
  setAuthError("");
}

function showAuth(message) {
  // clear everything belonging to the previous user
  allItems = [];
  currentItems = [];
  allIncome = [];
  currentIncome = [];
  categories = [];
  currentBudget = 0;
  groupBudgets = {};
  if (typeof Reports !== "undefined") Reports.last = null;
  resetForm();
  clearError();

  authView.hidden = false;
  appView.hidden = true;
  sessionControls.hidden = true;
  setAuthError(message);
}

function showApp(user) {
  authView.hidden = true;
  appView.hidden = false;
  sessionControls.hidden = false;
  userName.textContent = user.name;
  setAuthError("");

  UI.renderGroupOptions();
  document.getElementById("date").value = todayISO();
  document.getElementById("incomeDate").value = todayISO();
  monthFilter.value = todayISO().slice(0, 7);
  refresh();
}

/* ---------- loading and drawing data ---------- */
async function refresh() {
  try {
    const [items, budget, income, cats, gBudgets] = await Promise.all([
      Storage.getAll(),
      Storage.getBudget(),
      Storage.getIncome(),
      Storage.getCategories(),
      Storage.getGroupBudgets()
    ]);
    allItems = items;
    currentBudget = budget;
    allIncome = income;
    categories = cats;
    groupBudgets = gBudgets;
    clearError();
  } catch (err) {
    handleError(err, "");
    return;
  }

  const month = monthFilter.value;
  currentItems = month ? allItems.filter(e => e.date.startsWith(month)) : allItems;
  currentIncome = month ? allIncome.filter(i => i.date.startsWith(month)) : allIncome;

  const spentThisMonth = UI.sum(currentItems);
  const balance = UI.sum(allIncome) - UI.sum(allItems);

  try {
    UI.renderCategoryOptions(categories);
    UI.renderCustomCategories(categories);
    UI.renderSummary(currentItems, currentIncome, allItems, allIncome);
    UI.renderBudget(spentThisMonth, currentBudget);
    UI.renderAllowance(month, spentThisMonth, currentBudget, balance);
    UI.renderGroupBudgets(groupBudgets, currentItems);
    UI.renderBars(currentItems);
    UI.renderList(currentItems);
    UI.renderIncomeList(currentIncome);
    if (typeof Reports !== "undefined") {
      Reports.renderCharts(currentItems, allItems);
    }
  } catch (err) {
    showError("Display error: " + err.message);
  }
}

function resetForm() {
  form.reset();
  editId.value = "";
  document.getElementById("date").value = todayISO();
  submitBtn.textContent = "Add Expense";
  cancelBtn.hidden = true;
}

/* ---------- login, register, logout ---------- */
tabLogin.addEventListener("click", () => setAuthMode("login"));
tabRegister.addEventListener("click", () => setAuthMode("register"));

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  setAuthError("");
  try {
    const user = await Storage.login(
      document.getElementById("loginEmail").value,
      document.getElementById("loginPassword").value
    );
    loginForm.reset();
    showApp(user);
  } catch (err) {
    setAuthError(err.message);
  }
});

registerForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  setAuthError("");

  const password = document.getElementById("regPassword").value;
  if (password !== document.getElementById("regConfirm").value) {
    setAuthError("Passwords do not match.");
    return;
  }

  try {
    const user = await Storage.register(
      document.getElementById("regName").value.trim(),
      document.getElementById("regEmail").value,
      password
    );
    registerForm.reset();
    showApp(user);
  } catch (err) {
    setAuthError(err.message);
  }
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
  try {
    await Storage.logout();
  } catch {
    // even if the server is unreachable, leave the screen
  }
  setAuthMode("login");
  showAuth("");
});

/* ---------- expenses ---------- */
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = {
    title: document.getElementById("title").value.trim(),
    amount: parseFloat(document.getElementById("amount").value),
    category_id: parseInt(document.getElementById("category").value, 10),
    date: document.getElementById("date").value
  };
  if (!data.title || !(data.amount > 0) || !data.category_id || !data.date) return;

  try {
    if (editId.value) {
      await Storage.update(editId.value, data);
    } else {
      await Storage.add(data);
    }
    resetForm();
    await refresh();
  } catch (err) {
    handleError(err, "Could not save: ");
  }
});

list.addEventListener("click", async (e) => {
  const del = e.target.closest(".del");
  const edit = e.target.closest(".edit");

  if (del && confirm("Delete this expense?")) {
    try {
      await Storage.remove(del.dataset.id);
      await refresh();
    } catch (err) {
      handleError(err, "Could not delete: ");
    }
  }

  if (edit) {
    const item = currentItems.find(x => String(x.id) === edit.dataset.id);
    if (!item) return;
    document.getElementById("title").value = item.title;
    document.getElementById("amount").value = item.amount;
    document.getElementById("category").value = String(item.category_id);
    document.getElementById("date").value = item.date;
    editId.value = item.id;
    submitBtn.textContent = "Save Changes";
    cancelBtn.hidden = false;
    form.scrollIntoView({ behavior: "smooth" });
  }
});

cancelBtn.addEventListener("click", resetForm);

/* ---------- income ---------- */
incomeForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = {
    amount: parseFloat(document.getElementById("incomeAmount").value),
    source: document.getElementById("incomeSource").value,
    date: document.getElementById("incomeDate").value
  };
  if (!(data.amount > 0) || !data.date) return;

  try {
    await Storage.addIncome(data);
    incomeForm.reset();
    document.getElementById("incomeDate").value = todayISO();
    await refresh();
  } catch (err) {
    handleError(err, "Could not save income: ");
  }
});

incomeList.addEventListener("click", async (e) => {
  const del = e.target.closest(".del-income");
  if (!del || !confirm("Delete this income entry?")) return;
  try {
    await Storage.removeIncome(del.dataset.id);
    await refresh();
  } catch (err) {
    handleError(err, "Could not delete income: ");
  }
});

/* ---------- custom categories ---------- */
categoryForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = {
    name: document.getElementById("catName").value.trim(),
    group: document.getElementById("catGroup").value,
    icon: document.getElementById("catIcon").value.trim()
  };
  if (!data.name) return;

  try {
    await Storage.addCategory(data);
    categoryForm.reset();
    await refresh();
  } catch (err) {
    handleError(err, "Could not add category: ");
  }
});

customCategories.addEventListener("click", async (e) => {
  const del = e.target.closest(".del-cat");
  if (!del || !confirm("Delete this category?")) return;
  try {
    await Storage.removeCategory(del.dataset.id);
    await refresh();
  } catch (err) {
    handleError(err, "Could not delete category: ");
  }
});

/* ---------- overall budget ---------- */
document.getElementById("setBudgetBtn").addEventListener("click", async () => {
  const input = document.getElementById("budgetInput");
  const value = parseFloat(input.value);
  if (isNaN(value) || value < 0) {
    showError("Please enter a valid budget amount.");
    return;
  }

  try {
    await Storage.setBudget(value);
    input.value = "";
    await refresh();
  } catch (err) {
    handleError(err, "Could not save budget: ");
  }
});

/* ---------- group budgets ---------- */
groupBudgetForm.addEventListener("submit", async (e) => {
  e.preventDefault();

  const budgets = {};
  for (const input of groupBudgetForm.querySelectorAll(".gb-input")) {
    const raw = input.value.trim();
    const value = raw === "" ? 0 : parseFloat(raw);
    if (isNaN(value) || value < 0) {
      showError("Please enter valid amounts for the group budgets.");
      return;
    }
    budgets[input.dataset.group] = value;
  }

  try {
    await Storage.setGroupBudgets(budgets);
    await refresh();
  } catch (err) {
    handleError(err, "Could not save group budgets: ");
  }
});

/* ---------- CSV export and month filter ---------- */
document.getElementById("exportBtn").addEventListener("click", () => {
  const done = Reports.exportCsv(currentItems, monthFilter.value);
  if (!done) showError("There are no expenses to export for this period.");
});

monthFilter.addEventListener("change", refresh);

/* ---------- start the app ---------- */
async function init() {
  try {
    const user = await Storage.me();
    showApp(user);
  } catch (err) {
    showAuth(err.status === 401 ? "" : err.message);
  }
}

init();