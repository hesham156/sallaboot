"""webhook_inbox: ensure partial unique index exists for ON CONFLICT dedup

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-10

The original baseline created the index but some Railway deployments may
have missed it. This migration is a no-op if the index already exists.
"""
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    # Ensure the partial unique index exists (safe to re-run, IF NOT EXISTS).
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_inbox_dedup
        ON webhook_inbox (source, dedup_key)
        WHERE dedup_key IS NOT NULL;
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_inbox_dedup;")
