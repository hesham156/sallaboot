"""0004 conversations hot-path indexes

Phase 3 removed the process-wide `_conversations` cache. Every read
now touches Postgres, so the lookups that used to be O(1) hash-map
hits in memory are now indexed scans. Two of them needed dedicated
indexes:

  1. `find_session_by_salla_customer(store_id, salla_customer_id)` —
     used on every /chat call by a logged-in shopper so we can
     resume their previous session instead of starting a new one.
     SQL:
       WHERE store_id = $1 AND data->>'salla_customer_id' = $2
       ORDER BY updated_at DESC LIMIT 1
     Pre-Phase-3 the in-memory scan was acceptable up to ~10K
     conversations per process. Post-Phase-3 we hit the DB on every
     resume — without this index, a 200K-row table forces a full
     seq scan and a JSONB extract per row.
     The index is a composite **expression index** on
       (store_id, data->>'salla_customer_id', updated_at DESC)
     so the planner can satisfy both the equality filters AND the
     ORDER BY ... LIMIT 1 with one index-only scan. Partial WHERE
     keeps it tiny — most conversations are anonymous visitors with
     no Salla customer link.

  2. `load_conversations(limit)` — cross-store admin view ("all
     stores, newest first") used by the super-admin dashboard.
     SQL:
       SELECT … FROM conversations ORDER BY updated_at DESC LIMIT $1
     The existing `idx_conv_store_upd (store_id, updated_at DESC)`
     can't satisfy this without a store_id predicate. Add a
     dedicated `idx_conv_updated_at` so the planner doesn't fall
     back to a sort over the whole table.

Concurrent index creation
─────────────────────────
We DO NOT use CREATE INDEX CONCURRENTLY here because alembic wraps
the migration in a transaction by default and CONCURRENTLY can't run
inside one. For prod, run this migration during a low-traffic
window; both indexes are tiny relative to the conversations table.
If you need concurrent creation, set autocommit_block via
`with op.get_context().autocommit_block(): op.execute(...)`.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-09 00:00:01 UTC
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


_UP_SQL = r"""
-- Resume-by-customer lookup. The WHERE clause keeps anonymous
-- conversations out of the index, so it's tiny — only sessions
-- linked to a Salla customer pay the storage cost.
CREATE INDEX IF NOT EXISTS idx_conv_store_customer
    ON conversations (store_id, (data->>'salla_customer_id'), updated_at DESC)
    WHERE data->>'salla_customer_id' IS NOT NULL
      AND data->>'salla_customer_id' <> '';

-- Cross-store newest-first view (super admin dashboard).
CREATE INDEX IF NOT EXISTS idx_conv_updated_at
    ON conversations (updated_at DESC);
"""

_DOWN_SQL = r"""
DROP INDEX IF EXISTS idx_conv_updated_at;
DROP INDEX IF EXISTS idx_conv_store_customer;
"""


def upgrade() -> None:
    op.execute(_UP_SQL)


def downgrade() -> None:
    op.execute(_DOWN_SQL)
