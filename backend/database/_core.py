"""Connection pool, schema init, and shared low-level helpers for the
database package (JSONB coercion, row serialisation, fire-and-forget).
Split out of the original single-file database.py."""
import os
import json
import asyncio
import datetime as _dt
import decimal as _decimal
import asyncpg
from typing import Optional


_pool: Optional[asyncpg.Pool] = None


def _iso_z(dt) -> str:
    """
    Render a datetime as a JS-parseable ISO-8601 UTC string.

    asyncpg returns TIMESTAMPTZ columns as tz-aware datetimes; calling
    `.isoformat() + "Z"` on those produces `…+00:00Z`, which JavaScript's
    Date constructor rejects as Invalid Date. This helper always returns
    a clean `…T…Z` form regardless of whether the input is tz-aware or
    naive (legacy code paths that produced naive datetimes were assumed
    to already be UTC, so the same tail char is correct).
    """
    if not dt:
        return ""
    if getattr(dt, "tzinfo", None) is None:
        return dt.isoformat() + "Z"
    return dt.astimezone(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _rows_affected(status: str) -> int:
    """Parse asyncpg's command tag ('UPDATE 3' / 'DELETE 1') into a row count."""
    try:
        return int((status or "").split()[-1])
    except (ValueError, IndexError):
        return 0


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
                owner_email  TEXT,
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );
            -- Idempotent for older deployments that already had the table.
            ALTER TABLE stores ADD COLUMN IF NOT EXISTS owner_email TEXT;
            CREATE INDEX IF NOT EXISTS idx_stores_owner_email
                ON stores (lower(owner_email))
                WHERE owner_email IS NOT NULL;

            -- Conversations: full conversation state per session
            CREATE TABLE IF NOT EXISTS conversations (
                session_id   TEXT PRIMARY KEY,
                store_id     TEXT NOT NULL DEFAULT 'default',
                data         JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_conv_store_upd
                ON conversations (store_id, updated_at DESC);
            -- Phase 3 hot-path indexes (no more in-memory cache, every
            -- read hits the DB). See alembic 0004 for the rationale.
            CREATE INDEX IF NOT EXISTS idx_conv_store_customer
                ON conversations (store_id, (data->>'salla_customer_id'), updated_at DESC)
                WHERE data->>'salla_customer_id' IS NOT NULL
                  AND data->>'salla_customer_id' <> '';
            CREATE INDEX IF NOT EXISTS idx_conv_updated_at
                ON conversations (updated_at DESC);

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

            -- ── Support-access grants (super JIT into store dashboards) ──
            -- A super admin can NOT open another store's dashboard unless
            -- the merchant has issued a grant. Grants are time-boxed (≤24h
            -- enforced in code) and revocable.
            --
            -- Read access is just "is there any non-revoked, non-expired
            -- row for this store_id" — a single indexed lookup hot enough
            -- to do on every super request through the auth middleware.
            CREATE TABLE IF NOT EXISTS support_access_grants (
                id            BIGSERIAL PRIMARY KEY,
                store_id      TEXT NOT NULL,
                granted_by    TEXT NOT NULL,     -- "owner" or "emp:<id>"
                granted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at    TIMESTAMPTZ NOT NULL,
                note          TEXT NOT NULL DEFAULT '',
                revoked_at    TIMESTAMPTZ,
                -- Admin-initiated request flow (added later; defaults keep
                -- legacy owner-granted rows = immediately 'active').
                status        TEXT NOT NULL DEFAULT 'active',  -- 'pending'|'active'|'rejected'
                requested_by  TEXT,              -- super-admin id/email for requests
                decided_by    TEXT,              -- who approved/rejected ("owner"|"emp:<id>")
                decided_at    TIMESTAMPTZ
            );
            -- Idempotent column adds for DBs created before the request flow.
            ALTER TABLE support_access_grants ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
            ALTER TABLE support_access_grants ADD COLUMN IF NOT EXISTS requested_by TEXT;
            ALTER TABLE support_access_grants ADD COLUMN IF NOT EXISTS decided_by TEXT;
            ALTER TABLE support_access_grants ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ;
            CREATE INDEX IF NOT EXISTS idx_sag_store_active
                ON support_access_grants (store_id, expires_at DESC)
                WHERE revoked_at IS NULL;
            CREATE INDEX IF NOT EXISTS idx_sag_store_pending
                ON support_access_grants (store_id)
                WHERE status = 'pending';

            -- ── Audit log (sensitive admin actions) ──────────────────────
            -- One row per security-relevant write. Designed for compliance /
            -- post-incident review, not for high-cardinality event tracking.
            -- Keep the payload small (≤ 4 KB) so the table stays cheap to scan.
            --
            -- `actor` is whoever performed the action — usually the bearer
            -- token's subject ("store:<id>", "super:<email>", "emp:<id>").
            -- `target_store` is the store affected (may equal actor's store
            -- for owner-changed-own-settings, or differ for super-admin).
            -- `action` is a stable enum-ish string (set_llm_budget,
            -- replace_ai_key, …) so dashboards can group cheaply.
            CREATE TABLE IF NOT EXISTS audit_log (
                id            BIGSERIAL PRIMARY KEY,
                actor         TEXT NOT NULL,
                target_store  TEXT NOT NULL DEFAULT '',
                action        TEXT NOT NULL,
                details       JSONB NOT NULL DEFAULT '{}'::jsonb,
                ip            TEXT NOT NULL DEFAULT '',
                user_agent    TEXT NOT NULL DEFAULT '',
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_audit_store_ts
                ON audit_log (target_store, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_action_ts
                ON audit_log (action, created_at DESC);

            -- ── LLM token usage (daily counters per store) ─────────────────
            -- Cheap UPSERT on each /chat call so the circuit breaker can read
            -- today's spend in a single indexed lookup. Date is UTC — the
            -- budget resets at 00:00 UTC, not the store's local midnight,
            -- because that's the only time we can compute consistently
            -- across instances without per-store timezone config.
            CREATE TABLE IF NOT EXISTS llm_usage (
                store_id    TEXT NOT NULL,
                usage_date  DATE NOT NULL,
                tokens_in   BIGINT NOT NULL DEFAULT 0,
                tokens_out  BIGINT NOT NULL DEFAULT 0,
                requests    INT    NOT NULL DEFAULT 0,
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (store_id, usage_date)
            );
            CREATE INDEX IF NOT EXISTS idx_llm_usage_recent
                ON llm_usage (store_id, usage_date DESC);

            -- ── Widget outbox (per-session durable queue) ───────────────────
            -- Replaces the in-memory conversations.data["pending_for_widget"]
            -- array. The old design only worked when the widget reconnected
            -- to the SAME web replica that handled the admin reply — across
            -- replicas the queue effectively didn't exist. Persisting per
            -- row makes the SSE flush-on-connect path correct under any
            -- topology (multi-instance web, sticky-less LB, restart).
            CREATE TABLE IF NOT EXISTS widget_outbox (
                id            BIGSERIAL PRIMARY KEY,
                session_id    TEXT NOT NULL,
                payload       JSONB NOT NULL,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                delivered_at  TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS idx_widget_outbox_pending
                ON widget_outbox (session_id, created_at)
                WHERE delivered_at IS NULL;
            CREATE INDEX IF NOT EXISTS idx_widget_outbox_delivered
                ON widget_outbox (delivered_at)
                WHERE delivered_at IS NOT NULL;

            -- ── WhatsApp broadcast campaigns ────────────────────────────────
            CREATE TABLE IF NOT EXISTS wa_campaigns (
                id            BIGSERIAL PRIMARY KEY,
                store_id      TEXT NOT NULL,
                name          TEXT NOT NULL,
                template_name TEXT NOT NULL,
                template_lang TEXT NOT NULL DEFAULT 'ar',
                header_params JSONB NOT NULL DEFAULT '[]',
                body_params   JSONB NOT NULL DEFAULT '[]',
                audience_type TEXT NOT NULL DEFAULT 'chat_users',
                phone_list    JSONB NOT NULL DEFAULT '[]',
                status        TEXT NOT NULL DEFAULT 'draft',
                scheduled_at  TIMESTAMPTZ,
                sent_at       TIMESTAMPTZ,
                total_count   INT NOT NULL DEFAULT 0,
                sent_count    INT NOT NULL DEFAULT 0,
                failed_count  INT NOT NULL DEFAULT 0,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_campaigns_store_ts
                ON wa_campaigns (store_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_campaigns_status
                ON wa_campaigns (status, scheduled_at)
                WHERE status = 'scheduled';

            CREATE TABLE IF NOT EXISTS wa_campaign_recipients (
                id          BIGSERIAL PRIMARY KEY,
                campaign_id BIGINT NOT NULL REFERENCES wa_campaigns(id) ON DELETE CASCADE,
                phone       TEXT NOT NULL,
                name        TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'pending',
                error       TEXT NOT NULL DEFAULT '',
                sent_at     TIMESTAMPTZ,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_camp_recip_campaign
                ON wa_campaign_recipients (campaign_id, status);

            -- ── Contacts (unified CRM from chat + Salla) ────────────────────
            CREATE TABLE IF NOT EXISTS contacts (
                id          BIGSERIAL PRIMARY KEY,
                store_id    TEXT NOT NULL,
                phone       TEXT NOT NULL,
                name        TEXT NOT NULL DEFAULT '',
                email       TEXT NOT NULL DEFAULT '',
                company     TEXT NOT NULL DEFAULT '',
                city        TEXT NOT NULL DEFAULT '',
                country     TEXT NOT NULL DEFAULT '',
                source      TEXT NOT NULL DEFAULT 'chat',  -- 'chat' | 'salla'
                salla_id    TEXT,
                last_seen   TIMESTAMPTZ,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(store_id, phone)
            );
            CREATE INDEX IF NOT EXISTS idx_contacts_store
                ON contacts (store_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_contacts_search
                ON contacts USING gin (to_tsvector('simple',
                    coalesce(name,'') || ' ' || coalesce(phone,'') || ' ' || coalesce(email,'')))
                WHERE store_id IS NOT NULL;

            -- ── Omni-channel broadcasts (free-text bulk send) ───────────────
            -- One row per broadcast. Unlike wa_campaigns (WhatsApp template
            -- only), this fans a free-text message out to every CONNECTED
            -- channel's active users (widget, telegram, messenger, instagram,
            -- email, and WhatsApp within the 24h customer-care window).
            CREATE TABLE IF NOT EXISTS broadcasts (
                id            BIGSERIAL PRIMARY KEY,
                store_id      TEXT NOT NULL,
                message       TEXT NOT NULL,
                channels      JSONB NOT NULL DEFAULT '[]',   -- ['widget','telegram',…]
                status        TEXT NOT NULL DEFAULT 'draft',  -- draft|sending|sent|failed
                total_count   INT NOT NULL DEFAULT 0,
                sent_count    INT NOT NULL DEFAULT 0,
                failed_count  INT NOT NULL DEFAULT 0,
                per_channel   JSONB NOT NULL DEFAULT '{}',    -- {channel:{sent,failed}}
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                sent_at       TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS idx_broadcasts_store_ts
                ON broadcasts (store_id, created_at DESC);

            -- ── Social comments (FB/IG comment automation) — see alembic 0014 ─
            CREATE TABLE IF NOT EXISTS social_comments (
                id                  BIGSERIAL PRIMARY KEY,
                store_id            TEXT NOT NULL,
                platform            TEXT NOT NULL,                 -- facebook|instagram
                object_type         TEXT NOT NULL DEFAULT 'comment',
                external_comment_id TEXT NOT NULL,
                parent_comment_id   TEXT,
                post_id             TEXT,
                recipient_id        TEXT,                          -- page_id (FB) / ig_id (IG)
                author_id           TEXT,
                author_name         TEXT NOT NULL DEFAULT '',
                message             TEXT NOT NULL DEFAULT '',
                permalink           TEXT,
                media_type          TEXT,
                sentiment           TEXT,
                intent              TEXT,
                category            TEXT,
                is_spam             BOOLEAN NOT NULL DEFAULT FALSE,
                lead_score          INT NOT NULL DEFAULT 0,
                lead_temp           TEXT,
                ai_confidence       NUMERIC,
                status              TEXT NOT NULL DEFAULT 'new',
                assigned_to         BIGINT,
                suggested_reply     TEXT,
                final_reply         TEXT,
                replied_by          TEXT,
                replied_at          TIMESTAMPTZ,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_social_comments_dedup
                ON social_comments (store_id, platform, external_comment_id);
            CREATE INDEX IF NOT EXISTS idx_social_comments_store_status
                ON social_comments (store_id, status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_social_comments_store_lead
                ON social_comments (store_id, lead_temp) WHERE lead_temp IS NOT NULL;

            CREATE TABLE IF NOT EXISTS comment_rules (
                id          BIGSERIAL PRIMARY KEY,
                store_id    TEXT NOT NULL,
                priority    INT NOT NULL DEFAULT 100,
                match_type  TEXT NOT NULL DEFAULT 'keyword',
                pattern     TEXT NOT NULL DEFAULT '',
                action      TEXT NOT NULL DEFAULT 'reply_template',
                template    TEXT NOT NULL DEFAULT '',
                enabled     BOOLEAN NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_comment_rules_store
                ON comment_rules (store_id, priority);

            CREATE TABLE IF NOT EXISTS store_entitlements (
                store_id               TEXT PRIMARY KEY,
                comments_enabled       BOOLEAN NOT NULL DEFAULT FALSE,
                comments_monthly_limit INT NOT NULL DEFAULT 0,
                updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # Separate idempotent migrations — run independently so a failure
        # in the main block above doesn't prevent these from running.
        migrations = [
            "ALTER TABLE stores ADD COLUMN IF NOT EXISTS integrations JSONB NOT NULL DEFAULT '{}'::jsonb;",
            # Per-store linking key: the merchant copies it from their 7ayak
            # dashboard into the Salla App Settings form to bind a Salla store
            # to their existing account. See routers/webhooks _handle_app_settings_updated.
            "ALTER TABLE stores ADD COLUMN IF NOT EXISTS api_key TEXT;",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_stores_api_key ON stores (api_key) WHERE api_key IS NOT NULL;",
        ]
        for sql in migrations:
            try:
                await conn.execute(sql)
            except Exception as e:
                print(f"[db] migration warning: {e}")


def available() -> bool:
    """True if the DB pool is up and ready."""
    return _pool is not None


def get_status() -> dict:
    """Return a summary of DB connectivity for /env-check and admin UI."""
    return {
        "connected":     _pool is not None,
        "database_url":  bool(os.getenv("DATABASE_URL", "").strip()),
    }


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


def _json_row(rec, drop: tuple = ()) -> dict:
    """
    Serialise an asyncpg Record into a JSON-safe dict.
      • datetime → ISO-8601 UTC 'Z'; date → ISO date
      • Decimal → float (NUMERIC money columns)
      • bytes/memoryview → SKIPPED (never inline binary in the JSON; the
        actual upload bytes are bundled as files in the ZIP instead)
      • JSONB is already a dict via the codec
    `drop` lists column names to omit entirely (secrets, password hashes).
    """
    out: dict = {}
    for k, v in dict(rec).items():
        if k in drop:
            continue
        if isinstance(v, _dt.datetime):
            v = _iso_z(v)
        elif isinstance(v, _dt.date):
            v = v.isoformat()
        elif isinstance(v, _decimal.Decimal):
            v = float(v)
        elif isinstance(v, (bytes, bytearray, memoryview)):
            continue
        out[k] = v
    return out


def _utcnow():
    """Localised helper so the comparison above stays tz-aware."""
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc)
