"""
rate_limit.py — Simple in-memory rate limiter for Finlumiq auth routes.

No Redis or external dependency required.
Suitable for single-process dev/small-scale deployment.

Usage:
    from rate_limit import RateLimiter

    limiter = RateLimiter(max_calls=5, window_seconds=300)

    @app.route("/api/auth/login", methods=["POST"])
    def login():
        ip = request.remote_addr
        if not limiter.allow(ip):
            return jsonify({"error": "Too many attempts. Please wait a few minutes."}), 429
        ...
"""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """
    Sliding-window rate limiter.
    Thread-safe via a lock.

    Args:
        max_calls:       Maximum requests allowed in the window.
        window_seconds:  Length of the sliding window in seconds.
    """

    def __init__(self, max_calls: int = 5, window_seconds: int = 300):
        self.max_calls = max_calls
        self.window    = window_seconds
        self._lock     = threading.Lock()
        # key → deque of timestamps
        self._calls: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """
        Return True if the request is allowed, False if rate-limited.
        Advances the internal counter on every call.
        """
        now = time.monotonic()
        cutoff = now - self.window

        with self._lock:
            dq = self._calls[key]
            # Evict timestamps outside the window
            while dq and dq[0] < cutoff:
                dq.popleft()

            if len(dq) >= self.max_calls:
                return False

            dq.append(now)
            return True

    def reset(self, key: str) -> None:
        """Clear the counter for a key (e.g. after successful login)."""
        with self._lock:
            self._calls.pop(key, None)

    def remaining(self, key: str) -> int:
        """Return how many calls are left in the current window."""
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            dq = self._calls[key]
            count = sum(1 for t in dq if t >= cutoff)
            return max(0, self.max_calls - count)


# ---------------------------------------------------------------
# Pre-configured limiters for each auth action
# ---------------------------------------------------------------

# Login: 10 attempts per 15 minutes per IP
login_limiter = RateLimiter(max_calls=10, window_seconds=900)

# Registration: 5 attempts per 10 minutes per IP
register_limiter = RateLimiter(max_calls=5, window_seconds=600)

# Resend verification email: 3 per 10 minutes per IP
resend_limiter = RateLimiter(max_calls=3, window_seconds=600)

# Forgot password: 5 per 15 minutes per IP
forgot_limiter = RateLimiter(max_calls=5, window_seconds=900)

# Reset password token submission: 10 per 15 minutes per IP
reset_limiter = RateLimiter(max_calls=10, window_seconds=900)
