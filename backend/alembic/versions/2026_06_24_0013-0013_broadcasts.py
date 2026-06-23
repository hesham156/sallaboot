"""0013 broadcasts — omni-channel free-text bulk send

Adds the `broadcasts` table backing the multi-channel broadcast feature
(widget / telegram / email / whatsapp / messenger / instagram). One row per
broadcast with status + total/sent/failed counters and a per-channel
breakdown. Idempotent CREATE so re-running is safe; mirrors the table that
database._create_tables() also ensures on boot.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS broadcasts (
            id            BIGSERIAL PRIMARY KEY,
            store_id      TEXT NOT NULL,
            message       TEXT NOT NULL,
            channels      JSONB NOT NULL DEFAULT '[]',
            status        TEXT NOT NULL DEFAULT 'draft',
            total_count   INT NOT NULL DEFAULT 0,
            sent_count    INT NOT NULL DEFAULT 0,
            failed_count  INT NOT NULL DEFAULT 0,
            per_channel   JSONB NOT NULL DEFAULT '{}',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sent_at       TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_broadcasts_store_ts
            ON broadcasts (store_id, created_at DESC);
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS broadcasts;")
