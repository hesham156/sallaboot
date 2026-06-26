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
import datetime as _dt
import decimal as _decimal
import secrets
import asyncpg
from typing import Optional

import crypto as _crypto

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
                "created_at": _iso_z(r["created_at"]),
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


async def update_training_enabled(training_id: int, enabled: bool, store_id: str) -> bool:
    """Toggle whether a training entry is included in the prompt.

    Scoped by store_id (finding M-1): the row is only updated when it belongs to
    the calling store, so a tenant can't toggle another tenant's training by
    guessing the global integer id. Returns True only when a row was affected.
    """
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE bot_training SET enabled = $1 WHERE id = $2 AND store_id = $3",
                enabled, int(training_id), store_id,
            )
        # asyncpg returns 'UPDATE <rowcount>'
        return int(result.split()[-1]) > 0
    except Exception as e:
        print(f"[db] update_training_enabled error: {e}")
        return False


async def delete_training(training_id: int, store_id: str) -> tuple[bool, str | None]:
    """Delete a training row. Returns (ok, deleted_file_id).

    Scoped by store_id (finding M-1): only deletes the row when it belongs to the
    calling store, so a tenant can't delete another tenant's training by guessing
    the global integer id. (ok=False, None) when no owned row matched.
    """
    if not _pool:
        return False, None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "DELETE FROM bot_training WHERE id = $1 AND store_id = $2 RETURNING file_id",
                int(training_id), store_id,
            )
        return (row is not None), (row["file_id"] if row else None)
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
                "created_at": _iso_z(r["created_at"]),
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
            "created_at":    _iso_z(row["created_at"]),
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
            "created_at":    _iso_z(row["created_at"]),
        }
    except Exception as e:
        print(f"[db] get_employee_by_email error: {e}")
        return None


async def update_employee(emp_id: int, store_id: str, *, name: str | None = None,
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
    args.append(store_id)
    try:
        async with _pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE employees SET {', '.join(sets)} WHERE id = ${len(args)-1} AND store_id = ${len(args)}",
                *args,
            )
        return result != "UPDATE 0"
    except Exception as e:
        print(f"[db] update_employee error: {e}")
        return False


async def delete_employee(emp_id: int, store_id: str) -> bool:
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM employees WHERE id = $1 AND store_id = $2",
                int(emp_id), store_id,
            )
        return result != "DELETE 0"
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
            {k: (_iso_z(v) if k == "created_at" and v else v) for k, v in dict(r).items()}
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
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
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
    if not _pool or not merchant_id:
        return None
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute("DELETE FROM app_settings WHERE key = $1", key)
    except Exception as e:
        print(f"[db] del_app_setting({key!r}) error: {e}")


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
    if not _pool or not store_id:
        return None
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
        result["errors"].append({"store_id": "*", "error": "DB not connected"})
        return result
    try:
        async with _pool.acquire() as conn:
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
                async with _pool.acquire() as conn:
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


# ── Broadcasts (omni-channel free-text bulk send) ───────────────────────────

async def broadcast_create(store_id: str, message: str, channels: list[str]) -> int | None:
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO broadcasts (store_id, message, channels)
                VALUES ($1, $2, $3::jsonb)
                RETURNING id
                """,
                store_id, message, json.dumps(channels, ensure_ascii=False),
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] broadcast_create error: {e}")
        return None


def _broadcast_row(r) -> dict:
    return {
        "id":           int(r["id"]),
        "store_id":     r["store_id"],
        "message":      r["message"],
        "channels":     _coerce_jsonb(r["channels"]) if not isinstance(r["channels"], list) else r["channels"],
        "status":       r["status"],
        "total_count":  int(r["total_count"] or 0),
        "sent_count":   int(r["sent_count"] or 0),
        "failed_count": int(r["failed_count"] or 0),
        "per_channel":  _coerce_jsonb(r["per_channel"]),
        "created_at":   _iso_z(r["created_at"]),
        "sent_at":      _iso_z(r["sent_at"]) if r["sent_at"] else "",
    }


async def broadcast_get(store_id: str, broadcast_id: int) -> dict | None:
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT * FROM broadcasts WHERE id = $1 AND store_id = $2",
                int(broadcast_id), store_id,
            )
        return _broadcast_row(r) if r else None
    except Exception as e:
        print(f"[db] broadcast_get error: {e}")
        return None


async def broadcast_list(store_id: str, limit: int = 50) -> list[dict]:
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM broadcasts WHERE store_id = $1 "
                "ORDER BY created_at DESC LIMIT $2",
                store_id, int(limit),
            )
        return [_broadcast_row(r) for r in rows]
    except Exception as e:
        print(f"[db] broadcast_list error: {e}")
        return []


async def broadcast_update(broadcast_id: int, *, status: str | None = None,
                           total: int | None = None, sent: int | None = None,
                           failed: int | None = None, per_channel: dict | None = None,
                           sent_at=None) -> None:
    if not _pool:
        return
    sets, args = [], []
    if status is not None:
        sets.append(f"status = ${len(args)+1}"); args.append(status)
    if total is not None:
        sets.append(f"total_count = ${len(args)+1}"); args.append(int(total))
    if sent is not None:
        sets.append(f"sent_count = ${len(args)+1}"); args.append(int(sent))
    if failed is not None:
        sets.append(f"failed_count = ${len(args)+1}"); args.append(int(failed))
    if per_channel is not None:
        sets.append(f"per_channel = ${len(args)+1}::jsonb")
        args.append(json.dumps(per_channel, ensure_ascii=False))
    if sent_at is not None:
        sets.append(f"sent_at = ${len(args)+1}"); args.append(sent_at)
    if not sets:
        return
    args.append(int(broadcast_id))
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                f"UPDATE broadcasts SET {', '.join(sets)} WHERE id = ${len(args)}", *args,
            )
    except Exception as e:
        print(f"[db] broadcast_update error: {e}")


async def broadcast_channel_recipients(store_id: str, channel: str,
                                       within_hours: int | None = None,
                                       limit: int = 5000) -> list[dict]:
    """
    Resolve the recipients of a chat CHANNEL from the conversations table.
    Returns [{recipient, session_id, name}] where `recipient` is the
    channel-native id (phone / chat_id / psid) parsed from the session_id
    (`{wa|tg|msgr|ig}:{store_id}:{recipient}`). For the website widget the
    recipient IS the session_id (used to enqueue into widget_outbox).

    `within_hours` limits to conversations active in that window — required
    for WhatsApp / Messenger / Instagram free-text sends (Meta's 24h
    customer-care window). None = no time limit (telegram / widget).
    """
    if not _pool:
        return []
    args: list = [store_id]
    if channel in ("widget", "web"):
        # Website widget sessions don't carry an explicit channel tag (the
        # external channels do). Identify them as "no external channel" — i.e.
        # channel is NULL or web/widget — and their session_id is the random
        # widget id, used directly as the widget_outbox key.
        where = ["store_id = $1",
                 "(data->>'channel' IS NULL OR data->>'channel' IN ('web','widget'))"]
    else:
        where = ["store_id = $1", "data->>'channel' = $2"]
        args.append(channel)
    if within_hours is not None:
        where.append(f"updated_at >= NOW() - INTERVAL '{int(within_hours)} hours'")
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT session_id, data->>'customer_name' AS name
                FROM conversations
                WHERE {' AND '.join(where)}
                ORDER BY updated_at DESC
                LIMIT ${len(args)+1}
                """,
                *args, int(limit),
            )
        out = []
        for r in rows:
            sid = r["session_id"]
            recipient = sid if channel in ("widget", "web") else sid.rsplit(":", 1)[-1]
            if recipient:
                out.append({"recipient": recipient, "session_id": sid,
                            "name": r["name"] or ""})
        return out
    except Exception as e:
        print(f"[db] broadcast_channel_recipients({channel}) error: {e}")
        return []


async def broadcast_email_recipients(store_id: str, limit: int = 5000) -> list[dict]:
    """Distinct contact emails for the email broadcast channel."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT email, name FROM contacts
                WHERE store_id = $1 AND email <> ''
                ORDER BY email
                LIMIT $2
                """,
                store_id, int(limit),
            )
        return [{"recipient": r["email"], "name": r["name"] or ""} for r in rows]
    except Exception as e:
        print(f"[db] broadcast_email_recipients error: {e}")
        return []


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
    if not _pool:
        return
    encrypted_blob = _crypto.encrypt_store_blob(tokens)
    email_arg = (owner_email or "").strip().lower() or None
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
        return False
    e = (email or "").strip().lower() or None
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
        return None
    e = (email or "").strip().lower()
    if not e:
        return None
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
        return None
    sid = (store_id or "").strip()
    if not sid:
        return None
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
        return None
    e = (email or "").strip().lower()
    if not e:
        return None
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
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
    if not _pool:
        return {}

    export: dict = {}
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
        return
    async with _pool.acquire() as conn:
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
    if not _pool:
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
        async with _pool.acquire() as conn:
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

async def save_abandoned_cart(store_id: str, cart_id: str, cart_data: dict) -> bool:
    """
    Insert a new abandoned cart notification (ignore duplicate cart_ids).
    Returns True only when a NEW row was inserted — callers use this to avoid
    re-notifying (email/WhatsApp) the same cart on every poll/retry.
    """
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            r = await conn.execute(
                """
                INSERT INTO abandoned_carts (store_id, cart_id, cart_data)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (store_id, cart_id) DO NOTHING
                """,
                store_id,
                cart_id,
                json.dumps(cart_data, ensure_ascii=False, default=str),
            )
        # asyncpg returns 'INSERT 0 1' on insert, 'INSERT 0 0' on conflict.
        return bool(r) and r.split()[-1] == "1"
    except Exception as e:
        print(f"[db] save_abandoned_cart({cart_id!r}) error: {e}")
        return False


async def list_stores_with_integration(platform: str) -> list:
    """
    Return [(store_id, integration_cfg_dict), …] for every store that has the
    given platform connected. Used by the abandoned-cart poller (and any other
    per-platform background sweep) to enumerate live integrations.
    """
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT store_id, integrations->$1 AS cfg FROM stores WHERE integrations ? $1",
                platform,
            )
        out = []
        for row in rows:
            cfg = row["cfg"]
            if isinstance(cfg, str):
                try:
                    cfg = json.loads(cfg)
                except Exception:
                    cfg = {}
            out.append((row["store_id"], cfg or {}))
        return out
    except Exception as e:
        print(f"[db] list_stores_with_integration({platform!r}) error: {e}")
        return []


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
            _dedup = dedup_key.strip() if dedup_key else ""
            if _dedup:
                # Has a dedup key — use ON CONFLICT to skip duplicates.
                row = await conn.fetchrow(
                    """
                    INSERT INTO webhook_inbox
                        (source, event_type, dedup_key, store_id, payload, meta)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
                    ON CONFLICT (source, dedup_key) WHERE dedup_key IS NOT NULL
                    DO NOTHING
                    RETURNING id
                    """,
                    source, event_type or "", _dedup,
                    store_id or "",
                    json.dumps(payload, ensure_ascii=False, default=str),
                    json.dumps(meta or {}, ensure_ascii=False, default=str),
                )
            else:
                # No dedup key — always insert (no conflict possible on NULL).
                row = await conn.fetchrow(
                    """
                    INSERT INTO webhook_inbox
                        (source, event_type, dedup_key, store_id, payload, meta)
                    VALUES ($1, $2, NULL, $3, $4::jsonb, $5::jsonb)
                    RETURNING id
                    """,
                    source, event_type or "",
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
# Widget outbox — per-session durable queue for messages destined to the
# widget (admin replies, post-chat bot follow-ups, CSAT prompts).
#
# Why this is its own table and not just `outbox`:
#   • Routing is by session_id, not by `kind`. The generic outbox is
#     drained by a worker; this queue is consumed inline by the per-
#     session SSE generator on flush-on-connect.
#   • No retry/backoff/DLQ — delivery is SSE, the only failure mode is
#     "client disconnected", and the next reconnect replays the same
#     pending rows.
#   • Different cleanup policy — delivered rows are pruned after 24h
#     instead of the outbox's 7 days.
# ─────────────────────────────────────────────────────────────────────────────

async def widget_outbox_enqueue(session_id: str, payload: dict) -> int | None:
    """
    Append one message for this session to the widget queue. Returns the
    new row id, or None if DB is unavailable (caller treats None as
    best-effort — the realtime NOTIFY will still fire for live SSE
    clients; only the catch-up-on-reconnect path is degraded).
    """
    if not _pool or not session_id:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO widget_outbox (session_id, payload)
                VALUES ($1, $2::jsonb)
                RETURNING id
                """,
                session_id,
                json.dumps(payload or {}, ensure_ascii=False, default=str),
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] widget_outbox_enqueue({session_id!r}) error: {e}")
        return None


async def widget_outbox_claim_pending(session_id: str, limit: int = 100) -> list[dict]:
    """
    Atomic claim-and-mark for the widget's flush-on-connect path. Picks
    up to `limit` undelivered rows for this session (oldest first), marks
    them delivered in the same transaction, and returns the payloads.

    `FOR UPDATE SKIP LOCKED` means two concurrent reconnects of the
    same session_id don't both deliver the same message — the second
    one gets nothing (correct: it's the same logical client).

    Trade-off: marking delivered BEFORE the SSE yield means a connection
    drop between this query and the actual yield loses those messages.
    The alternative (mark AFTER yield) double-delivers on reconnect. We
    accept the loss because:
      • The realtime NOTIFY fired at the time of the original write —
        a connected widget already saw the message live.
      • For a disconnected widget catching up, missing one message in
        the catch-up window is less disruptive than a duplicate.
      • Widget reconnects are rare enough that this is a noise-level
        edge case, not a steady-state property.
    """
    if not _pool or not session_id:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH cte AS (
                    SELECT id
                    FROM widget_outbox
                    WHERE session_id = $1 AND delivered_at IS NULL
                    ORDER BY created_at
                    LIMIT $2
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE widget_outbox w
                   SET delivered_at = NOW()
                  FROM cte
                 WHERE w.id = cte.id
              RETURNING w.id, w.payload
                """,
                session_id, limit,
            )
        return [_coerce_jsonb(r["payload"]) for r in rows]
    except Exception as e:
        print(f"[db] widget_outbox_claim_pending({session_id!r}) error: {e}")
        return []


async def widget_outbox_pending_count(session_id: str) -> int:
    """Diagnostic: how many undelivered rows are sitting for this session."""
    if not _pool or not session_id:
        return 0
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM widget_outbox "
                "WHERE session_id = $1 AND delivered_at IS NULL",
                session_id,
            )
        return int(row["n"]) if row else 0
    except Exception as e:
        print(f"[db] widget_outbox_pending_count error: {e}")
        return 0


async def prune_widget_outbox_delivered(keep_last_hours: int = 24) -> int:
    """
    Drop widget_outbox rows whose delivered_at is older than N hours.
    Pending rows (delivered_at IS NULL) are NEVER pruned — they would
    represent un-delivered messages and must survive until consumed.
    """
    if not _pool:
        return 0
    try:
        async with _pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM widget_outbox "
                "WHERE delivered_at IS NOT NULL "
                "  AND delivered_at < NOW() - ($1 || ' hours')::interval",
                str(int(keep_last_hours)),
            )
        try:
            return int(result.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_widget_outbox_delivered error: {e}")
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


# ── LLM token usage (daily circuit breaker) ─────────────────────────────────
# Three calls, all cheap:
#   • llm_usage_today(store_id)       — single-row indexed read; 0 if no row yet
#   • llm_usage_record(store_id, ti, to) — UPSERT on (store_id, today)
#   • llm_usage_report(store_id, days)  — 7- or 30-day chart for the admin UI
#
# The check happens BEFORE the LLM call and the record happens AFTER, so a
# burst of N concurrent /chat requests can race past the limit by up to N
# requests' worth of tokens. That's acceptable: the budget is a soft target
# anyway (real abuse comes from sustained traffic, not a 0.5s burst).

async def llm_usage_today(store_id: str) -> dict:
    """
    Tokens + request count consumed by `store_id` today (UTC).
    Returns zeros when the DB is down so the breaker fails open — refusing
    every chat because Postgres hiccupped would be worse than the abuse risk.
    """
    if not _pool:
        return {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "requests": 0}
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT tokens_in, tokens_out, requests
                  FROM llm_usage
                 WHERE store_id = $1 AND usage_date = (NOW() AT TIME ZONE 'UTC')::date
                """,
                store_id,
            )
        if not row:
            return {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "requests": 0}
        ti = int(row["tokens_in"])
        to = int(row["tokens_out"])
        return {
            "tokens_in":    ti,
            "tokens_out":   to,
            "tokens_total": ti + to,
            "requests":     int(row["requests"]),
        }
    except Exception as e:
        print(f"[db] llm_usage_today({store_id!r}) error: {e}")
        return {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "requests": 0}


async def llm_usage_record(store_id: str, tokens_in: int, tokens_out: int) -> dict:
    """
    UPSERT today's usage row and return the totals before/after the
    increment. Callers use the delta to check whether this request just
    crossed a budget threshold (80/90/100%) so they can fire an alert
    exactly once per crossing instead of on every subsequent request.

    Never raises — a failure here would lose a counter increment but
    should never block the user-facing reply that already succeeded.
    Returns zeros + delta=(ti+to) on failure so the caller's threshold
    math still works in the degraded path.
    """
    ti = max(0, int(tokens_in or 0))
    to = max(0, int(tokens_out or 0))
    if not _pool or not store_id:
        return {"before": 0, "after": ti + to, "delta": ti + to}
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO llm_usage (store_id, usage_date, tokens_in, tokens_out, requests, updated_at)
                VALUES ($1, (NOW() AT TIME ZONE 'UTC')::date, $2, $3, 1, NOW())
                ON CONFLICT (store_id, usage_date) DO UPDATE
                   SET tokens_in  = llm_usage.tokens_in  + EXCLUDED.tokens_in,
                       tokens_out = llm_usage.tokens_out + EXCLUDED.tokens_out,
                       requests   = llm_usage.requests   + 1,
                       updated_at = NOW()
                RETURNING (llm_usage.tokens_in + llm_usage.tokens_out) AS after_total
                """,
                store_id, ti, to,
            )
        after = int(row["after_total"]) if row else (ti + to)
        return {"before": after - (ti + to), "after": after, "delta": ti + to}
    except Exception as e:
        print(f"[db] llm_usage_record({store_id!r}) error: {e}")
        return {"before": 0, "after": ti + to, "delta": ti + to}


async def llm_usage_report(store_id: str, days: int = 7) -> list[dict]:
    """
    Last N days of usage for the admin dashboard, newest first. Includes
    zero-rows for missing days so the frontend can render a continuous bar
    chart without gap-filling logic.
    """
    if not _pool:
        return []
    days = max(1, min(int(days or 7), 90))
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH dates AS (
                    SELECT generate_series(
                        (NOW() AT TIME ZONE 'UTC')::date - ($1::int - 1),
                        (NOW() AT TIME ZONE 'UTC')::date,
                        '1 day'::interval
                    )::date AS d
                )
                SELECT d.d AS usage_date,
                       COALESCE(u.tokens_in,  0) AS tokens_in,
                       COALESCE(u.tokens_out, 0) AS tokens_out,
                       COALESCE(u.requests,   0) AS requests
                  FROM dates d
                  LEFT JOIN llm_usage u
                    ON u.store_id   = $2
                   AND u.usage_date = d.d
                 ORDER BY d.d DESC
                """,
                days, store_id,
            )
        return [
            {
                "date":         r["usage_date"].isoformat(),
                "tokens_in":    int(r["tokens_in"]),
                "tokens_out":   int(r["tokens_out"]),
                "tokens_total": int(r["tokens_in"]) + int(r["tokens_out"]),
                "requests":     int(r["requests"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] llm_usage_report({store_id!r}) error: {e}")
        return []


# ── Platform Operations aggregates (super-admin dashboard) ───────────────
# Surface read-only operational metrics so the platform owner can see the
# health of every store + queue at a glance. No customer data, no
# secrets — just counters, error counts, and top-N error lists.
#
# All queries are scoped to "today" (UTC) where time-based, so a single
# refresh of the dashboard shows current-day activity. Functions tolerate
# DB unavailability by returning empty/zero so the page still renders the
# operational layout instead of failing.

async def llm_tokens_today_all_stores() -> dict:
    """Platform-wide LLM totals + per-store breakdown for today."""
    if not _pool:
        return {"total_tokens": 0, "total_requests": 0, "per_store": []}
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT store_id,
                       (tokens_in + tokens_out) AS tokens_total,
                       tokens_in, tokens_out, requests
                  FROM llm_usage
                 WHERE usage_date = (NOW() AT TIME ZONE 'UTC')::date
                 ORDER BY (tokens_in + tokens_out) DESC
                """,
            )
        total_tok = sum(int(r["tokens_total"]) for r in rows)
        total_req = sum(int(r["requests"])     for r in rows)
        return {
            "total_tokens":   total_tok,
            "total_requests": total_req,
            "per_store": [
                {
                    "store_id":     r["store_id"],
                    "tokens_total": int(r["tokens_total"]),
                    "tokens_in":    int(r["tokens_in"]),
                    "tokens_out":   int(r["tokens_out"]),
                    "requests":     int(r["requests"]),
                }
                for r in rows
            ],
        }
    except Exception as e:
        print(f"[db] llm_tokens_today_all_stores error: {e}")
        return {"total_tokens": 0, "total_requests": 0, "per_store": []}


async def conversations_active_today() -> dict:
    """
    Active conversations + estimated message count today.

    "Active" = conversation row touched today (updated_at::date == today).
    "Messages today" is an approximation — we count rows where the
    last_activity in the JSONB blob falls on today. Accurate per-message
    timestamps would need a normalised messages table; we don't have one
    yet and adding it for a dashboard counter would be over-engineering.
    """
    if not _pool:
        return {"active_sessions": 0, "messages_today_estimate": 0}
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS active_sessions,
                    COALESCE(SUM(jsonb_array_length(data->'messages')), 0) AS msg_sum
                  FROM conversations
                 WHERE updated_at::date = (NOW() AT TIME ZONE 'UTC')::date
                """,
            )
        return {
            "active_sessions":         int(row["active_sessions"]) if row else 0,
            "messages_today_estimate": int(row["msg_sum"])         if row else 0,
        }
    except Exception as e:
        print(f"[db] conversations_active_today error: {e}")
        return {"active_sessions": 0, "messages_today_estimate": 0}


async def webhook_error_counts(window_hours: int = 24) -> dict:
    """
    Webhook errors in the last `window_hours`. Two slices: total count
    and a per-store top-N. Status 'rejected' covers signature failures.
    """
    if not _pool:
        return {"errors_24h": 0, "signature_failures_24h": 0, "top_stores": []}
    window_hours = max(1, min(int(window_hours or 24), 168))  # 1h–1w
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT
                    SUM(CASE WHEN status IN ('error', 'rejected') THEN 1 ELSE 0 END)::int AS errors,
                    SUM(CASE WHEN sig_status LIKE 'signature_%' AND status='rejected' THEN 1 ELSE 0 END)::int AS sig_fails
                  FROM webhook_log
                 WHERE created_at >= NOW() - INTERVAL '{window_hours} hours'
                """,
            )
            top = await conn.fetch(
                f"""
                SELECT store_id, COUNT(*) AS n
                  FROM webhook_log
                 WHERE status IN ('error', 'rejected')
                   AND created_at >= NOW() - INTERVAL '{window_hours} hours'
                   AND store_id <> ''
                 GROUP BY store_id
                 ORDER BY n DESC
                 LIMIT 5
                """,
            )
        return {
            "errors_24h":             int(row["errors"]    or 0) if row else 0,
            "signature_failures_24h": int(row["sig_fails"] or 0) if row else 0,
            "top_stores": [
                {"store_id": r["store_id"], "errors": int(r["n"])}
                for r in top
            ],
        }
    except Exception as e:
        print(f"[db] webhook_error_counts error: {e}")
        return {"errors_24h": 0, "signature_failures_24h": 0, "top_stores": []}


async def outbox_dead_top_stores(limit: int = 5) -> list[dict]:
    """Stores whose outbox has dead rows — they need operator attention."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT store_id, COUNT(*) AS n
                  FROM outbox
                 WHERE status = 'dead'
                   AND store_id IS NOT NULL AND store_id <> ''
                 GROUP BY store_id
                 ORDER BY n DESC
                 LIMIT $1
                """,
                int(limit),
            )
        return [{"store_id": r["store_id"], "dead": int(r["n"])} for r in rows]
    except Exception as e:
        print(f"[db] outbox_dead_top_stores error: {e}")
        return []


async def login_failures_24h() -> int:
    """Count failed login attempts in the last 24h (for the security card)."""
    if not _pool:
        return 0
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS n
                  FROM login_attempts
                 WHERE created_at >= NOW() - INTERVAL '24 hours'
                """,
            )
        return int(row["n"]) if row else 0
    except Exception as e:
        print(f"[db] login_failures_24h error: {e}")
        return 0


# ── Audit log (sensitive admin actions) ──────────────────────────────────
# Tiny API: write once per action, read for the audit viewer. Reads are
# paginated by created_at (newest first). Writes NEVER raise — losing an
# audit entry is better than failing the user's actual action because of
# a logging issue, but a missing entry is still loud in the server logs.

async def audit_record(
    actor: str,
    action: str,
    *,
    target_store: str = "",
    details: dict | None = None,
    ip: str = "",
    user_agent: str = "",
) -> None:
    """Insert one audit row. Trim user_agent to 500 chars to keep the row small."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (actor, target_store, action, details, ip, user_agent)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                """,
                str(actor or "")[:200],
                str(target_store or "")[:200],
                str(action or "")[:100],
                json.dumps(details or {}, ensure_ascii=False, default=str),
                str(ip or "")[:64],
                str(user_agent or "")[:500],
            )
    except Exception as e:
        print(f"[db] audit_record({action!r}) error: {e}")


async def audit_list(
    *,
    store_id: str | None = None,
    action: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """
    Newest-first list of audit rows. `store_id=None` returns all stores
    (super-admin view); a store_id scopes to that store's own activity.
    `action` filter is exact-match on the action enum string.
    """
    if not _pool:
        return []
    limit  = max(1, min(int(limit  or 200), 1000))
    offset = max(0, int(offset or 0))
    where: list[str] = []
    params: list = []
    if store_id is not None:
        where.append(f"target_store = ${len(params) + 1}")
        params.append(store_id)
    if action:
        where.append(f"action = ${len(params) + 1}")
        params.append(action)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.extend([limit, offset])

    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, actor, target_store, action, details, ip, user_agent, created_at
                  FROM audit_log
                  {where_sql}
                 ORDER BY created_at DESC
                 LIMIT ${len(params) - 1}
                 OFFSET ${len(params)}
                """,
                *params,
            )
        return [
            {
                "id":           int(r["id"]),
                "actor":        r["actor"],
                "target_store": r["target_store"],
                "action":       r["action"],
                "details":      _coerce_jsonb(r["details"]),
                "ip":           r["ip"],
                "user_agent":   r["user_agent"],
                "created_at":   _iso_z(r["created_at"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] audit_list error: {e}")
        return []


# ── Support-access grants (JIT super access into a merchant's store) ────
#
# Tiny API. The auth middleware checks `support_access_active(store_id)`
# on every super-cross-store request, so the read is on the hot path.
# It's a single-row indexed lookup that returns the soonest expiring
# row for the store; cheap even at scale.

# Hard ceiling for grant duration. The owner picks (15m / 1h / 4h / 24h)
# from the UI but a malicious /direct POST shouldn't be able to set
# 365 days.
_MAX_GRANT_DURATION_MINUTES = 24 * 60


async def support_access_create(
    store_id: str,
    *,
    granted_by: str,
    duration_minutes: int,
    note: str = "",
) -> dict | None:
    """
    Create a new grant. Returns the new row dict, or None on failure /
    DB-down. duration_minutes is clamped to [1, _MAX_GRANT_DURATION_MINUTES].
    """
    if not _pool or not store_id:
        return None
    dur = max(1, min(int(duration_minutes or 60), _MAX_GRANT_DURATION_MINUTES))
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO support_access_grants
                    (store_id, granted_by, expires_at, note)
                VALUES ($1, $2, NOW() + ($3 || ' minutes')::interval, $4)
                RETURNING id, store_id, granted_by, granted_at, expires_at, note
                """,
                store_id, granted_by, str(dur), (note or "")[:500],
            )
        if not row:
            return None
        return {
            "id":           int(row["id"]),
            "store_id":     row["store_id"],
            "granted_by":   row["granted_by"],
            "granted_at":   _iso_z(row["granted_at"]),
            "expires_at":   _iso_z(row["expires_at"]),
            "note":         row["note"] or "",
            "revoked_at":   None,
        }
    except Exception as e:
        print(f"[db] support_access_create error: {e}")
        return None


async def support_access_revoke(grant_id: int, store_id: str) -> bool:
    """
    Revoke a grant. Scoped to store_id so an owner can't revoke another
    store's grant by guessing ids. Returns True on success.
    """
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE support_access_grants
                   SET revoked_at = NOW()
                 WHERE id = $1 AND store_id = $2 AND revoked_at IS NULL
                """,
                int(grant_id), store_id,
            )
        # asyncpg returns 'UPDATE <rowcount>'
        try:
            return int(result.split()[-1]) > 0
        except Exception:
            return False
    except Exception as e:
        print(f"[db] support_access_revoke error: {e}")
        return False


async def support_access_active(store_id: str) -> dict | None:
    """
    Hot path: is there an active grant for this store? Returns the
    earliest-expiring active grant (so the UI can show the right
    countdown), or None.
    """
    if not _pool or not store_id:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, store_id, granted_by, granted_at, expires_at, note
                  FROM support_access_grants
                 WHERE store_id   = $1
                   AND status     = 'active'
                   AND revoked_at IS NULL
                   AND expires_at > NOW()
                 ORDER BY expires_at ASC
                 LIMIT 1
                """,
                store_id,
            )
        if not row:
            return None
        return {
            "id":           int(row["id"]),
            "store_id":     row["store_id"],
            "granted_by":   row["granted_by"],
            "granted_at":   _iso_z(row["granted_at"]),
            "expires_at":   _iso_z(row["expires_at"]),
            "note":         row["note"] or "",
            "revoked_at":   None,
        }
    except Exception as e:
        print(f"[db] support_access_active error: {e}")
        return None


async def support_access_list(store_id: str, *, limit: int = 50) -> list[dict]:
    """
    All grants for a store, newest first. Owner UI uses it to show
    history (so the merchant sees who they granted to, when, and whether
    it was used). Includes revoked + expired rows so the trail is
    complete.
    """
    if not _pool:
        return []
    limit = max(1, min(int(limit or 50), 200))
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, store_id, granted_by, granted_at, expires_at, note,
                       revoked_at, status, requested_by, decided_by, decided_at
                  FROM support_access_grants
                 WHERE store_id = $1
                 ORDER BY granted_at DESC
                 LIMIT $2
                """,
                store_id, limit,
            )
        out = []
        for r in rows:
            now_active = (
                r["status"] == "active"
                and r["revoked_at"] is None
                and r["expires_at"] > _utcnow()
            )
            out.append({
                "id":           int(r["id"]),
                "store_id":     r["store_id"],
                "granted_by":   r["granted_by"],
                "granted_at":   _iso_z(r["granted_at"]),
                "expires_at":   _iso_z(r["expires_at"]),
                "note":         r["note"] or "",
                "revoked_at":   _iso_z(r["revoked_at"]) or None,
                "active":       now_active,
                "status":       r["status"],
                "requested_by": r["requested_by"],
                "decided_by":   r["decided_by"],
                "decided_at":   _iso_z(r["decided_at"]) or None,
            })
        return out
    except Exception as e:
        print(f"[db] support_access_list error: {e}")
        return []


def _sag_row(row) -> dict:
    """Shape a support_access_grants row into the API dict."""
    now_active = (
        row["status"] == "active"
        and row["revoked_at"] is None
        and row["expires_at"] > _utcnow()
    )
    return {
        "id":           int(row["id"]),
        "store_id":     row["store_id"],
        "granted_by":   row["granted_by"],
        "granted_at":   _iso_z(row["granted_at"]),
        "expires_at":   _iso_z(row["expires_at"]),
        "note":         row["note"] or "",
        "revoked_at":   _iso_z(row["revoked_at"]) or None,
        "active":       now_active,
        "status":       row["status"],
        "requested_by": row["requested_by"],
        "decided_by":   row["decided_by"],
        "decided_at":   _iso_z(row["decided_at"]) or None,
    }


async def support_access_request(
    store_id: str, *, requested_by: str, note: str = "",
) -> dict | None:
    """
    Create a PENDING access request (admin-initiated). It grants NO access
    until an owner/manager approves — `expires_at` is set in the past and
    `status='pending'` so support_access_active() never returns it.
    """
    if not _pool or not store_id:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO support_access_grants
                    (store_id, granted_by, expires_at, note, status, requested_by)
                VALUES ($1, '', NOW(), $2, 'pending', $3)
                RETURNING id, store_id, granted_by, granted_at, expires_at, note,
                          revoked_at, status, requested_by, decided_by, decided_at
                """,
                store_id, (note or "")[:500], (requested_by or "")[:200],
            )
        return _sag_row(row) if row else None
    except Exception as e:
        print(f"[db] support_access_request error: {e}")
        return None


async def support_access_pending(store_id: str) -> list[dict]:
    """Open (pending) access requests for a store — for the owner to act on."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, store_id, granted_by, granted_at, expires_at, note,
                       revoked_at, status, requested_by, decided_by, decided_at
                  FROM support_access_grants
                 WHERE store_id = $1 AND status = 'pending'
                 ORDER BY granted_at DESC
                """,
                store_id,
            )
        return [_sag_row(r) for r in rows]
    except Exception as e:
        print(f"[db] support_access_pending error: {e}")
        return []


async def support_access_approve(
    grant_id: int, store_id: str, *, decided_by: str, duration_minutes: int,
) -> dict | None:
    """
    Approve a pending request → active grant. The owner chooses the
    duration; the window starts NOW. Scoped to store_id + status='pending'
    so a stale/foreign id can't be approved. Returns the row or None.
    """
    if not _pool:
        return None
    dur = max(1, min(int(duration_minutes or 60), _MAX_GRANT_DURATION_MINUTES))
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE support_access_grants
                   SET status      = 'active',
                       granted_at  = NOW(),
                       expires_at  = NOW() + ($3 || ' minutes')::interval,
                       decided_by  = $4,
                       decided_at  = NOW()
                 WHERE id = $1 AND store_id = $2 AND status = 'pending'
                RETURNING id, store_id, granted_by, granted_at, expires_at, note,
                          revoked_at, status, requested_by, decided_by, decided_at
                """,
                int(grant_id), store_id, str(dur), (decided_by or "")[:200],
            )
        return _sag_row(row) if row else None
    except Exception as e:
        print(f"[db] support_access_approve error: {e}")
        return None


async def support_access_reject(
    grant_id: int, store_id: str, *, decided_by: str,
) -> bool:
    """Reject a pending request. Returns True if a pending row was updated."""
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE support_access_grants
                   SET status     = 'rejected',
                       revoked_at = NOW(),
                       decided_by = $3,
                       decided_at = NOW()
                 WHERE id = $1 AND store_id = $2 AND status = 'pending'
                """,
                int(grant_id), store_id, (decided_by or "")[:200],
            )
        try:
            return int(result.split()[-1]) > 0
        except Exception:
            return False
    except Exception as e:
        print(f"[db] support_access_reject error: {e}")
        return False


def _utcnow():
    """Localised helper so the comparison above stays tz-aware."""
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc)


# ── WhatsApp Templates ────────────────────────────────────────────────────────

async def wa_template_save(store_id: str, tpl: dict) -> dict:
    """Upsert a template definition. Returns the saved row."""
    if not _pool:
        return {}
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO whatsapp_templates
                    (store_id, name, language, category,
                     header_type, header_text, body_text, footer_text,
                     buttons, variables, status, notes, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,$12,NOW())
                ON CONFLICT (store_id, name) DO UPDATE SET
                    language    = EXCLUDED.language,
                    category    = EXCLUDED.category,
                    header_type = EXCLUDED.header_type,
                    header_text = EXCLUDED.header_text,
                    body_text   = EXCLUDED.body_text,
                    footer_text = EXCLUDED.footer_text,
                    buttons     = EXCLUDED.buttons,
                    variables   = EXCLUDED.variables,
                    status      = EXCLUDED.status,
                    notes       = EXCLUDED.notes,
                    updated_at  = NOW()
                RETURNING id, created_at, updated_at
                """,
                store_id,
                tpl["name"],
                tpl.get("language", "ar"),
                tpl.get("category", "MARKETING"),
                tpl.get("header_type") or None,
                tpl.get("header_text") or None,
                tpl.get("body_text", ""),
                tpl.get("footer_text") or None,
                json.dumps(tpl.get("buttons", []), ensure_ascii=False),
                json.dumps(tpl.get("variables", []), ensure_ascii=False),
                tpl.get("status", "approved"),
                tpl.get("notes") or None,
            )
        return {"id": int(row["id"]), **tpl}
    except Exception as e:
        print(f"[db] wa_template_save error: {e}")
        return {}


async def wa_template_list(store_id: str) -> list[dict]:
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM whatsapp_templates
                   WHERE store_id=$1 ORDER BY created_at DESC""",
                store_id,
            )
        result = []
        for r in rows:
            result.append({
                "id":          int(r["id"]),
                "name":        r["name"],
                "language":    r["language"],
                "category":    r["category"],
                "header_type": r["header_type"] or "",
                "header_text": r["header_text"] or "",
                "body_text":   r["body_text"],
                "footer_text": r["footer_text"] or "",
                "buttons":     r["buttons"] or [],
                "variables":   r["variables"] or [],
                "status":      r["status"],
                "notes":       r["notes"] or "",
                "created_at":  _iso_z(r["created_at"]),
                "updated_at":  _iso_z(r["updated_at"]),
            })
        return result
    except Exception as e:
        print(f"[db] wa_template_list error: {e}")
        return []


async def wa_template_delete(store_id: str, name: str) -> bool:
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            r = await conn.execute(
                "DELETE FROM whatsapp_templates WHERE store_id=$1 AND name=$2",
                store_id, name,
            )
        return r == "DELETE 1"
    except Exception as e:
        print(f"[db] wa_template_delete error: {e}")
        return False


# ── Customer Segments ─────────────────────────────────────────────────────────

async def seg_upsert(store_id: str, customer_id: str, data: dict) -> dict | None:
    """Insert or update a customer segment row. Returns the saved row."""
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO customer_segments
                    (store_id, customer_id, customer_name, phone, email,
                     segment, segment_reason, last_order_id, last_order_at,
                     last_conv_id, last_conv_at, next_followup_at, notes, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW())
                ON CONFLICT (store_id, customer_id) DO UPDATE SET
                    customer_name    = COALESCE(NULLIF(EXCLUDED.customer_name,''), customer_segments.customer_name),
                    phone            = COALESCE(NULLIF(EXCLUDED.phone,''),         customer_segments.phone),
                    email            = COALESCE(NULLIF(EXCLUDED.email,''),         customer_segments.email),
                    segment          = EXCLUDED.segment,
                    segment_reason   = EXCLUDED.segment_reason,
                    last_order_id    = COALESCE(EXCLUDED.last_order_id,   customer_segments.last_order_id),
                    last_order_at    = COALESCE(EXCLUDED.last_order_at,   customer_segments.last_order_at),
                    last_conv_id     = COALESCE(EXCLUDED.last_conv_id,    customer_segments.last_conv_id),
                    last_conv_at     = COALESCE(EXCLUDED.last_conv_at,    customer_segments.last_conv_at),
                    next_followup_at = EXCLUDED.next_followup_at,
                    notes            = COALESCE(NULLIF(EXCLUDED.notes,''), customer_segments.notes),
                    updated_at       = NOW()
                RETURNING *
            """,
            store_id, customer_id,
            data.get("customer_name", ""), data.get("phone", ""), data.get("email", ""),
            data.get("segment", "new"), data.get("segment_reason", ""),
            data.get("last_order_id"), data.get("last_order_at"),
            data.get("last_conv_id"), data.get("last_conv_at"),
            data.get("next_followup_at"), data.get("notes", ""))
            return dict(row) if row else None
    except Exception as e:
        print(f"[db] seg_upsert error: {e}")
        return None


async def seg_list(store_id: str, segment: str | None = None,
                   limit: int = 100, offset: int = 0) -> list[dict]:
    """List customer segments for a store, optionally filtered by segment type."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            if segment:
                rows = await conn.fetch("""
                    SELECT * FROM customer_segments
                    WHERE store_id=$1 AND segment=$2
                    ORDER BY updated_at DESC LIMIT $3 OFFSET $4
                """, store_id, segment, limit, offset)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM customer_segments
                    WHERE store_id=$1
                    ORDER BY updated_at DESC LIMIT $2 OFFSET $3
                """, store_id, limit, offset)
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] seg_list error: {e}")
        return []


async def seg_count_by_type(store_id: str) -> dict:
    """Return {segment: count} for all segments in a store."""
    if not _pool:
        return {}
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT segment, COUNT(*) as cnt
                FROM customer_segments WHERE store_id=$1
                GROUP BY segment
            """, store_id)
            return {r["segment"]: int(r["cnt"]) for r in rows}
    except Exception as e:
        print(f"[db] seg_count_by_type error: {e}")
        return {}


async def seg_get_due_followups(store_id: str, limit: int = 50) -> list[dict]:
    """Return customers whose next_followup_at <= now and not paused."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM customer_segments
                WHERE store_id=$1
                  AND next_followup_at <= NOW()
                  AND followup_paused = FALSE
                  AND phone <> ''
                ORDER BY next_followup_at ASC
                LIMIT $2
            """, store_id, limit)
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] seg_get_due_followups error: {e}")
        return []


async def seg_mark_followup_sent(store_id: str, customer_id: str,
                                 next_followup_at=None) -> None:
    """Increment followup_count and set last/next followup timestamps."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute("""
                UPDATE customer_segments
                SET followup_count   = followup_count + 1,
                    last_followup_at = NOW(),
                    next_followup_at = $3,
                    updated_at       = NOW()
                WHERE store_id=$1 AND customer_id=$2
            """, store_id, customer_id, next_followup_at)
    except Exception as e:
        print(f"[db] seg_mark_followup_sent error: {e}")


async def seg_pause(store_id: str, customer_id: str, paused: bool) -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute("""
                UPDATE customer_segments
                SET followup_paused=$3, updated_at=NOW()
                WHERE store_id=$1 AND customer_id=$2
            """, store_id, customer_id, paused)
    except Exception as e:
        print(f"[db] seg_pause error: {e}")


async def seg_get_all_stores_due() -> list[dict]:
    """Return all customers across all stores with due follow-ups."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM customer_segments
                WHERE next_followup_at <= NOW()
                  AND followup_paused = FALSE
                  AND phone <> ''
                ORDER BY next_followup_at ASC
                LIMIT 200
            """)
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] seg_get_all_stores_due error: {e}")
        return []


# ── Blog posts ──────────────────────────────────────────────────────────────
# Dashboard-managed SEO articles. Public reads filter on published=TRUE and
# order by published_at DESC. Super-admin writes go through the /admin/blog
# endpoints — we trust the caller to have been authenticated by middleware.

async def blog_list_public() -> list[dict]:
    """Newest published posts first — what BlogList renders."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, slug, title, description, tags, author,
                       read_time, cover_image, published_at
                FROM blog_posts
                WHERE published = TRUE
                ORDER BY published_at DESC NULLS LAST, created_at DESC
            """)
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] blog_list_public error: {e}")
        return []


async def blog_list_all() -> list[dict]:
    """Every post incl. drafts — what the admin dashboard renders."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, slug, title, description, tags, author,
                       read_time, cover_image, published, published_at,
                       created_at, updated_at
                FROM blog_posts
                ORDER BY COALESCE(published_at, created_at) DESC
            """)
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] blog_list_all error: {e}")
        return []


async def blog_get_by_slug(slug: str, *, only_published: bool = True) -> dict | None:
    """Single post. Public callers must pass only_published=True so a
    draft slug can't be guessed and leaked before launch."""
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            if only_published:
                row = await conn.fetchrow("""
                    SELECT id, slug, title, description, content_md, tags,
                           author, read_time, cover_image, published, published_at
                    FROM blog_posts
                    WHERE slug = $1 AND published = TRUE
                """, slug)
            else:
                row = await conn.fetchrow("""
                    SELECT id, slug, title, description, content_md, tags,
                           author, read_time, cover_image, published, published_at,
                           created_at, updated_at
                    FROM blog_posts
                    WHERE slug = $1
                """, slug)
            return dict(row) if row else None
    except Exception as e:
        print(f"[db] blog_get_by_slug({slug!r}) error: {e}")
        return None


async def blog_get_by_id(post_id: int) -> dict | None:
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, slug, title, description, content_md, tags,
                       author, read_time, cover_image, published, published_at,
                       created_at, updated_at
                FROM blog_posts
                WHERE id = $1
            """, post_id)
            return dict(row) if row else None
    except Exception as e:
        print(f"[db] blog_get_by_id({post_id}) error: {e}")
        return None


async def blog_create(data: dict) -> dict | None:
    """Insert a new post. `data` keys: slug, title, description, content_md,
    tags (list), author, read_time, published. published_at auto-set when
    published is True. Returns the inserted row or None on failure."""
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO blog_posts
                    (slug, title, description, content_md, tags, author,
                     read_time, published, cover_image, published_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                        CASE WHEN $8 THEN NOW() ELSE NULL END)
                RETURNING id, slug, title, description, content_md, tags,
                          author, read_time, cover_image, published, published_at,
                          created_at, updated_at
            """,
                data["slug"], data["title"], data.get("description", ""),
                data.get("content_md", ""), data.get("tags", []) or [],
                data.get("author", "فريق حياك"),
                int(data.get("read_time", 5)), bool(data.get("published", False)),
                data.get("cover_image") or None,
            )
            return dict(row) if row else None
    except Exception as e:
        print(f"[db] blog_create error: {e}")
        return None


async def blog_update(post_id: int, data: dict) -> dict | None:
    """Update a post in place. Flipping published False→True sets
    published_at to NOW (first publication). Flipping True→False doesn't
    clear it — once published, the date stays for canonical reference."""
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE blog_posts SET
                    slug         = COALESCE($2, slug),
                    title        = COALESCE($3, title),
                    description  = COALESCE($4, description),
                    content_md   = COALESCE($5, content_md),
                    tags         = COALESCE($6, tags),
                    author       = COALESCE($7, author),
                    read_time    = COALESCE($8, read_time),
                    published    = COALESCE($9, published),
                    cover_image  = COALESCE($10, cover_image),
                    published_at = CASE
                        WHEN $9 = TRUE AND published_at IS NULL THEN NOW()
                        ELSE published_at
                    END,
                    updated_at   = NOW()
                WHERE id = $1
                RETURNING id, slug, title, description, content_md, tags,
                          author, read_time, cover_image, published, published_at,
                          created_at, updated_at
            """,
                post_id,
                data.get("slug"),
                data.get("title"),
                data.get("description"),
                data.get("content_md"),
                data.get("tags"),
                data.get("author"),
                data.get("read_time"),
                data.get("published"),
                data.get("cover_image"),
            )
            return dict(row) if row else None
    except Exception as e:
        print(f"[db] blog_update({post_id}) error: {e}")
        return None


async def blog_delete(post_id: int) -> bool:
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            r = await conn.execute("DELETE FROM blog_posts WHERE id = $1", post_id)
        # `r` looks like "DELETE 1" / "DELETE 0"
        return r.endswith("1")
    except Exception as e:
        print(f"[db] blog_delete({post_id}) error: {e}")
        return False


# ── WhatsApp Campaigns ─────────────────────────────────────────────────────────

async def campaign_create(store_id: str, data: dict) -> dict | None:
    if not _pool:
        return None
    import json as _j
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO wa_campaigns
                    (store_id, name, template_name, template_lang,
                     header_params, body_params, audience_type, phone_list,
                     status, scheduled_at)
                VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7,$8::jsonb,$9,$10)
                RETURNING *
                """,
                store_id,
                data["name"],
                data["template_name"],
                data.get("template_lang", "ar"),
                _j.dumps(data.get("header_params", [])),
                _j.dumps(data.get("body_params", [])),
                data.get("audience_type", "chat_users"),
                _j.dumps(data.get("phone_list", [])),
                data.get("status", "draft"),
                data.get("scheduled_at"),
            )
        return dict(row) if row else None
    except Exception as e:
        print(f"[db] campaign_create error: {e}")
        return None


async def campaign_list(store_id: str) -> list[dict]:
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name, template_name, template_lang,
                       audience_type, status, scheduled_at, sent_at,
                       total_count, sent_count, failed_count, created_at
                FROM wa_campaigns
                WHERE store_id = $1
                ORDER BY created_at DESC
                LIMIT 100
                """,
                store_id,
            )
        return [
            {
                "id":            r["id"],
                "name":          r["name"],
                "template_name": r["template_name"],
                "template_lang": r["template_lang"],
                "audience_type": r["audience_type"],
                "status":        r["status"],
                "scheduled_at":  _iso_z(r["scheduled_at"]),
                "sent_at":       _iso_z(r["sent_at"]),
                "total_count":   r["total_count"],
                "sent_count":    r["sent_count"],
                "failed_count":  r["failed_count"],
                "created_at":    _iso_z(r["created_at"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] campaign_list error: {e}")
        return []


async def campaign_get(campaign_id: int) -> dict | None:
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM wa_campaigns WHERE id = $1", campaign_id
            )
        return dict(row) if row else None
    except Exception as e:
        print(f"[db] campaign_get error: {e}")
        return None


async def campaign_update_status(
    campaign_id: int,
    status: str,
    *,
    total: int | None = None,
    sent: int | None = None,
    failed: int | None = None,
    sent_at=None,
) -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE wa_campaigns
                SET status       = $2,
                    total_count  = COALESCE($3, total_count),
                    sent_count   = COALESCE($4, sent_count),
                    failed_count = COALESCE($5, failed_count),
                    sent_at      = COALESCE($6, sent_at),
                    updated_at   = NOW()
                WHERE id = $1
                """,
                campaign_id, status, total, sent, failed, sent_at,
            )
    except Exception as e:
        print(f"[db] campaign_update_status error: {e}")


async def campaign_delete(store_id: str, campaign_id: int) -> bool:
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            r = await conn.execute(
                "DELETE FROM wa_campaigns WHERE id=$1 AND store_id=$2",
                campaign_id, store_id,
            )
        return r.endswith("1")
    except Exception as e:
        print(f"[db] campaign_delete error: {e}")
        return False


async def campaign_add_recipients(campaign_id: int, recipients: list[dict]) -> int:
    """Bulk-insert recipients. Returns inserted count."""
    if not _pool or not recipients:
        return 0
    try:
        async with _pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO wa_campaign_recipients (campaign_id, phone, name)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                [(campaign_id, r["phone"], r.get("name", "")) for r in recipients],
            )
        return len(recipients)
    except Exception as e:
        print(f"[db] campaign_add_recipients error: {e}")
        return 0


async def campaign_mark_recipient(
    campaign_id: int, phone: str, *, ok: bool, error: str = ""
) -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE wa_campaign_recipients
                SET status = $3, error = $4, sent_at = CASE WHEN $3='sent' THEN NOW() ELSE NULL END
                WHERE campaign_id = $1 AND phone = $2
                """,
                campaign_id, phone,
                "sent" if ok else "failed",
                error,
            )
    except Exception as e:
        print(f"[db] campaign_mark_recipient error: {e}")


async def campaign_recipient_stats(campaign_id: int) -> dict:
    if not _pool:
        return {}
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)                                       AS total,
                    COUNT(*) FILTER (WHERE status='sent')         AS sent,
                    COUNT(*) FILTER (WHERE status='failed')       AS failed,
                    COUNT(*) FILTER (WHERE status='pending')      AS pending
                FROM wa_campaign_recipients
                WHERE campaign_id = $1
                """,
                campaign_id,
            )
        return dict(row) if row else {}
    except Exception as e:
        print(f"[db] campaign_recipient_stats error: {e}")
        return {}


# ── Contacts (unified CRM) ─────────────────────────────────────────────────────

async def contacts_count(store_id: str, search: str = "") -> int:
    if not _pool:
        return 0
    try:
        async with _pool.acquire() as conn:
            if search:
                return await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM contacts
                    WHERE store_id = $1
                      AND (name ILIKE $2 OR phone ILIKE $2 OR email ILIKE $2)
                    """,
                    store_id, f"%{search}%",
                ) or 0
            return await conn.fetchval(
                "SELECT COUNT(*) FROM contacts WHERE store_id = $1", store_id,
            ) or 0
    except Exception as e:
        print(f"[db] contacts_count error: {e}")
        return 0


async def contacts_list(
    store_id: str, page: int = 1, per_page: int = 25, search: str = ""
) -> list[dict]:
    if not _pool:
        return []
    offset = (page - 1) * per_page
    try:
        async with _pool.acquire() as conn:
            if search:
                rows = await conn.fetch(
                    """
                    SELECT id, phone, name, email, company, city, country,
                           source, salla_id, last_seen, created_at, updated_at
                    FROM contacts
                    WHERE store_id = $1
                      AND (name ILIKE $2 OR phone ILIKE $2 OR email ILIKE $2)
                    ORDER BY updated_at DESC
                    LIMIT $3 OFFSET $4
                    """,
                    store_id, f"%{search}%", per_page, offset,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, phone, name, email, company, city, country,
                           source, salla_id, last_seen, created_at, updated_at
                    FROM contacts
                    WHERE store_id = $1
                    ORDER BY updated_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    store_id, per_page, offset,
                )
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] contacts_list error: {e}")
        return []


async def contacts_upsert_batch(store_id: str, records: list[dict]) -> int:
    """
    Upsert a batch of contacts. Records should have: phone, name, email,
    company, city, country, source, salla_id (all optional except phone).
    Returns number of rows upserted.
    """
    if not _pool or not records:
        return 0
    try:
        async with _pool.acquire() as conn:
            count = 0
            for r in records:
                phone = (r.get("phone") or "").strip()
                if not phone:
                    continue
                source = r.get("source", "chat")
                await conn.execute(
                    """
                    INSERT INTO contacts
                        (store_id, phone, name, email, company, city, country,
                         source, salla_id, last_seen, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW())
                    ON CONFLICT (store_id, phone) DO UPDATE SET
                        name      = CASE WHEN contacts.source='salla' OR excluded.source='salla'
                                         THEN GREATEST(excluded.name, contacts.name)
                                         ELSE COALESCE(NULLIF(excluded.name,''), contacts.name) END,
                        email     = COALESCE(NULLIF(excluded.email,''), contacts.email),
                        company   = COALESCE(NULLIF(excluded.company,''), contacts.company),
                        city      = COALESCE(NULLIF(excluded.city,''), contacts.city),
                        country   = COALESCE(NULLIF(excluded.country,''), contacts.country),
                        source    = CASE WHEN excluded.source='salla' THEN 'salla' ELSE contacts.source END,
                        salla_id  = COALESCE(excluded.salla_id, contacts.salla_id),
                        last_seen = GREATEST(excluded.last_seen, contacts.last_seen),
                        updated_at = NOW()
                    """,
                    store_id,
                    phone,
                    (r.get("name") or "").strip(),
                    (r.get("email") or "").strip(),
                    (r.get("company") or "").strip(),
                    (r.get("city") or "").strip(),
                    (r.get("country") or "").strip(),
                    source,
                    r.get("salla_id") or None,
                    r.get("last_seen") or None,
                )
                count += 1
        return count
    except Exception as e:
        print(f"[db] contacts_upsert_batch error: {e}")
        return 0


# ── Integrations ──────────────────────────────────────────────────────────────

async def clear_salla_tokens(store_id: str) -> None:
    """Remove only Salla OAuth fields from tokens, preserving admin_password_hash, store_name, etc."""
    if not _pool:
        raise RuntimeError("Database pool not initialised")
    async with _pool.acquire() as conn:
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
    if not _pool:
        return ""
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
        return ""
    try:
        key = _new_api_key()
        async with _pool.acquire() as conn:
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
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
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
    if not _pool or not placeholder_id or placeholder_id == target_id:
        return False
    try:
        async with _pool.acquire() as conn:
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
    if not _pool:
        return None
    key = (api_key or "").strip()
    if not key:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT store_id FROM stores WHERE api_key = $1 LIMIT 1", key,
            )
        return row["store_id"] if row else None
    except Exception as e:
        print(f"[db] find_store_by_api_key error: {e}")
        return None


async def find_store_by_shopify_shop(shop: str) -> str | None:
    """Return the store_id that already owns this Shopify shop, or None."""
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT store_id FROM stores WHERE integrations->'shopify'->>'shop' = $1 LIMIT 1",
                shop,
            )
            return row["store_id"] if row else None
    except Exception as e:
        print(f"[db] find_store_by_shopify_shop error: {e}")
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
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT integrations, tokens FROM stores WHERE store_id = $1",
                store_id,
            )
            if not row:
                print(f"[db] get_integrations: no row for store_id='{store_id}'")
                return {}
            result = _coerce_jsonb(row["integrations"])
            tokens = _coerce_jsonb(row["tokens"])
            if tokens.get("access_token"):
                result.setdefault("salla", {"connected": True})
            print(f"[db] get_integrations({store_id}): keys={list(result.keys())}")
            return result
    except Exception as e:
        print(f"[db] get_integrations error: {e}")
        return {}


async def save_integration(store_id: str, platform: str, data: dict) -> None:
    """Upsert a single platform entry inside stores.integrations."""
    if not _pool:
        raise RuntimeError("Database pool not initialised")
    async with _pool.acquire() as conn:
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
            {platform: data},
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
        async with _pool.acquire() as conn:
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


# ── Social comments (FB/IG comment automation) ──────────────────────────────
# Comments are PUBLIC, one-shot events (not threaded conversation sessions), so
# they live in their own tenant-scoped table rather than `conversations`. Every
# function here is store_id-scoped. See alembic 0014 + comments.py / comment_ai.

# Columns the API/pipeline may update post-insert. Whitelisted so column names
# can never come from caller input (the values are still parameterised).
_SOCIAL_COMMENT_UPDATABLE = {
    "sentiment", "intent", "category", "is_spam", "lead_score", "lead_temp",
    "ai_confidence", "status", "assigned_to", "suggested_reply", "final_reply",
    "replied_by", "replied_at",
}


def _social_comment_row(r) -> dict:
    return {
        "id":                  r["id"],
        "store_id":            r["store_id"],
        "platform":            r["platform"],
        "object_type":         r["object_type"],
        "external_comment_id": r["external_comment_id"],
        "parent_comment_id":   r["parent_comment_id"] or "",
        "post_id":             r["post_id"] or "",
        "recipient_id":        r["recipient_id"] or "",
        "author_id":           r["author_id"] or "",
        "author_name":         r["author_name"] or "",
        "message":             r["message"] or "",
        "permalink":           r["permalink"] or "",
        "sentiment":           r["sentiment"] or "",
        "intent":              r["intent"] or "",
        "category":            r["category"] or "",
        "is_spam":             bool(r["is_spam"]),
        "lead_score":          int(r["lead_score"] or 0),
        "lead_temp":           r["lead_temp"] or "",
        "ai_confidence":       float(r["ai_confidence"]) if r["ai_confidence"] is not None else None,
        "status":              r["status"],
        "assigned_to":         r["assigned_to"],
        "suggested_reply":     r["suggested_reply"] or "",
        "final_reply":         r["final_reply"] or "",
        "replied_by":          r["replied_by"] or "",
        "replied_at":          _iso_z(r["replied_at"]) if r["replied_at"] else "",
        "created_at":          _iso_z(r["created_at"]),
        "updated_at":          _iso_z(r["updated_at"]),
    }


async def social_comment_upsert(store_id: str, platform: str, comment: dict) -> dict:
    """
    Idempotent insert of one inbound comment, dedup on
    (store_id, platform, external_comment_id). Returns
    {"inserted": bool, "id": int|None}. inserted=False means Meta retried a
    delivery we already have — the caller should not re-run AI on it.

    `comment` is the dict produced by comments.extract_comments().
    """
    if not _pool:
        return {"inserted": False, "id": None}
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO social_comments
                    (store_id, platform, object_type, external_comment_id,
                     parent_comment_id, post_id, recipient_id, author_id,
                     author_name, message, permalink)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (store_id, platform, external_comment_id)
                DO NOTHING
                RETURNING id
                """,
                store_id, platform,
                comment.get("object_type", "comment"),
                str(comment.get("comment_id", "")),
                comment.get("parent_id", "") or None,
                comment.get("post_id", "") or None,
                comment.get("recipient_id", "") or None,
                comment.get("author_id", "") or None,
                comment.get("author_name", "") or "",
                comment.get("text", "") or "",
                comment.get("permalink", "") or None,
            )
        if row is None:
            return {"inserted": False, "id": None}
        return {"inserted": True, "id": int(row["id"])}
    except Exception as e:
        print(f"[db] social_comment_upsert error: {e}")
        return {"inserted": False, "id": None}


async def list_social_comments(store_id: str, *, status: str = "", platform: str = "",
                               lead_temp: str = "", limit: int = 100,
                               offset: int = 0) -> list[dict]:
    """Smart-Inbox listing, newest first. Optional status/platform/lead filters."""
    if not _pool:
        return []
    clauses = ["store_id = $1"]
    args: list = [store_id]
    if status:
        args.append(status);    clauses.append(f"status = ${len(args)}")
    if platform:
        args.append(platform);  clauses.append(f"platform = ${len(args)}")
    if lead_temp:
        args.append(lead_temp); clauses.append(f"lead_temp = ${len(args)}")
    args.append(max(1, min(int(limit or 100), 500)))
    lim = f"${len(args)}"
    args.append(max(0, int(offset or 0)))
    off = f"${len(args)}"
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM social_comments
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC
                LIMIT {lim} OFFSET {off}
                """,
                *args,
            )
        return [_social_comment_row(r) for r in rows]
    except Exception as e:
        print(f"[db] list_social_comments error: {e}")
        return []


async def get_social_comment(store_id: str, comment_pk: int) -> dict | None:
    """Fetch a single comment by primary key, tenant-scoped. None if not found."""
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT * FROM social_comments WHERE id = $1 AND store_id = $2",
                int(comment_pk), store_id,
            )
        return _social_comment_row(r) if r else None
    except Exception as e:
        print(f"[db] get_social_comment error: {e}")
        return None


async def update_social_comment(store_id: str, comment_pk: int, **fields) -> bool:
    """
    Patch whitelisted columns on a comment (tenant-scoped). Unknown keys are
    ignored. Always bumps updated_at. Returns True if a row was updated.
    """
    if not _pool:
        return False
    sets, args = [], []
    for k, v in fields.items():
        if k not in _SOCIAL_COMMENT_UPDATABLE:
            continue
        args.append(v)
        sets.append(f"{k} = ${len(args)}")
    if not sets:
        return False
    sets.append("updated_at = NOW()")
    args.append(int(comment_pk)); pk_ph = f"${len(args)}"
    args.append(store_id);        sid_ph = f"${len(args)}"
    try:
        async with _pool.acquire() as conn:
            res = await conn.execute(
                f"UPDATE social_comments SET {', '.join(sets)} "
                f"WHERE id = {pk_ph} AND store_id = {sid_ph}",
                *args,
            )
        return _rows_affected(res) > 0  # "UPDATE n"
    except Exception as e:
        print(f"[db] update_social_comment error: {e}")
        return False


# ── Comment rules (deterministic pre-LLM replies) ───────────────────────────

async def list_comment_rules(store_id: str) -> list[dict]:
    """Per-store reply rules, lowest priority value first (most specific)."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, priority, match_type, pattern, action, template, enabled
                FROM comment_rules WHERE store_id = $1
                ORDER BY priority ASC, id ASC
                """,
                store_id,
            )
        return [
            {
                "id":         r["id"],
                "priority":   int(r["priority"]),
                "match_type": r["match_type"],
                "pattern":    r["pattern"],
                "action":     r["action"],
                "template":   r["template"] or "",
                "enabled":    bool(r["enabled"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] list_comment_rules error: {e}")
        return []


async def add_comment_rule(store_id: str, *, match_type: str, pattern: str,
                           action: str, template: str = "", priority: int = 100,
                           enabled: bool = True) -> int | None:
    if not _pool:
        return None
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO comment_rules
                    (store_id, priority, match_type, pattern, action, template, enabled)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                RETURNING id
                """,
                store_id, int(priority), match_type, pattern, action,
                template or "", bool(enabled),
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] add_comment_rule error: {e}")
        return None


async def delete_comment_rule(store_id: str, rule_id: int) -> bool:
    if not _pool:
        return False
    try:
        async with _pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM comment_rules WHERE id = $1 AND store_id = $2",
                int(rule_id), store_id,
            )
        return _rows_affected(res) > 0
    except Exception as e:
        print(f"[db] delete_comment_rule error: {e}")
        return False


# ── Store entitlements (minimal comment-feature gate) ───────────────────────

async def get_entitlements(store_id: str) -> dict:
    """Return {comments_enabled, comments_monthly_limit}. Defaults (disabled,
    0) when the store has no row yet."""
    default = {"comments_enabled": False, "comments_monthly_limit": 0}
    if not _pool:
        return default
    try:
        async with _pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT comments_enabled, comments_monthly_limit "
                "FROM store_entitlements WHERE store_id = $1",
                store_id,
            )
        if not r:
            return default
        return {
            "comments_enabled":       bool(r["comments_enabled"]),
            "comments_monthly_limit": int(r["comments_monthly_limit"] or 0),
        }
    except Exception as e:
        print(f"[db] get_entitlements error: {e}")
        return default


async def get_entitlements_map() -> dict:
    """Return {store_id: comments_enabled} for every store that has a row.
    Used by the platform-ops snapshot to render the per-store toggle without
    an N+1 query. Stores absent from the map default to disabled."""
    if not _pool:
        return {}
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT store_id, comments_enabled FROM store_entitlements"
            )
        return {r["store_id"]: bool(r["comments_enabled"]) for r in rows}
    except Exception as e:
        print(f"[db] get_entitlements_map error: {e}")
        return {}


async def set_entitlements(store_id: str, *, comments_enabled: bool,
                           comments_monthly_limit: int = 0) -> None:
    """Upsert a store's comment-feature entitlement."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO store_entitlements
                    (store_id, comments_enabled, comments_monthly_limit, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (store_id) DO UPDATE
                   SET comments_enabled       = EXCLUDED.comments_enabled,
                       comments_monthly_limit = EXCLUDED.comments_monthly_limit,
                       updated_at             = NOW()
                """,
                store_id, bool(comments_enabled), int(comments_monthly_limit or 0),
            )
    except Exception as e:
        print(f"[db] set_entitlements error: {e}")


async def social_comment_analytics(store_id: str, days: int = 30) -> dict:
    """Aggregate comment metrics for the analytics dashboard (last `days`)."""
    empty = {
        "total": 0, "replied": 0, "ai_replied": 0, "response_rate": 0.0,
        "ai_response_rate": 0.0, "leads": 0, "avg_response_secs": 0,
        "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
    }
    if not _pool:
        return empty
    try:
        async with _pool.acquire() as conn:
            r = await conn.fetchrow(
                """
                SELECT
                  COUNT(*)                                                          AS total,
                  COUNT(*) FILTER (WHERE status IN ('replied','ai_replied'))         AS replied,
                  COUNT(*) FILTER (WHERE status = 'replied' AND replied_by = 'ai')   AS ai_replied,
                  COUNT(*) FILTER (WHERE lead_temp IN ('hot','warm'))                AS leads,
                  COUNT(*) FILTER (WHERE sentiment = 'positive')                     AS positive,
                  COUNT(*) FILTER (WHERE sentiment = 'neutral')                      AS neutral,
                  COUNT(*) FILTER (WHERE sentiment = 'negative')                     AS negative,
                  AVG(EXTRACT(EPOCH FROM (replied_at - created_at)))
                      FILTER (WHERE replied_at IS NOT NULL)                          AS avg_secs
                FROM social_comments
                WHERE store_id = $1
                  AND created_at >= NOW() - make_interval(days => $2)
                """,
                store_id, int(days),
            )
        total   = int(r["total"] or 0)
        replied = int(r["replied"] or 0)
        ai_rep  = int(r["ai_replied"] or 0)
        return {
            "total":            total,
            "replied":          replied,
            "ai_replied":       ai_rep,
            "response_rate":    round(replied / total, 3) if total else 0.0,
            "ai_response_rate": round(ai_rep / replied, 3) if replied else 0.0,
            "leads":            int(r["leads"] or 0),
            "avg_response_secs": int(r["avg_secs"] or 0),
            "sentiment": {
                "positive": int(r["positive"] or 0),
                "neutral":  int(r["neutral"] or 0),
                "negative": int(r["negative"] or 0),
            },
        }
    except Exception as e:
        print(f"[db] social_comment_analytics error: {e}")
        return empty
