"""
Multi-tenant store registry.

Storage priority:
  1. In-memory _registry (always used — primary read path)
  2. PostgreSQL via database.py (write-through; loaded on startup)
  3. JSON files in data/stores/ (fallback when no DB is available)

All public functions keep their SYNCHRONOUS signatures so the rest of the
codebase doesn't change. DB writes use database.fire() (fire-and-forget
async tasks) which are safe to call from any async FastAPI handler.
"""

import os
import json
import datetime
from pathlib import Path

import database as db

DATA_DIR = Path(__file__).parent / "data" / "stores"

# In-memory registry:
# { store_id: {"tokens": {...}, "cache": {...}, "agent": PrintingAgent|None} }
_registry: dict = {}


# ── Directory helpers (JSON fallback) ─────────────────────────────────────────

def _store_dir(store_id: str) -> Path:
    d = DATA_DIR / str(store_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tokens_path(store_id: str) -> Path:
    return DATA_DIR / str(store_id) / "tokens.json"


def _cache_path(store_id: str) -> Path:
    return DATA_DIR / str(store_id) / "cache.json"


# ── Startup ────────────────────────────────────────────────────────────────────

def load_all_stores() -> dict:
    """
    Load registered stores from JSON files on disk (filesystem fallback).
    Called at startup BEFORE load_from_db() — DB rows then overwrite file data.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for store_dir in sorted(DATA_DIR.iterdir()):
        if not store_dir.is_dir():
            continue
        store_id = store_dir.name
        tp = store_dir / "tokens.json"
        cp = store_dir / "cache.json"

        tokens: dict = {}
        if tp.exists():
            try:
                tokens = json.loads(tp.read_text(encoding="utf-8"))
            except Exception:
                pass

        cache: dict = {}
        if cp.exists():
            try:
                cache = json.loads(cp.read_text(encoding="utf-8"))
            except Exception:
                pass

        if tokens.get("access_token"):
            _registry[store_id] = {"tokens": tokens, "cache": cache, "agent": None}
            print(f"[store_manager] Loaded (file) store {store_id!r}: {tokens.get('store_name', '?')}")

    # Backward-compat: env-var fallback for single-store setups
    env_token = os.getenv("SALLA_ACCESS_TOKEN", "")
    if env_token and "default" not in _registry:
        print("[store_manager] Using SALLA_ACCESS_TOKEN env var as 'default' store")
        _register_memory(
            store_id="default",
            access_token=env_token,
            refresh_token=os.getenv("SALLA_REFRESH_TOKEN", ""),
            store_info={"name": "المتجر الافتراضي"},
        )

    print(f"[store_manager] {len(_registry)} store(s) loaded from files")
    return _registry


async def load_from_db():
    """
    Async — load stores from PostgreSQL (called from FastAPI startup event).
    DB rows take precedence over JSON file data loaded earlier.

    Verbose logging: prints why each row was skipped (no access_token,
    reserved id, etc.) so silent data loss becomes impossible to miss.
    """
    rows = await db.load_all_stores()
    if not rows:
        print("[store_manager] load_from_db: 0 rows returned (DB empty or query failed)")
        return

    loaded  = 0
    skipped = 0
    for row in rows:
        sid    = row["store_id"]
        tokens = row["tokens"]

        # Skip the diagnostic test row (created by db.test_round_trip)
        if sid == "_diagnostic_test_row":
            continue

        if not tokens.get("access_token"):
            print(
                f"[store_manager] ⚠️ Skipped {sid!r} — no access_token in DB. "
                f"Re-register the store or reinstall the app on Salla."
            )
            skipped += 1
            continue

        ai_cfg = row.get("ai_config", {})
        cache  = row.get("cache",     {})

        # Merge ai_config into tokens dict (that's where the rest of the code reads it)
        if ai_cfg:
            tokens["ai_config"] = ai_cfg

        if sid in _registry:
            _registry[sid]["tokens"] = tokens
            _registry[sid]["cache"]  = cache if cache else _registry[sid].get("cache", {})
            _registry[sid]["agent"]  = None  # reset so new token is picked up
        else:
            _registry[sid] = {"tokens": tokens, "cache": cache, "agent": None}

        loaded += 1
        print(f"[store_manager] ✅ Loaded (DB) store {sid!r}: {tokens.get('store_name', '?')}")

    print(
        f"[store_manager] load_from_db done — loaded={loaded}, skipped={skipped}, "
        f"total_in_registry={len(_registry)}"
    )


# ── Registration ───────────────────────────────────────────────────────────────

def _register_memory(store_id: str, access_token: str, refresh_token: str = "", store_info: dict = None):
    """Register in-memory only (no disk / DB write). Used for env-var fallback."""
    info = store_info or {}
    existing = _registry.get(store_id, {}).get("tokens", {})
    tokens = {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "store_name":    info.get("name",   existing.get("store_name",   f"متجر {store_id}")),
        "store_domain":  info.get("domain", existing.get("store_domain", "")),
        "store_avatar":  info.get("avatar", existing.get("store_avatar", "")),
        "store_url":     info.get("url",    existing.get("store_url",    "")),
        "connected_at":  existing.get("connected_at") or info.get("connected_at") or datetime.datetime.utcnow().isoformat(),
    }
    if store_id in _registry:
        _registry[store_id]["tokens"] = tokens
        _registry[store_id]["agent"]  = None
    else:
        _registry[store_id] = {"tokens": tokens, "cache": {}, "agent": None}


def register_store(
    store_id: str,
    access_token: str,
    refresh_token: str = "",
    store_info: dict = None,
):
    """
    Register or update a store, persist to DB (fire-and-forget) and JSON file.
    Called from webhook (app.store.authorize) or OAuth callback.
    """
    store_id = str(store_id)
    info     = store_info or {}
    existing = _registry.get(store_id, {}).get("tokens", {})

    tokens = {
        "access_token":       access_token,
        "refresh_token":      refresh_token,
        "store_name":         info.get("name")   or existing.get("store_name")   or f"متجر {store_id}",
        "store_domain":       info.get("domain") or existing.get("store_domain") or "",
        "store_avatar":       info.get("avatar") or existing.get("store_avatar") or "",
        "store_url":          info.get("url")    or existing.get("store_url")    or "",
        "connected_at":       existing.get("connected_at") or info.get("connected_at") or datetime.datetime.utcnow().isoformat(),
        # Token expiry — set by OAuth flow; preserved across re-registrations
        "expires_at":         info.get("expires_at") or existing.get("expires_at") or "",
        # Preserve existing password hash and AI config
        "admin_password_hash": existing.get("admin_password_hash", ""),
        "ai_config":           existing.get("ai_config", {}),
    }

    # Auto-set initial password = store_id on first registration
    if not tokens["admin_password_hash"]:
        from auth import hash_password
        tokens["admin_password_hash"] = hash_password(str(store_id))
        print(f"[store_manager] Initial password for {store_id!r} set to store_id")

    if store_id in _registry:
        _registry[store_id]["tokens"] = tokens
        _registry[store_id]["agent"]  = None  # reset so new token is picked up
    else:
        _registry[store_id] = {"tokens": tokens, "cache": {}, "agent": None}

    # ── Persist: DB (primary) + JSON file (fallback) ───────────────────────────
    db.fire(db.save_store(store_id, tokens))

    try:
        _store_dir(store_id)
        _tokens_path(store_id).write_text(
            json.dumps(tokens, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[store_manager] Saved store {store_id!r}: {tokens['store_name']}")
    except Exception as e:
        print(f"[store_manager] Warning: could not save store file {store_id!r}: {e}")


# ── Token access ───────────────────────────────────────────────────────────────

def get_access_token(store_id: str) -> str:
    return _registry.get(str(store_id), {}).get("tokens", {}).get("access_token", "")


def get_refresh_token(store_id: str) -> str:
    return _registry.get(str(store_id), {}).get("tokens", {}).get("refresh_token", "")


def get_token_expires_at(store_id: str) -> str:
    """Return ISO timestamp when the access token expires (empty if not stored)."""
    return _registry.get(str(store_id), {}).get("tokens", {}).get("expires_at", "")


def get_store_info(store_id: str) -> dict:
    """Return name, domain, avatar, connected_at, etc. for a store."""
    return _registry.get(str(store_id), {}).get("tokens", {})


# ── Cache ──────────────────────────────────────────────────────────────────────

def get_cache(store_id: str) -> dict:
    return _registry.get(str(store_id), {}).get("cache", {})


def set_cache(store_id: str, data: dict):
    store_id = str(store_id)
    if store_id not in _registry:
        _registry[store_id] = {"tokens": {}, "cache": data, "agent": None}
    else:
        _registry[store_id]["cache"] = data

    # ── Persist: DB (primary) + JSON file (fallback) ───────────────────────────
    db.fire(db.save_cache(store_id, data))

    try:
        _store_dir(store_id)
        _cache_path(store_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[store_manager] Warning: could not save cache file {store_id!r}: {e}")


# ── Agent factory ──────────────────────────────────────────────────────────────

def get_agent(store_id: str):
    """
    Lazy-init a PrintingAgent instance per store.
    Returns None (never raises) so callers can show a friendly message instead of 500.
    """
    from agent import PrintingAgent

    store_id = str(store_id)
    if store_id not in _registry:
        return None
    if _registry[store_id]["agent"] is None:
        token = get_access_token(store_id)
        try:
            _registry[store_id]["agent"] = PrintingAgent(store_id=store_id, access_token=token)
        except Exception as e:
            print(f"[store_manager] ❌ Failed to init agent for {store_id!r}: {e}")
            return None   # caller will show friendly error
    return _registry[store_id]["agent"]


def reset_agent(store_id: str):
    """
    Force the per-store agent to be re-created on the next call to get_agent().
    Call this after product cache updates, token refreshes, or AI config changes
    so the new state is picked up immediately.
    """
    store_id = str(store_id)
    if store_id in _registry:
        _registry[store_id]["agent"] = None


# ── Query helpers ──────────────────────────────────────────────────────────────

def is_registered(store_id: str) -> bool:
    return str(store_id) in _registry


def list_stores() -> list:
    """Summary list of all registered stores, sorted by connected_at desc."""
    result = []
    for sid, state in _registry.items():
        tokens = state.get("tokens", {})
        cache  = state.get("cache",  {})
        result.append({
            "store_id":         sid,
            "store_name":       tokens.get("store_name",   f"متجر {sid}"),
            "store_domain":     tokens.get("store_domain", ""),
            "store_avatar":     tokens.get("store_avatar", ""),
            "connected_at":     tokens.get("connected_at", ""),
            "products_count":   cache.get("products_count", 0),
            "last_sync":        cache.get("last_sync", "never"),
            "last_sync_errors": cache.get("last_sync_errors", []),
            "has_ai_config":    bool(
                tokens.get("ai_config", {}).get("groq_api_key")      or
                tokens.get("ai_config", {}).get("anthropic_api_key") or
                tokens.get("ai_config", {}).get("openai_api_key")
            ),
        })
    return sorted(result, key=lambda x: x.get("connected_at", ""), reverse=True)


# ── AI configuration ───────────────────────────────────────────────────────────

def get_ai_config(store_id: str) -> dict:
    """Return per-store AI settings (groq_api_key, anthropic_api_key, model, bot_name)."""
    return _registry.get(str(store_id), {}).get("tokens", {}).get("ai_config", {})


def set_ai_config(store_id: str, config: dict):
    """Save AI settings for a store and reset its agent."""
    store_id = str(store_id)
    if store_id not in _registry:
        return
    tokens = _registry[store_id]["tokens"]
    tokens["ai_config"] = config
    _registry[store_id]["agent"] = None  # force re-init with new keys

    # ── Persist ────────────────────────────────────────────────────────────────
    db.fire(db.save_store(store_id, tokens))   # full tokens upsert covers ai_config
    db.fire(db.save_ai_config(store_id, config))

    try:
        _store_dir(store_id)
        _tokens_path(store_id).write_text(
            json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[store_manager] AI config updated for {store_id!r}")
    except Exception as e:
        print(f"[store_manager] Warning: could not save ai_config file {store_id!r}: {e}")


# ── Admin password ─────────────────────────────────────────────────────────────

def get_admin_password_hash(store_id: str) -> str:
    return _registry.get(str(store_id), {}).get("tokens", {}).get("admin_password_hash", "")


def set_admin_password(store_id: str, password_hash: str):
    """Save a new (already-hashed) admin password for a store."""
    store_id = str(store_id)
    if store_id not in _registry:
        return
    tokens = _registry[store_id]["tokens"]
    tokens["admin_password_hash"] = password_hash

    # ── Persist ────────────────────────────────────────────────────────────────
    db.fire(db.save_store(store_id, tokens))

    try:
        _store_dir(store_id)
        _tokens_path(store_id).write_text(
            json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[store_manager] Password updated for {store_id!r}")
    except Exception as e:
        print(f"[store_manager] Warning: could not save password file {store_id!r}: {e}")
