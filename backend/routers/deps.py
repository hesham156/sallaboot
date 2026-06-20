"""
Shared dependencies used across multiple routers.

Keeps rate-limiting, audit helpers, budget checks, and access-control
utilities in one place so routers don't cross-import each other.
"""
import os
import hmac
import hashlib
from pathlib import Path

import auth as _auth
import database as db
import store_manager as sm

# ── Upload constants (shared between settings and files routers) ────────────
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_MB        = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
ALLOWED_EXTENSIONS = {
    ".pdf", ".ai", ".eps", ".psd", ".png", ".jpg", ".jpeg",
    ".svg", ".tiff", ".tif", ".cdr", ".zip",
}

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".tif": "image/tiff", ".tiff": "image/tiff",
    ".ai":  "application/postscript", ".eps": "application/postscript",
    ".psd": "image/vnd.adobe.photoshop",
    ".cdr": "application/vnd.corel-draw",
    ".zip": "application/zip",
}

# Slack for the multipart envelope (boundaries + small form fields) when using
# Content-Length as a coarse early-reject, so a file exactly at the limit isn't
# falsely rejected. The streaming check below remains the authoritative bound.
_UPLOAD_CL_SLACK = 64 * 1024


async def read_upload_bounded(file, max_bytes: int, *, content_length: int | None = None) -> bytes:
    """
    Read an UploadFile in chunks, aborting the moment it exceeds ``max_bytes``
    (finding M-4). Replaces ``await file.read()`` which buffers the ENTIRE body
    into RAM before any size check — a memory-exhaustion DoS on a large upload.

    Honours ``content_length`` (the request's Content-Length) as an early reject
    so an oversized body isn't streamed at all. Memory is bounded to ~max_bytes.
    Raises HTTPException(413) on overflow.
    """
    from fastapi import HTTPException
    limit_mb = max(1, max_bytes // (1024 * 1024))
    too_big  = HTTPException(413, f"حجم الملف يتجاوز الحد المسموح ({limit_mb} MB)")
    if content_length is not None and content_length > max_bytes + _UPLOAD_CL_SLACK:
        raise too_big
    chunks: list[bytes] = []
    total  = 0
    while True:
        part = await file.read(1024 * 1024)
        if not part:
            break
        total += len(part)
        if total > max_bytes:
            raise too_big
        chunks.append(part)
    return b"".join(chunks)


def _content_length(request) -> int | None:
    """Best-effort parse of the request Content-Length header → int or None."""
    try:
        raw = request.headers.get("content-length") if request else None
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None

# ── Audit ─────────────────────────────────────────────────────────────────────
_REASON_MIN_LENGTH = 5
_REASON_MAX_LENGTH = 500


def audit_actor(request) -> str:
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token) or {}
    if not claims:
        return "anonymous"
    if claims.get("su"):
        return "super"
    sid = claims.get("s", "")
    eid = claims.get("eid")
    if eid:
        return f"emp:{eid}@{sid}"
    return f"store:{sid}"


async def audit(request, action: str, *, target_store: str = "", details: dict | None = None) -> None:
    await db.audit_record(
        actor        = audit_actor(request),
        action       = action,
        target_store = target_store,
        details      = details or {},
        ip           = (request.client.host if request.client else "")[:64],
        user_agent   = request.headers.get("User-Agent", "")[:500],
    )


def super_viewing_other_store(request, store_id: str) -> bool:
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token) or {}
    if not claims.get("su"):
        return False
    return (claims.get("s") or "") != store_id


# ── Session revocation (H-2) ───────────────────────────────────────────────────
# Single source of truth for "should this still-unexpired token be REJECTED
# because the principal changed since it was issued?" Used by the middleware AND
# every inline guard so revocation is enforced identically everywhere.
# auth.session_invalidated() holds the actual decision; these helpers only fetch
# the current backing state. Fail-open on any backend hiccup so a transient
# outage can't lock everyone out.

def _owner_session_revoked(claims: dict, store_id: str) -> bool:
    """Owner-token revocation (password change). Synchronous + in-memory: the
    store's pwd_changed_at lives in the registry, so no I/O is needed. Employee
    tokens are handled by session_is_revoked (they need a DB read)."""
    try:
        pwd_at = (sm.get_store_info(store_id) or {}).get("pwd_changed_at", 0)
        return _auth.session_invalidated(claims, pwd_changed_at=float(pwd_at or 0))
    except Exception:
        return False


async def session_is_revoked(claims: dict, store_id: str) -> bool:
    """Full revocation check for the auth boundary. True if the token must be
    rejected. Super tokens are env-credential based and are never revoked here
    (rotate ADMIN_SECRET instead)."""
    if claims.get("su"):
        return False
    if "eid" in claims:
        # Employee: verify the live DB record — but only when the DB is
        # reachable, else fail-open (a missing row during an outage must not be
        # misread as "deleted" → mass lockout).
        if not db.available():
            return False
        try:
            emp = await db.get_employee(int(claims["eid"]))
        except Exception:
            return False
        return _auth.session_invalidated(claims, employee=emp)
    return _owner_session_revoked(claims, store_id)


# ── Role guards ───────────────────────────────────────────────────────────────

def require_store_owner(request, store_id: str):
    from fastapi import HTTPException
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    # No / invalid token → reject. (Without this an unauthenticated caller fell
    # through to the implicit allow below — and these owner endpoints sit OUTSIDE
    # the middleware's _PROTECTED_RE allowlist, so this guard is the only gate.)
    if not claims:
        raise HTTPException(401, "يرجى تسجيل الدخول")
    if claims.get("su"):
        return
    # Bind the token to the store being acted on. Without this, any valid owner
    # token authorised every other store (cross-store IDOR — e.g. reading another
    # merchant's linking api-key, then hijacking their account).
    if (claims.get("s") or "") != store_id:
        raise HTTPException(403, "غير مصرح لك بالوصول")
    if "eid" in claims:
        raise HTTPException(403, "هذا الإجراء مخصّص لمالك المتجر")
    # H-2: revoke owner tokens issued before the last password change. (Employees
    # are rejected above, so only owner tokens reach here → the sync check is
    # sufficient; no DB read needed.)
    if _owner_session_revoked(claims, store_id):
        raise HTTPException(401, "انتهت الجلسة، يرجى تسجيل الدخول مجدداً")


async def require_store_member(request, store_id: str):
    """Any authenticated member of THIS store (owner, manager, or agent),
    bound to store_id. Super admin passes (cross-store).

    Use on per-store routes that sit OUTSIDE the middleware's _PROTECTED_RE
    allowlist and therefore have no other gate (e.g. contacts, campaigns).
    Unlike require_store_owner this does NOT reject employees — it only
    enforces authentication + tenant binding, so an agent or manager of the
    same store still passes, while a token for another store (or no token at
    all) is rejected (closes the unauthenticated + cross-store IDOR).

    Async because the H-2 revocation check needs a DB read for employee tokens;
    it shares session_is_revoked() with the middleware so enforcement is
    identical on these inline-guarded routes."""
    from fastapi import HTTPException
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims:
        raise HTTPException(401, "يرجى تسجيل الدخول")
    if claims.get("su"):
        return
    if (claims.get("s") or "") != store_id:
        raise HTTPException(403, "غير مصرح لك بالوصول")
    # H-2: reject fired/deactivated/demoted employees + post-password-change owners.
    if await session_is_revoked(claims, store_id):
        raise HTTPException(401, "انتهت الجلسة، يرجى تسجيل الدخول مجدداً")


def require_manager_or_owner(request):
    from fastapi import HTTPException
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token) or {}
    if claims.get("su"):
        return
    if "eid" not in claims:
        return  # store owner
    role = claims.get("er", "agent")
    if role != "manager":
        raise HTTPException(403, "صلاحيتك لا تسمح بهذا الإجراء")


# ── Rate limiting ─────────────────────────────────────────────────────────────

async def is_rate_limited(attempt_key: str, max_attempts: int = 5, window: int = 300) -> bool:
    if db.available():
        count = await db.count_recent_login_attempts(attempt_key, window)
        if count >= max_attempts:
            return True
        await db.record_login_attempt(attempt_key)
        return False
    return False


CHAT_RL_PER_SESSION = (40, 60)
CHAT_RL_PER_IP      = (200, 60)
CHAT_RL_PER_STORE   = (2000, 60)


async def chat_rate_limited(store_id: str, session_id: str, ip: str) -> str | None:
    if not db.available():
        return None
    sess_max, sess_win = CHAT_RL_PER_SESSION
    ip_max,   ip_win   = CHAT_RL_PER_IP
    str_max,  str_win  = CHAT_RL_PER_STORE
    if await is_rate_limited(f"chat:s:{session_id}", sess_max, sess_win):
        return "session"
    if await is_rate_limited(f"chat:i:{ip}",         ip_max,   ip_win):
        return "ip"
    if await is_rate_limited(f"chat:t:{store_id}",   str_max,  str_win):
        return "store"
    return None


# ── Daily token budget ────────────────────────────────────────────────────────
_DEFAULT_DAILY_TOKEN_BUDGET = 500_000


def daily_token_budget(store_id: str) -> int:
    cfg = sm.get_ai_config(store_id) or {}
    override = cfg.get("daily_token_budget")
    if override is not None:
        try:
            return max(0, int(override))
        except (TypeError, ValueError):
            pass
    try:
        return max(0, int(os.getenv("LLM_DAILY_TOKEN_BUDGET", _DEFAULT_DAILY_TOKEN_BUDGET)))
    except ValueError:
        return _DEFAULT_DAILY_TOKEN_BUDGET


async def budget_exhausted(store_id: str) -> tuple[bool, int, int]:
    budget = daily_token_budget(store_id)
    if budget <= 0 or not db.available():
        return False, 0, budget
    snapshot = await db.llm_usage_today(store_id)
    used = int(snapshot.get("tokens_total", 0))
    return used >= budget, used, budget


# ── Public widget session safety ───────────────────────────────────────────────
# Channel-owned conversations (WhatsApp / Messenger / Instagram) use
# deterministic, enumerable session ids (wa:<phone>, msgr:<psid>, ig:<igsid>).
# The PUBLIC widget endpoints (/chat/history, /chat/poll, /chat/stream,
# /chat/rate) must never expose those by id — only the random-uuid widget
# sessions. Without this, anyone could read a customer's WhatsApp transcript
# (or live-tap their replies) by guessing their phone number (finding H-1).
_INTERNAL_SESSION_PREFIXES = ("wa:", "msgr:", "ig:")


def is_internal_session_id(session_id: str) -> bool:
    """True for channel-owned session ids that the public widget API must not
    serve. Case-insensitive so a mixed-case prefix can't slip through."""
    return (session_id or "").strip().lower().startswith(_INTERNAL_SESSION_PREFIXES)
