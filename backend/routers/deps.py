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


# ── Role guards ───────────────────────────────────────────────────────────────

def require_store_owner(request, store_id: str):
    from fastapi import HTTPException
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token) or {}
    if claims.get("su"):
        return
    if "eid" in claims:
        raise HTTPException(403, "هذا الإجراء مخصّص لمالك المتجر")


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
