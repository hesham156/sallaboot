"""
Admin authentication.
- HMAC-SHA256 signed tokens (like JWT but without python-jose/PyJWT)
- Argon2id password hashing (was salted SHA-256 — legacy hashes still verify
  and are transparently upgraded on next successful login).
"""

import os
import hmac
import hashlib
import base64
import json
import time
import secrets
from typing import Optional

# argon2-cffi: required for new password hashes. Install via requirements.txt.
# If the package is missing we fall back to legacy SHA-256 so an emergency
# deploy without the dep still boots (auth still works for existing accounts).
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
    # Conservative parameters — fast enough for interactive login (< 60 ms on
    # a Railway shared CPU) while well above the 2024 OWASP minimum.
    _ph = PasswordHasher(
        time_cost=3,
        memory_cost=64 * 1024,  # 64 MiB
        parallelism=2,
        hash_len=32,
        salt_len=16,
    )
    _ARGON2_AVAILABLE = True
except ImportError:
    print("⚠️  [auth] argon2-cffi not installed — falling back to SHA-256 (insecure)")
    _ph = None
    _ARGON2_AVAILABLE = False
    VerifyMismatchError = InvalidHashError = VerificationError = Exception

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
#
# Hash layout discrimination:
#   • Argon2id → starts with "$argon2"     (PHC string format)
#   • Legacy   → "<hex_salt>:<sha256_hex>" (no leading "$")
#
# This lets a single check_password() verify both formats without a flag.

def _legacy_check(password: str, stored: str) -> bool:
    """Constant-time SHA-256+salt verify (the original scheme)."""
    if not stored or ":" not in stored:
        return False
    try:
        salt, h = stored.split(":", 1)
        candidate = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return hmac.compare_digest(candidate, h)
    except Exception:
        return False


def hash_password(password: str) -> str:
    """Hash a password with argon2id (preferred) or SHA-256+salt (fallback)."""
    if _ARGON2_AVAILABLE and _ph is not None:
        return _ph.hash(password)
    # Fallback — only reached if argon2-cffi isn't installed.
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def check_password(password: str, stored: str) -> bool:
    """Verify against either argon2id or the legacy SHA-256+salt format."""
    if not stored:
        return False
    if stored.startswith("$argon2") and _ARGON2_AVAILABLE and _ph is not None:
        try:
            _ph.verify(stored, password)
            return True
        except (VerifyMismatchError, InvalidHashError, VerificationError):
            return False
        except Exception:
            return False
    return _legacy_check(password, stored)


def needs_rehash(stored: str) -> bool:
    """
    True if `stored` should be upgraded to a fresh argon2id hash. Call this
    right after a successful check_password() and, if True, re-hash the
    password and persist the new value. Used to migrate legacy SHA-256
    entries silently as users log in.
    """
    if not stored:
        return False
    if not stored.startswith("$argon2"):
        return _ARGON2_AVAILABLE  # legacy → upgrade if argon2 is available
    if _ARGON2_AVAILABLE and _ph is not None:
        try:
            return _ph.check_needs_rehash(stored)
        except Exception:
            return False
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
    now = int(time.time())
    payload: dict = {
        "s":   store_id,
        "su":  is_super,
        "iat": now,   # issued-at — enables password-change session revocation (H-2)
        "exp": now + TOKEN_EXPIRY_SECONDS,
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


# ── Password-reset tokens ─────────────────────────────────────────────────────

RESET_TOKEN_EXPIRY = 60 * 60  # 1 hour


def make_reset_token(email: str) -> str:
    """Return a signed, time-limited password-reset token for *email*."""
    exp = int(time.time()) + RESET_TOKEN_EXPIRY
    payload = base64.urlsafe_b64encode(
        json.dumps({"e": email.lower(), "exp": exp}, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    sig = hmac.new(ADMIN_SECRET.encode(), f"reset:{payload}".encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_reset_token(token: str) -> Optional[str]:
    """Verify a reset token. Returns the email or None if invalid / expired."""
    if not token:
        return None
    try:
        payload, sig = token.rsplit(".", 1)
        expected = hmac.new(ADMIN_SECRET.encode(), f"reset:{payload}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        padding = 4 - len(payload) % 4
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * padding))
        if data.get("exp", 0) < time.time():
            return None
        return data.get("e")
    except Exception:
        return None


# ── Email OTP + trusted-device tokens ──────────────────────────────────────────
#
# Both are STATELESS (no DB table): a payload is HMAC-signed with ADMIN_SECRET,
# exactly like the session tokens above. For OTP the signed "challenge" carries
# only the HMAC of the 6-digit code — never the code itself — so even if the
# challenge leaks, the code can't be brute-forced offline (the attacker lacks
# ADMIN_SECRET). Online guessing is capped by the verify endpoint's rate limit.

OTP_TTL_SECONDS          = 10 * 60          # code valid for 10 minutes
DEVICE_TRUST_TTL_SECONDS = 30 * 24 * 60 * 60  # "remember this device" for 30 days


def _sign_payload(payload: dict) -> str:
    """base64url(json).hmac — same envelope as create_token."""
    data = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    sig = hmac.new(ADMIN_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"


def _unsign_payload(token: str) -> Optional[dict]:
    """Verify signature + return the payload, or None. Does NOT check expiry."""
    if not token or "." not in token:
        return None
    try:
        data, sig = token.rsplit(".", 1)
        expected = hmac.new(ADMIN_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        padding = 4 - len(data) % 4
        return json.loads(base64.urlsafe_b64decode(data + "=" * padding))
    except Exception:
        return None


def generate_otp_code() -> str:
    """A 6-digit numeric one-time code (cryptographically random)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _otp_code_hash(code: str) -> str:
    return hmac.new(ADMIN_SECRET.encode(), code.encode(), hashlib.sha256).hexdigest()


def make_otp_challenge(email: str, purpose: str, code: str) -> str:
    """Signed proof of an outstanding OTP. Carries the code's HMAC, not the code."""
    return _sign_payload({
        "em":  (email or "").strip().lower(),
        "p":   purpose,
        "ch":  _otp_code_hash(code),
        "exp": int(time.time()) + OTP_TTL_SECONDS,
        "n":   secrets.token_hex(4),
    })


def verify_otp_challenge(challenge: str, email: str, purpose: str, code: str) -> bool:
    """True iff `challenge` is a valid, unexpired challenge for (email, purpose)
    and `code` matches the hash it carries."""
    p = _unsign_payload(challenge)
    if not p:
        return False
    if int(p.get("exp", 0)) < int(time.time()):
        return False
    if p.get("em") != (email or "").strip().lower():
        return False
    if p.get("p") != purpose:
        return False
    return hmac.compare_digest(str(p.get("ch", "")), _otp_code_hash(code or ""))


def make_device_trust(email: str) -> str:
    """A 30-day 'this device already passed OTP' token, bound to the email."""
    return _sign_payload({
        "em":  (email or "").strip().lower(),
        "typ": "devtrust",
        "exp": int(time.time()) + DEVICE_TRUST_TTL_SECONDS,
    })


def device_trust_valid(token: str, email: str) -> bool:
    """True iff `token` is a valid, unexpired device-trust token for `email`."""
    p = _unsign_payload(token)
    if not p:
        return False
    return (
        p.get("typ") == "devtrust"
        and p.get("em") == (email or "").strip().lower()
        and int(p.get("exp", 0)) >= int(time.time())
    )


def session_invalidated(claims: dict, *, pwd_changed_at: float = 0.0,
                        employee: Optional[dict] = None) -> bool:
    """
    Decide whether a still-unexpired token must nonetheless be REJECTED because
    the underlying principal changed since the token was issued (finding H-2).

    Stateless verify_token() can't see these changes, so the auth boundary
    (middleware) supplies the current backing state and calls this:

      • Employee token ("eid" present): pass the live DB record as `employee`.
        Revoked when the employee is deleted (None), deactivated (active=False),
        or their role no longer matches the role baked into the token.
        NOTE: only call this for employees when the DB is reachable — otherwise
        a missing record is indistinguishable from an outage. The caller must
        skip the check (fail-open) when the DB is down.

      • Owner token (no "eid"): pass the store's `pwd_changed_at` (epoch secs).
        Revoked when the token was issued before the last password change.

    Super tokens are env-credential based and are never versioned here (rotate
    ADMIN_SECRET to revoke them); the caller skips super tokens entirely.
    """
    if "eid" in claims:
        if not employee or not employee.get("active"):
            return True
        return str(employee.get("role", "agent")) != str(claims.get("er", "agent"))
    iat = int(claims.get("iat", 0))
    return bool(pwd_changed_at) and iat < int(pwd_changed_at)
