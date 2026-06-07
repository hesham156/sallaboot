"""
Tests for the Phase 3 realtime layer.

Three categories:
  • Unit: in-process fanout (publish → subscriber receives, multi-sub
    fan-out, slow-consumer drop policy). No DB.
  • Integration: end-to-end Postgres NOTIFY round-trip. Needs DB.
  • Endpoint: SSE ticket exchange + /chat/stream handshake. Needs DB
    because the stream subscribes to realtime which needs the listener.
"""
from __future__ import annotations

import asyncio
import json

import pytest


# ─────────────────────────────────────────────────────────────────────────
# UNIT — in-process fanout without touching Postgres
# ─────────────────────────────────────────────────────────────────────────

class TestRealtimeFanout:
    pytestmark = pytest.mark.unit

    async def test_single_subscriber_receives_published_event(self):
        """The simplest contract — publish then subscribe sees the event.
        We bypass the actual Postgres NOTIFY by calling the in-process
        dispatch directly. The integration test below covers the real
        NOTIFY path."""
        import realtime

        # Subscribe BEFORE the dispatch so the queue is registered.
        events = []
        sub_task = asyncio.create_task(self._collect_one(realtime, "test:1", events))
        await asyncio.sleep(0.05)  # let the subscriber register its queue

        # Synthesise a NOTIFY callback as if Postgres delivered it.
        realtime._on_notify(
            None, 0, realtime.NOTIFY_CHANNEL,
            json.dumps({"ch": "test:1", "ev": "hello", "d": {"x": 1}}),
        )

        # The subscriber should now see exactly one event.
        await asyncio.wait_for(sub_task, timeout=1.0)
        assert events == [{"type": "hello", "data": {"x": 1}}]

    async def test_multiple_subscribers_all_receive(self):
        """Fan-out: two subscribers on the same channel both see the event."""
        import realtime

        events_a, events_b = [], []
        ta = asyncio.create_task(self._collect_one(realtime, "test:2", events_a))
        tb = asyncio.create_task(self._collect_one(realtime, "test:2", events_b))
        await asyncio.sleep(0.05)

        realtime._on_notify(
            None, 0, realtime.NOTIFY_CHANNEL,
            json.dumps({"ch": "test:2", "ev": "bcast", "d": {}}),
        )

        await asyncio.wait_for(asyncio.gather(ta, tb), timeout=1.0)
        assert len(events_a) == 1 and len(events_b) == 1
        assert events_a[0]["type"] == "bcast"
        assert events_b[0]["type"] == "bcast"

    async def test_unsubscribed_channel_does_not_fan_out(self):
        """An event on channel X must NOT wake a subscriber on channel Y."""
        import realtime

        events_x: list = []
        # Subscribe to channel X.
        async def collect_x():
            async for ev in realtime.subscribe("test:x"):
                events_x.append(ev)
                return

        task = asyncio.create_task(collect_x())
        await asyncio.sleep(0.05)

        # Publish on Y.
        realtime._on_notify(
            None, 0, realtime.NOTIFY_CHANNEL,
            json.dumps({"ch": "test:y", "ev": "should-not-reach", "d": {}}),
        )

        # Give it time to NOT arrive.
        try:
            await asyncio.wait_for(task, timeout=0.2)
            assert False, "subscriber should still be waiting"
        except asyncio.TimeoutError:
            pass
        assert events_x == [], "channel isolation broken"
        task.cancel()

    async def test_subscriber_cleanup_on_generator_exit(self):
        """When a subscriber's generator exits, its queue is removed from
        the registry — otherwise we leak memory over long-running processes.

        We drive the generator explicitly via aclose() (instead of relying
        on `return` from a wrapper task) so the cleanup is deterministic.
        That mirrors what FastAPI's StreamingResponse does when a client
        disconnects."""
        import realtime

        # Get the generator directly and aclose() it after one event.
        gen = realtime.subscribe("test:cleanup").__aiter__()

        # Wait one tick so the generator registers its queue.
        # __anext__ on first call enters the body up to the first await.
        anext_task = asyncio.create_task(gen.__anext__())
        await asyncio.sleep(0.05)
        assert "test:cleanup" in realtime._subscribers
        assert len(realtime._subscribers["test:cleanup"]) == 1

        realtime._on_notify(
            None, 0, realtime.NOTIFY_CHANNEL,
            json.dumps({"ch": "test:cleanup", "ev": "x", "d": {}}),
        )
        ev = await asyncio.wait_for(anext_task, timeout=1.0)
        assert ev["type"] == "x"

        # Explicit aclose — runs the generator's `finally` block which
        # discards the queue and (when empty) GCs the channel entry.
        await gen.aclose()
        leftover = realtime._subscribers.get("test:cleanup", set())
        assert not leftover, f"queue leaked: {leftover}"

    async def test_slow_consumer_drops_oldest_not_block(self):
        """When a subscriber's queue is full, the dispatcher drops the
        OLDEST event and inserts the new one — never blocks."""
        import realtime

        # Force a tiny queue size for this test by patching the constant.
        # (We register a subscriber manually to control the queue.)
        q: asyncio.Queue = asyncio.Queue(maxsize=2)
        realtime._subscribers["test:slow"].add(q)
        try:
            # Fill the queue: 2 items + 1 more should evict the oldest.
            for i in range(3):
                realtime._on_notify(
                    None, 0, realtime.NOTIFY_CHANNEL,
                    json.dumps({"ch": "test:slow", "ev": str(i), "d": {}}),
                )

            assert q.qsize() == 2, "queue should still be at max size"
            # The oldest (ev=0) was dropped; we should see 1 and 2.
            first  = q.get_nowait()
            second = q.get_nowait()
            assert first["type"]  == "1"
            assert second["type"] == "2"
        finally:
            realtime._subscribers["test:slow"].discard(q)

    async def test_publish_when_db_unavailable_is_noop(self, monkeypatch):
        """Without a DB the publish call must NOT raise — it's a hot path
        on add_message, and crashing chat would be a much worse outcome
        than a missed live update."""
        import realtime
        import database as db
        # Force db.available() → False
        monkeypatch.setattr(db, "_pool", None)
        # Should complete without exception.
        await realtime.publish("test:noop", "ev", {"d": 1})

    # ── Helper ───────────────────────────────────────────────────────────
    async def _collect_one(self, realtime_mod, channel: str, sink: list) -> None:
        """Subscribe and collect the first event, then return."""
        async for ev in realtime_mod.subscribe(channel):
            sink.append(ev)
            return


# ─────────────────────────────────────────────────────────────────────────
# INTEGRATION — round-trip through Postgres NOTIFY
# ─────────────────────────────────────────────────────────────────────────

class TestRealtimePostgresRoundTrip:
    pytestmark = pytest.mark.integration

    async def test_publish_then_subscribe_via_postgres(self, clean_db):
        """The real end-to-end: publish() fires a NOTIFY, the listener
        connection receives it, dispatches to a subscriber. Validates that
        the asyncpg.add_listener wiring works."""
        import realtime
        # Start the listener bound to the test DB. start() is idempotent.
        ok = await realtime.start()
        assert ok, "listener should connect to test DB"

        events: list = []

        async def collect():
            async for ev in realtime.subscribe("itest:rt"):
                events.append(ev)
                return

        sub_task = asyncio.create_task(collect())
        await asyncio.sleep(0.1)  # listener registers

        # Real publish: this fires SELECT pg_notify(...) through the pool.
        await realtime.publish("itest:rt", "ping", {"hello": "world"})

        # NOTIFY delivery is async — give it a moment.
        try:
            await asyncio.wait_for(sub_task, timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("subscriber never received the event from Postgres NOTIFY")

        assert events == [{"type": "ping", "data": {"hello": "world"}}]


# ─────────────────────────────────────────────────────────────────────────
# ENDPOINT — SSE handshake + ticket exchange
# ─────────────────────────────────────────────────────────────────────────

class TestSseEndpoints:
    pytestmark = pytest.mark.integration

    async def test_admin_stream_rejects_without_ticket(self, app_client):
        """No ticket → 401. EventSource won't get past this."""
        r = await app_client.get("/admin/some-store/stream")
        assert r.status_code == 401

    async def test_admin_stream_ticket_requires_bearer(self, app_client):
        r = await app_client.post("/admin/some-store/stream/ticket")
        assert r.status_code == 401

    async def test_ticket_exchange_then_open_stream(self, app_client, register_test_store, make_token):
        """The happy path: POST ticket with bearer → GET stream with ticket."""
        await register_test_store("test-stream-store")
        token = make_token("test-stream-store")

        r = await app_client.post(
            "/admin/test-stream-store/stream/ticket",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        ticket = r.json()["ticket"]
        assert len(ticket) >= 20, "ticket should be cryptographically long"

        # Open the stream with the ticket. SSE responses are
        # text/event-stream and stream forever — read just the first
        # 'connected' event so the test exits quickly.
        import realtime
        await realtime.start()
        async with app_client.stream(
            "GET",
            f"/admin/test-stream-store/stream?ticket={ticket}",
        ) as s:
            assert s.status_code == 200
            assert s.headers["content-type"].startswith("text/event-stream")
            # Read just enough to see the connected event.
            chunk = b""
            async for piece in s.aiter_bytes():
                chunk += piece
                if b"event: connected" in chunk:
                    break
                if len(chunk) > 1024:
                    break
            assert b"event: connected" in chunk

    async def test_ticket_is_single_use(self, app_client, register_test_store, make_token):
        await register_test_store("test-single-use")
        token = make_token("test-single-use")
        r = await app_client.post(
            "/admin/test-single-use/stream/ticket",
            headers={"Authorization": f"Bearer {token}"},
        )
        ticket = r.json()["ticket"]

        import realtime
        await realtime.start()

        # First use OK.
        async with app_client.stream(
            "GET",
            f"/admin/test-single-use/stream?ticket={ticket}",
        ) as s:
            assert s.status_code == 200
            # Drain just the connected event.
            async for piece in s.aiter_bytes():
                if b"event: connected" in piece:
                    break

        # Second use of same ticket → 401.
        r2 = await app_client.get(f"/admin/test-single-use/stream?ticket={ticket}")
        assert r2.status_code == 401

    async def test_chat_stream_requires_session_id(self, app_client):
        r = await app_client.get("/chat/stream")
        # Missing required query param → 422 (FastAPI default).
        assert r.status_code in (400, 422)
