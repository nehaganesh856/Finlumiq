"""Local Gemini connectivity test for Finlumiq. Never prints the API key."""
from pathlib import Path
import os
import sys

BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = BACKEND_DIR / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE, override=False)
except ImportError:
    print("NOTE: python-dotenv is not installed; checking environment variables only.")

api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
model = (os.getenv("GEMINI_MODEL") or "gemini-3.8-flash").strip()

print("Finlumiq Gemini diagnostic")
print("-----------------------------")
print(f"Backend folder: {BACKEND_DIR}")
print(f".env file exists: {'YES' if ENV_FILE.exists() else 'NO'}")
print(f"GEMINI_API_KEY configured: {'YES' if api_key else 'NO'}")
print(f"GEMINI_MODEL: {model}")

if not api_key or api_key in {"YOUR_API_KEY_HERE", "PASTE_YOUR_GEMINI_API_KEY_HERE"}:
    print("RESULT: FAIL — Add a real Gemini API key to backend/.env.")
    sys.exit(2)

try:
    from google import genai
    from google.genai import errors
except ImportError as exc:
    print(f"RESULT: FAIL — Google Gen AI SDK is not installed: {exc}")
    print("Run: python -m pip install --upgrade google-genai")
    sys.exit(3)

try:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents="Reply with exactly: GEMINI_OK",
    )
    reply = (getattr(response, "text", None) or "").strip()
    if not reply:
        print("RESULT: FAIL — Gemini API responded but returned no text.")
        sys.exit(4)
    print("RESULT: SUCCESS — Gemini API request completed.")
    print(f"Model response: {reply[:300]}")
except errors.APIError as exc:
    print(f"RESULT: FAIL — Gemini API HTTP {getattr(exc, 'code', 'unknown')}.")
    print(f"Provider message: {getattr(exc, 'message', str(exc))}")
    code = getattr(exc, "code", None)
    if code in (401, 403):
        print("Check that the key was created in Google AI Studio and is permitted to use Gemini API.")
    elif code == 404:
        print("Check GEMINI_MODEL spelling and model availability for this key/project.")
    elif code == 429:
        print("Check Google AI Studio usage, quota and billing/rate limits.")
    sys.exit(5)
except Exception as exc:
    print(f"RESULT: FAIL — {type(exc).__name__}: {exc}")
    print("Check internet access, firewall/proxy, Python SDK version and the traceback above.")
    sys.exit(6)
