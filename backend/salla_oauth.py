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
import json
import httpx
from pathlib import Path

AUTH_URL  = "https://accounts.salla.sa/oauth2/auth"
TOKEN_URL = "https://accounts.salla.sa/oauth2/token"

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

def get_auth_url(redirect_uri: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id":     os.environ["SALLA_CLIENT_ID"],
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         "offline_access",
    }
    return AUTH_URL + "?" + urlencode(params)


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

        # Persist to store_manager → data/stores/{store_id}/tokens.json
        # register_store preserves admin_password_hash, ai_config, store info, etc.
        sm.register_store(
            store_id=store_id,
            access_token=new_access,
            refresh_token=new_refresh,
        )
        print(f"[salla_oauth] ✅ Token refreshed for store {store_id!r} ({new_access[:8]}…)")

        # Keep env vars in sync for the "default" store (backward compat)
        if store_id == "default":
            os.environ["SALLA_ACCESS_TOKEN"]  = new_access
            os.environ["SALLA_REFRESH_TOKEN"] = new_refresh

        return new_access


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
