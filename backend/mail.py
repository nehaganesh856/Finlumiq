"""
mail.py — Gmail SMTP email sender for Finlumiq
Uses environment variables — never hardcode credentials.

Required .env keys:
  MAIL_USERNAME        = your_gmail@gmail.com
  MAIL_PASSWORD        = xxxx xxxx xxxx xxxx  (Google App Password)
  MAIL_DEFAULT_SENDER  = Finlumiq <your_gmail@gmail.com>
  FRONTEND_ORIGIN      = http://127.0.0.1:8000
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_SENDER   = os.getenv("MAIL_DEFAULT_SENDER", MAIL_USERNAME)
FRONTEND_URL  = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:8000")
SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587


def _mail_configured() -> bool:
    return bool(MAIL_USERNAME and MAIL_PASSWORD)


def _send(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """
    Send an email via Gmail SMTP.
    Returns True on success, False on failure.
    Never raises — logs errors instead.
    """
    if not _mail_configured():
        logger.warning(
            "MAIL_USERNAME / MAIL_PASSWORD not set in .env — email not sent to %s", to_email
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = MAIL_SENDER
    msg["To"]      = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html",  "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(MAIL_USERNAME, MAIL_PASSWORD)
            smtp.sendmail(MAIL_USERNAME, to_email, msg.as_string())
        logger.info("Email sent to %s — subject: %s", to_email, subject)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed — check MAIL_USERNAME / MAIL_PASSWORD in .env")
    except smtplib.SMTPException as exc:
        logger.error("SMTP error sending to %s: %s", to_email, exc)
    except Exception as exc:
        logger.error("Unexpected error sending email to %s: %s", to_email, exc)
    return False


# ---------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------

_BASE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',system-ui,sans-serif;}}
  .wrap{{max-width:560px;margin:40px auto;background:#ffffff;border-radius:16px;
         overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);}}
  .header{{background:linear-gradient(135deg,#6366f1,#8b5cf6);padding:36px 40px;text-align:center;}}
  .header h1{{margin:0;color:#fff;font-size:24px;font-weight:800;}}
  .header p{{margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:14px;}}
  .body{{padding:36px 40px;}}
  .body h2{{margin:0 0 12px;font-size:18px;color:#0f172a;}}
  .body p{{margin:0 0 16px;font-size:14px;line-height:1.6;color:#475569;}}
  .btn{{display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#6366f1,#8b5cf6);
        color:#fff;text-decoration:none;border-radius:999px;font-weight:700;font-size:15px;
        margin:8px 0 20px;}}
  .note{{font-size:12px;color:#94a3b8;line-height:1.5;border-top:1px solid #e2e8f0;
         padding-top:16px;margin-top:8px;}}
  .footer{{background:#f8fafc;padding:20px 40px;text-align:center;
           font-size:12px;color:#94a3b8;border-top:1px solid #e2e8f0;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>🎓 Finlumiq</h1>
    <p>Smart Student Expense Tracker</p>
  </div>
  <div class="body">
    {content}
  </div>
  <div class="footer">
    &copy; 2024 Finlumiq &bull; This email was sent because you registered or requested a password reset.
    If you did not request this, ignore this email.
  </div>
</div>
</body>
</html>
"""


def send_verification_email(to_email: str, name: str, token: str) -> bool:
    """Send email verification link."""
    verify_url = f"{FRONTEND_URL}/verify-email.html?token={token}"

    content = f"""\
<h2>Verify your email address</h2>
<p>Hi <strong>{name}</strong>,</p>
<p>Welcome to Finlumiq! Please click the button below to verify your email address
and activate your account.</p>
<a class="btn" href="{verify_url}">✅ Verify Email Address</a>
<p class="note">
  This link expires in <strong>30 minutes</strong>.<br>
  If the button doesn't work, copy and paste this URL into your browser:<br>
  <span style="word-break:break-all;color:#6366f1;">{verify_url}</span>
</p>
"""

    text = (
        f"Hi {name},\n\n"
        f"Welcome to Finlumiq! Please verify your email by visiting:\n{verify_url}\n\n"
        f"This link expires in 30 minutes.\n\nIf you did not register, ignore this email."
    )

    return _send(to_email, "Verify your Finlumiq email address", _BASE_HTML.format(content=content), text)


def send_reset_email(to_email: str, name: str, token: str) -> bool:
    """Send password reset link."""
    reset_url = f"{FRONTEND_URL}/reset-password.html?token={token}"

    content = f"""\
<h2>Reset your password</h2>
<p>Hi <strong>{name}</strong>,</p>
<p>We received a request to reset your Finlumiq password.
Click the button below to choose a new password.</p>
<a class="btn" href="{reset_url}">🔑 Reset Password</a>
<p class="note">
  This link expires in <strong>20 minutes</strong> and can only be used once.<br>
  If you did not request a password reset, you can safely ignore this email —
  your password will not change.<br><br>
  If the button doesn't work, copy and paste this URL:<br>
  <span style="word-break:break-all;color:#6366f1;">{reset_url}</span>
</p>
"""

    text = (
        f"Hi {name},\n\n"
        f"Reset your Finlumiq password by visiting:\n{reset_url}\n\n"
        f"This link expires in 20 minutes and can only be used once.\n\n"
        f"If you did not request this, ignore this email."
    )

    return _send(to_email, "Reset your Finlumiq password", _BASE_HTML.format(content=content), text)


def is_configured() -> bool:
    """Return True if SMTP credentials are set in .env."""
    return _mail_configured()
