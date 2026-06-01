"""
Async PostgreSQL persistence layer — asyncpg connection pool.

All public functions silently no-op when DATABASE_URL is not configured,
so the app keeps working with in-memory / JSON-file fallback on local dev.

Usage:
    import database as db

    # Startup (in FastAPI lifespan / startup event):
    await db.init()

    # Fire-and-forget from sync code running inside the event loop:
    db.fire(db.save_store(store_id, tokens))
"""

import os
import json
import asyncio
import asyncpg
from typing import Optional

_pool: Optional[asyncpg.Pool] = None


# ── Init & schema ──────────────────────────────────────────────────────────────

async def _setup_jsonb_codec(conn):
    """
    Register a JSON↔dict codec for JSONB columns. WITHOUT this, asyncpg
    returns JSONB as raw strings — and the rest of the code calls dict()
    on those strings, which raises TypeError that gets silently swallowed.
    Result: stores load from DB as 0 rows even though the table has data.
    This is the #1 cause of "stores deleted after every deploy".
    """
    await conn.set_type_codec(
        "jsonb",
        encoder=lambda v: json.dumps(v, ensure_ascii=False, default=str),
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init() -> bool:
    """
    Connect to PostgreSQL and create tables if they don't exist.
    Returns True on success, False if DATABASE_URL is missing or connection fails.
    """
    global _pool
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        print("[db] DATABASE_URL not set — using filesystem/memory fallback")
        return False

    # Railway sometimes gives postgres:// — asyncpg needs postgresql://
    dsn = dsn.replace("postgres://", "postgresql://", 1)

    try:
        _pool = await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=5,
            command_timeout=15,
            init=_setup_jsonb_codec,   # ← critical: auto-decode JSONB → dict
        )
        await _create_tables()
        print("[db] ✅ PostgreSQL connected, JSONB codec registered, schema ready")
        return True
    except Exception as e:
        print(f"[db] ❌ PostgreSQL connection failed: {e}")
        _pool = None
        return False


async def _create_tables():
    async with _pool.acquire() as conn:
        await conn.execute("""
            -- Stores: tokens, AI config, product cache
            CREATE TABLE IF NOT EXISTS stores (
                store_id     TEXT PRIMARY KEY,
                tokens       JSONB NOT NULL DEFAULT '{}'::jsonb,
                ai_config    JSONB NOT NULL DEFAULT '{}'::jsonb,
                cache_data   JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );

            -- Conversations: full conversation state per session
            CREATE TABLE IF NOT EXISTS conversations (
                session_id   TEXT PRIMARY KEY,
                store_id     TEXT NOT NULL DEFAULT 'default',
                data         JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_conv_store_upd
                ON conversations (store_id, updated_at DESC);

            -- Abandoned carts from webhook notifications
            CREATE TABLE IF NOT EXISTS abandoned_carts (
                pk           BIGSERIAL PRIMARY KEY,
                store_id     TEXT NOT NULL,
                cart_id      TEXT NOT NULL,
                cart_data    JSONB NOT NULL DEFAULT '{}'::jsonb,
                recovered    BOOLEAN NOT NULL DEFAULT FALSE,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (store_id, cart_id)
            );
            CREATE INDEX IF NOT EXISTS idx_abn_store_crt
                ON abandoned_carts (store_id, created_at DESC);

            -- Customer file uploads — stored as bytea so they survive every
            -- Railway deploy (the filesystem is ephemeral and wipes on
            -- every restart)
            CREATE TABLE IF NOT EXISTS uploads (
                file_id      TEXT PRIMARY KEY,
                filename     TEXT NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                size_bytes   INTEGER NOT NULL DEFAULT 0,
                data         BYTEA NOT NULL,
                store_id     TEXT,
                session_id   TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_uploads_session
                ON uploads (session_id, created_at DESC);

            -- Webhook event log (replaces in-memory _webhook_log + _raw_attempts).
            -- One row per incoming webhook attempt, with both the parsed event
            -- (after JSON parse + signature check) and the raw body head for
            -- debugging failed deliveries.
            CREATE TABLE IF NOT EXISTS webhook_log (
                pk           BIGSERIAL PRIMARY KEY,
                store_id     TEXT,
                event        TEXT,
                status       TEXT,        -- 'ok' | 'unhandled' | 'skip' | 'error' | 'duplicate'
                detail       TEXT,
                sig_status   TEXT,        -- 'signature_ok' | 'signature_absent_accepted' | ...
                body_head    TEXT,        -- first 200 chars of the raw request body
                content_type TEXT,
                user_agent   TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_wh_store_ts ON webhook_log (store_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_wh_ts       ON webhook_log (created_at DESC);

            -- Webhook idempotency (replaces in-memory _seen_events deque).
            -- Key = "{event}:{merchant_id}:{created_at}" — Salla retries up to
            -- 3× every 5 min; this must survive restarts or duplicates leak
            -- through and re-create rows / re-trigger syncs.
            CREATE TABLE IF NOT EXISTS webhook_seen (
                dedup_key    TEXT PRIMARY KEY,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_wh_seen_ts ON webhook_seen (created_at);

            -- Login rate-limiting (replaces in-memory _login_attempts).
            -- Persisting this means a server restart doesn't reset an attacker's
            -- attempt counter, so the 5-attempts-per-5-min lockout actually works.
            CREATE TABLE IF NOT EXISTS login_attempts (
                pk           BIGSERIAL PRIMARY KEY,
                attempt_key  TEXT NOT NULL,      -- "super:<ip>" or "<store_id>:<ip>"
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_login_key_ts ON login_attempts (attempt_key, created_at DESC);

            -- App-level settings (single-row JSON blobs keyed by name).
            -- Used for things like the global bot toggle that aren't per-store.
            CREATE TABLE IF NOT EXISTS app_settings (
                key    TEXT PRIMARY KEY,
                value  JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );

            -- Bot training material — the admin's own instructions, FAQs,
            -- and uploaded reference files. Injected into the AI system
            -- prompt so the bot uses this content when answering customers.
            CREATE TABLE IF NOT EXISTS bot_training (
                id           BIGSERIAL PRIMARY KEY,
                store_id     TEXT NOT NULL,
                kind         TEXT NOT NULL,        -- 'instruction' | 'faq' | 'file'
                title        TEXT NOT NULL,
                content      TEXT NOT NULL DEFAULT '',
                file_id      TEXT,                 -- FK-ish into uploads.file_id
                file_name    TEXT,
                size_chars   INTEGER NOT NULL DEFAULT 0,
                enabled      BOOLEAN NOT NULL DEFAULT TRUE,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_train_store_ts
                ON bot_training (store_id, created_at DESC);
        """)


# ── Bot training material ────────────────────────────────────────────────────

async def list_training(store_id: str) -> list[dict]:
    """Return all training entries for a store, newest first."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, kind, title, content, file_id, file_name,
                       size_chars, enabled, created_at
                FROM bot_training
                WHERE store_id = $1
                ORDER BY created_at DESC
                """,
                store_id,
            )
        return [
            {
                "id":         r["id"],
                "kind":       r["kind"],
                "title":      r["title"],
                "content":    r["content"] or "",
                "file_id":    r["file_id"] or "",
                "file_name":  r["file_name"] or "",
                "size_chars": int(r["size_chars"] or 0),
                "enabled":    bool(r["enabled"]),
                "created_at": r["created_at"].isoformat() + "Z" if r["created_at"] else "",
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] list_training error: {e}")
        return []


async def add_training(store_id: str, kind: str, title: str, content: str,
                        file_id: str = "", file_name: str = "") -> int | None:
    """Insert one training row. Returns the new id, or None on failure."""
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO bot_training
                  (store_id, kind, title, content, file_id, file_name, size_chars)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                store_id, kind, title, content or "",
                file_id or None, file_name or None, len(content or ""),
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] add_training error: {e}")
        return None


async def update_training_enabled(training_id: int, enabled: bool) -> bool:
    """Toggle whether a training entry is included in the prompt."""
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "UPDATE bot_training SET enabled = $1 WHERE id = $2",
                enabled, int(training_id),
            )
        return True
    except Exception as e:
        print(f"[db] update_training_enabled error: {e}")
        return False


async def delete_training(training_id: int) -> tuple[bool, str | None]:
    """Delete a training row. Returns (ok, deleted_file_id)."""
    if not _pool:
        return False, None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "DELETE FROM bot_training WHERE id = $1 RETURNING file_id",
                int(training_id),
            )
        return True, (row["file_id"] if row else None)
    except Exception as e:
        print(f"[db] delete_training error: {e}")
        return False, None


# ── Conversation lookups by customer ────────────────────────────────────────

async def find_session_by_salla_customer(store_id: str, salla_customer_id: str) -> str | None:
    """
    Find the most-recently-active session for a given Salla customer in a
    store. Uses a JSONB path query so it doesn't need a dedicated column —
    cheap enough at small scale; add an expression index on
    (store_id, data->>'salla_customer_id') if this gets slow.
    """
    if not _pool or not salla_customer_id:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT session_id FROM conversations
                WHERE store_id = $1
                  AND data->>'salla_customer_id' = $2
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                store_id, str(salla_customer_id),
            )
        return row["session_id"] if row else None
    except Exception as e:
        print(f"[db] find_session_by_salla_customer error: {e}")
        return None


# ── Webhook log (debugging + audit trail) ───────────────────────────────────

async def log_webhook(*, store_id: str = "", event: str = "", status: str = "ok",
                       detail: str = "", sig_status: str = "", body_head: str = "",
                       content_type: str = "", user_agent: str = "") -> None:
    """Append one webhook attempt row. Silent no-op when DB is unavailable."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO webhook_log
                  (store_id, event, status, detail, sig_status, body_head, content_type, user_agent)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                store_id or "", event or "", status or "", detail or "",
                sig_status or "", body_head or "", content_type or "", user_agent or "",
            )
    except Exception as e:
        print(f"[db] log_webhook error: {e}")


async def get_webhook_log(store_id: str | None = None, limit: int = 200) -> list[dict]:
    """Return the newest `limit` webhook rows, optionally filtered by store_id."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            if store_id:
                rows = await conn.fetch(
                    """
                    SELECT event, status, detail, sig_status, body_head,
                           content_type, user_agent, created_at
                    FROM webhook_log
                    WHERE store_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    store_id, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT store_id, event, status, detail, sig_status, body_head,
                           content_type, user_agent, created_at
                    FROM webhook_log
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
        return [
            {k: (v.isoformat() + "Z" if k == "created_at" and v else v) for k, v in dict(r).items()}
            for r in rows
        ]
    except Exception as e:
        print(f"[db] get_webhook_log error: {e}")
        return []


async def prune_webhook_log(keep_last_days: int = 30) -> int:
    """Delete webhook_log rows older than `keep_last_days`. Returns count deleted."""
    if not _pool:
        return 0
    try:
        async with _pool.acquire() as conn:
            r = await conn.execute(
                f"DELETE FROM webhook_log WHERE created_at < NOW() - INTERVAL '{int(keep_last_days)} days'"
            )
        # asyncpg returns 'DELETE <n>' — parse the n
        try:
            return int(r.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_webhook_log error: {e}")
        return 0


# ── Webhook idempotency ─────────────────────────────────────────────────────

async def is_webhook_seen(dedup_key: str) -> bool:
    """True if this webhook key has already been processed. Atomic insert."""
    if not _pool or not dedup_key:
        return False
    try:
        async with _pool.acquire() as conn:
            # ON CONFLICT DO NOTHING + RETURNING tells us whether this was a new row
            row = await conn.fetchrow(
                """
                INSERT INTO webhook_seen (dedup_key) VALUES ($1)
                ON CONFLICT (dedup_key) DO NOTHING
                RETURNING dedup_key
                """,
                dedup_key,
            )
        # row is None when conflict happened → we've seen it before
        return row is None
    except Exception as e:
        print(f"[db] is_webhook_seen error: {e}")
        return False  # Fail-open: better to process duplicate than drop a real event


async def prune_webhook_seen(keep_last_hours: int = 24) -> int:
    """
    Drop dedup keys older than `keep_last_hours`. Salla retries up to 3× over
    15 min so 24h is plenty of safety margin.
    """
    if not _pool:
        return 0
    try:
        async with _pool.acquire() as conn:
            r = await conn.execute(
                f"DELETE FROM webhook_seen WHERE created_at < NOW() - INTERVAL '{int(keep_last_hours)} hours'"
            )
        try:
            return int(r.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_webhook_seen error: {e}")
        return 0


# ── Login rate-limiting ─────────────────────────────────────────────────────

async def count_recent_login_attempts(attempt_key: str, window_secs: int) -> int:
    """Count attempts for this key in the last `window_secs` seconds."""
    if not _pool:
        return 0
    try:
        async with _pool.acquire() as conn:
            n = await conn.fetchval(
                f"""
                SELECT COUNT(*) FROM login_attempts
                WHERE attempt_key = $1
                  AND created_at >= NOW() - INTERVAL '{int(window_secs)} seconds'
                """,
                attempt_key,
            )
        return int(n or 0)
    except Exception as e:
        print(f"[db] count_recent_login_attempts error: {e}")
        return 0


async def record_login_attempt(attempt_key: str) -> None:
    """Record a login attempt (success or failure)."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO login_attempts (attempt_key) VALUES ($1)",
                attempt_key,
            )
    except Exception as e:
        print(f"[db] record_login_attempt error: {e}")


async def prune_login_attempts(keep_last_hours: int = 24) -> int:
    """Delete old login attempts to keep the table small."""
    if not _pool:
        return 0
    try:
        async with _pool.acquire() as conn:
            r = await conn.execute(
                f"DELETE FROM login_attempts WHERE created_at < NOW() - INTERVAL '{int(keep_last_hours)} hours'"
            )
        try:
            return int(r.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_login_attempts error: {e}")
        return 0


# ── App-level settings (global flags) ───────────────────────────────────────

async def get_app_setting(key: str, default=None):
    """Read a JSON value from app_settings, falling back to `default`."""
    if not _pool:
        return default
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
        return
    try:
        # Wrap primitives so the codec serialises cleanly
        payload = value if isinstance(value, dict) else {"value": value}
        async with _pool.acquire() as conn:
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


# ── Uploads (persistent file storage in PostgreSQL) ──────────────────────────

async def save_upload(file_id: str, filename: str, content_type: str,
                       data: bytes, store_id: str = "", session_id: str = "") -> bool:
    """Persist an uploaded file to PostgreSQL. Returns True on success."""
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO uploads (file_id, filename, content_type, size_bytes, data, store_id, session_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                file_id, filename, content_type, len(data), data, store_id, session_id,
            )
        return True
    except Exception as e:
        print(f"[db] save_upload({file_id!r}) error: {e}")
        return False


async def load_upload(file_id: str) -> dict | None:
    """Read an uploaded file back from PostgreSQL. Returns None if missing."""
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT filename, content_type, data FROM uploads WHERE file_id = $1",
                file_id,
            )
        if not row:
            return None
        return {
            "filename":     row["filename"],
            "content_type": row["content_type"],
            "data":         bytes(row["data"]),
        }
    except Exception as e:
        print(f"[db] load_upload({file_id!r}) error: {e}")
        return None


def available() -> bool:
    """True if the DB pool is up and ready."""
    return _pool is not None


def get_status() -> dict:
    """Return a summary of DB connectivity for /env-check and admin UI."""
    return {
        "connected":     _pool is not None,
        "database_url":  bool(os.getenv("DATABASE_URL", "").strip()),
    }


async def force_save_all_stores(stores: list[dict]) -> int:
    """
    Bulk-upsert every store from the in-memory registry into PostgreSQL.
    Called when admin clicks 'Force Save to DB'.
    Returns the number of stores saved.
    """
    if not _pool:
        return 0
    saved = 0
    for s in stores:
        sid    = s.get("store_id", "")
        tokens = s.get("tokens",   {})
        if not sid or not tokens:
            continue
        try:
            ai_cfg = tokens.get("ai_config", {})
            async with _pool.acquire() as conn:
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
                    json.dumps(tokens,  ensure_ascii=False),
                    json.dumps(ai_cfg,  ensure_ascii=False),
                )
            saved += 1
        except Exception as e:
            print(f"[db] force_save_all_stores({sid!r}) error: {e}")
    return saved


def _log_task_error(task: asyncio.Task):
    """Print exceptions raised by fire-and-forget DB tasks so they don't vanish."""
    try:
        exc = task.exception()
    except (asyncio.CancelledError, asyncio.InvalidStateError):
        return
    if exc:
        print(f"[db] ❌ Fire-and-forget DB task FAILED: {type(exc).__name__}: {exc}")


def fire(coro):
    """
    Schedule an async DB coroutine from synchronous code that is already
    running inside an asyncio event loop (e.g. FastAPI route handlers).
    Silently ignored when no event loop is running (unit tests / CLI scripts).

    Attaches an error logger so silent write failures become visible in
    Railway logs — previously a failing fire-and-forget write would just
    disappear and the data would be lost without any trace.
    """
    try:
        task = asyncio.get_running_loop().create_task(coro)
        task.add_done_callback(_log_task_error)
    except RuntimeError:
        pass  # No running loop — skip the write gracefully


async def test_round_trip() -> dict:
    """
    Diagnostic: write a test row, read it back, delete it.
    Returns {ok, write_ok, read_ok, delete_ok, store_count, error}.
    Used by /admin/db-test to verify the DB is actually usable end-to-end.
    """
    result = {
        "ok":           False,
        "connected":    _pool is not None,
        "write_ok":     False,
        "read_ok":      False,
        "delete_ok":    False,
        "store_count":  0,
        "error":        "",
    }
    if not _pool:
        result["error"] = "DATABASE_URL not set or connection failed at startup"
        return result

    test_id = "_diagnostic_test_row"
    test_payload = {"diagnostic": True, "ts": "round_trip"}
    try:
        # WRITE
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stores (store_id, tokens, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (store_id) DO UPDATE
                  SET tokens = EXCLUDED.tokens, updated_at = NOW()
                """,
                test_id,
                json.dumps(test_payload),
            )
        result["write_ok"] = True

        # READ
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tokens FROM stores WHERE store_id = $1", test_id
            )
        if row and dict(row["tokens"]).get("diagnostic") is True:
            result["read_ok"] = True

        # COUNT real stores (excluding the test row)
        async with _pool.acquire() as conn:
            cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM stores WHERE store_id != $1", test_id
            )
        result["store_count"] = int(cnt or 0)

        # DELETE
        async with _pool.acquire() as conn:
            await conn.execute("DELETE FROM stores WHERE store_id = $1", test_id)
        result["delete_ok"] = True

        result["ok"] = result["write_ok"] and result["read_ok"] and result["delete_ok"]
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        print(f"[db] ❌ test_round_trip failed: {result['error']}")

    return result


# ── Stores ─────────────────────────────────────────────────────────────────────

def _coerce_jsonb(value) -> dict:
    """
    Defensive: handle both dict (codec registered) and str (codec missing)
    so an old pool without the JSONB codec doesn't lose data either.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except Exception:
            return {}
    # Some other type — best effort
    try:
        return dict(value)
    except Exception:
        return {}


async def load_all_stores() -> list:
    """
    Return all store rows from the DB.
    Each row: {store_id, tokens, ai_config, cache_data}
    """
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT store_id, tokens, ai_config, cache_data FROM stores"
            )
        result = [
            {
                "store_id":  r["store_id"],
                "tokens":    _coerce_jsonb(r["tokens"]),
                "ai_config": _coerce_jsonb(r["ai_config"]),
                "cache":     _coerce_jsonb(r["cache_data"]),
            }
            for r in rows
        ]
        print(f"[db] load_all_stores: fetched {len(result)} row(s) from PostgreSQL")
        return result
    except Exception as e:
        # Print the FULL exception (not just message) so silent failures
        # like dict(str) TypeErrors are visible in Railway logs
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
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
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


async def save_store(store_id: str, tokens: dict):
    """Upsert store tokens (access/refresh token, store name, etc.)."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stores (store_id, tokens, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (store_id) DO UPDATE
                  SET tokens = EXCLUDED.tokens, updated_at = NOW()
                """,
                store_id,
                json.dumps(tokens, ensure_ascii=False),
            )
    except Exception as e:
        print(f"[db] save_store({store_id!r}) error: {e}")


async def save_ai_config(store_id: str, ai_config: dict):
    """Upsert only the ai_config column, leaving tokens and cache unchanged."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stores (store_id, ai_config, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (store_id) DO UPDATE
                  SET ai_config = EXCLUDED.ai_config, updated_at = NOW()
                """,
                store_id,
                json.dumps(ai_config, ensure_ascii=False),
            )
    except Exception as e:
        print(f"[db] save_ai_config({store_id!r}) error: {e}")


async def save_cache(store_id: str, cache: dict):
    """Upsert only the product cache column."""
    if not _pool:
        return
    try:
        # Serialise with a default to handle datetime objects in cache
        payload = json.dumps(cache, ensure_ascii=False, default=str)
        async with _pool.acquire() as conn:
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


# ── Conversations ──────────────────────────────────────────────────────────────

async def load_conversations(limit: int = 500) -> list:
    """
    Load the most recent `limit` conversations from the DB.
    Returns list of {session_id, store_id, data}.
    """
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, store_id, data
                FROM conversations
                ORDER BY updated_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [
            {
                "session_id": r["session_id"],
                "store_id":   r["store_id"],
                "data":       _coerce_jsonb(r["data"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] load_conversations error: {e}")
        return []


async def load_store_conversations(store_id: str, limit: int = 2000) -> list:
    """
    Load the most recent `limit` conversations for a specific store from the DB.
    Returns list of {session_id, store_id, data}.
    """
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, store_id, data
                FROM conversations
                WHERE store_id = $1
                ORDER BY updated_at DESC
                LIMIT $2
                """,
                store_id,
                limit,
            )
        return [
            {
                "session_id": r["session_id"],
                "store_id":   r["store_id"],
                "data":       _coerce_jsonb(r["data"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] load_store_conversations({store_id!r}) error: {e}")
        return []



async def load_conversation(session_id: str) -> dict | None:
    """Load a specific conversation from the DB. Returns None if missing."""
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM conversations WHERE session_id = $1",
                session_id,
            )
        if not row:
            return None
        return _coerce_jsonb(row["data"])
    except Exception as e:
        print(f"[db] load_conversation({session_id!r}) error: {e}")
        return None



async def save_conversation(session_id: str, store_id: str, data: dict):
    """Upsert a full conversation state dict."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO conversations (session_id, store_id, data, updated_at)
                VALUES ($1, $2, $3::jsonb, NOW())
                ON CONFLICT (session_id) DO UPDATE
                  SET data = EXCLUDED.data, store_id = EXCLUDED.store_id,
                      updated_at = NOW()
                """,
                session_id,
                store_id,
                json.dumps(data, ensure_ascii=False, default=str),
            )
    except Exception as e:
        print(f"[db] save_conversation({session_id!r}) error: {e}")


# ── Abandoned carts ────────────────────────────────────────────────────────────

async def save_abandoned_cart(store_id: str, cart_id: str, cart_data: dict):
    """Insert a new abandoned cart notification (ignore duplicate cart_ids)."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO abandoned_carts (store_id, cart_id, cart_data)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (store_id, cart_id) DO NOTHING
                """,
                store_id,
                cart_id,
                json.dumps(cart_data, ensure_ascii=False, default=str),
            )
    except Exception as e:
        print(f"[db] save_abandoned_cart({cart_id!r}) error: {e}")


async def load_abandoned_carts(store_id: str) -> list:
    """Return all abandoned cart notifications for a store, newest first."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT cart_id, cart_data, recovered
                FROM abandoned_carts
                WHERE store_id = $1
                ORDER BY created_at DESC
                LIMIT 500
                """,
                store_id,
            )
        result = []
        for r in rows:
            entry = _coerce_jsonb(r["cart_data"])
            entry["recovered"] = r["recovered"]
            result.append(entry)
        return result
    except Exception as e:
        print(f"[db] load_abandoned_carts({store_id!r}) error: {e}")
        return []


async def mark_cart_recovered(store_id: str, cart_id: str):
    """Mark a specific abandoned cart as recovered in the DB."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "UPDATE abandoned_carts SET recovered = TRUE WHERE store_id = $1 AND cart_id = $2",
                store_id,
                cart_id,
            )
    except Exception as e:
        print(f"[db] mark_cart_recovered({cart_id!r}) error: {e}")
