import hashlib
import logging
import os
import re
import secrets
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
import mysql.connector
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, session
from flask_cors import CORS
from mysql.connector import errors as mysql_errors
from werkzeug.security import check_password_hash, generate_password_hash
from receipt_scanner_phase3_routes import register_receipt_scanner_phase3_routes
import mail as mailer
from rate_limit import (
    forgot_limiter,
    login_limiter,
    register_limiter,
    resend_limiter,
    reset_limiter,
)
import secrets
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_auth_requests
import smtplib
from email.message import EmailMessage
# Load environment variables from backend/.env
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
  
    raise RuntimeError("SECRET_KEY is missing in backend/.env")
app.config["GOOGLE_CLIENT_ID"] = (
    "10575419495-ahcn2dttd279kurp8ihha1p6ujg84ifp.apps.googleusercontent.com"
)

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:8000")


app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="None",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)


CORS(app, origins=[FRONTEND_ORIGIN], supports_credentials=True)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

GROUPS = ["Food", "Shopping", "College", "Transport", "Living",
          "Bills", "Fun", "Health", "Other"]
INCOME_SOURCES = ["Pocket Money", "Scholarship", "Part-time Job", "Gift", "Other"]
FEE_CATEGORIES = ["Tuition", "Examination", "Hostel", "Transport",
                  "Library", "Laboratory", "Admission", "Other"]
PAYMENT_METHODS = ["Cash", "UPI", "Bank Transfer", "Card", "Other"]
SEMESTER_STATUSES = ["Upcoming", "Active", "Completed"]
GOAL_STATUSES = ["Active", "Completed", "Paused", "Cancelled"]
SCHOLARSHIP_STATUSES = [
    "Not Applied", "Applied", "Under Review", "Approved",
    "Rejected", "Payment Pending", "Partially Received", "Received"
]



def get_db():
    try:
        db_config = {
            "host": os.getenv("DB_HOST", "127.0.0.1"),
            "port": int(os.getenv("DB_PORT", "3306")),
            "user": os.getenv("DB_USER", "root"),
            "password": os.getenv("DB_PASSWORD", ""),
            "database": os.getenv("DB_NAME", "expense_tracker"),
            "charset": "utf8mb4",
            "connection_timeout": 15,
            "autocommit": False
        }

        # Enable TLS when DB_SSL_CA is configured (TiDB Cloud).
        ssl_ca = os.getenv("DB_SSL_CA")

        if ssl_ca:
            ca_path = Path(ssl_ca)

            if not ca_path.is_absolute():
                ca_path = Path(__file__).resolve().parent / ca_path

            if not ca_path.is_file():
                raise FileNotFoundError(
                    f"Database CA certificate not found: {ca_path}"
                )

            db_config.update({
                "ssl_ca": str(ca_path),
                "ssl_verify_cert": True,
                "ssl_verify_identity": True
            })

        connection = mysql.connector.connect(**db_config)

        if not connection.is_connected():
            raise mysql.connector.Error(
                "MySQL connection was not established."
            )

        logger.info(
            "MySQL connected successfully: database=%s host=%s port=%s",
            db_config["database"],
            db_config["host"],
            db_config["port"]
        )

        return connection

    except (mysql.connector.Error, ValueError, OSError):
        logger.exception("MySQL database connection failed")

        from flask import abort
        abort(503)



@app.errorhandler(503)
def service_unavailable(e):
    return jsonify({
        "error": "Database unavailable. Please start MySQL and try again.",
        "hint": "Start MySQL from XAMPP Control Panel or run start.bat as Administrator."
    }), 503


@app.errorhandler(500)
def internal_error(e):
    logger.error("Unhandled error: %s", e)
    return jsonify({"error": "An internal server error occurred. Check the backend terminal."}), 500


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "API endpoint not found"}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "HTTP method not allowed for this endpoint"}), 405


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Please log in"}), 401
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------
# Health
# ---------------------------------------------------------------
@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------

def _hash_token(raw: str) -> str:
    """Return SHA-256 hex of a raw token string."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _create_auth_token(db, user_id: int, purpose: str, expires_minutes: int) -> str:
    """
    Generate a secure random token, store its hash in auth_tokens, return raw token.
    Invalidates any previous unused tokens for the same user+purpose.
    """
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    expires_at = datetime.utcnow() + timedelta(minutes=expires_minutes)
    cur = db.cursor()
    # Invalidate old unused tokens for this user+purpose
    cur.execute(
        "DELETE FROM auth_tokens WHERE user_id = %s AND purpose = %s AND used_at IS NULL",
        (user_id, purpose)
    )
    cur.execute(
        "INSERT INTO auth_tokens (user_id, token_hash, purpose, expires_at) VALUES (%s,%s,%s,%s)",
        (user_id, token_hash, purpose, expires_at)
    )
    db.commit()
    return raw


def _consume_token(db, raw: str, purpose: str):
    """
    Validate and consume a token. Returns the matching row dict, or None if invalid/expired.
    Marks token as used on success.
    """
    token_hash = _hash_token(raw)
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT * FROM auth_tokens WHERE token_hash = %s AND purpose = %s",
        (token_hash, purpose)
    )
    row = cur.fetchone()
    if not row:
        return None
    if row["used_at"] is not None:
        return None  # Already used
    if datetime.utcnow() > row["expires_at"]:
        return None  # Expired
    # Mark used
    cur.execute("UPDATE auth_tokens SET used_at = %s WHERE id = %s",
                (datetime.utcnow(), row["id"]))
    db.commit()
    return row


# ---------------------------------------------------------------
# Auth — Accounts
# ---------------------------------------------------------------

@app.route("/api/auth/register", methods=["POST"])
def register():
    ip = request.remote_addr or "unknown"
    if not register_limiter.allow(ip):
        return jsonify({"error": "Too many registration attempts. Please wait a few minutes."}), 429

    data = request.get_json(silent=True) or {}
    name     = str(data.get("name", "")).strip()
    email    = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not name or len(name) > 80:
        return jsonify({"error": "Name is required (max 80 characters)"}), 400
    if not EMAIL_RE.match(email) or len(email) > 120:
        return jsonify({"error": "Please enter a valid email address"}), 400
    if len(password) < 8 or len(password) > 128:
        return jsonify({"error": "Password must be 8 to 128 characters"}), 400

    mail_configured = mailer.is_configured()

    db = get_db()
    try:
        cur = db.cursor()

        # Check if email_verified column exists; if not, insert without it
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users' AND COLUMN_NAME='email_verified'"
        )
        has_verified_col = cur.fetchone()[0] > 0

        try:
            if has_verified_col:
                # Auto-verify if mail not configured — no point gating login on email
                verified_val = 0 if mail_configured else 1
                cur.execute(
                    "INSERT INTO users (name, email, password_hash, email_verified) VALUES (%s,%s,%s,%s)",
                    (name, email, generate_password_hash(password), verified_val),
                )
            else:
                cur.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (%s,%s,%s)",
                    (name, email, generate_password_hash(password)),
                )
            db.commit()
            email_sent = send_registration_email(email, name)
        except mysql_errors.IntegrityError:
            return jsonify({
                "error": "This email address is already registered. Please log in."
            }), 409
        user_id = cur.lastrowid

        # Try to create email verification token (requires auth_tokens table)
        raw_token = None
        if mail_configured and has_verified_col:
            try:
                raw_token = _create_auth_token(db, user_id, "email_verify", 30)
            except Exception as token_err:
                logger.warning("Could not create auth token (run auth_migration.sql?): %s", token_err)
    finally:
        db.close()

    # If mail not configured OR token table missing — log user in immediately
    if not mail_configured or raw_token is None:
        session.clear()
        session.permanent = True
        session["user_id"] = user_id
        return jsonify({
            "id": user_id, "name": name, "email": email,
            "message": "Account created successfully.",
            "needs_verification": False,
            "mail_configured": False,
            "welcome_email_sent":email_sent
        }), 201

    # Send verification email
    sent = mailer.send_verification_email(email, name, raw_token)
    logger.info("Verification email sent=%s to %s", sent, email)

    return jsonify({
        "message": "Account created. Please check your email to verify your account.",
        "needs_verification": True,
        "email": email,
        "mail_sent": sent,
        "mail_configured": True,
    }), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    ip = request.remote_addr or "unknown"
    if not login_limiter.allow(ip):
        return jsonify({"error": "Too many login attempts. Please wait a few minutes."}), 429

    data     = request.get_json(silent=True) or {}
    email    = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        # Try with email_verified column first; fall back for old schema
        try:
            cur.execute(
                "SELECT id, name, email, password_hash, email_verified FROM users WHERE email = %s",
                (email,)
            )
        except Exception:
            cur.execute(
                "SELECT id, name, email, password_hash FROM users WHERE email = %s",
                (email,)
            )
        user = cur.fetchone()
    finally:
        db.close()

    # Check credentials — constant-time to prevent email enumeration
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401

    # Check email verification.
    # email_verified == 0 means unverified. None or 1 means verified (or column missing).
    email_verified = user.get("email_verified")
    if email_verified is not None and email_verified == 0:
        return jsonify({
            "error": "Please verify your email address before logging in. Check your inbox.",
            "needs_verification": True,
            "email": email,
        }), 403

    # Successful login
    login_limiter.reset(ip)
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    return jsonify({"id": user["id"], "name": user["name"], "email": user["email"]})


@app.route("/api/auth/logout", methods=["POST", "GET", "DELETE"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})

@app.route("/api/auth/google", methods=["POST"])
def google_login():
    ip = request.remote_addr or "unknown"

    if not login_limiter.allow(ip):
        return jsonify({
            "error": "Too many login attempts. Please wait a few minutes."
        }), 429

    data = request.get_json(silent=True) or {}
    token = str(data.get("credential", "")).strip()
    link_password = str(data.get("password", ""))

    client_id = app.config.get("GOOGLE_CLIENT_ID")

    if not client_id or client_id == "PASTE_YOUR_GOOGLE_CLIENT_ID_HERE":
        return jsonify({
            "error": "Google login is not configured on the server."
        }), 500

    if not token:
        return jsonify({
            "error": "Google credential is missing."
        }), 400

    # Verify the Google ID token on the backend.
    try:
        google_info = google_id_token.verify_oauth2_token(
            token,
            google_auth_requests.Request(),
            client_id
        )
    except ValueError:
        return jsonify({
            "error": "Invalid or expired Google sign-in. Please try again."
        }), 401
    except Exception:
        logger.exception("Google token verification failed")
        return jsonify({
            "error": "Unable to verify Google sign-in. Please try again."
        }), 503

    # Only accept verified Google email accounts.
    if google_info.get("iss") not in (
        "accounts.google.com",
        "https://accounts.google.com"
    ):
        return jsonify({"error": "Invalid Google token issuer."}), 401

    if google_info.get("email_verified") is not True:
        return jsonify({
            "error": "Your Google email address must be verified."
        }), 403

    google_sub = str(google_info.get("sub", "")).strip()
    email = str(google_info.get("email", "")).strip().lower()
    name = str(google_info.get("name", "")).strip()[:80]

    if not google_sub or not email or not EMAIL_RE.match(email):
        return jsonify({
            "error": "Google did not return valid account information."
        }), 400

    if not name:
        name = email.split("@")[0][:80]

    db = get_db()

    try:
        cur = db.cursor(dictionary=True)

        # Confirm that the Google identifier migration exists.
        cur.execute(
            "SELECT COUNT(*) AS column_count "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() "
            "AND TABLE_NAME='users' "
            "AND COLUMN_NAME='google_sub'"
        )

        if cur.fetchone()["column_count"] == 0:
            return jsonify({
                "error": "Google login database migration is missing. "
                         "Add the google_sub column to users first."
            }), 500

        # Check whether the optional email_verified column exists.
        cur.execute(
            "SELECT COUNT(*) AS column_count "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() "
            "AND TABLE_NAME='users' "
            "AND COLUMN_NAME='email_verified'"
        )

        has_verified_col = cur.fetchone()["column_count"] > 0

        # First look for an already linked Google account.
        cur.execute(
            "SELECT id, name, email, password_hash, google_sub "
            "FROM users WHERE google_sub=%s LIMIT 1",
            (google_sub,)
        )

        user = cur.fetchone()

        if user:
            # Returning Google user: sign in.
            user_id = user["id"]

        else:
            # Check whether an Finlumiq account already uses this email.
            cur.execute(
                "SELECT id, name, email, password_hash, google_sub "
                "FROM users WHERE email=%s LIMIT 1",
                (email,)
            )

            existing_user = cur.fetchone()

            if existing_user:

                # Never overwrite a different linked Google identity.
                if existing_user.get("google_sub"):
                    return jsonify({
                        "error": "This Finlumiq account is already linked "
                                 "to another Google account."
                    }), 409

                # Require the existing Finlumiq password for safe linking.
                if not link_password:
                    return jsonify({
                        "error": "An Finlumiq account already exists "
                                 "with this email. Enter its existing password "
                                 "once to link Google sign-in.",
                        "link_required": True
                    }), 409

                if not check_password_hash(
                    existing_user["password_hash"],
                    link_password
                ):
                    return jsonify({
                        "error": "Incorrect Finlumiq password. "
                                 "Google account was not linked."
                    }), 401

                updates = ["google_sub=%s"]
                params = [google_sub]

                # A verified Google account can verify the matching email.
                if has_verified_col:
                    updates.append("email_verified=1")

                params.append(existing_user["id"])

                cur.execute(
                    "UPDATE users SET " + ", ".join(updates) +
                    " WHERE id=%s AND google_sub IS NULL",
                    tuple(params)
                )

                if cur.rowcount != 1:
                    db.rollback()
                    return jsonify({
                        "error": "This account was changed during linking. "
                                 "Please try signing in again."
                    }), 409

                db.commit()
                user_id = existing_user["id"]

            else:
                # New Google user: create an account.
                # Generate an unknown random password because the existing
                # database requires password_hash to be non-null.
                random_password = secrets.token_urlsafe(48)
                password_hash = generate_password_hash(random_password)

                if has_verified_col:
                    cur.execute(
                        "INSERT INTO users "
                        "(name, email, password_hash, google_sub, email_verified) "
                        "VALUES (%s, %s, %s, %s, 1)",
                        (name, email, password_hash, google_sub)
                    )
                else:
                    cur.execute(
                        "INSERT INTO users "
                        "(name, email, password_hash, google_sub) "
                        "VALUES (%s, %s, %s, %s)",
                        (name, email, password_hash, google_sub)
                    )

                db.commit()
                user_id = cur.lastrowid

    except mysql_errors.IntegrityError:
        db.rollback()
        return jsonify({
            "error": "This Google account or email is already registered. "
                     "Please try signing in again."
        }), 409

    except Exception:
        db.rollback()
        logger.exception("Finlumiq Google login database error")
        return jsonify({
            "error": "Unable to complete Google login. "
                     "Please try again."
        }), 500

    finally:
        db.close()

    # Establish the same Flask session used by password login.
    login_limiter.reset(ip)

    session.clear()
    session.permanent = True
    session["user_id"] = user_id

    return jsonify({
        "id": user_id,
        "name": name if not user else user["name"],
        "email": email if not user else user["email"],
        "message": "Google sign-in successful."
    }), 200



@app.route("/api/auth/me", methods=["GET"])
def me():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT id, name, email, email_verified FROM users WHERE id = %s", (user_id,)
            )
        except Exception:
            cur.execute(
                "SELECT id, name, email FROM users WHERE id = %s", (user_id,)
            )
        user = cur.fetchone()
    finally:
        db.close()

    if not user:
        session.clear()
        return jsonify({"error": "Not logged in"}), 401
    return jsonify(user)


@app.route("/api/auth/verify-email", methods=["GET"])
def verify_email():
    """Called when user clicks the email link: /api/auth/verify-email?token=..."""
    raw = request.args.get("token", "").strip()
    if not raw:
        return redirect(f"{mailer.FRONTEND_URL}/verify-email.html?status=invalid")

    db = get_db()
    try:
        row = _consume_token(db, raw, "email_verify")
        if not row:
            return redirect(f"{mailer.FRONTEND_URL}/verify-email.html?status=invalid")

        cur = db.cursor()
        cur.execute("UPDATE users SET email_verified = 1 WHERE id = %s", (row["user_id"],))
        db.commit()
    finally:
        db.close()

    return redirect(f"{mailer.FRONTEND_URL}/verify-email.html?status=success")


@app.route("/api/auth/resend-verification", methods=["POST"])
def resend_verification():
    """Resend email verification link."""
    ip = request.remote_addr or "unknown"
    if not resend_limiter.allow(ip):
        return jsonify({"error": "Too many requests. Please wait a few minutes."}), 429

    data  = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    if not email:
        return jsonify({"error": "Email is required"}), 400

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT id, name, email_verified FROM users WHERE email = %s", (email,)
        )
        user = cur.fetchone()
        if not user or user["email_verified"]:
            # Generic response — don't reveal whether account exists
            return jsonify({"message": "If this email is registered and unverified, a new link has been sent."})

        raw_token = _create_auth_token(db, user["id"], "email_verify", 30)
    finally:
        db.close()

    mailer.send_verification_email(email, user["name"], raw_token)
    return jsonify({"message": "Verification email sent. Please check your inbox."})


@app.route("/api/auth/forgot-password", methods=["POST"])
def forgot_password():
    """Generate a password reset link and send it."""
    ip = request.remote_addr or "unknown"
    if not forgot_limiter.allow(ip):
        return jsonify({"error": "Too many requests. Please wait a few minutes."}), 429

    data  = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    if not email:
        return jsonify({"error": "Email is required"}), 400

    # Generic response regardless of outcome (prevents email enumeration)
    generic = {"message": "If that email is registered, a password reset link has been sent."}

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id, name FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        if not user:
            return jsonify(generic)

        raw_token = _create_auth_token(db, user["id"], "password_reset", 20)
    finally:
        db.close()

    mailer.send_reset_email(email, user["name"], raw_token)
    return jsonify(generic)


@app.route("/api/auth/reset-password", methods=["POST"])
def reset_password():
    """Validate reset token and update password."""
    ip = request.remote_addr or "unknown"
    if not reset_limiter.allow(ip):
        return jsonify({"error": "Too many requests. Please wait a few minutes."}), 429

    data      = request.get_json(silent=True) or {}
    raw       = str(data.get("token", "")).strip()
    new_pw    = str(data.get("new_password", ""))
    confirm   = str(data.get("confirm_password", ""))

    if not raw:
        return jsonify({"error": "Reset token is missing or invalid."}), 400
    if len(new_pw) < 8 or len(new_pw) > 128:
        return jsonify({"error": "Password must be 8 to 128 characters"}), 400
    if new_pw != confirm:
        return jsonify({"error": "Passwords do not match"}), 400

    db = get_db()
    try:
        row = _consume_token(db, raw, "password_reset")
        if not row:
            return jsonify({"error": "This reset link is invalid or has expired. Please request a new one."}), 400

        user_id = row["user_id"]
        cur = db.cursor()
        cur.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (generate_password_hash(new_pw), user_id)
        )
        # Invalidate any other outstanding reset tokens for this user
        cur.execute(
            "DELETE FROM auth_tokens WHERE user_id = %s AND purpose = 'password_reset' AND used_at IS NULL",
            (user_id,)
        )
        db.commit()
    finally:
        db.close()

    # Revoke active session if user is currently logged in with this account
    if session.get("user_id") == user_id:
        session.clear()

    return jsonify({"message": "Password reset successfully. You can now log in with your new password."})


@app.route("/api/auth/profile", methods=["PUT"])
@login_required
def update_profile():
    uid  = session["user_id"]
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 80:
        return jsonify({"error": "Name is required (max 80 characters)"}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("UPDATE users SET name = %s WHERE id = %s", (name, uid))
        db.commit()
        cur.execute("SELECT id, name, email FROM users WHERE id = %s", (uid,))
        return jsonify(cur.fetchone())
    finally:
        db.close()


@app.route("/api/auth/change-password", methods=["PUT"])
@login_required
def change_password():
    uid    = session["user_id"]
    data   = request.get_json(silent=True) or {}
    current = str(data.get("current_password", ""))
    new_pw  = str(data.get("new_password", ""))
    if len(new_pw) < 8 or len(new_pw) > 128:
        return jsonify({"error": "New password must be 8-128 characters"}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (uid,))
        row = cur.fetchone()
        if not row or not check_password_hash(row["password_hash"], current):
            return jsonify({"error": "Current password is incorrect"}), 403
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                    (generate_password_hash(new_pw), uid))
        db.commit()
        return jsonify({"message": "Password changed successfully"})
    finally:
        db.close()


# ---------------------------------------------------------------
# Categories
# ---------------------------------------------------------------
def category_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "group": row["grp"],
        "icon": row["icon"],
        "custom": row["user_id"] is not None,
    }


@app.route("/api/categories", methods=["GET"])
@login_required
def get_categories():
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT id, user_id, name, grp, icon FROM categories "
            "WHERE user_id IS NULL OR user_id = %s ORDER BY grp, name", (uid,))
        return jsonify([category_json(r) for r in cur.fetchall()])
    finally:
        db.close()


@app.route("/api/categories", methods=["POST"])
@login_required
def add_category():
    uid = session["user_id"]
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    group = str(data.get("group", "")).strip()
    icon = str(data.get("icon", "")).strip() or "🏷️"

    if not name or len(name) > 40:
        return jsonify({"error": "Category name is required (max 40 characters)"}), 400
    if group not in GROUPS:
        return jsonify({"error": "Please choose a valid group"}), 400
    if len(icon) > 8:
        return jsonify({"error": "Icon must be a single emoji or short symbol"}), 400

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT id FROM categories WHERE LOWER(name)=LOWER(%s) AND (user_id IS NULL OR user_id=%s)",
            (name, uid))
        if cur.fetchone():
            return jsonify({"error": "A category with this name already exists"}), 409
        cur.execute("INSERT INTO categories (user_id, name, grp, icon) VALUES (%s,%s,%s,%s)",
                    (uid, name, group, icon))
        db.commit()
        cur.execute("SELECT id, user_id, name, grp, icon FROM categories WHERE id = %s", (cur.lastrowid,))
        return jsonify(category_json(cur.fetchone())), 201
    finally:
        db.close()


@app.route("/api/categories/<int:category_id>", methods=["DELETE"])
@login_required
def delete_category(category_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT user_id FROM categories WHERE id=%s AND (user_id IS NULL OR user_id=%s)",
            (category_id, uid))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Category not found"}), 404
        if row["user_id"] is None:
            return jsonify({"error": "Default categories cannot be deleted"}), 403
        cur.execute("SELECT COUNT(*) AS n FROM expenses WHERE category_id = %s", (category_id,))
        used = cur.fetchone()["n"]
        if used:
            return jsonify({"error": f"This category is used by {used} expense(s). Change or delete those first."}), 409
        cur.execute("DELETE FROM categories WHERE id=%s AND user_id=%s", (category_id, uid))
        db.commit()
        return jsonify({"message": "Deleted"})
    finally:
        db.close()


# ---------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------
EXPENSE_SELECT= (
    "SELECT e.id, e.title, e.amount, e.expense_date, e.category_id, "
    "c.name AS category, c.grp AS category_group, c.icon AS icon "
    "FROM expenses e JOIN categories c ON c.id = e.category_id "
)


def expense_json(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "amount": float(row["amount"]),
        "category_id": row["category_id"],
        "category": row["category"],
        "group": row["category_group"],
        "icon": row["icon"],
        "date": row["expense_date"].isoformat(),
    }


def clean_expense(data):
    if not data:
        return None, "No data received"
    try:
        title = str(data.get("title", "")).strip()
        amount = float(data.get("amount", 0))
        category_id = int(data.get("category_id"))
        expense_date = date.fromisoformat(str(data.get("date", "")))
    except (ValueError, TypeError):
        return None, "Invalid amount, category or date"
    if not title or len(title) > 100:
        return None, "Title is required (max 100 characters)"
    if amount <= 0 or amount > 99999999.99:
        return None, "Amount must be greater than 0"
    return (title, amount, category_id, expense_date), None


def category_allowed(cur, category_id, uid):
    cur.execute(
        "SELECT id FROM categories WHERE id=%s AND (user_id IS NULL OR user_id=%s)",
        (category_id, uid))
    return cur.fetchone() is not None



@app.route("/api/expenses", methods=["GET"])
@login_required
def get_expenses():
    uid = session["user_id"]
    month = request.args.get("month", "").strip()

    db = get_db()

    try:
        cur = db.cursor(dictionary=True)

        if month:
            try:
                year_str, month_str = month.split("-")
                year = int(year_str)
                month_num = int(month_str)

                if year < 1 or month_num < 1 or month_num > 12:
                    raise ValueError

                start_date = f"{year:04d}-{month_num:02d}-01"

                if month_num == 12:
                    end_date = f"{year + 1:04d}-01-01"
                else:
                    end_date = f"{year:04d}-{month_num + 1:02d}-01"

            except (ValueError, TypeError):
                return jsonify({
                    "error": "Invalid month format. Use YYYY-MM."
                }), 400

            cur.execute(
                EXPENSE_SELECT +
                "WHERE e.user_id=%s "
                "AND e.expense_date >= %s "
                "AND e.expense_date < %s "
                "ORDER BY e.expense_date DESC, e.id DESC",
                (uid, start_date, end_date)
            )

        else:
            cur.execute(
                EXPENSE_SELECT +
                "WHERE e.user_id=%s "
                "ORDER BY e.expense_date DESC, e.id DESC",
                (uid,)
            )

        rows = cur.fetchall()

        return jsonify([expense_json(row) for row in rows])

    finally:
        db.close()



@app.route("/api/expenses", methods=["POST"])
@login_required
def add_expense():
    uid = session["user_id"]
    values, error = clean_expense(request.get_json(silent=True))
    if error:
        return jsonify({"error": error}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        if not category_allowed(cur, values[2], uid):
            return jsonify({"error": "Invalid category"}), 400
        cur.execute(
            "INSERT INTO expenses (user_id, title, amount, category_id, expense_date) VALUES (%s,%s,%s,%s,%s)",
            (uid,) + values)
        db.commit()
        cur.execute(EXPENSE_SELECT + "WHERE e.id=%s AND e.user_id=%s", (cur.lastrowid, uid))
        return jsonify(expense_json(cur.fetchone())), 201
    finally:
        db.close()


@app.route("/api/expenses/<int:expense_id>", methods=["PUT"])
@login_required
def update_expense(expense_id):
    uid = session["user_id"]
    values, error = clean_expense(request.get_json(silent=True))
    if error:
        return jsonify({"error": error}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        if not category_allowed(cur, values[2], uid):
            return jsonify({"error": "Invalid category"}), 400
        cur.execute(
            "UPDATE expenses SET title=%s, amount=%s, category_id=%s, expense_date=%s WHERE id=%s AND user_id=%s",
            values + (expense_id, uid))
        db.commit()
        cur.execute(EXPENSE_SELECT + "WHERE e.id=%s AND e.user_id=%s", (expense_id, uid))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Expense not found"}), 404
        return jsonify(expense_json(row))
    finally:
        db.close()


@app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
@login_required
def delete_expense(expense_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("DELETE FROM expenses WHERE id=%s AND user_id=%s", (expense_id, uid))
        db.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Expense not found"}), 404
        return jsonify({"message": "Deleted"})
    finally:
        db.close()


# ---------------------------------------------------------------
# Income
# ---------------------------------------------------------------
def income_json(row):
    return {
        "id": row["id"],
        "amount": float(row["amount"]),
        "source": row["source"],
        "date": row["income_date"].isoformat(),
    }


@app.route("/api/income", methods=["GET"])
@login_required
def get_income():
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT id, amount, source, income_date FROM income "
            "WHERE user_id=%s ORDER BY income_date DESC, id DESC", (uid,))
        return jsonify([income_json(r) for r in cur.fetchall()])
    finally:
        db.close()


@app.route("/api/income", methods=["POST"])
@login_required
def add_income():
    uid = session["user_id"]
    data = request.get_json(silent=True) or {}
    try:
        amount = float(data.get("amount", 0))
        income_date = date.fromisoformat(str(data.get("date", "")))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount or date"}), 400
    source = str(data.get("source", "")).strip()
    if amount <= 0 or amount > 99999999.99:
        return jsonify({"error": "Amount must be greater than 0"}), 400
    if source not in INCOME_SOURCES:
        return jsonify({"error": "Please choose a valid source"}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "INSERT INTO income (user_id, amount, source, income_date) VALUES (%s,%s,%s,%s)",
            (uid, amount, source, income_date))
        db.commit()
        cur.execute(
            "SELECT id, amount, source, income_date FROM income WHERE id=%s AND user_id=%s",
            (cur.lastrowid, uid))
        return jsonify(income_json(cur.fetchone())), 201
    finally:
        db.close()


@app.route("/api/income/<int:income_id>", methods=["DELETE"])
@login_required
def delete_income(income_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("DELETE FROM income WHERE id=%s AND user_id=%s", (income_id, uid))
        db.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Income entry not found"}), 404
        return jsonify({"message": "Deleted"})
    finally:
        db.close()


# ---------------------------------------------------------------
# Budget
# ---------------------------------------------------------------
@app.route("/api/budget", methods=["GET"])
@login_required
def get_budget():
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT amount FROM user_budget WHERE user_id=%s", (uid,))
        row = cur.fetchone()
        return jsonify({"amount": float(row[0]) if row else 0})
    finally:
        db.close()


@app.route("/api/budget", methods=["PUT"])
@login_required
def set_budget():
    uid = session["user_id"]
    data = request.get_json(silent=True) or {}
    try:
        amount = float(data.get("amount", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount"}), 400
    if amount < 0 or amount > 99999999.99:
        return jsonify({"error": "Budget must be between 0 and 99,999,999.99"}), 400
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute(
            "INSERT INTO user_budget (user_id, amount) VALUES (%s,%s) ON DUPLICATE KEY UPDATE amount=VALUES(amount)",
            (uid, amount))
        db.commit()
        return jsonify({"amount": amount})
    finally:
        db.close()


# ---------------------------------------------------------------
# Group Budgets
# ---------------------------------------------------------------
@app.route("/api/group-budgets", methods=["GET"])
@login_required
def get_group_budgets():
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT grp, amount FROM group_budgets WHERE user_id=%s", (uid,))
        return jsonify({g: float(a) for g, a in cur.fetchall()})
    finally:
        db.close()


@app.route("/api/group-budgets", methods=["PUT"])
@login_required
def set_group_budgets():
    uid = session["user_id"]
    data = request.get_json(silent=True) or {}
    budgets = data.get("budgets")
    if not isinstance(budgets, dict):
        return jsonify({"error": "Invalid data"}), 400
    clean = {}
    for group, value in budgets.items():
        if group not in GROUPS:
            return jsonify({"error": "Unknown group: " + str(group)}), 400
        try:
            amount = float(value)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid amount for " + group}), 400
        if not (0 <= amount <= 99999999.99):
            return jsonify({"error": f"Budget for {group} must be between 0 and 99,999,999.99"}), 400
        clean[group] = amount
    db = get_db()
    try:
        cur = db.cursor()
        for group, amount in clean.items():
            if amount == 0:
                cur.execute("DELETE FROM group_budgets WHERE user_id=%s AND grp=%s", (uid, group))
            else:
                cur.execute(
                    "INSERT INTO group_budgets (user_id, grp, amount) VALUES (%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE amount=VALUES(amount)",
                    (uid, group, amount))
        db.commit()
        cur.execute("SELECT grp, amount FROM group_budgets WHERE user_id=%s", (uid,))
        return jsonify({g: float(a) for g, a in cur.fetchall()})
    finally:
        db.close()


# ---------------------------------------------------------------
# Dashboard Summary
# ---------------------------------------------------------------
@app.route("/api/dashboard", methods=["GET"])
@login_required
def get_dashboard():
    uid = session["user_id"]
    today = date.today()
    this_month = today.strftime("%Y-%m")
    in_15 = today + timedelta(days=15)
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)

        cur.execute("SELECT COALESCE(SUM(amount),0) AS t FROM income WHERE user_id=%s", (uid,))
        total_income = float(cur.fetchone()["t"])
        cur.execute("SELECT COALESCE(SUM(amount),0) AS t FROM expenses WHERE user_id=%s", (uid,))
        total_expenses = float(cur.fetchone()["t"])
        cur.execute(
            "SELECT COALESCE(SUM(amount),0) AS t FROM expenses "
            "WHERE user_id=%s AND DATE_FORMAT(expense_date,'%%Y-%%m')=%s", (uid, this_month))
        month_expenses = float(cur.fetchone()["t"])
        cur.execute(
            "SELECT COALESCE(SUM(amount),0) AS t FROM income "
            "WHERE user_id=%s AND DATE_FORMAT(income_date,'%%Y-%%m')=%s", (uid, this_month))
        month_income = float(cur.fetchone()["t"])
        cur.execute("SELECT amount FROM user_budget WHERE user_id=%s", (uid,))
        row = cur.fetchone()
        monthly_budget = float(row["amount"]) if row else 0

        # Active semester
        active_semester = None
        try:
            cur.execute(
                "SELECT id, semester_name, academic_year, start_date, end_date, budget, status "
                "FROM semesters WHERE user_id=%s AND status='Active' ORDER BY created_at DESC LIMIT 1", (uid,))
            sem = cur.fetchone()
            if sem:
                s_start = sem["start_date"].isoformat()
                s_end = sem["end_date"].isoformat()
                cur.execute(
                    "SELECT COALESCE(SUM(amount),0) AS t FROM expenses "
                    "WHERE user_id=%s AND expense_date BETWEEN %s AND %s", (uid, s_start, s_end))
                active_semester = {
                    "id": sem["id"],
                    "semester_name": sem["semester_name"],
                    "academic_year": sem["academic_year"],
                    "start_date": s_start,
                    "end_date": s_end,
                    "budget": float(sem["budget"]),
                    "status": sem["status"],
                    "total_expenses": float(cur.fetchone()["t"])
                }
        except Exception:
            pass

        # Upcoming fees
        upcoming_fees = []
        try:
            cur.execute(
                "SELECT f.id, f.fee_title, f.fee_category, f.total_amount, f.due_date, "
                "COALESCE(SUM(p.amount_paid),0) AS paid "
                "FROM college_fees f LEFT JOIN fee_payments p ON p.fee_id=f.id "
                "WHERE f.user_id=%s AND f.due_date BETWEEN %s AND %s "
                "GROUP BY f.id HAVING paid < f.total_amount ORDER BY f.due_date ASC LIMIT 5",
                (uid, today.isoformat(), in_15.isoformat()))
            for row in cur.fetchall():
                upcoming_fees.append({
                    "id": row["id"], "fee_title": row["fee_title"],
                    "fee_category": row["fee_category"],
                    "total_amount": float(row["total_amount"]),
                    "due_date": row["due_date"].isoformat(),
                    "paid": float(row["paid"]),
                    "remaining": float(row["total_amount"]) - float(row["paid"])
                })
        except Exception:
            pass

        # Active savings goals
        active_goals = []
        try:
            cur.execute(
                "SELECT id, goal_title, target_amount, current_saved_amount, target_date "
                "FROM savings_goals WHERE user_id=%s AND status='Active' "
                "ORDER BY target_date ASC LIMIT 4", (uid,))
            for row in cur.fetchall():
                tgt = float(row["target_amount"])
                sav = float(row["current_saved_amount"])
                active_goals.append({
                    "id": row["id"], "goal_title": row["goal_title"],
                    "target_amount": tgt, "current_saved_amount": sav,
                    "progress_pct": round((sav / tgt * 100) if tgt > 0 else 0, 1),
                    "target_date": row["target_date"].isoformat() if row["target_date"] else None
                })
        except Exception:
            pass

        # Scholarship summary
        scholarships = {"total_awarded": 0, "total_received": 0, "total_count": 0, "pending_count": 0}
        try:
            cur.execute(
                "SELECT COALESCE(SUM(CASE WHEN status IN "
                "('Approved','Payment Pending','Partially Received','Received') "
                "THEN awarded_amount ELSE 0 END),0) AS ta, "
                "COUNT(*) AS tc, "
                "SUM(CASE WHEN status IN ('Applied','Under Review') THEN 1 ELSE 0 END) AS pc "
                "FROM scholarships WHERE user_id=%s", (uid,))
            sr = cur.fetchone()
            scholarships = {
                "total_awarded": float(sr["ta"]),
                "total_count": sr["tc"],
                "pending_count": sr["pc"] or 0
            }
        except Exception:
            pass

        # Recent expenses
        cur.execute(
            EXPENSE_SELECT + "WHERE e.user_id=%s ORDER BY e.expense_date DESC, e.id DESC LIMIT 5", (uid,))
        recent_expenses = [expense_json(r) for r in cur.fetchall()]

        return jsonify({
            "total_income": total_income,
            "total_expenses": total_expenses,
            "balance": total_income - total_expenses,
            "month_income": month_income,
            "month_expenses": month_expenses,
            "monthly_budget": monthly_budget,
            "active_semester": active_semester,
            "upcoming_fees": upcoming_fees,
            "active_goals": active_goals,
            "scholarships": scholarships,
            "recent_expenses": recent_expenses
        })
    finally:
        db.close()


# ===============================================================
# PHASE 3 — Semester Management
# ===============================================================
def semester_json(row):
    return {
        "id": row["id"],
        "semester_name": row["semester_name"],
        "semester_number": row["semester_number"],
        "academic_year": row["academic_year"],
        "start_date": row["start_date"].isoformat(),
        "end_date": row["end_date"].isoformat(),
        "budget": float(row["budget"]),
        "description": row.get("description") or "",
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def _clean_semester(data):
    name = str(data.get("semester_name", "")).strip()
    academic_year = str(data.get("academic_year", "")).strip()
    description = str(data.get("description", "")).strip()
    status = str(data.get("status", "Upcoming")).strip()
    if not name or len(name) > 100:
        return "Semester name is required (max 100 characters)", None
    if not academic_year or len(academic_year) > 20:
        return "Academic year is required (e.g. 2024-25)", None
    if status not in SEMESTER_STATUSES:
        return "Status must be Upcoming, Active, or Completed", None
    try:
        sem_num = int(data.get("semester_number", 0))
        budget = float(data.get("budget", 0))
        start = date.fromisoformat(str(data.get("start_date", "")))
        end = date.fromisoformat(str(data.get("end_date", "")))
    except (ValueError, TypeError):
        return "Invalid semester number, budget, or dates", None
    if not (1 <= sem_num <= 20):
        return "Semester number must be between 1 and 20", None
    if budget < 0 or budget > 99999999.99:
        return "Budget must be 0 or a positive amount", None
    if end <= start:
        return "End date must be after start date", None
    return None, {
        "semester_name": name, "semester_number": sem_num, "academic_year": academic_year,
        "start_date": start, "end_date": end, "budget": budget,
        "description": description, "status": status
    }


@app.route("/api/semesters", methods=["GET"])
@login_required
def get_semesters():
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT id, semester_name, semester_number, academic_year, start_date, end_date, "
            "budget, description, status, created_at FROM semesters "
            "WHERE user_id=%s ORDER BY start_date DESC", (uid,))
        return jsonify([semester_json(r) for r in cur.fetchall()])
    finally:
        db.close()


@app.route("/api/semesters", methods=["POST"])
@login_required
def add_semester():
    uid = session["user_id"]
    err, c = _clean_semester(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "INSERT INTO semesters (user_id, semester_name, semester_number, academic_year, "
            "start_date, end_date, budget, description, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (uid, c["semester_name"], c["semester_number"], c["academic_year"],
             c["start_date"], c["end_date"], c["budget"], c["description"], c["status"]))
        db.commit()
        new_id = cur.lastrowid
        cur.execute(
            "SELECT id, semester_name, semester_number, academic_year, start_date, end_date, "
            "budget, description, status, created_at FROM semesters WHERE id=%s", (new_id,))
        return jsonify(semester_json(cur.fetchone())), 201
    finally:
        db.close()


@app.route("/api/semesters/<int:semester_id>", methods=["GET"])
@login_required
def get_semester(semester_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT id, semester_name, semester_number, academic_year, start_date, end_date, "
            "budget, description, status, created_at FROM semesters WHERE id=%s AND user_id=%s",
            (semester_id, uid))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Semester not found"}), 404
        return jsonify(semester_json(row))
    finally:
        db.close()


@app.route("/api/semesters/<int:semester_id>", methods=["PUT"])
@login_required
def update_semester(semester_id):
    uid = session["user_id"]
    err, c = _clean_semester(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id FROM semesters WHERE id=%s AND user_id=%s", (semester_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Semester not found"}), 404
        cur.execute(
            "UPDATE semesters SET semester_name=%s, semester_number=%s, academic_year=%s, "
            "start_date=%s, end_date=%s, budget=%s, description=%s, status=%s "
            "WHERE id=%s AND user_id=%s",
            (c["semester_name"], c["semester_number"], c["academic_year"],
             c["start_date"], c["end_date"], c["budget"], c["description"], c["status"],
             semester_id, uid))
        db.commit()
        cur.execute(
            "SELECT id, semester_name, semester_number, academic_year, start_date, end_date, "
            "budget, description, status, created_at FROM semesters WHERE id=%s", (semester_id,))
        return jsonify(semester_json(cur.fetchone()))
    finally:
        db.close()


@app.route("/api/semesters/<int:semester_id>", methods=["DELETE"])
@login_required
def delete_semester(semester_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT id FROM semesters WHERE id=%s AND user_id=%s", (semester_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Semester not found"}), 404
        cur.execute("DELETE FROM semesters WHERE id=%s AND user_id=%s", (semester_id, uid))
        db.commit()
        return jsonify({"message": "Semester deleted"})
    finally:
        db.close()


@app.route("/api/semesters/<int:semester_id>/overview", methods=["GET"])
@login_required
def semester_overview(semester_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT id, semester_name, semester_number, academic_year, start_date, end_date, "
            "budget, status FROM semesters WHERE id=%s AND user_id=%s", (semester_id, uid))
        sem = cur.fetchone()
        if not sem:
            return jsonify({"error": "Semester not found"}), 404
        start = sem["start_date"].isoformat()
        end = sem["end_date"].isoformat()

        cur.execute(
            "SELECT COALESCE(SUM(e.amount),0) AS total, c.grp AS grp "
            "FROM expenses e JOIN categories c ON c.id=e.category_id "
            "WHERE e.user_id=%s AND e.expense_date BETWEEN %s AND %s GROUP BY c.grp",
            (uid, start, end))
        by_group = {r["grp"]: float(r["total"]) for r in cur.fetchall()}
        total_expenses = sum(by_group.values())

        cur.execute(
            "SELECT DATE_FORMAT(expense_date,'%%Y-%%m') AS month, SUM(amount) AS total "
            "FROM expenses WHERE user_id=%s AND expense_date BETWEEN %s AND %s "
            "GROUP BY month ORDER BY month", (uid, start, end))
        monthly = {r["month"]: float(r["total"]) for r in cur.fetchall()}

        cur.execute(
            "SELECT f.id, f.fee_title, f.fee_category, f.total_amount, f.due_date, "
            "COALESCE(SUM(p.amount_paid),0) AS paid "
            "FROM college_fees f LEFT JOIN fee_payments p ON p.fee_id=f.id "
            "WHERE f.user_id=%s AND f.semester_id=%s GROUP BY f.id", (uid, semester_id))
        fees = []
        total_fees = total_paid_fees = 0
        for row in cur.fetchall():
            total = float(row["total_amount"])
            paid = float(row["paid"])
            today_dt = date.today()
            if paid >= total:
                st = "Paid"
            elif paid > 0:
                st = "Partially Paid"
            elif row["due_date"] < today_dt:
                st = "Overdue"
            else:
                st = "Pending"
            fees.append({
                "id": row["id"], "fee_title": row["fee_title"], "fee_category": row["fee_category"],
                "total_amount": total, "paid": paid, "remaining": total - paid,
                "due_date": row["due_date"].isoformat(), "status": st
            })
            total_fees += total
            total_paid_fees += paid

        budget = float(sem["budget"])
        return jsonify({
            "semester": {
                "id": sem["id"], "semester_name": sem["semester_name"],
                "semester_number": sem["semester_number"], "academic_year": sem["academic_year"],
                "start_date": start, "end_date": end, "budget": budget, "status": sem["status"]
            },
            "total_expenses": total_expenses,
            "remaining_budget": budget - total_expenses,
            "budget_used_pct": round((total_expenses / budget * 100) if budget > 0 else 0, 1),
            "expenses_by_group": by_group, "monthly_expenses": monthly,
            "total_fees": total_fees, "total_paid_fees": total_paid_fees,
            "pending_fees": total_fees - total_paid_fees, "fees": fees
        })
    finally:
        db.close()


# ===============================================================
# PHASE 3 — College Fees
# ===============================================================
def _fee_status(paid_amt, total, due_date):
    if paid_amt >= total:
        return "Paid"
    elif paid_amt > 0:
        return "Partially Paid"
    elif due_date < date.today():
        return "Overdue"
    return "Pending"


def fee_json(row, paid=None):
    total = float(row["total_amount"])
    paid_amt = float(paid if paid is not None else row.get("paid", 0))
    return {
        "id": row["id"], "user_id": row.get("user_id"), "semester_id": row.get("semester_id"),
        "semester_name": row.get("semester_name"), "fee_title": row["fee_title"],
        "fee_category": row["fee_category"], "total_amount": total,
        "paid": paid_amt, "remaining": total - paid_amt,
        "due_date": row["due_date"].isoformat(),
        "description": row.get("description") or "",
        "status": _fee_status(paid_amt, total, row["due_date"]),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def _clean_fee(data):
    fee_title = str(data.get("fee_title", "")).strip()
    fee_category = str(data.get("fee_category", "")).strip()
    description = str(data.get("description", "")).strip()
    semester_id = data.get("semester_id") or None
    if not fee_title or len(fee_title) > 150:
        return "Fee title is required (max 150 characters)", None
    if fee_category not in FEE_CATEGORIES:
        return f"Fee category must be one of: {', '.join(FEE_CATEGORIES)}", None
    try:
        total_amount = float(data.get("total_amount", 0))
        due_date = date.fromisoformat(str(data.get("due_date", "")))
        if semester_id is not None:
            semester_id = int(semester_id)
    except (ValueError, TypeError):
        return "Invalid amount, due date, or semester", None
    if total_amount <= 0 or total_amount > 99999999.99:
        return "Fee amount must be greater than 0", None
    return None, {
        "fee_title": fee_title, "fee_category": fee_category, "total_amount": total_amount,
        "due_date": due_date, "description": description, "semester_id": semester_id
    }


FEE_SELECT = (
    "SELECT f.id, f.user_id, f.semester_id, f.fee_title, f.fee_category, "
    "f.total_amount, f.due_date, f.description, f.created_at, s.semester_name, "
    "COALESCE(SUM(p.amount_paid),0) AS paid "
    "FROM college_fees f "
    "LEFT JOIN semesters s ON s.id=f.semester_id "
    "LEFT JOIN fee_payments p ON p.fee_id=f.id "
)


@app.route("/api/fees", methods=["GET"])
@login_required

def get_fees():
    uid = session["user_id"]
    semester_id = request.args.get("semester_id")
    fee_category = request.args.get("category")
    status_filter = request.args.get("status")
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        q = FEE_SELECT + "WHERE f.user_id=%s"
        params = [uid]

        if semester_id:
            q += " AND f.semester_id=%s"
            params.append(semester_id)

        if fee_category and fee_category in FEE_CATEGORIES:
            q += " AND f.fee_category=%s"
            params.append(fee_category)

        q += (
            " GROUP BY f.id, f.user_id, f.semester_id, f.fee_title, f.fee_category, "
            "f.total_amount, f.due_date, f.description, f.created_at, s.semester_name "
            "ORDER BY f.due_date ASC"
        )

        cur.execute(q, params)
        result = [fee_json(r) for r in cur.fetchall()]

        if status_filter:
            result = [r for r in result if r["status"] == status_filter]

        return jsonify(result)
    finally:
        db.close()



@app.route("/api/fees", methods=["POST"])
@login_required
def add_fee():
    uid = session["user_id"]
    err, c = _clean_fee(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        if c["semester_id"]:
            cur.execute("SELECT id FROM semesters WHERE id=%s AND user_id=%s", (c["semester_id"], uid))
            if not cur.fetchone():
                return jsonify({"error": "Semester not found"}), 404
        cur.execute(
            "INSERT INTO college_fees (user_id, semester_id, fee_title, fee_category, "
            "total_amount, due_date, description) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (uid, c["semester_id"], c["fee_title"], c["fee_category"],
             c["total_amount"], c["due_date"], c["description"]))
        db.commit()
        new_id = cur.lastrowid
        cur.execute(FEE_SELECT + "WHERE f.id=%s GROUP BY f.id", (new_id,))
        return jsonify(fee_json(cur.fetchone(), paid=0)), 201
    finally:
        db.close()


@app.route("/api/fees/<int:fee_id>", methods=["GET"])
@login_required
def get_fee(fee_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
    FEE_SELECT + "WHERE f.id=%s AND f.user_id=%s "
    "GROUP BY f.id, f.user_id, f.semester_id, f.fee_title, f.fee_category, "
    "f.total_amount, f.due_date, f.description, f.created_at, s.semester_name",
    (fee_id, uid)
)
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Fee not found"}), 404
        return jsonify(fee_json(row))
    finally:
        db.close()


@app.route("/api/fees/<int:fee_id>", methods=["PUT"])
@login_required
def update_fee(fee_id):
    uid = session["user_id"]
    err, c = _clean_fee(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id FROM college_fees WHERE id=%s AND user_id=%s", (fee_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Fee not found"}), 404
        cur.execute("SELECT COALESCE(SUM(amount_paid),0) AS paid FROM fee_payments WHERE fee_id=%s", (fee_id,))
        already_paid = float(cur.fetchone()["paid"])
        if c["total_amount"] < already_paid:
            return jsonify({"error": f"Total cannot be less than already paid \u20b9{already_paid:.2f}"}), 400
        cur.execute(
            "UPDATE college_fees SET semester_id=%s, fee_title=%s, fee_category=%s, "
            "total_amount=%s, due_date=%s, description=%s WHERE id=%s AND user_id=%s",
            (c["semester_id"], c["fee_title"], c["fee_category"],
             c["total_amount"], c["due_date"], c["description"], fee_id, uid))
        db.commit()
        cur.execute(FEE_SELECT + "WHERE f.id=%s GROUP BY f.id", (fee_id,))
        return jsonify(fee_json(cur.fetchone()))
    finally:
        db.close()


@app.route("/api/fees/<int:fee_id>", methods=["DELETE"])
@login_required
def delete_fee(fee_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT id FROM college_fees WHERE id=%s AND user_id=%s", (fee_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Fee not found"}), 404
        cur.execute("DELETE FROM college_fees WHERE id=%s AND user_id=%s", (fee_id, uid))
        db.commit()
        return jsonify({"message": "Fee deleted"})
    finally:
        db.close()


@app.route("/api/fees/<int:fee_id>/payments", methods=["GET"])
@login_required
def get_fee_payments(fee_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id FROM college_fees WHERE id=%s AND user_id=%s", (fee_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Fee not found"}), 404
        cur.execute(
            "SELECT id, fee_id, amount_paid, payment_date, payment_method, "
            "transaction_reference, remarks, created_at "
            "FROM fee_payments WHERE fee_id=%s ORDER BY payment_date DESC, id DESC", (fee_id,))
        return jsonify([{
            "id": r["id"], "fee_id": r["fee_id"], "amount_paid": float(r["amount_paid"]),
            "payment_date": r["payment_date"].isoformat(), "payment_method": r["payment_method"],
            "transaction_reference": r["transaction_reference"] or "",
            "remarks": r["remarks"] or "", "created_at": r["created_at"].isoformat()
        } for r in cur.fetchall()])
    finally:
        db.close()


@app.route("/api/fees/<int:fee_id>/payments", methods=["POST"])
@login_required
def add_fee_payment(fee_id):
    uid = session["user_id"]
    data = request.get_json(silent=True) or {}
    try:
        amount_paid = float(data.get("amount_paid", 0))
        payment_date = date.fromisoformat(str(data.get("payment_date", "")))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount or payment date"}), 400
    payment_method = str(data.get("payment_method", "Cash")).strip()
    transaction_reference = str(data.get("transaction_reference", "")).strip()[:100]
    remarks = str(data.get("remarks", "")).strip()
    if amount_paid <= 0:
        return jsonify({"error": "Payment amount must be greater than 0"}), 400
    if payment_method not in PAYMENT_METHODS:
        return jsonify({"error": "Invalid payment method"}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT total_amount FROM college_fees WHERE id=%s AND user_id=%s", (fee_id, uid))
        fee = cur.fetchone()
        if not fee:
            return jsonify({"error": "Fee not found"}), 404
        cur.execute("SELECT COALESCE(SUM(amount_paid),0) AS paid FROM fee_payments WHERE fee_id=%s", (fee_id,))
        already = float(cur.fetchone()["paid"])
        remaining = float(fee["total_amount"]) - already
        if amount_paid > remaining:
            return jsonify({"error": f"Payment \u20b9{amount_paid:.2f} exceeds balance \u20b9{remaining:.2f}"}), 400
        cur.execute(
            "INSERT INTO fee_payments (fee_id, user_id, amount_paid, payment_date, "
            "payment_method, transaction_reference, remarks) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (fee_id, uid, amount_paid, payment_date, payment_method,
             transaction_reference or None, remarks or None))
        db.commit()
        new_id = cur.lastrowid
        cur.execute(
            "SELECT id, fee_id, amount_paid, payment_date, payment_method, "
            "transaction_reference, remarks, created_at FROM fee_payments WHERE id=%s", (new_id,))
        r = cur.fetchone()
        return jsonify({
            "id": r["id"], "fee_id": r["fee_id"], "amount_paid": float(r["amount_paid"]),
            "payment_date": r["payment_date"].isoformat(), "payment_method": r["payment_method"],
            "transaction_reference": r["transaction_reference"] or "",
            "remarks": r["remarks"] or "", "created_at": r["created_at"].isoformat()
        }), 201
    finally:
        db.close()


@app.route("/api/fees/<int:fee_id>/payments/<int:payment_id>", methods=["DELETE"])
@login_required
def delete_fee_payment(fee_id, payment_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT id FROM college_fees WHERE id=%s AND user_id=%s", (fee_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Fee not found"}), 404
        cur.execute("DELETE FROM fee_payments WHERE id=%s AND fee_id=%s AND user_id=%s",
                    (payment_id, fee_id, uid))
        db.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Payment not found"}), 404
        return jsonify({"message": "Payment deleted"})
    finally:
        db.close()


# ===============================================================
# PHASE 4 — Savings Goals
# ===============================================================
def goal_json(row):
    target = float(row["target_amount"])
    saved = float(row["current_saved_amount"])
    return {
        "id": row["id"], "goal_title": row["goal_title"],
        "goal_category": row.get("goal_category") or "General",
        "target_amount": target, "current_saved_amount": saved,
        "remaining": max(target - saved, 0),
        "progress_pct": round((saved / target * 100) if target > 0 else 0, 1),
        "start_date": row["start_date"].isoformat(),
        "target_date": row["target_date"].isoformat() if row.get("target_date") else None,
        "description": row.get("description") or "", "status": row["status"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def _clean_goal(data):
    goal_title = str(data.get("goal_title", "")).strip()
    goal_category = str(data.get("goal_category", "General")).strip() or "General"
    description = str(data.get("description", "")).strip()
    if not goal_title or len(goal_title) > 150:
        return "Goal title is required (max 150 characters)", None
    try:
        target_amount = float(data.get("target_amount", 0))
        start_date = date.fromisoformat(str(data.get("start_date", "")))
        raw_td = data.get("target_date")
        target_date = date.fromisoformat(str(raw_td)) if raw_td else None
    except (ValueError, TypeError):
        return "Invalid amount or dates", None
    if target_amount <= 0 or target_amount > 99999999.99:
        return "Target amount must be greater than 0", None
    if target_date and target_date < start_date:
        return "Target date must be after start date", None
    return None, {
        "goal_title": goal_title, "goal_category": goal_category,
        "target_amount": target_amount, "start_date": start_date,
        "target_date": target_date, "description": description
    }


@app.route("/api/savings-goals", methods=["GET"])
@login_required
def get_savings_goals():
    uid = session["user_id"]
    status_filter = request.args.get("status")
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        if status_filter and status_filter in GOAL_STATUSES:
            cur.execute(
                "SELECT id, goal_title, goal_category, target_amount, current_saved_amount, "
                "start_date, target_date, description, status, created_at "
                "FROM savings_goals WHERE user_id=%s AND status=%s ORDER BY created_at DESC",
                (uid, status_filter))
        else:
            cur.execute(
                "SELECT id, goal_title, goal_category, target_amount, current_saved_amount, "
                "start_date, target_date, description, status, created_at "
                "FROM savings_goals WHERE user_id=%s ORDER BY created_at DESC", (uid,))
        return jsonify([goal_json(r) for r in cur.fetchall()])
    finally:
        db.close()


@app.route("/api/savings-goals", methods=["POST"])
@login_required
def add_savings_goal():
    uid = session["user_id"]
    err, c = _clean_goal(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "INSERT INTO savings_goals (user_id, goal_title, goal_category, target_amount, "
            "current_saved_amount, start_date, target_date, description, status) "
            "VALUES (%s,%s,%s,%s,0,%s,%s,%s,'Active')",
            (uid, c["goal_title"], c["goal_category"], c["target_amount"],
             c["start_date"], c["target_date"], c["description"]))
        db.commit()
        new_id = cur.lastrowid
        cur.execute(
            "SELECT id, goal_title, goal_category, target_amount, current_saved_amount, "
            "start_date, target_date, description, status, created_at "
            "FROM savings_goals WHERE id=%s", (new_id,))
        return jsonify(goal_json(cur.fetchone())), 201
    finally:
        db.close()


@app.route("/api/savings-goals/<int:goal_id>", methods=["GET"])
@login_required
def get_savings_goal(goal_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT id, goal_title, goal_category, target_amount, current_saved_amount, "
            "start_date, target_date, description, status, created_at "
            "FROM savings_goals WHERE id=%s AND user_id=%s", (goal_id, uid))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Savings goal not found"}), 404
        return jsonify(goal_json(row))
    finally:
        db.close()


@app.route("/api/savings-goals/<int:goal_id>", methods=["PUT"])
@login_required
def update_savings_goal(goal_id):
    uid = session["user_id"]
    data = request.get_json(silent=True) or {}
    err, c = _clean_goal(data)
    if err:
        return jsonify({"error": err}), 400
    status = str(data.get("status", "Active")).strip()
    if status not in GOAL_STATUSES:
        return jsonify({"error": "Invalid status"}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id FROM savings_goals WHERE id=%s AND user_id=%s", (goal_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Savings goal not found"}), 404
        cur.execute(
            "UPDATE savings_goals SET goal_title=%s, goal_category=%s, target_amount=%s, "
            "start_date=%s, target_date=%s, description=%s, status=%s WHERE id=%s AND user_id=%s",
            (c["goal_title"], c["goal_category"], c["target_amount"],
             c["start_date"], c["target_date"], c["description"], status, goal_id, uid))
        db.commit()
        cur.execute(
            "SELECT id, goal_title, goal_category, target_amount, current_saved_amount, "
            "start_date, target_date, description, status, created_at "
            "FROM savings_goals WHERE id=%s", (goal_id,))
        return jsonify(goal_json(cur.fetchone()))
    finally:
        db.close()


@app.route("/api/savings-goals/<int:goal_id>", methods=["DELETE"])
@login_required
def delete_savings_goal(goal_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT id FROM savings_goals WHERE id=%s AND user_id=%s", (goal_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Savings goal not found"}), 404
        cur.execute("DELETE FROM savings_goals WHERE id=%s AND user_id=%s", (goal_id, uid))
        db.commit()
        return jsonify({"message": "Goal deleted"})
    finally:
        db.close()


@app.route("/api/savings-goals/<int:goal_id>/transactions", methods=["GET"])
@login_required
def get_goal_transactions(goal_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id FROM savings_goals WHERE id=%s AND user_id=%s", (goal_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Savings goal not found"}), 404
        cur.execute(
            "SELECT id, goal_id, transaction_type, amount, transaction_date, remarks, created_at "
            "FROM savings_transactions WHERE goal_id=%s ORDER BY transaction_date DESC, id DESC",
            (goal_id,))
        return jsonify([{
            "id": r["id"], "goal_id": r["goal_id"], "transaction_type": r["transaction_type"],
            "amount": float(r["amount"]), "transaction_date": r["transaction_date"].isoformat(),
            "remarks": r["remarks"] or "", "created_at": r["created_at"].isoformat()
        } for r in cur.fetchall()])
    finally:
        db.close()


@app.route("/api/savings-goals/<int:goal_id>/transactions", methods=["POST"])
@login_required
def add_goal_transaction(goal_id):
    uid = session["user_id"]
    data = request.get_json(silent=True) or {}
    try:
        amount = float(data.get("amount", 0))
        txn_date = date.fromisoformat(str(data.get("transaction_date", "")))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount or date"}), 400
    txn_type = str(data.get("transaction_type", "Deposit")).strip()
    remarks = str(data.get("remarks", "")).strip()
    if txn_type not in ["Deposit", "Withdrawal", "Correction"]:
        return jsonify({"error": "Transaction type must be Deposit, Withdrawal, or Correction"}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than 0"}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT id, target_amount, current_saved_amount FROM savings_goals WHERE id=%s AND user_id=%s",
            (goal_id, uid))
        goal = cur.fetchone()
        if not goal:
            return jsonify({"error": "Savings goal not found"}), 404
        current = float(goal["current_saved_amount"])
        if txn_type == "Deposit":
            new_amount = current + amount
        elif txn_type == "Withdrawal":
            if amount > current:
                return jsonify({"error": f"Withdrawal \u20b9{amount:.2f} exceeds savings \u20b9{current:.2f}"}), 400
            new_amount = current - amount
        else:  # Correction — set directly
            new_amount = amount
        target = float(goal["target_amount"])
        new_status = "Completed" if new_amount >= target else None
        cur.execute(
            "INSERT INTO savings_transactions (goal_id, user_id, transaction_type, amount, "
            "transaction_date, remarks) VALUES (%s,%s,%s,%s,%s,%s)",
            (goal_id, uid, txn_type, amount, txn_date, remarks or None))
        upd = "UPDATE savings_goals SET current_saved_amount=%s"
        params = [new_amount]
        if new_status:
            upd += ", status=%s"
            params.append(new_status)
        upd += " WHERE id=%s AND user_id=%s"
        params += [goal_id, uid]
        cur.execute(upd, params)
        db.commit()
        cur.execute(
            "SELECT id, goal_title, goal_category, target_amount, current_saved_amount, "
            "start_date, target_date, description, status, created_at FROM savings_goals WHERE id=%s",
            (goal_id,))
        return jsonify({
            "goal": goal_json(cur.fetchone()),
            "transaction": {"type": txn_type, "amount": amount, "new_total": new_amount}
        }), 201
    finally:
        db.close()


# ===============================================================
# PHASE 4 — Scholarships
# ===============================================================
def scholarship_json(row):
    return {
        "id": row["id"], "scholarship_name": row["scholarship_name"],
        "provider": row.get("provider") or "", "category": row.get("category") or "",
        "application_date": row["application_date"].isoformat() if row.get("application_date") else None,
        "application_deadline": row["application_deadline"].isoformat() if row.get("application_deadline") else None,
        "expected_amount": float(row.get("expected_amount") or 0),
        "awarded_amount": float(row.get("awarded_amount") or 0),
        "expected_payment_date": row["expected_payment_date"].isoformat() if row.get("expected_payment_date") else None,
        "total_received": float(row.get("total_received") or 0),
        "status": row["status"], "description": row.get("description") or "",
        "reference_number": row.get("reference_number") or "",
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def _clean_scholarship(data):
    name = str(data.get("scholarship_name", "")).strip()
    provider = str(data.get("provider", "")).strip()
    category = str(data.get("category", "")).strip()
    status = str(data.get("status", "Not Applied")).strip()
    description = str(data.get("description", "")).strip()
    reference_number = str(data.get("reference_number", "")).strip()[:100]
    if not name or len(name) > 200:
        return "Scholarship name is required (max 200 characters)", None
    if status not in SCHOLARSHIP_STATUSES:
        return f"Invalid status. Choose from: {', '.join(SCHOLARSHIP_STATUSES)}", None
    def parse_d(v):
        return date.fromisoformat(str(v)) if v else None
    try:
        expected_amount = float(data.get("expected_amount") or 0)
        awarded_amount = float(data.get("awarded_amount") or 0)
        application_date = parse_d(data.get("application_date"))
        application_deadline = parse_d(data.get("application_deadline"))
        expected_payment_date = parse_d(data.get("expected_payment_date"))
    except (ValueError, TypeError):
        return "Invalid amount or date fields", None
    if expected_amount < 0 or awarded_amount < 0:
        return "Amounts cannot be negative", None
    return None, {
        "scholarship_name": name, "provider": provider or None,
        "category": category or None, "application_date": application_date,
        "application_deadline": application_deadline, "expected_amount": expected_amount,
        "awarded_amount": awarded_amount, "expected_payment_date": expected_payment_date,
        "status": status, "description": description or None,
        "reference_number": reference_number or None
    }


SCHOL_SELECT = (
    "SELECT s.id, s.scholarship_name, s.provider, s.category, "
    "s.application_date, s.application_deadline, s.expected_amount, s.awarded_amount, "
    "s.expected_payment_date, s.status, s.description, s.reference_number, s.created_at, "
    "COALESCE(SUM(p.amount_received),0) AS total_received "
    "FROM scholarships s LEFT JOIN scholarship_payments p ON p.scholarship_id=s.id "
)


@app.route("/api/scholarships", methods=["GET"])
@login_required
def get_scholarships():
    uid = session["user_id"]
    status_filter = request.args.get("status")
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        q = SCHOL_SELECT + "WHERE s.user_id=%s"
        params = [uid]
        if status_filter and status_filter in SCHOLARSHIP_STATUSES:
            q += " AND s.status=%s"
            params.append(status_filter)
        q += " GROUP BY s.id ORDER BY s.created_at DESC"
        cur.execute(q, params)
        return jsonify([scholarship_json(r) for r in cur.fetchall()])
    finally:
        db.close()


@app.route("/api/scholarships", methods=["POST"])
@login_required
def add_scholarship():
    uid = session["user_id"]
    err, c = _clean_scholarship(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "INSERT INTO scholarships (user_id, scholarship_name, provider, category, "
            "application_date, application_deadline, expected_amount, awarded_amount, "
            "expected_payment_date, status, description, reference_number) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (uid, c["scholarship_name"], c["provider"], c["category"],
             c["application_date"], c["application_deadline"], c["expected_amount"],
             c["awarded_amount"], c["expected_payment_date"], c["status"],
             c["description"], c["reference_number"]))
        db.commit()
        new_id = cur.lastrowid
        cur.execute(SCHOL_SELECT + "WHERE s.id=%s GROUP BY s.id", (new_id,))
        return jsonify(scholarship_json(cur.fetchone())), 201
    finally:
        db.close()


@app.route("/api/scholarships/<int:scholarship_id>", methods=["GET"])
@login_required
def get_scholarship(scholarship_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(SCHOL_SELECT + "WHERE s.id=%s AND s.user_id=%s GROUP BY s.id",
                    (scholarship_id, uid))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Scholarship not found"}), 404
        return jsonify(scholarship_json(row))
    finally:
        db.close()


@app.route("/api/scholarships/<int:scholarship_id>", methods=["PUT"])
@login_required
def update_scholarship(scholarship_id):
    uid = session["user_id"]
    err, c = _clean_scholarship(request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id FROM scholarships WHERE id=%s AND user_id=%s", (scholarship_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Scholarship not found"}), 404
        cur.execute(
            "UPDATE scholarships SET scholarship_name=%s, provider=%s, category=%s, "
            "application_date=%s, application_deadline=%s, expected_amount=%s, "
            "awarded_amount=%s, expected_payment_date=%s, status=%s, "
            "description=%s, reference_number=%s WHERE id=%s AND user_id=%s",
            (c["scholarship_name"], c["provider"], c["category"],
             c["application_date"], c["application_deadline"], c["expected_amount"],
             c["awarded_amount"], c["expected_payment_date"], c["status"],
             c["description"], c["reference_number"], scholarship_id, uid))
        db.commit()
        cur.execute(SCHOL_SELECT + "WHERE s.id=%s GROUP BY s.id", (scholarship_id,))
        return jsonify(scholarship_json(cur.fetchone()))
    finally:
        db.close()


@app.route("/api/scholarships/<int:scholarship_id>", methods=["DELETE"])
@login_required
def delete_scholarship(scholarship_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("SELECT id FROM scholarships WHERE id=%s AND user_id=%s", (scholarship_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Scholarship not found"}), 404
        cur.execute("DELETE FROM scholarships WHERE id=%s AND user_id=%s", (scholarship_id, uid))
        db.commit()
        return jsonify({"message": "Scholarship deleted"})
    finally:
        db.close()


@app.route("/api/scholarships/<int:scholarship_id>/payments", methods=["GET"])
@login_required
def get_scholarship_payments(scholarship_id):
    uid = session["user_id"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id FROM scholarships WHERE id=%s AND user_id=%s", (scholarship_id, uid))
        if not cur.fetchone():
            return jsonify({"error": "Scholarship not found"}), 404
        cur.execute(
            "SELECT id, scholarship_id, amount_received, payment_date, "
            "transaction_reference, remarks, created_at "
            "FROM scholarship_payments WHERE scholarship_id=%s ORDER BY payment_date DESC, id DESC",
            (scholarship_id,))
        return jsonify([{
            "id": r["id"], "scholarship_id": r["scholarship_id"],
            "amount_received": float(r["amount_received"]),
            "payment_date": r["payment_date"].isoformat(),
            "transaction_reference": r["transaction_reference"] or "",
            "remarks": r["remarks"] or "", "created_at": r["created_at"].isoformat()
        } for r in cur.fetchall()])
    finally:
        db.close()


@app.route("/api/scholarships/<int:scholarship_id>/payments", methods=["POST"])
@login_required
def add_scholarship_payment(scholarship_id):
    uid = session["user_id"]
    data = request.get_json(silent=True) or {}
    try:
        amount_received = float(data.get("amount_received", 0))
        payment_date = date.fromisoformat(str(data.get("payment_date", "")))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount or date"}), 400
    transaction_reference = str(data.get("transaction_reference", "")).strip()[:100]
    remarks = str(data.get("remarks", "")).strip()
    if amount_received <= 0:
        return jsonify({"error": "Payment amount must be greater than 0"}), 400
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id, awarded_amount FROM scholarships WHERE id=%s AND user_id=%s",
                    (scholarship_id, uid))
        schol = cur.fetchone()
        if not schol:
            return jsonify({"error": "Scholarship not found"}), 404
        cur.execute(
            "SELECT COALESCE(SUM(amount_received),0) AS total FROM scholarship_payments WHERE scholarship_id=%s",
            (scholarship_id,))
        already = float(cur.fetchone()["total"])
        cur.execute(
            "INSERT INTO scholarship_payments (scholarship_id, user_id, amount_received, "
            "payment_date, transaction_reference, remarks) VALUES (%s,%s,%s,%s,%s,%s)",
            (scholarship_id, uid, amount_received, payment_date,
             transaction_reference or None, remarks or None))
        new_total = already + amount_received
        awarded = float(schol.get("awarded_amount") or 0)
        new_status = "Received" if (awarded > 0 and new_total >= awarded) else "Partially Received"
        cur.execute("UPDATE scholarships SET status=%s WHERE id=%s AND user_id=%s",
                    (new_status, scholarship_id, uid))
        db.commit()
        new_id = cur.lastrowid
        cur.execute(
            "SELECT id, scholarship_id, amount_received, payment_date, "
            "transaction_reference, remarks, created_at FROM scholarship_payments WHERE id=%s", (new_id,))
        r = cur.fetchone()
        return jsonify({
            "id": r["id"], "scholarship_id": r["scholarship_id"],
            "amount_received": float(r["amount_received"]),
            "payment_date": r["payment_date"].isoformat(),
            "transaction_reference": r["transaction_reference"] or "",
            "remarks": r["remarks"] or "", "created_at": r["created_at"].isoformat(),
            "new_scholarship_status": new_status
        }), 201
    finally:
        db.close()


# ===============================================================
# Reminders
# ===============================================================
@app.route("/api/reminders", methods=["GET"])
@login_required
def get_reminders():
    uid = session["user_id"]
    today = date.today()
    in_7 = today + timedelta(days=7)
    in_15 = today + timedelta(days=15)
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT f.id, f.fee_title, f.fee_category, f.total_amount, f.due_date, "
            "COALESCE(SUM(p.amount_paid),0) AS paid "
            "FROM college_fees f LEFT JOIN fee_payments p ON p.fee_id=f.id "
            "WHERE f.user_id=%s GROUP BY f.id HAVING paid < f.total_amount ORDER BY f.due_date ASC",
            (uid,))
        overdue, due_7, due_15 = [], [], []
        for row in cur.fetchall():
            item = {
                "id": row["id"], "fee_title": row["fee_title"],
                "fee_category": row["fee_category"],
                "total_amount": float(row["total_amount"]),
                "paid": float(row["paid"]),
                "remaining": float(row["total_amount"]) - float(row["paid"]),
                "due_date": row["due_date"].isoformat()
            }
            if row["due_date"] < today:
                overdue.append(item)
            elif row["due_date"] <= in_7:
                due_7.append(item)
            elif row["due_date"] <= in_15:
                due_15.append(item)

        cur.execute(
            "SELECT id, goal_title, target_amount, current_saved_amount, target_date "
            "FROM savings_goals WHERE user_id=%s AND status='Active' "
            "AND target_date IS NOT NULL AND target_date<=%s ORDER BY target_date ASC",
            (uid, in_15.isoformat()))
        upcoming_goals = [{
            "id": r["id"], "goal_title": r["goal_title"],
            "target_amount": float(r["target_amount"]),
            "current_saved_amount": float(r["current_saved_amount"]),
            "target_date": r["target_date"].isoformat()
        } for r in cur.fetchall()]

        cur.execute(
            "SELECT id, scholarship_name, application_deadline, status FROM scholarships "
            "WHERE user_id=%s AND status='Not Applied' AND application_deadline IS NOT NULL "
            "AND application_deadline<=%s ORDER BY application_deadline ASC",
            (uid, in_15.isoformat()))
        upcoming_schols = [{
            "id": r["id"], "scholarship_name": r["scholarship_name"],
            "application_deadline": r["application_deadline"].isoformat(), "status": r["status"]
        } for r in cur.fetchall()]

        return jsonify({
            "overdue_fees": overdue, "fees_due_7_days": due_7, "fees_due_15_days": due_15,
            "upcoming_goal_deadlines": upcoming_goals,
            "upcoming_scholarship_deadlines": upcoming_schols,
            "total_alerts": len(overdue) + len(due_7)
        })
    finally:
        db.close()
from phase5 import register_phase5_routes
register_phase5_routes(app, get_db, login_required)        

# ==========================================
# PHASE 6 - AI FINANCIAL ASSISTANT
# ==========================================

from ai_assistant import register_ai_assistant

register_ai_assistant(
    app,
    get_db,
    login_required
)

print("\n========== PHASE 6 API ROUTES ==========")

for rule in app.url_map.iter_rules():
    if rule.rule.startswith("/api/ai"):
        print(rule.rule, sorted(rule.methods))
from name_based_split import register_name_based_split_routes

register_name_based_split_routes(
    app,
    get_db,
    login_required
)        

print("========================================\n")
register_receipt_scanner_phase3_routes(app, get_db, login_required)
def send_registration_email(to_email, user_name):
    sender = os.getenv("MAIL_USERNAME", "").strip()
    password = os.getenv("MAIL_APP_PASSWORD", "").replace(" ", "")
    sender_name = os.getenv("MAIL_SENDER_NAME", "Finlumiq")

    if not sender or not password:
        app.logger.warning("Email settings are missing.")
        return False

    msg = EmailMessage()
    msg["Subject"] = f"Welcome to {sender_name}!"
    msg["From"] = f"{sender_name} <{sender}>"
    msg["To"] = to_email

    msg.set_content(f"""
Hi {user_name},

Welcome to {sender_name}!

Your account has been created successfully.

Thank you for joining us!

Team {sender_name}
""")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)

        return True

    except (smtplib.SMTPException, OSError):
        app.logger.exception("Registration email could not be sent.")
        return False
if __name__ == "__main__":
    app.run(debug=True, port=5000)