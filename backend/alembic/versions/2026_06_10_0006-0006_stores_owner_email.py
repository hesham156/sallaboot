"""stores: add owner_email + index for unified email/password login

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-10

The login flow used to be three separate paths (super / store-id+password /
employee email+password). Adding owner_email lets us auto-detect which
account an email belongs to and serve a single unified /auth/login.

Backfill: existing stores get NULL. They'll either pick up the email on
next OAuth refresh (the callback now saves it) or via admin manual entry.
Lookup is case-insensitive — we lower() both sides at query time, and the
index is on lower(owner_email) so matches stay fast.
"""
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE stores ADD COLUMN IF NOT EXISTS owner_email TEXT;
        CREATE INDEX IF NOT EXISTS idx_stores_owner_email
            ON stores (lower(owner_email))
            WHERE owner_email IS NOT NULL;
    """)


def downgrade():
    op.execute("""
        DROP INDEX IF EXISTS idx_stores_owner_email;
        ALTER TABLE stores DROP COLUMN IF EXISTS owner_email;
    """)
