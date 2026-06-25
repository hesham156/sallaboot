"""0014 social comments — Facebook/Instagram comment automation

Adds the tables backing the AI comment-management feature:

  • social_comments   — one row per inbound FB/IG comment, with AI enrichment
                        (sentiment/intent/category/lead/spam/confidence) and the
                        reply workflow state. UNIQUE(store_id, platform,
                        external_comment_id) makes ingest idempotent under Meta's
                        webhook retries.
  • comment_rules     — per-store deterministic reply rules (keyword/regex/intent
                        → reply_template/send_contact/escalate/hide/ignore),
                        evaluated before the LLM (mirrors smart_router, but
                        admin-editable).
  • store_entitlements— minimal per-store feature gate + monthly cap for the
                        comment feature (usage is metered via the existing
                        llm_usage table).

Idempotent CREATE so re-running is safe; mirrors what database._create_tables()
also ensures on boot.

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        -- ── Inbound social comments (FB Pages + IG Business) ──────────────────
        CREATE TABLE IF NOT EXISTS social_comments (
            id                  BIGSERIAL PRIMARY KEY,
            store_id            TEXT NOT NULL,
            platform            TEXT NOT NULL,                 -- facebook | instagram
            object_type         TEXT NOT NULL DEFAULT 'comment', -- comment | mention
            external_comment_id TEXT NOT NULL,
            parent_comment_id   TEXT,
            post_id             TEXT,
            recipient_id        TEXT,                          -- page_id (FB) / ig_id (IG)
            author_id           TEXT,
            author_name         TEXT NOT NULL DEFAULT '',
            message             TEXT NOT NULL DEFAULT '',
            permalink           TEXT,
            media_type          TEXT,
            -- AI enrichment (filled by comment_ai) --
            sentiment           TEXT,                          -- positive|neutral|negative
            intent              TEXT,
            category            TEXT,
            is_spam             BOOLEAN NOT NULL DEFAULT FALSE,
            lead_score          INT NOT NULL DEFAULT 0,
            lead_temp           TEXT,                          -- hot|warm|cold
            ai_confidence       NUMERIC,
            -- Reply workflow --
            status              TEXT NOT NULL DEFAULT 'new',
            assigned_to         BIGINT,                        -- employees.id
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
            ON social_comments (store_id, lead_temp)
            WHERE lead_temp IS NOT NULL;

        -- ── Per-store deterministic reply rules ───────────────────────────────
        CREATE TABLE IF NOT EXISTS comment_rules (
            id          BIGSERIAL PRIMARY KEY,
            store_id    TEXT NOT NULL,
            priority    INT NOT NULL DEFAULT 100,
            match_type  TEXT NOT NULL DEFAULT 'keyword',       -- keyword|regex|intent
            pattern     TEXT NOT NULL DEFAULT '',
            action      TEXT NOT NULL DEFAULT 'reply_template', -- reply_template|send_contact|escalate|hide|ignore
            template    TEXT NOT NULL DEFAULT '',
            enabled     BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_comment_rules_store
            ON comment_rules (store_id, priority);

        -- ── Minimal feature gate / metering ───────────────────────────────────
        CREATE TABLE IF NOT EXISTS store_entitlements (
            store_id               TEXT PRIMARY KEY,
            comments_enabled       BOOLEAN NOT NULL DEFAULT FALSE,
            comments_monthly_limit INT NOT NULL DEFAULT 0,      -- 0 = unlimited
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def downgrade():
    op.execute("""
        DROP TABLE IF EXISTS comment_rules;
        DROP TABLE IF EXISTS store_entitlements;
        DROP TABLE IF EXISTS social_comments;
    """)
