"""database.linking — split out of the original single-file database.py."""
import json
import secrets
from typing import Optional
import crypto as _crypto
from database import _core
from database._core import _coerce_jsonb




# ── App-level settings (global flags) ───────────────────────────────────────

async def get_app_setting(key: str, default=None):
    """Read a JSON value from app_settings, falling back to `default`."""
    if not _core._pool:
        return default
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM app_settings WHERE key = $1", key,
            )
        if not row:
            return default
        val = row["value"]
        # JSONB codec decodes to dict; for primitive values we stored {value: x}
        if isinstance(val, dict) and "value" in val and len(val) == 1:
            return val["value"]
        return val
    except Exception as e:
        print(f"[db] get_app_setting({key!r}) error: {e}")
        return default


async def set_app_setting(key: str, value) -> None:
    """Upsert a JSON value into app_settings."""
    if not _core._pool:
        return
    try:
        # Wrap primitives so the codec serialises cleanly
        payload = value if isinstance(value, dict) else {"value": value}
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                  SET value = EXCLUDED.value, updated_at = NOW()
                """,
                key, json.dumps(payload, ensure_ascii=False, default=str),
            )
    except Exception as e:
        print(f"[db] set_app_setting({key!r}) error: {e}")


# ── Account-link forwarding (seamless session migration) ─────────────────────
# When a signup placeholder store is merged into the canonical Salla store and
# deleted, the merchant's browser still holds a session token bound to the dead
# placeholder id. These breadcrumbs let /auth/resolve-link trade that token for
# a fresh one on the new store WITHOUT a re-login. Stored in app_settings (JSONB
# KV) so there's no schema migration; the row is tiny and resolve ignores any
# breadcrumb past _LINK_FORWARD_TTL_SECS (the old token it serves can't outlive
# the 7-day session window anyway).

_LINK_FORWARD_PREFIX = "link_forward:"
# A forward can only ever be followed by a session token bound to the old
# placeholder, and those expire after auth.TOKEN_EXPIRY_SECONDS (7 days). A
# breadcrumb older than that window is therefore un-followable — treat it as
# expired so a long-stale record (e.g. a placeholder id later reused) can't be
# resolved. Within the window the record is kept so multi-device sessions can
# each recover.
_LINK_FORWARD_TTL_SECS = 8 * 24 * 60 * 60


async def record_account_forward(old_store_id: str, new_store_id: str) -> None:
    """Leave an old_store_id → new_store_id breadcrumb after a placeholder merge."""
    old_store_id = str(old_store_id)
    new_store_id = str(new_store_id)
    if not old_store_id or not new_store_id or old_store_id == new_store_id:
        return
    import time as _t
    await set_app_setting(
        f"{_LINK_FORWARD_PREFIX}{old_store_id}",
        {"to": new_store_id, "at": int(_t.time())},
    )


async def resolve_account_forward(old_store_id: str) -> Optional[str]:
    """Return the canonical store a merged placeholder was forwarded to, or None.

    Forwards older than _LINK_FORWARD_TTL_SECS are ignored: the only token that
    could legitimately follow one has already expired, so a stale breadcrumb is
    inert and must not resolve.
    """
    old_store_id = str(old_store_id)
    if not old_store_id:
        return None
    rec = await get_app_setting(f"{_LINK_FORWARD_PREFIX}{old_store_id}")
    if not isinstance(rec, dict) or not rec.get("to"):
        return None
    import time as _t
    at = rec.get("at")
    if isinstance(at, (int, float)) and (_t.time() - at) > _LINK_FORWARD_TTL_SECS:
        return None
    return str(rec["to"])


# ── Salla merchant → account mapping (account-preserving linking) ────────────
# A 7ayak account keeps its OWN stable store_id even after it links Salla. The
# Salla store is identified by Salla's merchant_id, which arrives on every Salla
# webhook — so we keep a merchant_id → account_store_id map (shared, in the
# app_settings KV) and route Salla events to the owning account. Salla-first
# installs (no prior signup) have no mapping: their account_store_id IS the
# merchant_id, so resolution falls through to the merchant_id unchanged.

_SALLA_MERCHANT_PREFIX = "salla_merchant:"


async def set_salla_merchant_map(merchant_id: str, account_store_id: str) -> None:
    """Route this Salla merchant's events/tokens to account_store_id."""
    merchant_id = str(merchant_id)
    account_store_id = str(account_store_id)
    if not merchant_id or not account_store_id or merchant_id == account_store_id:
        return
    await set_app_setting(f"{_SALLA_MERCHANT_PREFIX}{merchant_id}", {"store": account_store_id})


async def list_salla_stores() -> list[dict]:
    """Diagnostic: every store that looks Salla-connected, with the merchant id it
    advertises. salla_merchant_id is plaintext; access_token is just a presence flag."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT store_id,
                       tokens->>'salla_merchant_id' AS salla_merchant_id,
                       (tokens->>'access_token') IS NOT NULL
                         AND tokens->>'access_token' <> '' AS has_token
                FROM stores
                WHERE (tokens->>'access_token') IS NOT NULL
                   OR (tokens->>'salla_merchant_id') IS NOT NULL
                """
            )
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] list_salla_stores error: {e}")
        return []


async def set_store_salla_merchant_id(store_id: str, merchant_id: str) -> None:
    """Stamp salla_merchant_id onto a store's tokens JSONB (plaintext, queryable)."""
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                "UPDATE stores SET tokens = jsonb_set(COALESCE(tokens,'{}'::jsonb), "
                "'{salla_merchant_id}', to_jsonb($2::text)), updated_at = NOW() "
                "WHERE store_id = $1",
                str(store_id), str(merchant_id),
            )
    except Exception as e:
        print(f"[db] set_store_salla_merchant_id error: {e}")


async def find_account_by_salla_merchant(merchant_id: str) -> Optional[str]:
    """Find the account that carries this Salla merchant id on its tokens.

    Authoritative fallback for resolve_merchant_to_account: the link writes
    salla_merchant_id onto the account, and it's PLAINTEXT in the tokens JSONB
    (only access/refresh tokens are encrypted), so it's directly queryable. This
    recovers the mapping even if the app_settings breadcrumb is missing.
    """
    merchant_id = str(merchant_id)
    if not _core._pool or not merchant_id:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT store_id FROM stores WHERE tokens->>'salla_merchant_id' = $1 LIMIT 1",
                merchant_id,
            )
        return row["store_id"] if row else None
    except Exception as e:
        print(f"[db] find_account_by_salla_merchant({merchant_id!r}) error: {e}")
        return None


async def resolve_merchant_to_account(merchant_id: str) -> Optional[str]:
    """Return the account that owns this Salla merchant, or None (Salla-first)."""
    merchant_id = str(merchant_id)
    if not merchant_id:
        return None
    rec = await get_app_setting(f"{_SALLA_MERCHANT_PREFIX}{merchant_id}")
    if isinstance(rec, dict) and rec.get("store"):
        return str(rec["store"])
    # Fallback: the app_settings breadcrumb can be missing (older link, or a write
    # that didn't land). The account's own salla_merchant_id is authoritative —
    # find it and self-heal the breadcrumb so later lookups are a single KV read.
    acct = await find_account_by_salla_merchant(merchant_id)
    if acct:
        print(f"[db] 🔧 self-healed salla map: merchant {merchant_id!r} → account {acct!r}")
        await set_salla_merchant_map(merchant_id, acct)
        return acct
    return None


async def clear_salla_merchant_map(merchant_id: str) -> None:
    """Drop a merchant→account mapping (on uninstall / disconnect)."""
    merchant_id = str(merchant_id)
    if not merchant_id:
        return
    await del_app_setting(f"{_SALLA_MERCHANT_PREFIX}{merchant_id}")


async def del_app_setting(key: str) -> None:
    """Delete an app_settings row. No-op when the DB is unavailable."""
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute("DELETE FROM app_settings WHERE key = $1", key)
    except Exception as e:
        print(f"[db] del_app_setting({key!r}) error: {e}")


# ── Integrations ──────────────────────────────────────────────────────────────

async def clear_salla_tokens(store_id: str) -> None:
    """Remove only Salla OAuth fields from tokens, preserving admin_password_hash, store_name, etc."""
    if not _core._pool:
        raise RuntimeError("Database pool not initialised")
    async with _core._pool.acquire() as conn:
        # Use the - operator to surgically remove Salla-only keys.
        # Do NOT use tokens = '{}'::jsonb — that nukes admin_password_hash and store metadata.
        await conn.execute(
            """
            UPDATE stores
               SET tokens = CASE
                       WHEN tokens IS NULL OR jsonb_typeof(tokens) != 'object'
                       THEN '{}'::jsonb
                       ELSE tokens
                            - 'access_token'
                            - 'refresh_token'
                            - 'token_type'
                            - 'expires_in'
                            - 'expires_at'
                            - 'scope'
                   END,
                   updated_at = NOW()
             WHERE store_id = $1
            """,
            store_id,
        )


# ── Per-store linking API key ────────────────────────────────────────────────
# Used by the Salla App Settings flow: the merchant pastes this key (+ their
# email) into the app's settings form in their Salla dashboard to bind the
# Salla store to their existing 7ayak account.

def _new_api_key() -> str:
    # Keep the key <= 28 chars: Salla's app-settings text field truncates the
    # pasted value at 30 chars, and a 36-char key (token_urlsafe(24)) silently
    # lost its tail there, so the linking key never matched. 18 bytes of
    # entropy (~144 bits) is still ample. "7yk_" (4) + 24 = 28 chars.
    return "7yk_" + secrets.token_urlsafe(18)


async def get_or_create_api_key(store_id: str) -> str:
    """Return the store's linking key, generating + persisting one on first use."""
    if not _core._pool:
        return ""
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT api_key FROM stores WHERE store_id = $1", store_id)
            if not row:
                return ""
            if row["api_key"]:
                return row["api_key"]
            key = _new_api_key()
            await conn.execute(
                "UPDATE stores SET api_key = $1, updated_at = NOW() WHERE store_id = $2",
                key, store_id,
            )
            return key
    except Exception as e:
        print(f"[db] get_or_create_api_key error: {e}")
        return ""


async def regenerate_api_key(store_id: str) -> str:
    """Rotate the store's linking key (invalidates the old one)."""
    if not _core._pool:
        return ""
    try:
        key = _new_api_key()
        async with _core._pool.acquire() as conn:
            r = await conn.execute(
                "UPDATE stores SET api_key = $1, updated_at = NOW() WHERE store_id = $2",
                key, store_id,
            )
        return key if (r and r.split()[-1] != "0") else ""
    except Exception as e:
        print(f"[db] regenerate_api_key error: {e}")
        return ""


async def set_api_key(store_id: str, key: str | None) -> None:
    """Set or clear (key=None) a store's api_key column directly."""
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                "UPDATE stores SET api_key = $1, updated_at = NOW() WHERE store_id = $2",
                (key or None), store_id,
            )
    except Exception as e:
        print(f"[db] set_api_key error: {e}")


async def merge_placeholder_into(placeholder_id: str, target_id: str) -> bool:
    """
    Migrate a freshly-signed-up placeholder account's merchant-authored content
    onto the canonical Salla store, then delete the placeholder row. Used by the
    app-settings linking flow so a merchant who signed up on 7ayak and then
    installed Salla ends up with ONE account, not a duplicate.

    Scope (a placeholder is a brand-new signup, so this is normally near-empty):
      • ai_config (bot settings) — copied only if the target hasn't set one yet.
      • bot_training + uploads (knowledge / files) — store_id repointed.
    Salla-sourced tables (orders, contacts, conversations) never exist on a
    placeholder, so they're left untouched. Runs in one transaction: a failure
    rolls back and leaves the placeholder intact rather than half-merged.
    """
    placeholder_id = str(placeholder_id)
    target_id      = str(target_id)
    if not _core._pool or not placeholder_id or placeholder_id == target_id:
        return False
    try:
        async with _core._pool.acquire() as conn:
            async with conn.transaction():
                # Carry the bot config only if the target doesn't have one yet,
                # so we never clobber settings already made on the Salla store.
                await conn.execute(
                    """
                    UPDATE stores t
                    SET ai_config = p.ai_config, updated_at = NOW()
                    FROM stores p
                    WHERE t.store_id = $1 AND p.store_id = $2
                      AND (t.ai_config IS NULL OR t.ai_config = '{}'::jsonb)
                      AND p.ai_config IS NOT NULL AND p.ai_config <> '{}'::jsonb
                    """,
                    target_id, placeholder_id,
                )
                await conn.execute(
                    "UPDATE bot_training SET store_id = $1 WHERE store_id = $2",
                    target_id, placeholder_id,
                )
                await conn.execute(
                    "UPDATE uploads SET store_id = $1 WHERE store_id = $2",
                    target_id, placeholder_id,
                )
                await conn.execute(
                    "DELETE FROM stores WHERE store_id = $1", placeholder_id,
                )
        print(f"[db] merged placeholder {placeholder_id!r} → {target_id!r} and deleted it")
        return True
    except Exception as e:
        print(f"[db] merge_placeholder_into({placeholder_id!r}→{target_id!r}) error: {e}")
        return False


async def find_store_by_api_key(api_key: str) -> str | None:
    """Return the store_id that owns this linking key, or None."""
    if not _core._pool:
        return None
    key = (api_key or "").strip()
    if not key:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT store_id FROM stores WHERE api_key = $1 LIMIT 1", key,
            )
        return row["store_id"] if row else None
    except Exception as e:
        print(f"[db] find_store_by_api_key error: {e}")
        return None


async def find_store_by_shopify_shop(shop: str) -> str | None:
    """Return the store_id that already owns this Shopify shop, or None."""
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT store_id FROM stores WHERE integrations->'shopify'->>'shop' = $1 LIMIT 1",
                shop,
            )
            return row["store_id"] if row else None
    except Exception as e:
        print(f"[db] find_store_by_shopify_shop error: {e}")
        return None


async def find_store_by_tiktok_open_id(open_id: str) -> str | None:
    """Return the store_id whose TikTok integration owns this open_id, or None."""
    if not (_core._pool and open_id):
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT store_id FROM stores WHERE integrations->'tiktok'->>'open_id' = $1 LIMIT 1",
                open_id,
            )
            return row["store_id"] if row else None
    except Exception as e:
        print(f"[db] find_store_by_tiktok_open_id error: {e}")
        return None


async def get_integrations(store_id: str) -> dict:
    """
    Return a merged integrations dict for the store.
    Includes the explicit integrations JSONB column PLUS a synthetic
    'salla' key when the store has live Salla OAuth tokens — so the
    frontend can enforce ecommerce-platform exclusivity without a
    separate API call.
    """
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT integrations, tokens FROM stores WHERE store_id = $1",
                store_id,
            )
            if not row:
                print(f"[db] get_integrations: no row for store_id='{store_id}'")
                return {}
            result = _coerce_jsonb(row["integrations"])
            # Decrypt each platform entry's OAuth secrets (mirror of the encrypt
            # in save_integration). Legacy plaintext rows pass through unchanged.
            for _plat, _cfg in list(result.items()):
                if isinstance(_cfg, dict):
                    result[_plat] = _crypto.decrypt_fields(_cfg, _crypto.INTEGRATION_SECRET_FIELDS)
            tokens = _coerce_jsonb(row["tokens"])
            if tokens.get("access_token"):
                result.setdefault("salla", {"connected": True})
            print(f"[db] get_integrations({store_id}): keys={list(result.keys())}")
            return result
    except Exception as e:
        print(f"[db] get_integrations error: {e}")
        return {}


async def save_integration(store_id: str, platform: str, data: dict) -> None:
    """Upsert a single platform entry inside stores.integrations.

    OAuth secrets (access_token / refresh_token) are encrypted at rest; the
    matching decrypt happens in get_integrations + list_stores_with_integration.
    """
    if not _core._pool:
        raise RuntimeError("Database pool not initialised")
    enc_data = _crypto.encrypt_fields(data, _crypto.INTEGRATION_SECRET_FIELDS)
    async with _core._pool.acquire() as conn:
        # Pass {platform: data} as a Python dict — the registered JSONB codec
        # handles serialisation. Do NOT use json.dumps() + ::jsonb cast here;
        # that double-encodes the value through the codec and the data is lost.
        status = await conn.execute(
            """
            UPDATE stores
               SET integrations = COALESCE(integrations, '{}'::jsonb) || $2,
                   updated_at   = NOW()
             WHERE store_id = $1
            """,
            store_id,
            {platform: enc_data},
        )
        rows_affected = int((status or "UPDATE 0").split()[-1])
        if rows_affected == 0:
            raise RuntimeError(
                f"[db] save_integration: no store found with store_id='{store_id}' "
                f"— UPDATE affected 0 rows"
            )
        print(f"[db] save_integration: saved '{platform}' for store_id='{store_id}'")


async def remove_integration(store_id: str, platform: str) -> None:
    """Remove a single platform key from stores.integrations."""
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE stores
                   SET integrations = integrations - $2,
                       updated_at   = NOW()
                 WHERE store_id = $1
                """,
                store_id,
                platform,
            )
    except Exception as e:
        print(f"[db] remove_integration error: {e}")
