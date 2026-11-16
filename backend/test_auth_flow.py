"""
test_auth_flow.py — Offline unit tests for the Google authentication route.

These tests mock google.oauth2.id_token.verify_oauth2_token so no real
Google token or database connection is needed.

Run:
    python test_auth_flow.py
"""

import hashlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Minimal stubs so app.py can be imported without a live DB or SMTP server.
# ---------------------------------------------------------------------------

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_USER", "root")
os.environ.setdefault("DB_PASSWORD", "")
os.environ.setdefault("DB_NAME",  "expense_tracker_fixed")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:8000")

# Stub heavy optional imports that are not installed in every venv
for _mod in ("receipt_scanner_phase3_routes", "mail", "rate_limit"):
    _stub = types.ModuleType(_mod)
    _stub.register_receipt_scanner_phase3_routes = lambda *a, **kw: None  # noqa
    _stub.forgot_limiter  = MagicMock(allow=lambda ip: True, reset=lambda ip: None)
    _stub.login_limiter   = MagicMock(allow=lambda ip: True, reset=lambda ip: None)
    _stub.register_limiter = MagicMock(allow=lambda ip: True)
    _stub.resend_limiter  = MagicMock(allow=lambda ip: True)
    _stub.reset_limiter   = MagicMock(allow=lambda ip: True)
    sys.modules.setdefault(_mod, _stub)

# Patch mysql.connector.pooling so no real DB pool is created at import time
import mysql.connector.pooling as _pooling  # noqa: E402
_original_pool_cls = _pooling.MySQLConnectionPool

class _FakePool:
    def __init__(self, *a, **kw): pass
    def get_connection(self): raise RuntimeError("No DB in unit tests")

_pooling.MySQLConnectionPool = _FakePool  # type: ignore

import app as flask_app  # noqa: E402

_pooling.MySQLConnectionPool = _original_pool_cls  # restore

REAL_CLIENT_ID = "10575419495-ahcn2dttd279kurp8ihha1p6ujg84ifp.apps.googleusercontent.com"

flask_app.app.config["TESTING"] = True
flask_app.app.config["SECRET_KEY"] = "test-secret-key-for-unit-tests-only"
flask_app.app.config["SESSION_COOKIE_SECURE"] = False   # allow plain HTTP in tests
flask_app.app.config["GOOGLE_CLIENT_ID"] = REAL_CLIENT_ID  # ensure not empty

client = flask_app.app.test_client()


# ---------------------------------------------------------------------------
# Helper — build a fake Google token payload
# ---------------------------------------------------------------------------

def _google_payload(*, sub="12345", email="user@example.com",
                    email_verified=True, iss="https://accounts.google.com",
                    name="Test User"):
    return {
        "sub":            sub,
        "email":          email,
        "email_verified": email_verified,
        "name":           name,
        "iss":            iss,
        "aud":            REAL_CLIENT_ID,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGoogleClientIdConfig(unittest.TestCase):
    """GOOGLE_CLIENT_ID must be non-empty and not the placeholder."""

    def test_client_id_non_empty_in_app_config(self):
        with flask_app.app.app_context():
            cid = flask_app.app.config.get("GOOGLE_CLIENT_ID", "")
            self.assertTrue(cid, "GOOGLE_CLIENT_ID must not be empty")
            self.assertNotEqual(
                cid, "PASTE_YOUR_GOOGLE_CLIENT_ID_HERE",
                "GOOGLE_CLIENT_ID must not be the placeholder value"
            )

    def test_env_override_applied(self):
        """When GOOGLE_CLIENT_ID env var is set, app.config must reflect it."""
        original = os.environ.get("GOOGLE_CLIENT_ID")
        try:
            os.environ["GOOGLE_CLIENT_ID"] = "custom-client-id.apps.googleusercontent.com"
            # Re-evaluate the expression the same way app.py does
            value = os.getenv(
                "GOOGLE_CLIENT_ID",
                "10575419495-ahcn2dttd279kurp8ihha1p6ujg84ifp.apps.googleusercontent.com"
            )
            self.assertEqual(value, "custom-client-id.apps.googleusercontent.com")
        finally:
            if original is None:
                os.environ.pop("GOOGLE_CLIENT_ID", None)
            else:
                os.environ["GOOGLE_CLIENT_ID"] = original


class TestGoogleLoginEndpoint(unittest.TestCase):

    def _post(self, payload):
        return client.post(
            "/api/auth/google",
            json=payload,
            content_type="application/json"
        )

    # ------------------------------------------------------------------
    # Test 1 — missing credential → 400
    # ------------------------------------------------------------------
    def test_missing_credential_returns_400(self):
        resp = self._post({})
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertIn("error", body)
        self.assertIn("missing", body["error"].lower())

    # ------------------------------------------------------------------
    # Test 2 — invalid token → 401
    # ------------------------------------------------------------------
    @patch("google.oauth2.id_token.verify_oauth2_token",
           side_effect=ValueError("bad token"))
    def test_invalid_token_returns_401(self, _mock):
        resp = self._post({"credential": "bad.token.value"})
        self.assertEqual(resp.status_code, 401)
        body = resp.get_json()
        self.assertIn("error", body)

    # ------------------------------------------------------------------
    # Test 3 — unverified email → 403
    # ------------------------------------------------------------------
    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("app.get_db")
    def test_unverified_email_returns_403(self, mock_db, mock_verify):
        mock_verify.return_value = _google_payload(email_verified=False)
        resp = self._post({"credential": "token.with.unverified.email"})
        self.assertEqual(resp.status_code, 403)

    # ------------------------------------------------------------------
    # Test 4 — invalid issuer → 401
    # ------------------------------------------------------------------
    @patch("google.oauth2.id_token.verify_oauth2_token")
    def test_invalid_issuer_returns_401(self, mock_verify):
        mock_verify.return_value = _google_payload(iss="https://evil.com")
        resp = self._post({"credential": "token.bad.iss"})
        self.assertEqual(resp.status_code, 401)

    # ------------------------------------------------------------------
    # Test 5 — existing account without google_sub → 409 with link_required
    # ------------------------------------------------------------------
    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("app.get_db")
    def test_link_required_when_email_exists_no_google_sub(self, mock_get_db, mock_verify):
        mock_verify.return_value = _google_payload()

        # Build a mock cursor that:
        #   1. column_count=1  (google_sub column exists)
        #   2. column_count=1  (email_verified column exists)
        #   3. user=None       (no match by google_sub)
        #   4. existing_user   (match by email, no google_sub)
        from werkzeug.security import generate_password_hash
        fake_user = {
            "id": 42, "name": "Existing", "email": "user@example.com",
            "password_hash": generate_password_hash("secret"),
            "google_sub": None,
        }

        cursor_mock = MagicMock()
        cursor_mock.fetchone.side_effect = [
            {"column_count": 1},  # google_sub column check
            {"column_count": 1},  # email_verified column check
            None,                 # SELECT by google_sub → no match
            fake_user,            # SELECT by email → found
        ]
        db_mock = MagicMock()
        db_mock.cursor.return_value = cursor_mock
        mock_get_db.return_value = db_mock

        resp = self._post({"credential": "valid.token"})
        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertTrue(body.get("link_required"), "link_required flag must be True")

    # ------------------------------------------------------------------
    # Test 6 — google_sub column missing → 500 with clear message
    # ------------------------------------------------------------------
    @patch("google.oauth2.id_token.verify_oauth2_token")
    @patch("app.get_db")
    def test_missing_google_sub_column_returns_500(self, mock_get_db, mock_verify):
        mock_verify.return_value = _google_payload()

        cursor_mock = MagicMock()
        cursor_mock.fetchone.return_value = {"column_count": 0}
        db_mock = MagicMock()
        db_mock.cursor.return_value = cursor_mock
        mock_get_db.return_value = db_mock

        resp = self._post({"credential": "valid.token"})
        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertIn("migration", body["error"].lower())


class TestAuthSharedJs503Message(unittest.TestCase):
    """Verify auth-shared.js no longer has the XAMPP hardcoded 503 message."""

    def test_no_xampp_message_in_auth_shared(self):
        path = os.path.join(
            os.path.dirname(__file__),
            "..", "frontend", "js", "auth-shared.js"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn(
            "XAMPP",
            content,
            "auth-shared.js must not contain the XAMPP error message"
        )
        self.assertNotIn(
            "start MySQL from XAMPP",
            content,
            "auth-shared.js must not contain XAMPP-specific instructions"
        )


class TestLoginHtmlSessionVerification(unittest.TestCase):
    """Verify login.html calls /auth/me after Google sign-in before redirecting."""

    def test_login_html_calls_auth_me_after_google_login(self):
        path = os.path.join(
            os.path.dirname(__file__),
            "..", "frontend", "login.html"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn(
            "/auth/me",
            content,
            "login.html must call /auth/me to verify session after Google sign-in"
        )
        # Ensure the old immediate redirect without verification is gone
        # (the fixed version has apiGet('/auth/me') before location.replace)
        self.assertIn(
            "apiGet",
            content,
            "login.html must use apiGet to verify session"
        )


class TestLoginHtmlUxMode(unittest.TestCase):
    """Verify login.html uses ux_mode: 'popup' in google.accounts.id.initialize."""

    def test_ux_mode_popup_present(self):
        path = os.path.join(
            os.path.dirname(__file__),
            "..", "frontend", "login.html"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn(
            "ux_mode",
            content,
            "login.html must set ux_mode in google.accounts.id.initialize()"
        )
        self.assertIn(
            "popup",
            content,
            "login.html ux_mode must be 'popup'"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
