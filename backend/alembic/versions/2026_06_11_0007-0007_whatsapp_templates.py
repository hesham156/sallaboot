"""whatsapp_templates: store per-store Meta-approved template definitions

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-11
"""
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_templates (
            id          BIGSERIAL PRIMARY KEY,
            store_id    TEXT        NOT NULL,
            name        TEXT        NOT NULL,          -- Meta template name (snake_case)
            language    TEXT        NOT NULL DEFAULT 'ar',
            category    TEXT        NOT NULL DEFAULT 'MARKETING',
            header_type TEXT,                          -- TEXT | IMAGE | VIDEO | DOCUMENT | none
            header_text TEXT,
            body_text   TEXT        NOT NULL,
            footer_text TEXT,
            buttons     JSONB       NOT NULL DEFAULT '[]'::jsonb,
            variables   JSONB       NOT NULL DEFAULT '[]'::jsonb,  -- ordered list of var names
            status      TEXT        NOT NULL DEFAULT 'approved',   -- approved|pending|rejected
            notes       TEXT,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            updated_at  TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (store_id, name)
        );
        CREATE INDEX IF NOT EXISTS idx_wa_templates_store
            ON whatsapp_templates (store_id);
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS whatsapp_templates;")
