"""
realtime.py — Pub/sub for live updates (SSE, future WS).

Goal: when a customer message lands, the admin's dashboard updates in the
same second — without polling. When an admin replies, the widget shows
the reply immediately — without polling.

Mechanism
─────────
Postgres LISTEN/NOTIFY as the transport, in-process asyncio.Queue
fanout for delivery.

  publisher → conn.execute("SELECT pg_notify('realtime', $1)", payload)
                          │
                          ▼ (all instances receive)
  every instance has ONE listener connection
                          │
                          ▼
  _on_notify dispatches to local subscribers by channel name
                          │
                          ▼
  each SSE client owns an asyncio.Queue; the listener puts the message
  on every matching queue

Why Postgres NOTIFY and not Redis
─────────────────────────────────
• We already have Postgres — no new infra.
• Multi-instance safe out of the box.
• 8 KB payload limit is fine: we only ship event ids + small dicts;
  callers re-query if they need the full state.

When to swap to Redis
─────────────────────
• > ~50 instances. Postgres NOTIFY funnels through one wal-sender thread.
• Sub-50ms fanout latency requirement on a high-write DB (NOTIFY is
  serialised with commits).

The contract here (publish/subscribe) is small enough that swapping the
implementation later is a one-file change.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from typing import AsyncIterator

import asyncpg

# Channel keys are short strings so the 8 KB NOTIFY payload limit is
# almost entirely available for the user-facing message:
#   "store:<store_id>"     — admin dashboard subscribes here
#   "session:<session_id>" — widget subscribes here
NOTIFY_CHANNEL = "realtime"


# ── State (module-global; one broker per process) ───────────────────────

# Dedicated long-lived asyncpg connection that holds the LISTEN. NOT
# borrowed from the pool — pool connections get released after each
# query, killing the listener. Set in start(); never released until
# stop() (graceful shutdown).
_listener_conn: asyncpg.Connection | None = None

# channel_name → set[asyncio.Queue] of local subscribers
_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

# Per-subscriber queue size. 100 events is comfortably more than a busy
# session generates in a 5-second window. If a subscriber falls behind
# (slow consumer), queue fills and we drop the oldest events rather than
# block the listener. SSE clients see a gap in the event stream and
# silently re-fetch — better than the whole broker stalling.
SUBSCRIBER_QUEUE_SIZE = 100


# ── Lifecycle ────────────────────────────────────────────────────────────

async def start() -> bool:
    """
    Open the dedicated listener connection and register the NOTIFY
    callback. Idempotent — safe to call from both web startup and worker
    startup. Returns True on success.

    Failure modes (returns False, never raises):
      • DATABASE_URL unset → realtime is a no-op everywhere
      • Connection refused → realtime degrades to no-op until next start()
    """
    global _listener_conn
    if _listener_conn is not None and not _listener_conn.is_closed():
        return True   # already running

    dsn = (os.getenv("DATABASE_URL") or "").strip()
    if not dsn:
        print("[realtime] DATABASE_URL not set — pubsub disabled")
        return False
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://"):]

    try:
        conn = await asyncpg.connect(dsn)
        # JSONB codec — not strictly needed (we ship plain TEXT in NOTIFY),
        # but consistent with the runtime pool keeps debugging painless.
        await conn.add_listener(NOTIFY_CHANNEL, _on_notify)
        _listener_conn = conn
        print(f"[realtime] 🔔 listener connected on channel {NOTIFY_CHANNEL!r}")
        return True
    except Exception as exc:
        print(f"[realtime] ❌ listener start failed: {exc}")
        _listener_conn = None
        return False


async def stop() -> None:
    """Close the listener connection. Safe to call multiple times."""
    global _listener_conn
    if _listener_conn is None:
        return
    try:
        await _listener_conn.remove_listener(NOTIFY_CHANNEL, _on_notify)
    except Exception:
        pass
    try:
        await _listener_conn.close()
    except Exception:
        pass
    _listener_conn = None
    # Wake every subscriber so its SSE generator can exit cleanly.
    for queues in list(_subscribers.values()):
        for q in list(queues):
            try:
                q.put_nowait(None)  # sentinel = "broker stopping"
            except asyncio.QueueFull:
                pass


def available() -> bool:
    return _listener_conn is not None and not _listener_conn.is_closed()


# ── Notify callback (single dispatcher for ALL channels) ────────────────

def _on_notify(_conn, _pid, _channel, payload: str) -> None:
    """
    Called by asyncpg whenever a NOTIFY lands on NOTIFY_CHANNEL.

    Payload format (JSON):
        {"ch": "<channel>", "ev": "<event_type>", "d": <data>}

    "ch" is the logical channel ('store:42'), the asyncpg-level
    NOTIFY_CHANNEL is just the transport. Sub-channel filtering happens
    here in the fan-out so a single Postgres NOTIFY can fan to thousands
    of in-process subscribers cheaply.
    """
    try:
        msg = json.loads(payload)
        ch  = msg.get("ch") or ""
    except Exception as exc:
        print(f"[realtime] bad payload from NOTIFY: {exc}: {payload[:120]!r}")
        return

    queues = _subscribers.get(ch)
    if not queues:
        return  # nobody on this instance listens to this channel

    event = {"type": msg.get("ev", ""), "data": msg.get("d") or {}}

    # Snapshot the set so a concurrent subscribe/unsubscribe during the
    # fan-out doesn't raise.
    for q in list(queues):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Slow consumer — drop the OLDEST item to make room. SSE
            # clients reconnect / re-query on event gaps; missing an
            # event is better than blocking the whole broker.
            try:
                q.get_nowait()
                q.put_nowait(event)
            except Exception:
                pass


# ── Public API: publish ──────────────────────────────────────────────────

async def publish(channel: str, event_type: str, data: dict | None = None) -> None:
    """
    Fire a real-time event. Fanout is best-effort: never raises, logs on
    failure. Callers should treat this as a side-effect — the
    authoritative state is already in the DB (we just notify watchers
    that something changed).

    Channel naming conventions:
      • "store:<store_id>"     — events relevant to the admin dashboard
      • "session:<session_id>" — events relevant to one widget session
    """
    import database as db
    if not db.available():
        return
    payload = json.dumps(
        {"ch": channel, "ev": event_type, "d": data or {}},
        ensure_ascii=False, default=str,
    )
    if len(payload) > 7800:
        # 8 KB is Postgres' hard limit. We trim the data part rather
        # than fail — receivers can re-query for the full record.
        print(f"[realtime] ⚠️ payload >7.8KB for {channel}:{event_type} — trimming")
        payload = json.dumps(
            {"ch": channel, "ev": event_type, "d": {"truncated": True}},
        )
    try:
        async with db._pool.acquire() as conn:  # type: ignore[union-attr]
            # pg_notify() is the function form — accepts parameters,
            # unlike the SQL-keyword NOTIFY which doesn't take $1.
            await conn.execute("SELECT pg_notify($1, $2)", NOTIFY_CHANNEL, payload)
    except Exception as exc:
        print(f"[realtime] publish error ({channel}:{event_type}): {exc}")


# ── Public API: subscribe ────────────────────────────────────────────────

async def subscribe(channel: str) -> AsyncIterator[dict]:
    """
    Yield events from `channel` as they arrive. Use with `async for` from
    an SSE endpoint or any consumer. The async generator owns its
    asyncio.Queue and unregisters on exit (caller breaking the loop OR
    the SSE client disconnecting).

    Yields dicts: {"type": str, "data": dict}

    Yields a final {"type": "_shutdown", "data": {}} if the broker stops.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
    _subscribers[channel].add(q)
    try:
        while True:
            event = await q.get()
            if event is None:
                # Broker stop sentinel.
                yield {"type": "_shutdown", "data": {}}
                return
            yield event
    finally:
        _subscribers[channel].discard(q)
        # GC empty channel entries so the dict doesn't grow forever in
        # long-running processes that touch many sessions.
        if not _subscribers[channel]:
            _subscribers.pop(channel, None)


# ── Diagnostics ──────────────────────────────────────────────────────────

def get_status() -> dict:
    """Snapshot for /env-check style endpoints."""
    return {
        "listener_connected": available(),
        "active_channels":    len(_subscribers),
        "active_subscribers": sum(len(s) for s in _subscribers.values()),
    }
