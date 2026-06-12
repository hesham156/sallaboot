"""customer_segments: classify customers and schedule WhatsApp follow-ups

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-12
"""
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_segments (
            id              BIGSERIAL PRIMARY KEY,
            store_id        TEXT        NOT NULL,
            customer_id     TEXT        NOT NULL,   -- Salla customer ID or phone
            customer_name   TEXT        NOT NULL DEFAULT '',
            phone           TEXT        NOT NULL DEFAULT '',
            email           TEXT        NOT NULL DEFAULT '',
            segment         TEXT        NOT NULL DEFAULT 'new',
            -- new | inquiry | hesitant | buyer | loyal | inactive
            segment_reason  TEXT        NOT NULL DEFAULT '',
            last_order_id   TEXT,
            last_order_at   TIMESTAMPTZ,
            last_conv_id    TEXT,
            last_conv_at    TIMESTAMPTZ,
            followup_count  INT         NOT NULL DEFAULT 0,
            last_followup_at TIMESTAMPTZ,
            next_followup_at TIMESTAMPTZ,
            followup_paused  BOOLEAN    NOT NULL DEFAULT FALSE,
            notes           TEXT        NOT NULL DEFAULT '',
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (store_id, customer_id)
        );
        CREATE INDEX IF NOT EXISTS idx_custseg_store_seg
            ON customer_segments (store_id, segment);
        CREATE INDEX IF NOT EXISTS idx_custseg_followup
            ON customer_segments (store_id, next_followup_at)
            WHERE next_followup_at IS NOT NULL AND followup_paused = FALSE;
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS customer_segments;")
