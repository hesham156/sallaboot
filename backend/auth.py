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

# ── Signing secret ────────────────────────────────────────────────────────────
# MUST be set as ADMIN_SECRET in Railway environment variables.
# If not set, a new random secret is generated on every restart — this
# immediately invalidates ALL admin tokens, forcing every user to re-login
# after each deploy.
_secret_from_env: str = os.getenv("ADMIN_SECRET", "").strip()
ADMIN_SECRET: str      = _secret_from_env or secrets.token_hex(32)
ADMIN_SECRET_STABLE: bool = bool(_secret_from_env)   # exposed to /env-check

if not ADMIN_SECRET_STABLE:
    print("=" * 60)
    print("⚠️  ADMIN_SECRET is NOT set!")
    print("    Admin tokens will be INVALIDATED on every server restart.")
    print("    Fix: add ADMIN_SECRET=<random_hex> to Railway env vars.")
    print("=" * 60)

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

def create_token(
    store_id: str,
    is_super: bool = False,
    employee_id: Optional[int] = None,
    employee_name: str = "",
    employee_role: str = "",
) -> str:
    """Create a signed token for the given store.

    When `employee_id` is set, the token represents an employee logged in
    under a store. The store-level routes still authorise (same store_id),
    but admin replies and audit trails carry the employee's name.
    """
    payload: dict = {
        "s":   store_id,
        "su":  is_super,
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
    }
    if employee_id is not None:
        payload["eid"] = int(employee_id)
        payload["en"]  = employee_name
        payload["er"]  = employee_role or "agent"
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


def token_employee(token: str) -> Optional[dict]:
    """Return {id, name, role} when the token belongs to an employee, else None."""
    p = verify_token(token)
    if not p or "eid" not in p:
        return None
    return {
        "id":   int(p.get("eid", 0)),
        "name": str(p.get("en", "")),
        "role": str(p.get("er", "agent")),
    }
