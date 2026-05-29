"""
Multi-tenant store registry.
Each Salla store is identified by its merchant ID (store_id).
Data is persisted at:  data/stores/{store_id}/tokens.json
                       data/stores/{store_id}/cache.json
"""

import os
import json
import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data" / "stores"

# In-memory registry:
# { store_id: {"tokens": {...}, "cache": {...}, "agent": PrintingAgent|None} }
_registry: dict = {}


# ── Directory helpers ──────────────────────────────────────────────────────────

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
    Load all registered stores from disk into memory.
    Also handles backward-compat: if SALLA_ACCESS_TOKEN env var is set
    and no stores are found on disk, creates a 'default' in-memory entry.
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
            print(f"[store_manager] Loaded store {store_id!r}: {tokens.get('store_name', '?')}")

    # Backward-compat: single-store env var fallback
    env_token = os.getenv("SALLA_ACCESS_TOKEN", "")
    if env_token and "default" not in _registry:
        print("[store_manager] Using SALLA_ACCESS_TOKEN env var as 'default' store")
        # Don't persist — env var is the source of truth for the default store
        _register_memory(
            store_id="default",
            access_token=env_token,
            refresh_token=os.getenv("SALLA_REFRESH_TOKEN", ""),
            store_info={"name": "المتجر الافتراضي"},
        )

    print(f"[store_manager] {len(_registry)} store(s) loaded")
    return _registry


# ── Registration ───────────────────────────────────────────────────────────────

def _register_memory(store_id: str, access_token: str, refresh_token: str = "", store_info: dict = None):
    """Register in-memory only (no disk write). Used for env-var fallback."""
    info = store_info or {}
    existing = _registry.get(store_id, {}).get("tokens", {})
    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "store_name": info.get("name", existing.get("store_name", f"متجر {store_id}")),
        "store_domain": info.get("domain", existing.get("store_domain", "")),
        "store_avatar": info.get("avatar", existing.get("store_avatar", "")),
        "store_url": info.get("url", existing.get("store_url", "")),
        "connected_at": existing.get("connected_at") or info.get("connected_at") or datetime.datetime.utcnow().isoformat(),
    }
    if store_id in _registry:
        _registry[store_id]["tokens"] = tokens
        _registry[store_id]["agent"] = None
    else:
        _registry[store_id] = {"tokens": tokens, "cache": {}, "agent": None}


def register_store(
    store_id: str,
    access_token: str,
    refresh_token: str = "",
    store_info: dict = None,
):
    """
    Register or update a store and persist to disk.
    Called from webhook (app.store.authorize) or OAuth callback.
    """
    store_id = str(store_id)
    info = store_info or {}
    existing = _registry.get(store_id, {}).get("tokens", {})

    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "store_name": info.get("name") or existing.get("store_name") or f"متجر {store_id}",
        "store_domain": info.get("domain") or existing.get("store_domain") or "",
        "store_avatar": info.get("avatar") or existing.get("store_avatar") or "",
        "store_url": info.get("url") or existing.get("store_url") or "",
        "connected_at": existing.get("connected_at") or info.get("connected_at") or datetime.datetime.utcnow().isoformat(),
    }

    if store_id in _registry:
        _registry[store_id]["tokens"] = tokens
        _registry[store_id]["agent"] = None  # reset so new token is picked up
    else:
        _registry[store_id] = {"tokens": tokens, "cache": {}, "agent": None}

    # Persist to disk
    try:
        _store_dir(store_id)
        _tokens_path(store_id).write_text(
            json.dumps(tokens, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[store_manager] Saved store {store_id!r}: {tokens['store_name']}")
    except Exception as e:
        print(f"[store_manager] Warning: could not save store {store_id!r}: {e}")


# ── Token access ───────────────────────────────────────────────────────────────

def get_access_token(store_id: str) -> str:
    return _registry.get(str(store_id), {}).get("tokens", {}).get("access_token", "")


def get_refresh_token(store_id: str) -> str:
    return _registry.get(str(store_id), {}).get("tokens", {}).get("refresh_token", "")


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
    try:
        _store_dir(store_id)
        _cache_path(store_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[store_manager] Warning: could not save cache for {store_id!r}: {e}")


# ── Agent factory ──────────────────────────────────────────────────────────────

def get_agent(store_id: str):
    """Lazy-init a PrintingAgent instance per store."""
    from agent import PrintingAgent

    store_id = str(store_id)
    if store_id not in _registry:
        return None
    if _registry[store_id]["agent"] is None:
        token = get_access_token(store_id)
        _registry[store_id]["agent"] = PrintingAgent(store_id=store_id, access_token=token)
    return _registry[store_id]["agent"]


# ── Query helpers ──────────────────────────────────────────────────────────────

def is_registered(store_id: str) -> bool:
    return str(store_id) in _registry


def list_stores() -> list:
    """Summary list of all registered stores, sorted by connected_at desc."""
    result = []
    for sid, state in _registry.items():
        tokens = state.get("tokens", {})
        cache = state.get("cache", {})
        result.append({
            "store_id": sid,
            "store_name": tokens.get("store_name", f"متجر {sid}"),
            "store_domain": tokens.get("store_domain", ""),
            "store_avatar": tokens.get("store_avatar", ""),
            "connected_at": tokens.get("connected_at", ""),
            "products_count": cache.get("products_count", 0),
            "last_sync": cache.get("last_sync", "never"),
            "last_sync_errors": cache.get("last_sync_errors", []),
        })
    return sorted(result, key=lambda x: x.get("connected_at", ""), reverse=True)
