const API_URL = "http://127.0.0.1:5000/api";

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(API_URL + path, {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      ...options
    });
  } catch {
    throw new Error("Cannot reach the server. Is the backend running on port 5000?");
  }

  let body = null;
  try {
    body = await response.json();
  } catch {
    // response had no JSON body
  }

  if (!response.ok) {
    const err = new Error((body && body.error) || "Request failed (" + response.status + ")");
    err.status = response.status;
    throw err;
  }
  return body;
}

const Storage = {
  // ----- accounts -----
  register(name, email, password) {
    return request("/auth/register", {
      method: "POST",
      body: JSON.stringify({ name, email, password })
    });
  },
  login(email, password) {
    return request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password })
    });
  },
  logout() {
    return request("/auth/logout", { method: "POST" });
  },
  me() {
    return request("/auth/me");
  },

  // ----- categories -----
  getCategories() {
    return request("/categories");
  },
  addCategory(category) {
    return request("/categories", { method: "POST", body: JSON.stringify(category) });
  },
  removeCategory(id) {
    return request("/categories/" + id, { method: "DELETE" });
  },

  // ----- expenses -----
  getAll(month) {
    const query = month ? "?month=" + encodeURIComponent(month) : "";
    return request("/expenses" + query);
  },
  add(expense) {
    return request("/expenses", { method: "POST", body: JSON.stringify(expense) });
  },
  update(id, expense) {
    return request("/expenses/" + id, { method: "PUT", body: JSON.stringify(expense) });
  },
  remove(id) {
    return request("/expenses/" + id, { method: "DELETE" });
  },

  // ----- income -----
  getIncome() {
    return request("/income");
  },
  addIncome(income) {
    return request("/income", { method: "POST", body: JSON.stringify(income) });
  },
  removeIncome(id) {
    return request("/income/" + id, { method: "DELETE" });
  },

  // ----- overall monthly budget -----
  async getBudget() {
    const data = await request("/budget");
    return data.amount;
  },
  async setBudget(amount) {
    const data = await request("/budget", {
      method: "PUT",
      body: JSON.stringify({ amount })
    });
    return data.amount;
  },

  // ----- group budgets -----
  getGroupBudgets() {
    return request("/group-budgets");
  },
  setGroupBudgets(budgets) {
    return request("/group-budgets", {
      method: "PUT",
      body: JSON.stringify({ budgets })
    });
  }
};