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

import crypto as _crypto

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

            -- Per-store employees (agents). Used when the store owner wants to
            -- give a colleague their own login so admin replies show the
            -- agent's name and CSAT surveys can rate each agent individually.
            CREATE TABLE IF NOT EXISTS employees (
                id            BIGSERIAL PRIMARY KEY,
                store_id      TEXT NOT NULL,
                name          TEXT NOT NULL,
                email         TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'agent',  -- 'agent' | 'manager'
                active        BOOLEAN NOT NULL DEFAULT TRUE,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (store_id, email)
            );
            CREATE INDEX IF NOT EXISTS idx_employees_store
                ON employees (store_id);

            -- Orders the BOT created (checkout / quote→order). Powers the ROI
            -- dashboard ("how much did the bot make you"). One row per order.
            CREATE TABLE IF NOT EXISTS bot_orders (
                id          BIGSERIAL PRIMARY KEY,
                store_id    TEXT NOT NULL,
                session_id  TEXT,
                order_ref   TEXT,
                amount      NUMERIC NOT NULL DEFAULT 0,
                currency    TEXT NOT NULL DEFAULT 'SAR',
                kind        TEXT NOT NULL DEFAULT 'checkout',  -- 'checkout' | 'quote'
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_bot_orders_store_ts
                ON bot_orders (store_id, created_at DESC);
            -- Avoid double-counting if the same order is recorded twice.
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_orders_unique
                ON bot_orders (store_id, order_ref);

            -- ── Durable webhook ingest queue ───────────────────────────────
            -- Every incoming webhook (Salla + WhatsApp) is INSERTed here
            -- BEFORE the 200 OK ack. A worker drains pending rows with
            -- SELECT FOR UPDATE SKIP LOCKED. This is the transactional
            -- inbox pattern — it guarantees that a process restart between
            -- "received" and "processed" doesn't lose the event.
            --
            -- The UNIQUE (source, dedup_key) constraint replaces the old
            -- webhook_seen table: idempotent receipts are now atomic at the
            -- INSERT level (ON CONFLICT DO NOTHING).
            CREATE TABLE IF NOT EXISTS webhook_inbox (
                id            BIGSERIAL PRIMARY KEY,
                source        TEXT NOT NULL,                  -- 'salla' | 'whatsapp'
                event_type    TEXT,                           -- 'order.created' | 'whatsapp.message' | …
                dedup_key     TEXT,                           -- '{event}:{merchant}:{created_at}' | 'wa:{message_id}'
                store_id      TEXT,                           -- for routing & log filtering
                payload       JSONB NOT NULL,                 -- full parsed body
                meta          JSONB NOT NULL DEFAULT '{}'::jsonb,  -- sig_status, body_head, headers
                status        TEXT NOT NULL DEFAULT 'pending',-- pending|processing|done|failed|dead
                attempts      INT  NOT NULL DEFAULT 0,
                last_error    TEXT,
                claimed_by    TEXT,
                claimed_at    TIMESTAMPTZ,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                processed_at  TIMESTAMPTZ
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_inbox_dedup
                ON webhook_inbox (source, dedup_key)
                WHERE dedup_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_inbox_pending
                ON webhook_inbox (status, created_at)
                WHERE status IN ('pending', 'failed');
            CREATE INDEX IF NOT EXISTS idx_inbox_dead
                ON webhook_inbox (status, created_at DESC)
                WHERE status = 'dead';

            -- ── Durable outbound delivery queue ────────────────────────────
            -- Every outbound side-effect (email, custom webhook, WhatsApp
            -- send) is INSERTed here as part of the same DB transaction
            -- that triggered it. A worker dispatches with exponential
            -- backoff and parks dead rows after MAX_ATTEMPTS for an admin
            -- to inspect.
            CREATE TABLE IF NOT EXISTS outbox (
                id              BIGSERIAL PRIMARY KEY,
                kind            TEXT NOT NULL,             -- notify_email|notify_webhook|whatsapp_send|whatsapp_csat
                store_id        TEXT,
                payload         JSONB NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                attempts        INT  NOT NULL DEFAULT 0,
                last_error      TEXT,
                next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                sent_at         TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_pending
                ON outbox (status, next_attempt_at)
                WHERE status IN ('pending', 'failed');
            CREATE INDEX IF NOT EXISTS idx_outbox_dead
                ON outbox (status, created_at DESC)
                WHERE status = 'dead';

            -- Track which sessions have unflushed conversation state. Used
            -- by the drainer to find work in O(index) time without a
            -- full-table JSONB scan. Replaces the in-memory _dirty_sessions
            -- set so multi-instance deployments stay coherent.
            ALTER TABLE conversations
              ADD COLUMN IF NOT EXISTS dirty_at TIMESTAMPTZ;
            CREATE INDEX IF NOT EXISTS idx_conv_dirty
                ON conversations (dirty_at) WHERE dirty_at IS NOT NULL;

            -- ── Leader-election leases ─────────────────────────────────────
            -- One row per named periodic job. The holder claims a TTL
            -- (acquire+renew is the same SQL); other instances see the
            -- row not-expired and sleep this tick. If the holder dies,
            -- the row's expires_at lapses and another instance takes over
            -- on its next tick. Survives connection drops (no advisory-
            -- lock session semantics).
            CREATE TABLE IF NOT EXISTS leader_locks (
                name        TEXT PRIMARY KEY,
                holder      TEXT NOT NULL,
                acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at  TIMESTAMPTZ NOT NULL
            );
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
                        file_id: str = "", file_name: str = "",
                        enabled: bool = True) -> int | None:
    """
    Insert one training row. Returns the new id, or None on failure.
    `enabled=False` is used for auto-learned lessons that wait for admin
    approval before they're injected into the bot's prompt.
    """
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO bot_training
                  (store_id, kind, title, content, file_id, file_name, size_chars, enabled)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                store_id, kind, title, content or "",
                file_id or None, file_name or None, len(content or ""), enabled,
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


# ── Employees ───────────────────────────────────────────────────────────────

async def list_employees(store_id: str) -> list[dict]:
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, store_id, name, email, role, active, created_at
                FROM employees
                WHERE store_id = $1
                ORDER BY created_at DESC
                """,
                store_id,
            )
        return [
            {
                "id":         int(r["id"]),
                "store_id":   r["store_id"],
                "name":       r["name"],
                "email":      r["email"],
                "role":       r["role"] or "agent",
                "active":     bool(r["active"]),
                "created_at": r["created_at"].isoformat() + "Z" if r["created_at"] else "",
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] list_employees error: {e}")
        return []


async def add_employee(store_id: str, name: str, email: str,
                       password_hash: str, role: str = "agent",
                       active: bool = True) -> int | None:
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO employees (store_id, name, email, password_hash, role, active)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                store_id, name, email.lower(), password_hash,
                role or "agent", bool(active),
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] add_employee error: {e}")
        return None


async def get_employee(emp_id: int) -> dict | None:
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, store_id, name, email, password_hash, role, active, created_at
                FROM employees WHERE id = $1
                """,
                int(emp_id),
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
            "created_at":    row["created_at"].isoformat() + "Z" if row["created_at"] else "",
        }
    except Exception as e:
        print(f"[db] get_employee error: {e}")
        return None


async def get_employee_by_email(store_id: str, email: str) -> dict | None:
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, store_id, name, email, password_hash, role, active, created_at
                FROM employees WHERE store_id = $1 AND email = $2
                """,
                store_id, email.lower(),
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
            "created_at":    row["created_at"].isoformat() + "Z" if row["created_at"] else "",
        }
    except Exception as e:
        print(f"[db] get_employee_by_email error: {e}")
        return None


async def update_employee(emp_id: int, *, name: str | None = None,
                          email: str | None = None,
                          password_hash: str | None = None,
                          role: str | None = None,
                          active: bool | None = None) -> bool:
    if not _pool:
        return False
    sets: list[str] = []
    args: list = []
    if name is not None:
        sets.append(f"name = ${len(args)+1}"); args.append(name)
    if email is not None:
        sets.append(f"email = ${len(args)+1}"); args.append(email.lower())
    if password_hash is not None:
        sets.append(f"password_hash = ${len(args)+1}"); args.append(password_hash)
    if role is not None:
        sets.append(f"role = ${len(args)+1}"); args.append(role)
    if active is not None:
        sets.append(f"active = ${len(args)+1}"); args.append(bool(active))
    if not sets:
        return True
    args.append(int(emp_id))
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                f"UPDATE employees SET {', '.join(sets)} WHERE id = ${len(args)}",
                *args,
            )
        return True
    except Exception as e:
        print(f"[db] update_employee error: {e}")
        return False


async def delete_employee(emp_id: int) -> bool:
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute("DELETE FROM employees WHERE id = $1", int(emp_id))
        return True
    except Exception as e:
        print(f"[db] delete_employee error: {e}")
        return False


# ── Bot ROI: orders the bot generated ───────────────────────────────────────

async def record_bot_order(store_id: str, session_id: str, order_ref: str,
                           amount: float, currency: str = "SAR",
                           kind: str = "checkout") -> None:
    """
    Record an order the bot created, for the ROI dashboard. Idempotent on
    (store_id, order_ref) so re-recording the same order doesn't double-count.
    Best-effort — never raises.
    """
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_orders (store_id, session_id, order_ref, amount, currency, kind)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (store_id, order_ref) DO NOTHING
                """,
                store_id, session_id or "", str(order_ref or ""),
                float(amount or 0), currency or "SAR", kind or "checkout",
            )
    except Exception as e:
        print(f"[db] record_bot_order error: {e}")


async def get_weekly_roi(store_id: str) -> dict:
    """
    Bot revenue + order counts for THIS week vs the PREVIOUS week, for the
    weekly report's week-over-week comparison.
    """
    empty = {"rev_this": 0.0, "ord_this": 0, "rev_prev": 0.0, "ord_prev": 0, "currency": "SAR"}
    if not _pool:
        return empty
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                  COALESCE(SUM(amount) FILTER (WHERE created_at >= NOW() - interval '7 days'), 0) AS rev_this,
                  COUNT(*)            FILTER (WHERE created_at >= NOW() - interval '7 days')        AS ord_this,
                  COALESCE(SUM(amount) FILTER (WHERE created_at >= NOW() - interval '14 days'
                                               AND created_at <  NOW() - interval '7 days'), 0)     AS rev_prev,
                  COUNT(*)            FILTER (WHERE created_at >= NOW() - interval '14 days'
                                               AND created_at <  NOW() - interval '7 days')         AS ord_prev,
                  MAX(currency) AS currency
                FROM bot_orders
                WHERE store_id = $1
                """,
                store_id,
            )
        if not row:
            return empty
        return {
            "rev_this": round(float(row["rev_this"] or 0), 2),
            "ord_this": int(row["ord_this"] or 0),
            "rev_prev": round(float(row["rev_prev"] or 0), 2),
            "ord_prev": int(row["ord_prev"] or 0),
            "currency": row["currency"] or "SAR",
        }
    except Exception as e:
        print(f"[db] get_weekly_roi error: {e}")
        return empty


async def get_bot_roi(store_id: str, days: int = 30) -> dict:
    """
    Aggregate bot-generated revenue for the last `days`. Returns
    {revenue, orders, currency, avg_order} for the window + all-time totals.
    """
    empty = {"revenue": 0.0, "orders": 0, "currency": "SAR", "avg_order": 0.0,
             "revenue_all": 0.0, "orders_all": 0}
    if not _pool:
        return empty
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                  COALESCE(SUM(amount) FILTER (WHERE created_at >= NOW() - ($2 || ' days')::interval), 0) AS revenue,
                  COUNT(*)            FILTER (WHERE created_at >= NOW() - ($2 || ' days')::interval)        AS orders,
                  COALESCE(SUM(amount), 0) AS revenue_all,
                  COUNT(*)                 AS orders_all,
                  MAX(currency)            AS currency
                FROM bot_orders
                WHERE store_id = $1
                """,
                store_id, str(int(days)),
            )
        if not row:
            return empty
        revenue = float(row["revenue"] or 0)
        orders  = int(row["orders"] or 0)
        return {
            "revenue":     round(revenue, 2),
            "orders":      orders,
            "currency":    row["currency"] or "SAR",
            "avg_order":   round(revenue / orders, 2) if orders else 0.0,
            "revenue_all": round(float(row["revenue_all"] or 0), 2),
            "orders_all":  int(row["orders_all"] or 0),
        }
    except Exception as e:
        print(f"[db] get_bot_roi error: {e}")
        return empty


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
            # Encrypt secrets before the bulk write — same boundary as
            # save_store / save_ai_config.
            enc_tokens = _crypto.encrypt_store_blob(tokens)
            enc_ai_cfg = _crypto.encrypt_ai_config_blob(ai_cfg)
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
                    json.dumps(enc_tokens,  ensure_ascii=False),
                    json.dumps(enc_ai_cfg,  ensure_ascii=False),
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
    Return all store rows from the DB with secrets decrypted in memory.
    Each row: {store_id, tokens, ai_config, cache_data}

    Decryption is transparent — callers iterating the returned list see
    plaintext access_token, refresh_token, and provider API keys, just
    like before Phase C9. The ciphertext only ever exists on disk.

    Legacy plaintext rows (pre-encryption deploys) pass through unchanged
    via crypto.decrypt's pass-through-on-no-prefix behaviour. The 0002
    migration upgrades them at deploy time.
    """
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
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
    """
    Upsert store tokens. Secrets inside the blob (access_token,
    refresh_token, ai_config.{groq,anthropic,openai,whatsapp}_*) are
    encrypted at this boundary — see crypto.encrypt_store_blob. Memory
    keeps plaintext, so existing callers reading tokens["access_token"]
    are unaffected.
    """
    if not _pool:
        return
    encrypted_blob = _crypto.encrypt_store_blob(tokens)
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
                json.dumps(encrypted_blob, ensure_ascii=False),
            )
    except Exception as e:
        print(f"[db] save_store({store_id!r}) error: {e}")


async def purge_store(store_id: str) -> dict:
    """
    Delete ALL data for a store — called on app.uninstalled to comply with
    Salla's data-privacy requirement that uninstalling removes merchant data.
    Removes the store row plus its conversations, abandoned carts, uploads,
    bot training, and webhook log. Returns a per-table deleted count.
    """
    if not _pool:
        return {}
    counts: dict = {}
    tables = [
        ("stores",          "store_id"),
        ("conversations",   "store_id"),
        ("abandoned_carts", "store_id"),
        ("uploads",         "store_id"),
        ("bot_training",    "store_id"),
        ("webhook_log",     "store_id"),
        ("employees",       "store_id"),
    ]
    try:
        async with _pool.acquire() as conn:
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


async def save_ai_config(store_id: str, ai_config: dict):
    """
    Upsert only the ai_config column. Provider API keys
    (groq/anthropic/openai/whatsapp) are encrypted before write — see
    crypto.encrypt_ai_config_blob.
    """
    if not _pool:
        return
    encrypted = _crypto.encrypt_ai_config_blob(ai_config)
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
                json.dumps(encrypted, ensure_ascii=False),
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


# ─────────────────────────────────────────────────────────────────────────────
# Webhook inbox (durable ingest queue)
# ─────────────────────────────────────────────────────────────────────────────

async def inbox_insert(
    source: str,
    payload: dict,
    *,
    event_type: str = "",
    dedup_key: str = "",
    store_id: str = "",
    meta: dict | None = None,
) -> dict:
    """
    Insert a new inbox row, atomic dedup on (source, dedup_key).

    Returns {"inserted": bool, "id": int|None}. inserted=False means a row
    with the same dedup_key already exists — Salla/Meta retried a duplicate
    delivery and we should just ack 200 without re-queueing the work.
    """
    if not _pool:
        return {"inserted": False, "id": None}
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO webhook_inbox
                    (source, event_type, dedup_key, store_id, payload, meta)
                VALUES ($1, $2, NULLIF($3, ''), $4, $5::jsonb, $6::jsonb)
                ON CONFLICT (source, dedup_key) DO NOTHING
                RETURNING id
                """,
                source,
                event_type or "",
                dedup_key or "",
                store_id or "",
                json.dumps(payload, ensure_ascii=False, default=str),
                json.dumps(meta or {}, ensure_ascii=False, default=str),
            )
        if row is None:
            return {"inserted": False, "id": None}
        return {"inserted": True, "id": int(row["id"])}
    except Exception as e:
        print(f"[db] inbox_insert error: {e}")
        return {"inserted": False, "id": None}


async def inbox_claim_batch(worker_id: str, limit: int = 20) -> list[dict]:
    """
    Atomic batch-claim: pick up to `limit` pending/retryable rows, mark them
    `processing`, and return them. Uses SELECT FOR UPDATE SKIP LOCKED so
    multiple drainer instances can run side-by-side without contention.
    """
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH cte AS (
                    SELECT id
                    FROM webhook_inbox
                    WHERE status IN ('pending', 'failed')
                    ORDER BY created_at
                    LIMIT $2
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE webhook_inbox w
                   SET status     = 'processing',
                       attempts   = w.attempts + 1,
                       claimed_by = $1,
                       claimed_at = NOW()
                  FROM cte
                 WHERE w.id = cte.id
              RETURNING w.id, w.source, w.event_type, w.dedup_key,
                        w.store_id, w.payload, w.meta, w.attempts
                """,
                worker_id, limit,
            )
        return [
            {
                "id":         int(r["id"]),
                "source":     r["source"],
                "event_type": r["event_type"] or "",
                "dedup_key":  r["dedup_key"] or "",
                "store_id":   r["store_id"] or "",
                "payload":    _coerce_jsonb(r["payload"]),
                "meta":       _coerce_jsonb(r["meta"]),
                "attempts":   int(r["attempts"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] inbox_claim_batch error: {e}")
        return []


async def inbox_mark_done(inbox_id: int) -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "UPDATE webhook_inbox SET status='done', processed_at=NOW(), last_error=NULL "
                "WHERE id=$1",
                inbox_id,
            )
    except Exception as e:
        print(f"[db] inbox_mark_done error: {e}")


# Same retry ladder used for the outbox (kept here so both drainers behave the
# same way for ops/runbooks). Index = attempts after the failure.
_RETRY_BACKOFF_SECONDS = (5, 30, 120, 600, 1800)   # 5s, 30s, 2m, 10m, 30m
_MAX_ATTEMPTS = 5


async def inbox_mark_failed(inbox_id: int, error: str, attempts: int) -> None:
    """
    Record a processing failure. After _MAX_ATTEMPTS the row is parked as
    `dead` for human inspection — never silently dropped.
    """
    if not _pool:
        return
    final = attempts >= _MAX_ATTEMPTS
    status = "dead" if final else "failed"
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "UPDATE webhook_inbox SET status=$2, last_error=$3 WHERE id=$1",
                inbox_id, status, (error or "")[:2000],
            )
    except Exception as e:
        print(f"[db] inbox_mark_failed error: {e}")


async def inbox_count_by_status() -> dict:
    """Health snapshot for /admin/db-test and a future ops dashboard."""
    if not _pool:
        return {}
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT status, COUNT(*) AS n FROM webhook_inbox GROUP BY status"
            )
        return {r["status"]: int(r["n"]) for r in rows}
    except Exception as e:
        print(f"[db] inbox_count_by_status error: {e}")
        return {}


async def prune_inbox_done(keep_last_days: int = 14) -> int:
    """Drop processed inbox rows older than N days. DEAD rows are kept."""
    if not _pool:
        return 0
    try:
        async with _pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM webhook_inbox "
                "WHERE status='done' AND processed_at < NOW() - ($1 || ' days')::interval",
                str(int(keep_last_days)),
            )
        # asyncpg returns 'DELETE <rowcount>' on success
        try:
            return int(result.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_inbox_done error: {e}")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Outbox (durable outbound delivery queue)
# ─────────────────────────────────────────────────────────────────────────────

async def outbox_enqueue(kind: str, payload: dict, *, store_id: str = "") -> int | None:
    """Schedule an outbound side-effect (email, custom webhook, WhatsApp send)."""
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO outbox (kind, store_id, payload)
                VALUES ($1, $2, $3::jsonb)
                RETURNING id
                """,
                kind, store_id or "",
                json.dumps(payload, ensure_ascii=False, default=str),
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] outbox_enqueue error: {e}")
        return None


async def outbox_claim_batch(worker_id: str, limit: int = 20) -> list[dict]:
    """Same claim-pattern as the inbox, scoped to outbox rows due now."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH cte AS (
                    SELECT id
                    FROM outbox
                    WHERE status IN ('pending', 'failed')
                      AND next_attempt_at <= NOW()
                    ORDER BY next_attempt_at
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE outbox o
                   SET status   = 'processing',
                       attempts = o.attempts + 1
                  FROM cte
                 WHERE o.id = cte.id
              RETURNING o.id, o.kind, o.store_id, o.payload, o.attempts
                """,
                limit,
            )
        return [
            {
                "id":       int(r["id"]),
                "kind":     r["kind"],
                "store_id": r["store_id"] or "",
                "payload":  _coerce_jsonb(r["payload"]),
                "attempts": int(r["attempts"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] outbox_claim_batch error: {e}")
        return []


async def outbox_mark_sent(outbox_id: int) -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "UPDATE outbox SET status='done', sent_at=NOW(), last_error=NULL WHERE id=$1",
                outbox_id,
            )
    except Exception as e:
        print(f"[db] outbox_mark_sent error: {e}")


async def outbox_mark_failed(outbox_id: int, error: str, attempts: int) -> None:
    """Apply exponential backoff or park as dead after MAX_ATTEMPTS."""
    if not _pool:
        return
    final = attempts >= _MAX_ATTEMPTS
    status = "dead" if final else "failed"
    delay_idx = min(attempts - 1, len(_RETRY_BACKOFF_SECONDS) - 1)
    delay_secs = _RETRY_BACKOFF_SECONDS[max(0, delay_idx)]
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox
                   SET status          = $2,
                       last_error      = $3,
                       next_attempt_at = NOW() + ($4 || ' seconds')::interval
                 WHERE id = $1
                """,
                outbox_id, status, (error or "")[:2000], str(delay_secs),
            )
    except Exception as e:
        print(f"[db] outbox_mark_failed error: {e}")


async def outbox_count_by_status() -> dict:
    if not _pool:
        return {}
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT status, COUNT(*) AS n FROM outbox GROUP BY status"
            )
        return {r["status"]: int(r["n"]) for r in rows}
    except Exception as e:
        print(f"[db] outbox_count_by_status error: {e}")
        return {}


async def prune_outbox_sent(keep_last_days: int = 7) -> int:
    if not _pool:
        return 0
    try:
        async with _pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM outbox WHERE status='done' AND sent_at < NOW() - ($1 || ' days')::interval",
                str(int(keep_last_days)),
            )
        try:
            return int(result.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_outbox_sent error: {e}")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Dirty-conversation tracking (replaces the in-memory _dirty_sessions set)
# ─────────────────────────────────────────────────────────────────────────────

async def mark_conversation_dirty(session_id: str) -> None:
    """
    Set conversations.dirty_at on the existing row so the periodic flusher
    can find it. No-op when DB is unavailable or the row doesn't exist yet
    (the next save_conversation will create it and the next mark_dirty will
    succeed).
    """
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "UPDATE conversations SET dirty_at = NOW() WHERE session_id = $1",
                session_id,
            )
    except Exception as e:
        print(f"[db] mark_conversation_dirty error: {e}")


async def fetch_dirty_sessions(limit: int = 200) -> list[str]:
    """Return up to `limit` session_ids that need a flush, oldest first."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id
                FROM conversations
                WHERE dirty_at IS NOT NULL
                ORDER BY dirty_at
                LIMIT $1
                """,
                limit,
            )
        return [r["session_id"] for r in rows]
    except Exception as e:
        print(f"[db] fetch_dirty_sessions error: {e}")
        return []


async def clear_conversation_dirty(session_ids: list[str]) -> None:
    """Clear dirty_at on the given session_ids after a successful save."""
    if not _pool or not session_ids:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "UPDATE conversations SET dirty_at = NULL WHERE session_id = ANY($1::text[])",
                session_ids,
            )
    except Exception as e:
        print(f"[db] clear_conversation_dirty error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Leader election (DB-row lease)
# ─────────────────────────────────────────────────────────────────────────────
# Used by periodic loops so a multi-instance deploy doesn't double-run them
# (e.g. token-refresh racing between web instances).
#
# The model is a "renewable TTL lease":
#   • try_lead(name, holder, ttl): inserts/refreshes the lock row.
#     Returns True if THIS holder is now the leader for the next ttl seconds.
#   • The leader either calls try_lead() again before expiry (renew), or
#     lets it lapse so another instance takes over.
#   • No automatic release on crash — the TTL handles it. Pick a TTL that
#     is comfortably longer than the loop's iteration time.
#
# Why not pg_advisory_lock? Advisory locks are session-scoped, so they
# need a dedicated long-lived connection per leader, plus they're invisible
# from outside SQL. The leader_locks table is observable, debuggable, and
# survives pool-connection churn.

async def try_lead(name: str, holder_id: str, ttl_seconds: int = 300) -> bool:
    """
    Atomically acquire OR renew leadership of `name` for `ttl_seconds`.
    Returns True iff after this call, `holder_id` holds the lock.

    Behaviour matrix:
      • No existing row              → INSERT, this holder wins.
      • Existing row, expired        → UPDATE to this holder, win.
      • Existing row held by SAME id → UPDATE (renew), win.
      • Existing row held by OTHER + not expired → no change, lose.
    """
    if not _pool:
        # No DB → can't coordinate. Best to assume sole leadership so
        # standalone-DB-less mode keeps periodic jobs running.
        return True
    try:
        async with _pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO leader_locks (name, holder, acquired_at, expires_at)
                VALUES ($1, $2, NOW(), NOW() + ($3 || ' seconds')::interval)
                ON CONFLICT (name) DO UPDATE
                  SET holder      = EXCLUDED.holder,
                      acquired_at = NOW(),
                      expires_at  = EXCLUDED.expires_at
                  WHERE leader_locks.expires_at < NOW()
                     OR leader_locks.holder = EXCLUDED.holder
                """,
                name, holder_id, str(int(ttl_seconds)),
            )
        # asyncpg returns 'INSERT 0 N' or 'UPDATE N'. N=1 means we own it.
        try:
            count = int(result.split()[-1])
        except Exception:
            return False
        return count == 1
    except Exception as e:
        print(f"[db] try_lead({name!r}) error: {e}")
        return False


async def release_leader(name: str, holder_id: str) -> None:
    """
    Voluntary release — clears the row if this holder still owns it.
    Idempotent; safe to call from a finally block on graceful shutdown.
    Optional: the TTL handles crashes; this just frees the slot sooner.
    """
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM leader_locks WHERE name=$1 AND holder=$2",
                name, holder_id,
            )
    except Exception as e:
        print(f"[db] release_leader({name!r}) error: {e}")


async def list_leader_locks() -> list[dict]:
    """Snapshot of who holds what — for /env-check style diagnostics."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name, holder, acquired_at, expires_at FROM leader_locks ORDER BY name"
            )
        return [
            {
                "name":        r["name"],
                "holder":      r["holder"],
                "acquired_at": r["acquired_at"].isoformat() if r["acquired_at"] else "",
                "expires_at":  r["expires_at"].isoformat()  if r["expires_at"]  else "",
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] list_leader_locks error: {e}")
        return []
