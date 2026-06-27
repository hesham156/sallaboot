"""database.stores — split out of the original single-file database.py."""
import json
from typing import Optional
import crypto as _crypto
from database import _core
from database._core import _coerce_jsonb, _iso_z, _json_row
from database.ops import load_upload




async def load_one_store(store_id: str) -> Optional[dict]:
    """
    Fetch a SINGLE store row (secrets decrypted), or None when it doesn't exist.

    Mirrors load_all_stores for one id. Used for cross-process registry
    coherence: the in-memory registry is per-process, so a store registered /
    deleted on one web replica or the worker is invisible to the others until
    they reload. This lets any process reconcile one store against the shared DB
    on demand (see store_manager.sync_one_from_db).
    """
    store_id = str(store_id)
    if not _core._pool or not store_id:
        return None
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT store_id, tokens, ai_config, cache_data FROM stores WHERE store_id = $1",
                store_id,
            )
        if not r:
            return None
        tokens    = _crypto.decrypt_store_blob(_coerce_jsonb(r["tokens"]))
        ai_config = _crypto.decrypt_ai_config_blob(_coerce_jsonb(r["ai_config"]))
        return {
            "store_id":  r["store_id"],
            "tokens":    tokens,
            "ai_config": ai_config,
            "cache":     _coerce_jsonb(r["cache_data"]),
        }
    except Exception as e:
        print(f"[db] load_one_store({store_id!r}) error: {e}")
        return None


async def force_save_all_stores(stores: list[dict]) -> int:
    """
    Bulk-upsert every store from the in-memory registry into PostgreSQL.
    Called when admin clicks 'Force Save to DB'.
    Returns the number of stores saved.
    """
    if not _core._pool:
        return 0
    saved = 0
    for s in stores:
        sid    = s.get("store_id", "")
        tokens = s.get("tokens",   {})
        if not sid or not tokens:
            continue
        try:
            ai_cfg = tokens.get("ai_config", {})
            # Encrypt secrets before the bulk write — same boundary as
            # save_store / save_ai_config.
            enc_tokens = _crypto.encrypt_store_blob(tokens)
            enc_ai_cfg = _crypto.encrypt_ai_config_blob(ai_cfg)
            async with _core._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO stores (store_id, tokens, ai_config, updated_at)
                    VALUES ($1, $2::jsonb, $3::jsonb, NOW())
                    ON CONFLICT (store_id) DO UPDATE
                      SET tokens    = EXCLUDED.tokens,
                          ai_config = EXCLUDED.ai_config,
                          updated_at = NOW()
                    """,
                    sid,
                    json.dumps(enc_tokens,  ensure_ascii=False),
                    json.dumps(enc_ai_cfg,  ensure_ascii=False),
                )
            saved += 1
        except Exception as e:
            print(f"[db] force_save_all_stores({sid!r}) error: {e}")
    return saved


async def rotate_encryption() -> dict:
    """
    Re-encrypt every stores row onto the ACTIVE encryption key, so the keys
    in ENCRYPTION_KEYS_OLD can be retired. Run AFTER deploying with the new
    key as ENCRYPTION_KEY and the previous key in ENCRYPTION_KEYS_OLD.

    For each row: decrypt the secret blobs (MultiFernet tries active + old
    keys) then re-encrypt with the active key, and UPDATE only when the
    ciphertext actually changed. Returns:
        {total, rotated, unchanged, errors:[{store_id, error}]}

    A row whose old key is missing from ENCRYPTION_KEYS_OLD is reported in
    `errors` and left untouched — rotation never drops an unreadable secret.
    """
    result = {"total": 0, "rotated": 0, "unchanged": 0, "errors": []}
    if not _core._pool:
        result["errors"].append({"store_id": "*", "error": "DB not connected"})
        return result
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch("SELECT store_id, tokens, ai_config FROM stores")
        result["total"] = len(rows)
        for r in rows:
            sid    = r["store_id"]
            tokens = _coerce_jsonb(r["tokens"])
            ai_cfg = _coerce_jsonb(r["ai_config"])
            try:
                new_tokens = _crypto.reencrypt_store_blob(tokens)
                new_ai_cfg = _crypto.reencrypt_ai_config_blob(ai_cfg)
            except ValueError as exc:
                # Missing old key — surface, don't clobber.
                result["errors"].append({"store_id": sid, "error": str(exc)[:200]})
                continue
            if new_tokens == tokens and new_ai_cfg == ai_cfg:
                result["unchanged"] += 1
                continue
            try:
                async with _core._pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE stores SET tokens = $2::jsonb, ai_config = $3::jsonb, "
                        "updated_at = NOW() WHERE store_id = $1",
                        sid,
                        json.dumps(new_tokens, ensure_ascii=False),
                        json.dumps(new_ai_cfg, ensure_ascii=False),
                    )
                result["rotated"] += 1
            except Exception as exc:
                result["errors"].append({"store_id": sid, "error": str(exc)[:200]})
    except Exception as e:
        result["errors"].append({"store_id": "*", "error": f"{type(e).__name__}: {e}"[:200]})
    return result


async def load_all_stores() -> list:
    """
    Return all store rows from the DB with secrets decrypted in memory.
    Each row: {store_id, tokens, ai_config, cache_data}

    Decryption is transparent — callers iterating the returned list see
    plaintext access_token, refresh_token, and provider API keys, just
    like before Phase C9. The ciphertext only ever exists on disk.

    Legacy plaintext rows (pre-encryption deploys) pass through unchanged
    via crypto.decrypt's pass-through-on-no-prefix behaviour. The 0002
    migration upgrades them at deploy time.
    """
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT store_id, tokens, ai_config, cache_data FROM stores"
            )
        result = []
        for r in rows:
            tokens    = _coerce_jsonb(r["tokens"])
            ai_config = _coerce_jsonb(r["ai_config"])
            # Decrypt at the boundary. crypto helpers are no-op for empty
            # / missing / non-string fields, so this is safe even for
            # half-populated rows.
            tokens    = _crypto.decrypt_store_blob(tokens)
            ai_config = _crypto.decrypt_ai_config_blob(ai_config)
            result.append({
                "store_id":  r["store_id"],
                "tokens":    tokens,
                "ai_config": ai_config,
                "cache":     _coerce_jsonb(r["cache_data"]),
            })
        print(f"[db] load_all_stores: fetched {len(result)} row(s) from PostgreSQL")
        return result
    except Exception as e:
        import traceback
        print(f"[db] ❌ load_all_stores error: {type(e).__name__}: {e}")
        traceback.print_exc()
        return []


async def list_raw_stores() -> list:
    """
    Diagnostic: return every store_id in the DB with a quick health flag
    (has_token / has_ai_config). Used by /admin/registry-vs-db so the
    admin can see exactly which DB rows would be skipped on load.
    """
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT store_id, tokens, ai_config, updated_at FROM stores ORDER BY updated_at DESC"
            )
        out = []
        for r in rows:
            tokens = _coerce_jsonb(r["tokens"])
            ai_cfg = _coerce_jsonb(r["ai_config"])
            out.append({
                "store_id":     r["store_id"],
                "store_name":   tokens.get("store_name", ""),
                "has_token":    bool(tokens.get("access_token")),
                "has_refresh":  bool(tokens.get("refresh_token")),
                "has_ai_config": bool(
                    ai_cfg.get("groq_api_key") or
                    ai_cfg.get("anthropic_api_key") or
                    ai_cfg.get("openai_api_key") or
                    tokens.get("ai_config", {}).get("groq_api_key") or
                    tokens.get("ai_config", {}).get("anthropic_api_key") or
                    tokens.get("ai_config", {}).get("openai_api_key")
                ),
                "updated_at":   r["updated_at"].isoformat() if r["updated_at"] else None,
            })
        return out
    except Exception as e:
        print(f"[db] list_raw_stores error: {e}")
        return []


async def save_store(store_id: str, tokens: dict, owner_email: str = ""):
    """
    Upsert store tokens. Secrets inside the blob (access_token,
    refresh_token, ai_config.{groq,anthropic,openai,whatsapp}_*) are
    encrypted at this boundary — see crypto.encrypt_store_blob. Memory
    keeps plaintext, so existing callers reading tokens["access_token"]
    are unaffected.

    owner_email is a column (not encrypted) because we need to query
    by it during the unified email/password login. Empty string keeps
    the existing value via COALESCE — pass it explicitly to overwrite.
    """
    if not _core._pool:
        return
    encrypted_blob = _crypto.encrypt_store_blob(tokens)
    email_arg = (owner_email or "").strip().lower() or None
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stores (store_id, tokens, owner_email, updated_at)
                VALUES ($1, $2::jsonb, $3, NOW())
                ON CONFLICT (store_id) DO UPDATE
                  SET tokens      = EXCLUDED.tokens,
                      owner_email = COALESCE(EXCLUDED.owner_email, stores.owner_email),
                      updated_at  = NOW()
                """,
                store_id,
                json.dumps(encrypted_blob, ensure_ascii=False),
                email_arg,
            )
    except Exception as e:
        print(f"[db] save_store({store_id!r}) error: {e}")


async def set_store_owner_email(store_id: str, email: str) -> bool:
    """
    Set or clear the owner_email column for one store, without touching
    the encrypted tokens blob (which would require a full re-encrypt).
    Used by the super-admin backfill endpoint after fetching the email
    from Salla's /oauth2/user/info for legacy stores.

    Returns True if a row was updated. Empty `email` is allowed and stores
    NULL — useful if a merchant explicitly wants their email unlinked.
    """
    if not _core._pool:
        return False
    e = (email or "").strip().lower() or None
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.execute(
                "UPDATE stores SET owner_email = $1, updated_at = NOW() WHERE store_id = $2",
                e, store_id,
            )
        # asyncpg returns 'UPDATE N' — trailing number is the row count
        return r.split()[-1] != "0" if r else False
    except Exception as ex:
        print(f"[db] set_store_owner_email({store_id!r}) error: {ex}")
        return False


async def find_store_by_owner_email(email: str) -> str | None:
    """
    Find the store_id whose owner_email matches (case-insensitive).
    Returns None if no match — caller decides whether to fall through
    to employee lookup or fail. Used by the unified /auth/login endpoint.
    """
    if not _core._pool:
        return None
    e = (email or "").strip().lower()
    if not e:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT store_id FROM stores WHERE lower(owner_email) = $1 LIMIT 1",
                e,
            )
        return row["store_id"] if row else None
    except Exception as ex:
        print(f"[db] find_store_by_owner_email error: {ex}")
        return None


async def get_store_owner_email(store_id: str) -> str | None:
    """Return the owner_email for *store_id*, or None if not found / not set."""
    if not _core._pool:
        return None
    sid = (store_id or "").strip()
    if not sid:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT owner_email FROM stores WHERE store_id = $1 LIMIT 1",
                sid,
            )
        return row["owner_email"] if row else None
    except Exception as ex:
        print(f"[db] get_store_owner_email error: {ex}")
        return None


async def find_employee_by_email_any_store(email: str) -> dict | None:
    """
    Find an active employee by email across ALL stores. Used by the
    unified login endpoint — the user enters just email+password, we
    don't know which store yet. Returns the same shape as
    get_employee_by_email so callers can reuse downstream code.

    If the same email exists in multiple stores (shouldn't happen — we
    enforce UNIQUE(store_id, email) but not globally), we return the
    most recently created row to favour the newest installation.
    """
    if not _core._pool:
        return None
    e = (email or "").strip().lower()
    if not e:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, store_id, name, email, password_hash, role, active, created_at
                FROM employees
                WHERE lower(email) = $1 AND active = TRUE
                ORDER BY created_at DESC
                LIMIT 1
                """,
                e,
            )
        if not row:
            return None
        return {
            "id":            int(row["id"]),
            "store_id":      row["store_id"],
            "name":          row["name"],
            "email":         row["email"],
            "password_hash": row["password_hash"],
            "role":          row["role"] or "agent",
            "active":        bool(row["active"]),
            "created_at":    _iso_z(row["created_at"]),
        }
    except Exception as ex:
        print(f"[db] find_employee_by_email_any_store error: {ex}")
        return None


async def purge_store(store_id: str) -> dict:
    """
    Delete ALL data for a store — called on app.uninstalled to comply with
    Salla's data-privacy requirement that uninstalling removes merchant AND
    customer data. Covers every table carrying a store_id column, including the
    customer-PII ones (contacts: phone/name/email, bot_orders, wa_campaigns).
    Deleting wa_campaigns cascades to wa_campaign_recipients via its FK.
    Returns a per-table deleted count.
    """
    if not _core._pool:
        return {}
    counts: dict = {}
    tables = [
        ("stores",                "store_id"),
        ("conversations",         "store_id"),
        ("abandoned_carts",       "store_id"),
        ("uploads",               "store_id"),
        ("bot_training",          "store_id"),
        ("webhook_log",           "store_id"),
        ("webhook_inbox",         "store_id"),
        ("outbox",                "store_id"),
        ("employees",             "store_id"),
        ("contacts",              "store_id"),  # customer PII: phone/name/email
        ("bot_orders",            "store_id"),
        ("wa_campaigns",          "store_id"),  # cascades → wa_campaign_recipients
        ("llm_usage",             "store_id"),
        ("support_access_grants", "store_id"),
    ]
    try:
        async with _core._pool.acquire() as conn:
            for table, col in tables:
                try:
                    r = await conn.execute(f"DELETE FROM {table} WHERE {col} = $1", store_id)
                    counts[table] = int(r.split()[-1]) if r and r.split()[-1].isdigit() else 0
                except Exception as te:
                    print(f"[db] purge_store {table} error: {te}")
        print(f"[db] 🗑️ purged store {store_id!r}: {counts}")
    except Exception as e:
        print(f"[db] purge_store({store_id!r}) error: {e}")
    return counts


def _redact_store_blob(blob) -> dict:
    """Drop every secret field from a stores tokens / ai_config blob so a
    merchant data export never leaks OAuth tokens or provider API keys.

    Copies defensively — _coerce_jsonb hands back the SAME dict when passed
    a dict, so popping in place would mutate the caller's data.
    """
    d = dict(_coerce_jsonb(blob))
    for f in _crypto.TOKENS_SECRET_FIELDS:
        d.pop(f, None)
    for f in _crypto.AI_CONFIG_SECRET_FIELDS:
        d.pop(f, None)
    nested = d.get("ai_config")
    if isinstance(nested, dict):
        nested = dict(nested)
        for f in _crypto.AI_CONFIG_SECRET_FIELDS:
            nested.pop(f, None)
        d["ai_config"] = nested
    return d


async def export_store(store_id: str) -> dict:
    """
    Gather ALL of one store's business + customer data for a data-portability
    export (the read-side mirror of purge_store). Secrets are redacted:
    OAuth tokens, provider API keys, the linking api_key, and employee
    password hashes never appear in the result.

    Returns a JSON-serialisable dict:
        {store, conversations, contacts, bot_orders, bot_training,
         abandoned_carts, wa_campaigns, wa_campaign_recipients, employees,
         llm_usage, uploads}
    `uploads` is metadata only — the file bytes are streamed separately by
    fetch_store_upload_blobs() so a huge attachment can't blow up memory here.
    """
    if not _core._pool:
        return {}

    export: dict = {}
    try:
        async with _core._pool.acquire() as conn:
            # stores — single row, secrets stripped, linking api_key omitted.
            srow = await conn.fetchrow(
                "SELECT store_id, tokens, ai_config, owner_email, integrations, updated_at "
                "FROM stores WHERE store_id = $1",
                store_id,
            )
            if srow:
                export["store"] = {
                    "store_id":    srow["store_id"],
                    "owner_email": srow["owner_email"],
                    "tokens":      _redact_store_blob(srow["tokens"]),
                    "ai_config":   _redact_store_blob(srow["ai_config"]),
                    "integrations": _coerce_jsonb(srow["integrations"]),
                    "updated_at":  _iso_z(srow["updated_at"]),
                }

            # Generic per-store tables: SELECT * filtered by store_id.
            # (table, drop-columns) — drop secret/binary columns per table.
            simple = [
                ("conversations",   ()),
                ("contacts",        ()),
                ("bot_orders",      ()),
                ("bot_training",    ()),
                ("abandoned_carts", ()),
                ("wa_campaigns",    ()),
                ("llm_usage",       ()),
                ("employees",       ("password_hash",)),
                ("uploads",         ("data",)),  # metadata only; bytes bundled separately
            ]
            for table, drop in simple:
                try:
                    rows = await conn.fetch(
                        f"SELECT * FROM {table} WHERE store_id = $1 ORDER BY 1", store_id
                    )
                    export[table] = [_json_row(r, drop=drop) for r in rows]
                except Exception as te:
                    print(f"[db] export_store {table} error: {te}")
                    export[table] = []

            # Campaign recipients are keyed by campaign_id → join through the
            # store's campaigns.
            try:
                rows = await conn.fetch(
                    """
                    SELECT r.* FROM wa_campaign_recipients r
                    JOIN wa_campaigns c ON c.id = r.campaign_id
                    WHERE c.store_id = $1
                    ORDER BY r.id
                    """,
                    store_id,
                )
                export["wa_campaign_recipients"] = [_json_row(r) for r in rows]
            except Exception as te:
                print(f"[db] export_store wa_campaign_recipients error: {te}")
                export["wa_campaign_recipients"] = []
    except Exception as e:
        print(f"[db] export_store({store_id!r}) error: {e}")
    return export


async def fetch_store_upload_blobs(store_id: str, max_total_bytes: int,
                                   skipped_out: list | None = None):
    """
    Async-generator yielding (file_id, filename, content_type, data) for a
    store's uploads, one row at a time so a huge attachment never forces the
    whole set into memory. Files are included in created order until the
    cumulative size would exceed `max_total_bytes`; remaining file_ids are
    appended to `skipped_out` (if provided) so the export can record them.
    """
    if not _core._pool:
        return
    async with _core._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT file_id, filename, content_type, size_bytes FROM uploads "
            "WHERE store_id = $1 ORDER BY created_at",
            store_id,
        )
    total = 0
    for r in rows:
        size = int(r["size_bytes"] or 0)
        if total + size > max_total_bytes:
            if skipped_out is not None:
                skipped_out.append(r["file_id"])
            continue
        blob = await load_upload(r["file_id"])
        if not blob:
            continue
        total += size
        yield (r["file_id"], blob["filename"], blob["content_type"], blob["data"])


async def clear_whatsapp_phone_id(phone_id: str, keep_store_id: str = "") -> list[str]:
    """
    DB-authoritative WhatsApp unlink. Wipe whatsapp_token / phone_id / waba_id
    and disable the channel in EVERY store whose ai_config (or tokens.ai_config)
    carries `phone_id`, except `keep_store_id` (pass "" to clear ALL).

    Why this matters: the in-memory registry clear only touches stores currently
    loaded in this process, but `load_from_db` reloads EVERY store's ai_config
    column at startup. If a stale store keeps the phone_id only in the DB, it
    reclaims the number on the next reload and inbound messages route to it again.
    whatsapp_phone_id is stored plaintext, so the match is a plain JSONB compare.
    Returns the cleared store_ids.
    """
    if not _core._pool:
        return []
    pid  = str(phone_id or "").strip()
    keep = str(keep_store_id or "")
    if not pid:
        return []
    wipe = json.dumps({
        "whatsapp_token":    "",
        "whatsapp_phone_id": "",
        "whatsapp_waba_id":  "",
        "whatsapp_enabled":  False,
    })
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE stores
                   SET ai_config = ai_config || $1::jsonb,
                       tokens = CASE
                           WHEN tokens ? 'ai_config'
                           THEN jsonb_set(tokens, '{ai_config}',
                                          (tokens->'ai_config') || $1::jsonb)
                           ELSE tokens
                       END,
                       updated_at = NOW()
                 WHERE (ai_config->>'whatsapp_phone_id' = $2
                        OR tokens->'ai_config'->>'whatsapp_phone_id' = $2)
                   AND store_id <> $3
                RETURNING store_id
                """,
                wipe, pid, keep,
            )
        cleared = [r["store_id"] for r in rows]
        if cleared:
            print(f"[db] cleared WhatsApp phone_id {pid} from {len(cleared)} "
                  f"store(s): {cleared}")
        return cleared
    except Exception as e:
        print(f"[db] clear_whatsapp_phone_id({phone_id!r}) error: {e}")
        return []


async def save_ai_config(store_id: str, ai_config: dict):
    """
    Upsert only the ai_config column. Provider API keys
    (groq/anthropic/openai/whatsapp) are encrypted before write — see
    crypto.encrypt_ai_config_blob.
    """
    if not _core._pool:
        return
    encrypted = _crypto.encrypt_ai_config_blob(ai_config)
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stores (store_id, ai_config, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (store_id) DO UPDATE
                  SET ai_config = EXCLUDED.ai_config, updated_at = NOW()
                """,
                store_id,
                json.dumps(encrypted, ensure_ascii=False),
            )
    except Exception as e:
        print(f"[db] save_ai_config({store_id!r}) error: {e}")


async def save_cache(store_id: str, cache: dict):
    """Upsert only the product cache column."""
    if not _core._pool:
        return
    try:
        # Serialise with a default to handle datetime objects in cache
        payload = json.dumps(cache, ensure_ascii=False, default=str)
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stores (store_id, cache_data, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (store_id) DO UPDATE
                  SET cache_data = EXCLUDED.cache_data, updated_at = NOW()
                """,
                store_id,
                payload,
            )
    except Exception as e:
        print(f"[db] save_cache({store_id!r}) error: {e}")
