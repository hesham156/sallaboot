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
import crypto as _crypto

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
                # Decrypt secrets in place — file format mirrors the DB
                # JSONB blob, so the same crypto helpers apply.
                tokens = _crypto.decrypt_store_blob(tokens)
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

        # A store may have no Salla access_token (disconnected or Shopify-only).
        # Load it anyway — admin_password_hash, store_name, and integrations
        # data all live in the same row; skipping wipes the store after redeploy.
        if not tokens and not row.get("integrations"):
            print(f"[store_manager] ⚠️ Skipped {sid!r} — row is completely empty")
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
        "bot_enabled":   info.get("bot_enabled", existing.get("bot_enabled", True)),
    }
    if store_id in _registry:
        _registry[store_id]["tokens"] = tokens
        _registry[store_id]["agent"]  = None
    else:
        _registry[store_id] = {"tokens": tokens, "cache": {}, "agent": None}


async def register_store(
    store_id: str,
    access_token: str,
    refresh_token: str = "",
    store_info: dict = None,
    owner_email: str = "",
):
    """
    Register or update a store, AWAIT the DB write, then save a JSON fallback.
    Called from webhook (app.store.authorize) or OAuth callback.

    owner_email is the email Salla returned for the authorising user. It
    powers the unified email/password login — without it the store owner
    can only log in via the legacy store_id+password path.

    The DB write is awaited (not fired-and-forgotten) so a Railway redeploy
    that races a save can't drop the tokens — the HTTP response only
    returns after PostgreSQL has committed.
    """
    store_id = str(store_id)
    info     = store_info or {}
    existing = _registry.get(store_id, {}).get("tokens", {})

    # Owner email resolution order:
    #   1. explicit arg (OAuth callback passes Salla's user/info email)
    #   2. store_info["email"] (some callers nest it here)
    #   3. existing value (preserve across re-registrations)
    resolved_email = (
        (owner_email or "").strip().lower()
        or (info.get("email") or "").strip().lower()
        or (existing.get("owner_email") or "").strip().lower()
    )

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
        "bot_enabled":         info.get("bot_enabled", existing.get("bot_enabled", True)),
        # Owner email mirrored into the tokens blob so file-only deployments
        # see it too. The authoritative copy is the `stores.owner_email`
        # column populated by save_store.
        "owner_email":         resolved_email,
    }

    # Set an UNGUESSABLE initial password on first registration. It used to be
    # the store_id itself — but a Salla store_id is the merchant id (semi-public:
    # it's in every webhook payload and dashboard URL), and the store_id+password
    # login path then let anyone who knew that id sign in as the store. Merchants
    # get a real password via /signup, the Salla app-settings link, a super reset,
    # or skip it entirely with OAuth auto-login.
    if not tokens["admin_password_hash"]:
        from auth import hash_password
        import secrets as _secrets
        tokens["admin_password_hash"] = hash_password(_secrets.token_urlsafe(32))
        print(f"[store_manager] Initial random password set for {store_id!r}")


    if store_id in _registry:
        _registry[store_id]["tokens"] = tokens
        _registry[store_id]["agent"]  = None  # reset so new token is picked up
    else:
        _registry[store_id] = {"tokens": tokens, "cache": {}, "agent": None}

    # ── Persist: DB (primary, AWAITED) + JSON file (fallback) ─────────────────
    await db.save_store(store_id, tokens, owner_email=resolved_email)

    try:
        _store_dir(store_id)
        # Encrypt secrets before writing to disk — same boundary as
        # database.save_store. Dev who accidentally commits the data/
        # dir leaks ciphertext, not raw API keys.
        encrypted_for_disk = _crypto.encrypt_store_blob(tokens)
        _tokens_path(store_id).write_text(
            json.dumps(encrypted_for_disk, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[store_manager] Saved store {store_id!r}: {tokens['store_name']}")
    except Exception as e:
        print(f"[store_manager] Warning: could not save store file {store_id!r}: {e}")


# ── Account unification (link an existing 7ayak account to a Salla install) ──────

async def reassign_owner_email(owner_email: str, new_store_id: str) -> tuple:
    """
    Ensure `owner_email` resolves to exactly one account: `new_store_id` — the
    store just connected via Salla.

    Salla's easy-mode install creates an account keyed by the Salla merchant_id.
    If the merchant had *already* signed up on 7ayak (via /auth/signup) their
    email belongs to a separate, platform-less placeholder account. Left as-is,
    the email would match two stores and unified login would be ambiguous.

    Detaches the email from that placeholder and returns BOTH its password hash
    (so the caller preserves the merchant's chosen password on the Salla store)
    AND the placeholder's store_id (so the caller can merge its data into the new
    store and delete the duplicate row — same as the app-settings link path).

    Safe by design: we REFUSE to touch an account that already has a platform
    connected (salla/shopify/zid/woocommerce) — that's a live store, not a
    placeholder.

    Returns (pwd_hash, placeholder_id), or ("", "") when there's nothing to do.
    """
    owner_email = (owner_email or "").strip().lower()
    if not owner_email:
        return "", ""
    other = await db.find_store_by_owner_email(owner_email)
    if not other or str(other) == str(new_store_id):
        return "", ""
    integrations = await db.get_integrations(other)
    if any(integrations.get(p) for p in ("salla", "shopify", "zid", "woocommerce")):
        print(f"[link] {other!r} already has a connected platform — leaving its email intact")
        return "", ""
    pwd_hash = get_admin_password_hash(other)
    await db.set_store_owner_email(other, "")   # detach → email login is now unambiguous
    print(f"[link] 🔗 email {owner_email!r} reassigned: placeholder {other!r} → Salla store {new_store_id!r}")
    return (pwd_hash or ""), str(other)


# ── Token access ───────────────────────────────────────────────────────────────

def get_access_token(store_id: str) -> str:
    return _registry.get(str(store_id), {}).get("tokens", {}).get("access_token", "")


def get_refresh_token(store_id: str) -> str:
    return _registry.get(str(store_id), {}).get("tokens", {}).get("refresh_token", "")


def clear_salla_token(store_id: str) -> None:
    """Remove Salla OAuth tokens from in-memory registry (keeps other store data intact)."""
    store_id = str(store_id)
    if store_id not in _registry:
        return
    tokens = _registry[store_id].get("tokens", {})
    for key in ("access_token", "refresh_token", "token_type", "expires_in", "expires_at", "scope"):
        tokens.pop(key, None)
    _registry[store_id]["tokens"] = tokens
    _registry[store_id]["agent"] = None  # reset agent so it re-initialises without Salla token


def get_token_expires_at(store_id: str) -> str:
    """Return ISO timestamp when the access token expires (empty if not stored)."""
    return _registry.get(str(store_id), {}).get("tokens", {}).get("expires_at", "")


def get_store_info(store_id: str) -> dict:
    """Return name, domain, avatar, connected_at, etc. for a store."""
    return _registry.get(str(store_id), {}).get("tokens", {})


def update_store_info(store_id: str, tokens: dict):
    """Merge updated fields into an existing store's token/info dict."""
    store_id = str(store_id)
    if store_id in _registry:
        _registry[store_id]["tokens"] = tokens


# ── Cache ──────────────────────────────────────────────────────────────────────

def get_cache(store_id: str) -> dict:
    return _registry.get(str(store_id), {}).get("cache", {})


def get_excluded_categories(store_id: str) -> set[str]:
    """Lower-cased set of category names the admin hid from the bot (ai_config
    `excluded_categories`). Products in these categories are treated as if
    hidden for every customer-facing/discovery path."""
    cfg = get_ai_config(store_id) or {}
    return {
        str(c).strip().lower()
        for c in (cfg.get("excluded_categories") or [])
        if str(c).strip()
    }


def bot_visible_products(store_id: str) -> list[dict]:
    """
    The products the bot is allowed to surface to a customer: not `hidden`
    and not belonging to an admin-excluded category. This is the single
    choke-point used by every discovery/knowledge path (catalogue summary,
    suggest_products, category map, overview…). Direct by-id lookups for an
    existing order or a product the customer already named deliberately
    bypass this — exclusion controls discovery, not record retrieval.
    """
    cache = get_cache(store_id) or {}
    excluded = get_excluded_categories(store_id)
    out: list[dict] = []
    for p in cache.get("products", []):
        if p.get("status") == "hidden":
            continue
        if excluded and any(
            (c or "").strip().lower() in excluded for c in (p.get("categories") or [])
        ):
            continue
        out.append(p)
    return out


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


def unregister_store(store_id: str):
    """
    Remove a store from memory + delete its JSON files. Called on
    app.uninstalled so we stop using a revoked token and comply with
    Salla's "uninstall removes merchant data" requirement. (DB rows are
    purged separately via database.purge_store.)
    """
    import shutil
    store_id = str(store_id)
    _registry.pop(store_id, None)
    try:
        d = DATA_DIR / store_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        print(f"[store_manager] 🗑️ unregistered store {store_id!r} (memory + files)")
    except Exception as e:
        print(f"[store_manager] Warning: could not remove store dir {store_id!r}: {e}")


# ── Query helpers ──────────────────────────────────────────────────────────────

def is_registered(store_id: str) -> bool:
    return str(store_id) in _registry


def unregister(store_id: str) -> None:
    """Drop a store from the in-memory registry (e.g. after a placeholder
    account is merged into a Salla store and deleted from the DB)."""
    _registry.pop(str(store_id), None)


def get_owner_email(store_id: str) -> str:
    """Stored owner email for unified email/password login. '' if unknown."""
    return _registry.get(str(store_id), {}).get("tokens", {}).get("owner_email", "")


async def set_owner_email(store_id: str, email: str) -> bool:
    """
    Update the owner_email both in the in-memory registry and in the DB.
    Returns True on DB write success. Empty string clears the link.

    Used by the super-admin backfill endpoint to retro-fit emails onto
    stores that were installed before the unified login shipped. The DB
    write is awaited so a redeploy can't silently drop the link.
    """
    store_id = str(store_id)
    if store_id not in _registry:
        return False
    e = (email or "").strip().lower()
    _registry[store_id].setdefault("tokens", {})["owner_email"] = e
    await db.set_store_owner_email(store_id, e)
    return True


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
            "owner_email":      tokens.get("owner_email", ""),
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


def find_store_by_whatsapp_phone_id(phone_id: str) -> str:
    """
    Reverse-lookup the store that owns a given WhatsApp Phone Number ID, so an
    incoming webhook message is routed to the right store's bot. Returns "" if
    no store has that phone_id configured.
    """
    pid = str(phone_id or "").strip()
    if not pid:
        return ""
    fallback = ""
    for sid, entry in _registry.items():
        cfg = (entry.get("tokens", {}) or {}).get("ai_config", {}) or {}
        if str(cfg.get("whatsapp_phone_id", "")).strip() != pid:
            continue
        # Prefer the store that still holds a token (the real, active owner).
        # A stale/half-disconnected store (phone_id set but token wiped) must
        # never steal messages from the store that actually owns the number now.
        if str(cfg.get("whatsapp_token", "")).strip():
            return str(sid)
        fallback = fallback or str(sid)
    return fallback


async def claim_whatsapp_phone_id(phone_id: str, owner_store_id: str) -> list[str]:
    """
    Enforce GLOBAL uniqueness of a WhatsApp phone_number_id across stores.

    Inbound WhatsApp webhooks are routed by phone_id to the first store that
    claims it (find_store_by_whatsapp_phone_id). If a merchant unlinks a number
    from store A and links the SAME number to store B, but A still carries the
    creds, A keeps receiving the messages. Calling this right after a store
    links/saves a phone_id wipes that number's WhatsApp creds from every OTHER
    store, so the latest store to link a number is its sole owner.

    Returns the list of store_ids that were released (usually empty).
    """
    pid  = str(phone_id or "").strip()
    keep = str(owner_store_id)
    released: list[str] = []
    if not pid:
        return released
    for sid in list(_registry.keys()):
        if str(sid) == keep:
            continue
        cfg = (_registry[sid].get("tokens", {}) or {}).get("ai_config", {}) or {}
        if str(cfg.get("whatsapp_phone_id", "")).strip() == pid:
            newcfg = dict(cfg)
            newcfg.update({
                "whatsapp_token":    "",
                "whatsapp_phone_id": "",
                "whatsapp_waba_id":  "",
                "whatsapp_enabled":  False,
            })
            await set_ai_config(sid, newcfg)   # persists to DB + resets agent
            released.append(str(sid))
            print(f"[store_manager] released WhatsApp phone_id {pid} from store "
                  f"{sid!r} — re-claimed by {keep!r}")
    return released


def find_store_by_page_id(page_id: str) -> str:
    """
    Reverse-lookup the store that owns a Facebook Page ID — routes inbound
    Messenger (and Instagram, via the linked page) webhook events to the right
    store's bot. Matches against both `page_id` and `ig_id` so an event whose
    recipient is the IG account id still resolves. Returns "" when none match.
    """
    pid = str(page_id or "").strip()
    if not pid:
        return ""
    for sid, entry in _registry.items():
        cfg = (entry.get("tokens", {}) or {}).get("ai_config", {}) or {}
        if pid in (str(cfg.get("page_id", "")).strip(), str(cfg.get("ig_id", "")).strip()):
            return str(sid)
    return ""


async def set_ai_config(store_id: str, config: dict):
    """Save AI settings for a store and reset its agent.

    Awaits both DB writes — previously the writes were fired-and-forgotten,
    so a redeploy seconds after the user clicked "Save" could drop the new
    API keys / WhatsApp config and leave the merchant looking at a fresh
    empty form on next page load.
    """
    store_id = str(store_id)
    if store_id not in _registry:
        return
    tokens = _registry[store_id]["tokens"]
    tokens["ai_config"] = config
    _registry[store_id]["agent"] = None  # force re-init with new keys

    # ── Persist (AWAITED — guarantee DB commit before returning) ──────────────
    await db.save_store(store_id, tokens)        # full tokens upsert covers ai_config
    await db.save_ai_config(store_id, config)    # dedicated column for fast queries

    try:
        _store_dir(store_id)
        encrypted_for_disk = _crypto.encrypt_store_blob(tokens)
        _tokens_path(store_id).write_text(
            json.dumps(encrypted_for_disk, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[store_manager] AI config updated for {store_id!r}")
    except Exception as e:
        print(f"[store_manager] Warning: could not save ai_config file {store_id!r}: {e}")


# ── Admin password ─────────────────────────────────────────────────────────────

def get_admin_password_hash(store_id: str) -> str:
    return _registry.get(str(store_id), {}).get("tokens", {}).get("admin_password_hash", "")


async def set_admin_password(store_id: str, password_hash: str):
    """Save a new (already-hashed) admin password for a store.

    Awaits the DB write — losing a password on redeploy locks the merchant
    out of their own dashboard until they reset, which is unacceptable.
    """
    store_id = str(store_id)
    if store_id not in _registry:
        return
    tokens = _registry[store_id]["tokens"]
    tokens["admin_password_hash"] = password_hash

    # ── Persist (AWAITED) ─────────────────────────────────────────────────────
    await db.save_store(store_id, tokens)

    try:
        _store_dir(store_id)
        encrypted_for_disk = _crypto.encrypt_store_blob(tokens)
        _tokens_path(store_id).write_text(
            json.dumps(encrypted_for_disk, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[store_manager] Password updated for {store_id!r}")
    except Exception as e:
        print(f"[store_manager] Warning: could not save password file {store_id!r}: {e}")
