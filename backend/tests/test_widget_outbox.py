"""
widget_outbox tests — the durable per-session queue that replaced
conversations.data["pending_for_widget"].

The contract the widget's SSE flush-on-connect path depends on:
  • Enqueue is durable — any replica's INSERT is visible to any other
    replica's claim.
  • Claim is atomic — two concurrent reconnects don't both deliver the
    same row (the second gets an empty list, not a duplicate).
  • Pending count reflects un-delivered rows only.
  • Pruning never touches pending rows.

All require Postgres and skip cleanly when none is available.
"""
from __future__ import annotations

import asyncio
import pytest


pytestmark = pytest.mark.integration


# ── Enqueue → claim → marked delivered ─────────────────────────────────────

async def test_enqueue_then_claim_returns_payload(clean_db):
    db = clean_db

    row_id = await db.widget_outbox_enqueue(
        "sess-1", {"role": "admin", "content": "hi", "ts": "2026-06-09T00:00:00"},
    )
    assert isinstance(row_id, int) and row_id > 0

    claimed = await db.widget_outbox_claim_pending("sess-1")
    assert len(claimed) == 1
    assert claimed[0]["role"]    == "admin"
    assert claimed[0]["content"] == "hi"


async def test_claim_marks_rows_delivered_so_second_call_is_empty(clean_db):
    """
    The whole point of the table: once a connection consumes a backlog,
    a subsequent connect to the same session must NOT replay the same
    messages. The atomic UPDATE delivered_at = NOW() inside the claim
    query enforces this.
    """
    db = clean_db
    await db.widget_outbox_enqueue("sess-2", {"role": "admin", "content": "a"})
    await db.widget_outbox_enqueue("sess-2", {"role": "admin", "content": "b"})

    first  = await db.widget_outbox_claim_pending("sess-2")
    second = await db.widget_outbox_claim_pending("sess-2")

    assert len(first)  == 2
    assert len(second) == 0


async def test_oldest_first_ordering(clean_db):
    db = clean_db
    # asyncpg's default isolation gives row-by-row INSERT timestamps; we
    # rely on created_at DEFAULT NOW() resolving to monotonic order.
    for i in range(5):
        await db.widget_outbox_enqueue("sess-3", {"role": "admin", "content": f"msg-{i}"})
        await asyncio.sleep(0.001)  # ensure distinct created_at

    claimed = await db.widget_outbox_claim_pending("sess-3")
    contents = [m["content"] for m in claimed]
    assert contents == ["msg-0", "msg-1", "msg-2", "msg-3", "msg-4"]


async def test_concurrent_claims_dedupe(clean_db):
    """
    Two web replicas both observe a widget reconnect (the same physical
    client may briefly hold two SSE connections during the handover).
    FOR UPDATE SKIP LOCKED must give one of them everything and the
    other nothing — never the same row twice.
    """
    db = clean_db
    for i in range(10):
        await db.widget_outbox_enqueue("sess-4", {"role": "admin", "content": f"msg-{i}"})

    results = await asyncio.gather(
        db.widget_outbox_claim_pending("sess-4"),
        db.widget_outbox_claim_pending("sess-4"),
    )

    seen_ids: set[str] = set()
    for batch in results:
        for msg in batch:
            key = msg["content"]
            assert key not in seen_ids, "same message claimed twice"
            seen_ids.add(key)
    assert len(seen_ids) == 10


async def test_pending_count_only_counts_undelivered(clean_db):
    db = clean_db
    await db.widget_outbox_enqueue("sess-5", {"role": "admin", "content": "x"})
    await db.widget_outbox_enqueue("sess-5", {"role": "admin", "content": "y"})

    assert await db.widget_outbox_pending_count("sess-5") == 2

    await db.widget_outbox_claim_pending("sess-5")
    assert await db.widget_outbox_pending_count("sess-5") == 0


async def test_claim_is_session_scoped(clean_db):
    """A claim on session A must never touch rows for session B."""
    db = clean_db
    await db.widget_outbox_enqueue("sess-A", {"role": "admin", "content": "for-A"})
    await db.widget_outbox_enqueue("sess-B", {"role": "admin", "content": "for-B"})

    claimed_a = await db.widget_outbox_claim_pending("sess-A")
    assert len(claimed_a) == 1 and claimed_a[0]["content"] == "for-A"

    # B's row remains pending
    assert await db.widget_outbox_pending_count("sess-B") == 1


# ── Pruning ────────────────────────────────────────────────────────────────

async def test_prune_never_touches_pending_rows(clean_db):
    """
    A pending row is a message that hasn't been delivered yet. Pruning
    must never delete it, regardless of how old it is — otherwise we'd
    lose admin replies for a customer who hasn't reopened the widget
    in 25h.
    """
    db = clean_db
    await db.widget_outbox_enqueue("sess-prune", {"role": "admin", "content": "old"})

    # Force the row's created_at into the distant past — pruning is by
    # delivered_at, but a buggy version that filtered on created_at would
    # delete this. The test catches that regression.
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE widget_outbox SET created_at = NOW() - INTERVAL '30 days' "
            "WHERE session_id = $1",
            "sess-prune",
        )

    deleted = await db.prune_widget_outbox_delivered(keep_last_hours=1)
    assert deleted == 0
    assert await db.widget_outbox_pending_count("sess-prune") == 1


async def test_prune_drops_old_delivered_rows(clean_db):
    db = clean_db
    await db.widget_outbox_enqueue("sess-old", {"role": "admin", "content": "delivered"})
    await db.widget_outbox_claim_pending("sess-old")

    # Backdate delivered_at past the keep window.
    async with db._pool.acquire() as conn:
        await conn.execute(
            "UPDATE widget_outbox SET delivered_at = NOW() - INTERVAL '48 hours' "
            "WHERE session_id = $1",
            "sess-old",
        )

    deleted = await db.prune_widget_outbox_delivered(keep_last_hours=24)
    assert deleted == 1


# ── Degraded-mode behaviour ────────────────────────────────────────────────

async def test_enqueue_with_empty_session_id_is_noop(clean_db):
    """Defensive — never write a row keyed by an empty session_id."""
    db = clean_db
    assert await db.widget_outbox_enqueue("", {"role": "admin"}) is None
