"""
Phase 1 durability tests — webhook_inbox + outbox.

These tests verify the contract our drainer + ack-fast endpoints rely on:
  • inbox_insert is atomic-dedup via UNIQUE(source, dedup_key).
  • inbox_claim_batch + SELECT FOR UPDATE SKIP LOCKED let two drainers
    work concurrently without claiming the same row.
  • mark_done / mark_failed / mark_dead transitions advance correctly.
  • Outbox enqueue → claim → mark_sent / mark_failed with backoff.
  • notifications.notify enqueues exactly one notify_event row.

All require a Postgres. They skip cleanly if no TEST_DATABASE_URL or
Docker is available (see conftest.db_dsn).
"""
from __future__ import annotations

import asyncio
import datetime as dt

import pytest


pytestmark = pytest.mark.integration


# ── Inbox: atomic dedup ───────────────────────────────────────────────────

async def test_inbox_insert_dedups_on_duplicate_key(clean_db):
    """Salla retries the same event on flaky networks — second INSERT must
    not create a duplicate row, and must return inserted=False so the
    endpoint can ack 200 without re-queueing work."""
    db = clean_db
    payload = {"event": "order.created", "merchant": "1", "data": {"id": 42}}

    first = await db.inbox_insert(
        source     = "salla",
        event_type = "order.created",
        dedup_key  = "order.created:1:2026-01-01T00:00:00",
        store_id   = "1",
        payload    = payload,
    )
    second = await db.inbox_insert(
        source     = "salla",
        event_type = "order.created",
        dedup_key  = "order.created:1:2026-01-01T00:00:00",
        store_id   = "1",
        payload    = payload,
    )

    assert first["inserted"]  is True
    assert first["id"] is not None
    assert second["inserted"] is False, "duplicate dedup_key must NOT create a row"
    assert second["id"] is None

    # Only one row in the table
    async with db._pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM webhook_inbox")
    assert count == 1


async def test_inbox_insert_without_dedup_key_does_not_collapse(clean_db):
    """When dedup_key is empty (e.g. a WhatsApp message with no id), each
    insert MUST create its own row — the UNIQUE index is partial WHERE
    dedup_key IS NOT NULL."""
    db = clean_db
    for _ in range(3):
        result = await db.inbox_insert(
            source     = "whatsapp",
            event_type = "whatsapp.message",
            dedup_key  = "",
            store_id   = "",
            payload    = {"from": "+966500000000", "text": "hi"},
        )
        assert result["inserted"] is True

    async with db._pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM webhook_inbox")
    assert count == 3, "rows without dedup_key must NOT collapse"


# ── Inbox: claim semantics ────────────────────────────────────────────────

async def test_claim_batch_picks_pending_rows(clean_db):
    db = clean_db
    for i in range(5):
        await db.inbox_insert(
            source     = "salla",
            event_type = "order.created",
            dedup_key  = f"o:{i}",
            payload    = {"i": i},
        )

    claimed = await db.inbox_claim_batch("worker-A", limit=10)
    assert len(claimed) == 5
    # All rows are now status='processing' and claimed_by='worker-A'
    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, claimed_by, attempts FROM webhook_inbox ORDER BY id"
        )
    for r in rows:
        assert r["status"]     == "processing"
        assert r["claimed_by"] == "worker-A"
        assert r["attempts"]   == 1


async def test_concurrent_claims_dont_collide(clean_db):
    """Two drainers running side-by-side must each get a disjoint slice of
    pending rows. The DB's SELECT FOR UPDATE SKIP LOCKED is what makes
    this safe — we verify the API exposes that behaviour."""
    db = clean_db
    for i in range(20):
        await db.inbox_insert(
            source = "salla", event_type = "order.created",
            dedup_key = f"row:{i}", payload = {"i": i},
        )

    # Race two claims at once — neither should see the same id twice.
    a, b = await asyncio.gather(
        db.inbox_claim_batch("worker-A", limit=10),
        db.inbox_claim_batch("worker-B", limit=10),
    )
    ids_a = {r["id"] for r in a}
    ids_b = {r["id"] for r in b}
    assert ids_a.isdisjoint(ids_b), "two workers claimed the same row(s): " + str(ids_a & ids_b)
    assert len(ids_a) + len(ids_b) == 20, "every row should be claimed exactly once"


# ── Inbox: status transitions ─────────────────────────────────────────────

async def test_mark_done_advances_state(clean_db):
    db = clean_db
    await db.inbox_insert(source="salla", dedup_key="d1", payload={})
    claimed = await db.inbox_claim_batch("worker-X", limit=1)
    inbox_id = claimed[0]["id"]

    await db.inbox_mark_done(inbox_id)

    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, processed_at, last_error FROM webhook_inbox WHERE id=$1",
            inbox_id,
        )
    assert row["status"]       == "done"
    assert row["processed_at"] is not None
    assert row["last_error"]   is None


async def test_mark_failed_keeps_retrying_until_max(clean_db):
    """Five attempts then status='dead'. _MAX_ATTEMPTS = 5."""
    db = clean_db
    await db.inbox_insert(source="salla", dedup_key="retry-me", payload={})

    for attempt in range(1, 6):
        claimed = await db.inbox_claim_batch("worker-R", limit=1)
        if not claimed:
            break
        await db.inbox_mark_failed(claimed[0]["id"], f"boom #{attempt}", claimed[0]["attempts"])
        # On the 5th attempt, mark_failed flips status to 'dead'.

    async with db._pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status, attempts, last_error FROM webhook_inbox")
    assert row["status"]   == "dead", "DLQ after 5 attempts"
    assert row["attempts"] == 5
    assert "boom" in (row["last_error"] or "")


# ── Outbox: backoff escalation ────────────────────────────────────────────

async def test_outbox_failed_uses_backoff_schedule(clean_db):
    """
    Each failure pushes next_attempt_at out by an increasing delay.
    Schedule is (5s, 30s, 2m, 10m, 30m) — verify attempts 1+2 land in
    the right ballpark.
    """
    db = clean_db
    obox_id = await db.outbox_enqueue("notify_event", {"event": "x"}, store_id="s1")
    assert obox_id is not None

    # Claim then fail attempt #1 → next_attempt_at ≈ NOW + 5s
    claimed = await db.outbox_claim_batch("w", limit=1)
    await db.outbox_mark_failed(claimed[0]["id"], "boom", claimed[0]["attempts"])

    async with db._pool.acquire() as conn:
        nxt, status = await conn.fetchrow(
            "SELECT next_attempt_at, status FROM outbox WHERE id=$1",
            obox_id,
        )
    delay = (nxt - dt.datetime.now(nxt.tzinfo)).total_seconds()
    assert status == "failed"
    assert 3 <= delay <= 8, f"expected ~5s backoff after attempt 1, got {delay:.1f}s"


async def test_outbox_dead_after_max_attempts(clean_db):
    db = clean_db
    await db.outbox_enqueue("notify_event", {"event": "x"}, store_id="s2")
    # Force-attempt 5 times: each iteration claims (only the first time;
    # subsequent claims require next_attempt_at <= NOW, which the backoff
    # pushes out). For this test we directly increment attempts via
    # mark_failed using a hand-rolled loop that bypasses the backoff wait.
    async with clean_db._pool.acquire() as conn:
        for attempt in range(1, 6):
            # Reset next_attempt_at to NOW so claim picks it up.
            await conn.execute(
                "UPDATE outbox SET next_attempt_at = NOW() WHERE status IN ('pending','failed')"
            )
            claimed = await db.outbox_claim_batch("w", limit=1)
            if not claimed:
                break
            await db.outbox_mark_failed(claimed[0]["id"], f"boom {attempt}", claimed[0]["attempts"])

    async with db._pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status, attempts FROM outbox")
    assert row["status"]   == "dead"
    assert row["attempts"] == 5


# ── Notifications: enqueue surface ────────────────────────────────────────

async def test_notifications_notify_enqueues_one_row(clean_db, register_test_store):
    """
    Phase 1: notifications.notify is now a thin enqueue — it must NOT
    do the actual delivery, and must produce exactly one outbox row
    when the store has email or webhook configured.
    """
    db = clean_db
    await register_test_store(
        "test-notif-store",
        ai_config={
            "notifications": {
                "email_enabled":      True,
                "email_address":      "owner@example.com",
                "webhook_url":        "",
                "on_new_conversation": True,
            }
        },
    )

    import notifications as notif
    await notif.notify("test-notif-store", "new_conversation", {
        "customer_name": "Sara",
        "session_id":    "sess-1",
        "first_message": "مرحبا",
    })

    async with db._pool.acquire() as conn:
        rows = await conn.fetch("SELECT kind, store_id, payload FROM outbox")
    assert len(rows) == 1, "exactly one outbox row per notify() call"
    assert rows[0]["kind"]     == "notify_event"
    assert rows[0]["store_id"] == "test-notif-store"


async def test_notifications_notify_no_op_when_no_channels(clean_db, register_test_store):
    """If neither email nor webhook is configured, notify() is a no-op —
    we don't queue a row that will fail immediately at delivery time."""
    db = clean_db
    await register_test_store("dark-store", ai_config={"notifications": {}})

    import notifications as notif
    await notif.notify("dark-store", "new_conversation", {})

    async with db._pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM outbox")
    assert count == 0


# ── Diagnostics ───────────────────────────────────────────────────────────

async def test_inbox_count_by_status_groups_correctly(clean_db):
    db = clean_db
    await db.inbox_insert(source="salla", dedup_key="a", payload={})
    await db.inbox_insert(source="salla", dedup_key="b", payload={})
    await db.inbox_insert(source="salla", dedup_key="c", payload={})

    claimed = await db.inbox_claim_batch("w", limit=2)
    await db.inbox_mark_done(claimed[0]["id"])

    counts = await db.inbox_count_by_status()
    # 1 done, 1 processing (claim[1] never marked), 1 pending (never claimed)
    assert counts.get("done")       == 1
    assert counts.get("processing") == 1
    assert counts.get("pending")    == 1
