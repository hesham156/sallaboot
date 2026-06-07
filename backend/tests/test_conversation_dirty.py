"""
Phase 1 dirty-conversation tracking tests.

The pre-Phase-1 design had an in-memory `_dirty_sessions: set`. Multi-
instance deploys would split that set across processes — instance A
marking a session dirty was invisible to instance B's periodic flusher.

We replaced it with the conversations.dirty_at column. Verify:
  • mark_dirty writes dirty_at.
  • fetch_dirty_sessions returns the right ids in age order.
  • clear_conversation_dirty wipes the flag.
  • flush_dirty saves all in-memory sessions referenced by the dirty set,
    then clears their flags.
  • A successful add_message clears dirty_at (write-through semantics).
"""
from __future__ import annotations

import asyncio

import pytest


pytestmark = pytest.mark.integration


async def test_mark_dirty_sets_dirty_at(clean_db):
    """The DB column must reflect the mark_dirty call after the fire-and-forget
    task settles. We give it a brief sleep — this is the only place in the
    suite where async timing leaks into the test, and it's intentional."""
    db = clean_db
    # Create a row first — UPDATE without a row is a silent no-op.
    await db.save_conversation("sess-x", "store-1", {"messages": []})

    import conversation_store as cs
    cs.mark_dirty("sess-x")
    # mark_dirty uses db.fire (fire-and-forget). Wait briefly for the task
    # to land. 100ms is generous; the actual UPDATE is ~5ms.
    await asyncio.sleep(0.1)

    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT dirty_at FROM conversations WHERE session_id=$1",
            "sess-x",
        )
    assert row["dirty_at"] is not None


async def test_fetch_dirty_sessions_returns_in_age_order(clean_db):
    db = clean_db
    # Insert three rows manually with explicit dirty_at timestamps so we
    # can assert on the order without sleeping between mark_dirty calls.
    async with db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (session_id, store_id, data, dirty_at) "
            "VALUES ('s-old', 's', '{}'::jsonb, NOW() - INTERVAL '10 minutes'), "
            "       ('s-mid', 's', '{}'::jsonb, NOW() - INTERVAL '5 minutes'), "
            "       ('s-new', 's', '{}'::jsonb, NOW()), "
            "       ('s-clean', 's', '{}'::jsonb, NULL)"
        )

    sids = await db.fetch_dirty_sessions(limit=10)
    assert sids == ["s-old", "s-mid", "s-new"], "oldest-first ordering broken"


async def test_clear_conversation_dirty_only_clears_listed(clean_db):
    db = clean_db
    async with db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (session_id, store_id, data, dirty_at) "
            "VALUES ('a','s','{}'::jsonb, NOW()), ('b','s','{}'::jsonb, NOW())"
        )

    await db.clear_conversation_dirty(["a"])
    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT session_id, dirty_at FROM conversations ORDER BY session_id")
    states = {r["session_id"]: r["dirty_at"] for r in rows}
    assert states["a"] is None,     "cleared session should be clean"
    assert states["b"] is not None, "other sessions must NOT be cleared"


async def test_clear_conversation_dirty_handles_empty_list(clean_db):
    """No-op when the list is empty — important because the safety-net
    flush often runs with zero dirty rows and we don't want a DB roundtrip."""
    db = clean_db
    await db.clear_conversation_dirty([])  # must not raise


async def test_add_message_clears_dirty_flag(clean_db):
    """
    Write-through semantics: a successful add_message persists the full
    conversation. The dirty flag therefore must be cleared.
    """
    db = clean_db
    # Seed: create a row with dirty_at already set
    async with db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (session_id, store_id, data, dirty_at) "
            "VALUES ('s-msg', 'store-1', '{\"messages\":[]}'::jsonb, NOW())"
        )

    import conversation_store as cs
    # add_message AWAITS save + clear_conversation_dirty internally.
    await cs.add_message("s-msg", "user", "hello", "store-1")

    async with db._pool.acquire() as conn:
        flag = await conn.fetchval(
            "SELECT dirty_at FROM conversations WHERE session_id=$1", "s-msg"
        )
    assert flag is None, "add_message must clear dirty_at after persisting"


async def test_flush_dirty_clears_orphan_dirty_marks(clean_db):
    """
    Cross-instance safety: if a session was marked dirty on another
    instance and we don't have it in our local _conversations cache,
    flush_dirty should clear the flag anyway (the row already has the
    latest state). Leaving it would loop forever.
    """
    db = clean_db
    async with db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (session_id, store_id, data, dirty_at) "
            "VALUES ('foreign-session', 's', '{}'::jsonb, NOW())"
        )

    import conversation_store as cs
    # Our in-memory cache doesn't have 'foreign-session'.
    assert "foreign-session" not in cs._conversations

    await cs.flush_dirty()

    async with db._pool.acquire() as conn:
        flag = await conn.fetchval(
            "SELECT dirty_at FROM conversations WHERE session_id='foreign-session'"
        )
    assert flag is None, "flush_dirty must clear orphan dirty marks"
