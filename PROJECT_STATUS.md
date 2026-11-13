# Finlumiq — Auth Upgrade Implementation Complete

## ✅ What Was Implemented

### Database (run `auth_migration.sql` in phpMyAdmin)
| Change | Details |
|---|---|
| `users.email_verified` | Added `TINYINT(1)` column; existing users auto-set to `1` |
| `users.google_id` | Added for future Google OAuth |
| `users.updated_at` | Timestamp auto-updated on row change |
| `auth_tokens` | New table storing SHA-256 hashed tokens for email verify + password reset |

### Backend (56 total routes, 10 auth routes)
| Route | Method | Description |
|---|---|---|
| `/api/auth/register` | POST | Creates unverified account, sends verification email |
| `/api/auth/login` | POST | Checks `email_verified=1` before allowing login |
| `/api/auth/logout` | POST | Clears session |
| `/api/auth/me` | GET | Returns current user (includes `email_verified`) |
| `/api/auth/verify-email` | GET | Validates token, marks email verified, redirects |
| `/api/auth/resend-verification` | POST | Rate-limited resend |
| `/api/auth/forgot-password` | POST | Sends reset email (generic response) |
| `/api/auth/reset-password` | POST | Validates token, updates password hash |
| `/api/auth/profile` | PUT | Update display name |
| `/api/auth/change-password` | PUT | Change password (requires current) |

New modules: `backend/mail.py` (Gmail SMTP), `backend/rate_limit.py` (sliding-window limiter)

### Frontend Pages (5 auth pages)
| Page | File | Purpose |
|---|---|---|
| Login | `login.html` | Redesigned split-panel fintech style |
| Register | `register.html` | Standalone with strength meter + verification state |
| Verify Email | `verify-email.html` | Landing page from email link |
| Forgot Password | `forgot-password.html` | Email input + generic success |
| Reset Password | `reset-password.html` | Token from URL, new password form |

Shared: `css/auth.css`, `js/auth-shared.js`

---

## 🚀 Setup Instructions

### Step 1 — Run Database Migration
1. Open **phpMyAdmin** → Select `expense_tracker` database
2. Click **SQL** tab
3. Paste contents of [`backend/auth_migration.sql`](backend/auth_migration.sql)
4. Click **Go**

### Step 2 — Configure Gmail SMTP (for email to work)
1. Enable 2-Step Verification at [myaccount.google.com/security](https://myaccount.google.com/security)
2. Go to **Security → App Passwords** → Generate for "Mail"
3. Edit `backend/.env` and fill in:
```
MAIL_USERNAME=your_gmail@gmail.com
MAIL_PASSWORD=xxxx xxxx xxxx xxxx
MAIL_DEFAULT_SENDER=Finlumiq <your_gmail@gmail.com>
```

### Step 3 — Start the app
Double-click `start.bat` → opens both servers + browser.

---

## 🔒 Security Features Implemented
- ✅ Secure password hashing (Werkzeug pbkdf2:sha256)
- ✅ Tokens stored as SHA-256 hashes only (never raw in DB)
- ✅ Token expiry (30 min verify, 20 min reset)
- ✅ Single-use tokens (marked `used_at` on consumption)
- ✅ Rate limiting (10 login/15min, 5 register/10min, 3 resend/10min, 5 forgot/15min)
- ✅ Email enumeration protection (generic responses)
- ✅ Session cookie: `HttpOnly`, `SameSite=Lax`
- ✅ SQL injection protection (all parameterized queries)
- ✅ CORS origin restriction
- ✅ No credentials in frontend JS
- ✅ `.env` excluded from Git

---

## ⚠️ Works Without Gmail Config
If SMTP is not configured, the app still works — registration succeeds, the backend logs a warning, and the register page shows a warning message. Email verification can be bypassed for testing by setting `email_verified = 1` directly in phpMyAdmin.

---

## 🧪 Test Checklist
- [ ] Register new account → "Check your inbox" state shown
- [ ] Try same email again → "already registered" error
- [ ] Try login before verify → "verify your email" error with resend link
- [ ] (If SMTP configured) Click email link → "Email Verified!" success
- [ ] Login after verify → Dashboard loads ✅
- [ ] Wrong password → "Invalid email or password"
- [ ] Forgot password → Generic "if registered, link sent" message
- [ ] (If SMTP configured) Click reset link → Reset password page
- [ ] Reset password → Login with new password works ✅
- [ ] Reuse reset link → "invalid or expired" state shown
- [ ] All existing expense/income/budget/fees features still work ✅
