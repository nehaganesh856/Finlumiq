



























// auth.js - remembers who is logged in (in the browser) and handles logout.
// The "token" is a long text the server gives us after login.
// We send it with every request to prove who we are.

const Auth = {
  TOKEN_KEY: "auth_token_v1",
  USER_KEY: "auth_user_v1",

  getToken() {
    try {
      return localStorage.getItem(this.TOKEN_KEY);
    } catch {
      return null;
    }
  },

  getUser() {
    try {
      return JSON.parse(localStorage.getItem(this.USER_KEY));
    } catch {
      return null;
    }
  },

  isLoggedIn() {
    return Boolean(this.getToken());
  },

  // Returns true if saved, false if the browser blocked storage.
  save(token, user) {
    try {
      localStorage.setItem(this.TOKEN_KEY, token);
      localStorage.setItem(this.USER_KEY, JSON.stringify(user));
      return true;
    } catch {
      return false;
    }
  },

  clear() {
    try {
      localStorage.removeItem(this.TOKEN_KEY);
      localStorage.removeItem(this.USER_KEY);
    } catch {
      // nothing to clear
    }
  },

  // Forget the login and go to the login page.
  logout(reason) {
    this.clear();
    location.replace("login.html" + (reason ? "?reason=" + reason : ""));
  },

  // Call this at the top of a private page.
  requireLogin() {
    if (!this.isLoggedIn()) {
      location.replace("login.html");
      return false;
    }
    return true;
  }
};
