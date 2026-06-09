"""
Dirty-conversation tracking tests.

Phase 1 introduced `conversations.dirty_at` as a cross-replica
replacement for an in-memory `_dirty_sessions: set`. Phase 3 made
every mutation persist inline, so the dirty_at mechanism is now a
safety net rather than the primary path. These tests verify:

  • The DB primitives (fetch_dirty_sessions / clear_conversation_dirty)
    still behave correctly — they're called by flush_dirty.
  • `add_message` clears dirty_at as part of its inline persist.
  • `flush_dirty` clears any orphan dirty_at left behind by older
    code (or by another instance still running pre-Phase-3 code).
  • `mark_dirty` is now an importable no-op so legacy call sites
    don't break during the migration window.
"""
from __future__ import annotations

import asyncio

import pytest


pytestmark = pytest.mark.integration


async def test_mark_dirty_is_now_a_noop(clean_db):
    """
    Phase 3 — mutations save inline, so mark_dirty no longer sets
    dirty_at. The function still exists as an importable name (so
    legacy callers don't crash on import), but the DB column stays
    untouched.
    """
    db = clean_db
    await db.save_conversation("sess-x", "store-1", {"messages": []})

    import conversation_store as cs
    cs.mark_dirty("sess-x")
    # Give any fire-and-forget background work a chance to land —
    # we want to assert NOTHING happened, so the wait must be
    # generous enough to catch a stray write.
    await asyncio.sleep(0.1)

    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT dirty_at FROM conversations WHERE session_id=$1",
            "sess-x",
        )
    assert row["dirty_at"] is None, \
        "mark_dirty is meant to be a no-op since Phase 3"


async def test_fetch_dirty_sessions_returns_in_age_order(clean_db):
    db = clean_db
    # Insert three rows manually with explicit dirty_at timestamps so we
    # can assert on the order without sleeping between writes.
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
    Write-through semantics: a successful add_message persists the
    full conversation and then clears dirty_at. Critical for the
    flush_dirty safety net to converge — if add_message left the
    flag set, the periodic loop would keep finding the same session.
    """
    db = clean_db
    async with db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (session_id, store_id, data, dirty_at) "
            "VALUES ('s-msg', 'store-1', '{\"messages\":[]}'::jsonb, NOW())"
        )

    import conversation_store as cs
    await cs.add_message("s-msg", "user", "hello", "store-1")

    async with db._pool.acquire() as conn:
        flag = await conn.fetchval(
            "SELECT dirty_at FROM conversations WHERE session_id=$1", "s-msg"
        )
    assert flag is None, "add_message must clear dirty_at after persisting"


async def test_flush_dirty_clears_orphan_dirty_marks(clean_db):
    """
    Phase 3 — flush_dirty no longer needs to re-save sessions (every
    mutation already saved inline). Its only job is to clear stale
    dirty_at flags left by pre-Phase-3 code, otherwise the periodic
    loop would spin on them forever.

    Verify: a row marked dirty is unflagged after one flush_dirty()
    call, regardless of whether we have it in cache.
    """
    db = clean_db
    async with db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (session_id, store_id, data, dirty_at) "
            "VALUES ('foreign-session', 's', '{}'::jsonb, NOW())"
        )

    import conversation_store as cs
    # Task-local cache doesn't have this session (we never loaded it).
    assert "foreign-session" not in cs._cache()

    cleared = await cs.flush_dirty()
    assert cleared == 1

    async with db._pool.acquire() as conn:
        flag = await conn.fetchval(
            "SELECT dirty_at FROM conversations WHERE session_id='foreign-session'"
        )
    assert flag is None, "flush_dirty must clear orphan dirty marks"
