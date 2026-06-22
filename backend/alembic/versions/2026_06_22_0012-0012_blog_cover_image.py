"""0012 blog cover image — optional hero/cover image URL per post

Adds a nullable `cover_image` column (stores a /file/<id> URL produced by the
admin blog image-upload endpoint). Idempotent ADD/DROP so re-running is safe.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS cover_image TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE blog_posts DROP COLUMN IF EXISTS cover_image")
