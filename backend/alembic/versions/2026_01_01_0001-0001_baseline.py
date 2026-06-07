"""0001 baseline — full Sallabot schema (idempotent)

This migration mirrors what backend/database.py::_create_tables() emits
verbatim. It is fully idempotent (CREATE TABLE IF NOT EXISTS / CREATE
INDEX IF NOT EXISTS), so:

  • A fresh DB can be bootstrapped from `alembic upgrade head` alone.
  • An existing prod DB (already bootstrapped by _create_tables() at
    startup before Phase 1F) survives — every statement is a no-op.

For the legacy DB path, run `alembic stamp head` once after upgrading
to mark migrations as already applied. New schema changes from now on
should be authored as fresh revisions, NOT edits to this file.

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00 UTC
"""
from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


_UP_SQL = r"""
-- ── Multi-tenant store registry ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stores (
    store_id     TEXT PRIMARY KEY,
    tokens       JSONB NOT NULL DEFAULT '{}'::jsonb,
    ai_config    JSONB NOT NULL DEFAULT '{}'::jsonb,
    cache_data   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── Conversations ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    session_id   TEXT PRIMARY KEY,
    store_id     TEXT NOT NULL DEFAULT 'default',
    data         JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conv_store_upd
    ON conversations (store_id, updated_at DESC);

-- ── Abandoned carts ──────────────────────────────────────────────────────────
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

-- ── Uploads (BYTEA so they survive Railway's ephemeral FS) ──────────────────
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

-- ── Webhook audit log ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webhook_log (
    pk           BIGSERIAL PRIMARY KEY,
    store_id     TEXT,
    event        TEXT,
    status       TEXT,
    detail       TEXT,
    sig_status   TEXT,
    body_head    TEXT,
    content_type TEXT,
    user_agent   TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wh_store_ts ON webhook_log (store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_wh_ts       ON webhook_log (created_at DESC);

-- ── Webhook idempotency (legacy — superseded by webhook_inbox UNIQUE) ───────
CREATE TABLE IF NOT EXISTS webhook_seen (
    dedup_key    TEXT PRIMARY KEY,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wh_seen_ts ON webhook_seen (created_at);

-- ── Login rate-limit log ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS login_attempts (
    pk           BIGSERIAL PRIMARY KEY,
    attempt_key  TEXT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_login_key_ts ON login_attempts (attempt_key, created_at DESC);

-- ── App-level KV settings ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS app_settings (
    key    TEXT PRIMARY KEY,
    value  JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Bot training material ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bot_training (
    id           BIGSERIAL PRIMARY KEY,
    store_id     TEXT NOT NULL,
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    content      TEXT NOT NULL DEFAULT '',
    file_id      TEXT,
    file_name    TEXT,
    size_chars   INTEGER NOT NULL DEFAULT 0,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_train_store_ts
    ON bot_training (store_id, created_at DESC);

-- ── Per-store employees ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS employees (
    id            BIGSERIAL PRIMARY KEY,
    store_id      TEXT NOT NULL,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'agent',
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (store_id, email)
);
CREATE INDEX IF NOT EXISTS idx_employees_store
    ON employees (store_id);

-- ── Bot-generated orders (ROI dashboard) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS bot_orders (
    id          BIGSERIAL PRIMARY KEY,
    store_id    TEXT NOT NULL,
    session_id  TEXT,
    order_ref   TEXT,
    amount      NUMERIC NOT NULL DEFAULT 0,
    currency    TEXT NOT NULL DEFAULT 'SAR',
    kind        TEXT NOT NULL DEFAULT 'checkout',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bot_orders_store_ts
    ON bot_orders (store_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_orders_unique
    ON bot_orders (store_id, order_ref);

-- ── Phase 1: durable webhook ingest queue ────────────────────────────────────
CREATE TABLE IF NOT EXISTS webhook_inbox (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT NOT NULL,
    event_type    TEXT,
    dedup_key     TEXT,
    store_id      TEXT,
    payload       JSONB NOT NULL,
    meta          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status        TEXT NOT NULL DEFAULT 'pending',
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

-- ── Phase 1: durable outbound queue ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outbox (
    id              BIGSERIAL PRIMARY KEY,
    kind            TEXT NOT NULL,
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

-- ── Phase 1: dirty-conversation tracking ─────────────────────────────────────
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS dirty_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_conv_dirty
    ON conversations (dirty_at) WHERE dirty_at IS NOT NULL;
"""


_DOWN_SQL = r"""
-- Intentionally narrow downgrade: only drop the Phase 1 tables.
-- We never drop the historical tables (stores, conversations, ...) because
-- a downgrade to a pre-Phase 1 state shouldn't risk data loss on those.
DROP TABLE IF EXISTS outbox;
DROP TABLE IF EXISTS webhook_inbox;
ALTER TABLE conversations DROP COLUMN IF EXISTS dirty_at;
"""


def upgrade() -> None:
    op.execute(_UP_SQL)


def downgrade() -> None:
    op.execute(_DOWN_SQL)
