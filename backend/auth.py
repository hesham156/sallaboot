"""
Admin authentication — no external dependencies.
- HMAC-SHA256 signed tokens (like JWT but without python-jose/PyJWT)
- SHA-256 + salt password hashing
"""

import os
import hmac
import hashlib
import base64
import json
import time
import secrets
from typing import Optional

# Server-side signing secret — set ADMIN_SECRET in Railway env vars!
# Falls back to a random secret (tokens invalidated on each restart).
ADMIN_SECRET: str = os.getenv("ADMIN_SECRET", "") or secrets.token_hex(32)

TOKEN_EXPIRY_SECONDS = 60 * 60 * 24 * 7  # 7 days


# ── Password hashing ───────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Return a salted SHA-256 hash string: '<salt>:<hex>'."""
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def check_password(password: str, stored: str) -> bool:
    """Constant-time comparison of password against stored hash."""
    if not stored or ":" not in stored:
        return False
    try:
        salt, h = stored.split(":", 1)
        candidate = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return hmac.compare_digest(candidate, h)
    except Exception:
        return False


# ── Token creation / verification ─────────────────────────────────────────────

def create_token(store_id: str, is_super: bool = False) -> str:
    """Create a signed token for the given store."""
    payload = {
        "s":   store_id,
        "su":  is_super,
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
    }
    # URL-safe base64 of JSON payload
    data = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    sig = hmac.new(ADMIN_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"


def verify_token(token: str) -> Optional[dict]:
    """
    Verify token signature + expiry.
    Returns the payload dict, or None if invalid/expired.
    """
    if not token:
        return None
    try:
        data, sig = token.rsplit(".", 1)
        expected = hmac.new(ADMIN_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        # Restore base64 padding
        padding = 4 - len(data) % 4
        payload = json.loads(base64.urlsafe_b64decode(data + "=" * padding))
        if payload.get("exp", 0) < time.time():
            return None  # expired
        return payload
    except Exception:
        return None


def token_store_id(token: str) -> Optional[str]:
    """Quick helper — returns store_id from token or None."""
    p = verify_token(token)
    return p.get("s") if p else None


def token_is_super(token: str) -> bool:
    p = verify_token(token)
    return bool(p and p.get("su"))
