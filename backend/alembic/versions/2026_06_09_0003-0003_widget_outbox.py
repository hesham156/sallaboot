"""0003 widget_outbox — durable per-session message queue for the widget

Background
──────────
`pending_for_widget` lived inside `conversations.data["pending_for_widget"]`
(an array), which in practice meant the queue only existed in the
in-process `_conversations` cache of the web replica that handled the
admin reply. When the widget reconnected to a *different* web replica's
SSE endpoint, the flush-on-connect path saw an empty list and the admin
reply was silently dropped.

This table is the durable, cross-replica replacement:

  • Admin replies / bot post-chat messages INSERT a row.
  • Widget SSE flush-on-connect SELECTs pending rows for its session_id,
    UPDATEs `delivered_at = NOW()`, and yields them over the stream.
  • A periodic cleanup deletes rows whose `delivered_at` is older than 24h.

The schema mirrors the inbox/outbox pattern but is intentionally
narrower: there is no `attempts` / `status` / `last_error`. Delivery is
SSE — we don't retry; if the client disconnects mid-yield the row stays
pending and the next reconnect picks it up.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-09 00:00:00 UTC
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


_UP_SQL = r"""
CREATE TABLE IF NOT EXISTS widget_outbox (
    id            BIGSERIAL PRIMARY KEY,
    session_id    TEXT NOT NULL,
    payload       JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at  TIMESTAMPTZ
);

-- Hot path: "give me everything still pending for this session, oldest
-- first". Partial index keeps it tiny — only undelivered rows.
CREATE INDEX IF NOT EXISTS idx_widget_outbox_pending
    ON widget_outbox (session_id, created_at)
    WHERE delivered_at IS NULL;

-- Cleanup scan: "what's old enough to prune". Full scan acceptable; the
-- periodic loop runs once an hour at most.
CREATE INDEX IF NOT EXISTS idx_widget_outbox_delivered
    ON widget_outbox (delivered_at)
    WHERE delivered_at IS NOT NULL;
"""

_DOWN_SQL = r"""
DROP INDEX IF EXISTS idx_widget_outbox_delivered;
DROP INDEX IF EXISTS idx_widget_outbox_pending;
DROP TABLE IF EXISTS widget_outbox;
"""


def upgrade() -> None:
    op.execute(_UP_SQL)


def downgrade() -> None:
    op.execute(_DOWN_SQL)
