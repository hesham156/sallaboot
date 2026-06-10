"""
Salla OAuth 2.0 — per-store token refresh with replay-attack protection.

Key design decisions (per Salla docs + RFC 6819 §5.2.2.3):
  • Each store has its own asyncio.Lock so that concurrent requests never
    send the same refresh token twice.  Salla will invalidate ALL tokens
    on a duplicate refresh and force re-installation.
  • After a successful refresh the new tokens are persisted via
    store_manager so they survive server restarts (Railway volumes or the
    per-store tokens.json file).
  • The legacy single-store env-var path is kept for backward compat.
"""

import os
import asyncio
import datetime
import json
import httpx
from pathlib import Path

AUTH_URL      = "https://accounts.salla.sa/oauth2/auth"
TOKEN_URL     = "https://accounts.salla.sa/oauth2/token"
USER_INFO_URL = "https://api.salla.dev/admin/v2/oauth2/user/info"

# ── Per-store async locks ─────────────────────────────────────────────────────
# One lock per store prevents parallel refresh calls that would trigger
# Salla's replay-attack protection and revoke all tokens.
_refresh_locks: dict = {}


def _get_refresh_lock(store_id: str) -> asyncio.Lock:
    if store_id not in _refresh_locks:
        _refresh_locks[store_id] = asyncio.Lock()
    return _refresh_locks[store_id]


# ── Legacy single-store token file (backward compat) ─────────────────────────
_TOKEN_FILE = Path(__file__).parent / "tokens.json"


def _load_tokens_from_file():
    """Load legacy root-level tokens.json into os.environ at startup."""
    try:
        if _TOKEN_FILE.exists():
            data = json.loads(_TOKEN_FILE.read_text(encoding="utf-8"))
            if not os.environ.get("SALLA_ACCESS_TOKEN") and data.get("access_token"):
                os.environ["SALLA_ACCESS_TOKEN"] = data["access_token"]
                print("[salla_oauth] Loaded access token from tokens.json")
            if not os.environ.get("SALLA_REFRESH_TOKEN") and data.get("refresh_token"):
                os.environ["SALLA_REFRESH_TOKEN"] = data["refresh_token"]
    except Exception as e:
        print(f"[salla_oauth] Could not load tokens.json: {e}")


_load_tokens_from_file()


# ── Auth URL helpers ──────────────────────────────────────────────────────────

def get_auth_url(redirect_uri: str, state: str = "") -> str:
    """
    Build the Salla OAuth authorize URL.

    `state` is the CSRF token the caller generated + stored (cookie/session).
    Salla echoes it back unchanged on /auth/callback so we can verify the
    redirect came from a flow we started, not an attacker pasting a code
    into a victim's browser. Empty string is allowed for backward compat
    but the caller should always pass one in production.
    """
    from urllib.parse import urlencode
    params = {
        "client_id":     os.environ["SALLA_CLIENT_ID"],
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         "offline_access",
    }
    if state:
        params["state"] = state
    return AUTH_URL + "?" + urlencode(params)


async def get_user_info(access_token: str) -> dict:
    """
    Fetch the authorising user's profile (incl. their store) using a fresh
    access token. Used in the /auth/callback to figure out which merchant
    just authorised — without this we'd have to hardcode store_id="default"
    and break multi-tenant.

    Response shape (per Salla OAS): {data: {id, name, email, ..., store: {id, name, ...}}}
    Newer responses use `merchant` instead of `store`; we accept either.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            USER_INFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r.raise_for_status()
        return r.json()


async def exchange_code(code: str, redirect_uri: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type":    "authorization_code",
                "client_id":     os.environ["SALLA_CLIENT_ID"],
                "client_secret": os.environ["SALLA_CLIENT_SECRET"],
                "code":          code,
                "redirect_uri":  redirect_uri,
                "scope":         "offline_access",
            },
        )
        r.raise_for_status()
        return r.json()


# ── Per-store token refresh ───────────────────────────────────────────────────

async def refresh_access_token(store_id: str = "default") -> str:
    """
    Refresh the OAuth access token for *store_id*.

    Thread-/coroutine-safe: uses a per-store asyncio.Lock so that if two
    requests arrive simultaneously and both get a 401, only one refresh
    call reaches Salla's token endpoint.  The second waits, then re-reads
    the freshly saved token instead of issuing a duplicate request.

    Persists the new token pair via store_manager (→ data/stores/{id}/tokens.json).
    Returns the new access token string.
    """
    import store_manager as sm

    lock = _get_refresh_lock(store_id)
    async with lock:
        # Re-read inside the lock: a previous waiter may have already refreshed.
        refresh_token = sm.get_refresh_token(store_id)
        if not refresh_token:
            refresh_token = os.getenv("SALLA_REFRESH_TOKEN", "")
        if not refresh_token:
            raise RuntimeError(
                f"[salla_oauth] No refresh token for store {store_id!r}. "
                "Re-installation required."
            )

        client_id     = os.getenv("SALLA_CLIENT_ID",     "")
        client_secret = os.getenv("SALLA_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            raise RuntimeError(
                "[salla_oauth] SALLA_CLIENT_ID and SALLA_CLIENT_SECRET env vars must be set."
            )

        print(f"[salla_oauth] Refreshing token for store {store_id!r} …")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(
                    TOKEN_URL,
                    data={
                        "grant_type":    "refresh_token",
                        "client_id":     client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                        "scope":         "offline_access",
                    },
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            raise RuntimeError(
                f"[salla_oauth] Token refresh HTTP error for store {store_id!r}: "
                f"{e.response.status_code} — {body}"
            ) from e

        new_access  = data.get("access_token", "")
        new_refresh = data.get("refresh_token") or refresh_token

        if not new_access:
            raise RuntimeError(
                f"[salla_oauth] Token refresh response missing access_token for store {store_id!r}."
            )

        # Compute expiry timestamp from expires_in (Salla default: 14 days = 1,209,600 s)
        expires_in = int(data.get("expires_in", 1_209_600))
        expires_at = (
            datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_in)
        ).isoformat()

        # Persist to store_manager → data/stores/{store_id}/tokens.json
        # register_store preserves admin_password_hash, ai_config, store info, etc.
        sm.register_store(
            store_id=store_id,
            access_token=new_access,
            refresh_token=new_refresh,
            store_info={"expires_at": expires_at},
        )
        print(
            f"[salla_oauth] ✅ Token refreshed for store {store_id!r} "
            f"({new_access[:8]}…) — expires {expires_at[:10]}"
        )

        # Keep env vars in sync for the "default" store (backward compat)
        if store_id == "default":
            os.environ["SALLA_ACCESS_TOKEN"]  = new_access
            os.environ["SALLA_REFRESH_TOKEN"] = new_refresh

        return new_access


# ── Token status helper ───────────────────────────────────────────────────────

def get_token_status(store_id: str) -> dict:
    """
    Return a health summary dict for the store's OAuth token.
    Used by the admin API endpoint and the proactive refresh loop.

    status values:
        "ok"       — more than 3 days remaining
        "warning"  — 1–3 days remaining
        "critical" — less than 1 day remaining
        "expired"  — already past expiry
        "unknown"  — no expires_at stored yet (will be populated after first refresh)
    """
    import store_manager as sm

    expires_at_str = sm.get_token_expires_at(store_id)
    if not expires_at_str:
        return {
            "status":         "unknown",
            "days_remaining": None,
            "expires_at":     "",
            "message":        "تاريخ الانتهاء غير مسجّل — سيُحدَّث عند أول تجديد تلقائي",
        }

    try:
        expires_at     = datetime.datetime.fromisoformat(expires_at_str)
        delta          = expires_at - datetime.datetime.utcnow()
        days_remaining = delta.days
    except Exception:
        return {
            "status":         "unknown",
            "days_remaining": None,
            "expires_at":     expires_at_str,
            "message":        "تعذّر تحليل تاريخ الانتهاء",
        }

    if days_remaining < 0:
        status  = "expired"
        message = "انتهت صلاحية الـ Token — يرجى إعادة تثبيت التطبيق"
    elif days_remaining < 1:
        status  = "critical"
        message = "الـ Token ينتهي خلال أقل من يوم ⚠️"
    elif days_remaining <= 3:
        status  = "warning"
        message = f"الـ Token ينتهي خلال {days_remaining} أيام — سيتجدد تلقائياً"
    else:
        status  = "ok"
        message = f"الـ Token سليم — يتبقى {days_remaining} يوماً"

    return {
        "status":         status,
        "days_remaining": days_remaining,
        "expires_at":     expires_at_str,
        "message":        message,
    }


# ── Backward-compat helper ────────────────────────────────────────────────────

def save_tokens(access_token: str, refresh_token: str, store_id: str = "default"):
    """
    Persist tokens.  Prefer calling store_manager.register_store() directly;
    this wrapper is kept for code that imported save_tokens previously.
    """
    import store_manager as sm
    sm.register_store(
        store_id=store_id,
        access_token=access_token,
        refresh_token=refresh_token,
    )
    if store_id == "default":
        os.environ["SALLA_ACCESS_TOKEN"]  = access_token
        os.environ["SALLA_REFRESH_TOKEN"] = refresh_token
