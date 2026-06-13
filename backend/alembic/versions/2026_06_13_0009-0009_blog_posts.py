"""blog_posts: dashboard-managed SEO articles

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-13
"""
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS blog_posts (
            id              BIGSERIAL PRIMARY KEY,
            slug            TEXT        NOT NULL UNIQUE,
            title           TEXT        NOT NULL,
            description     TEXT        NOT NULL DEFAULT '',
            content_md      TEXT        NOT NULL DEFAULT '',
            tags            TEXT[]      NOT NULL DEFAULT '{}',
            author          TEXT        NOT NULL DEFAULT 'فريق حياك',
            read_time       INT         NOT NULL DEFAULT 5,
            published       BOOLEAN     NOT NULL DEFAULT FALSE,
            published_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        -- Public reads filter on published + order by published_at — index that.
        CREATE INDEX IF NOT EXISTS idx_blog_published
            ON blog_posts (published, published_at DESC)
            WHERE published = TRUE;
        -- Single-post lookup by slug is the hot read path.
        CREATE INDEX IF NOT EXISTS idx_blog_slug ON blog_posts (slug);
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS blog_posts;")
