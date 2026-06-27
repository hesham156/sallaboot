"""database.queues — split out of the original single-file database.py."""
import json
from database import _core
from database._core import _coerce_jsonb




# ─────────────────────────────────────────────────────────────────────────────
# Webhook inbox (durable ingest queue)
# ─────────────────────────────────────────────────────────────────────────────

async def inbox_insert(
    source: str,
    payload: dict,
    *,
    event_type: str = "",
    dedup_key: str = "",
    store_id: str = "",
    meta: dict | None = None,
) -> dict:
    """
    Insert a new inbox row, atomic dedup on (source, dedup_key).

    Returns {"inserted": bool, "id": int|None}. inserted=False means a row
    with the same dedup_key already exists — Salla/Meta retried a duplicate
    delivery and we should just ack 200 without re-queueing the work.
    """
    if not _core._pool:
        return {"inserted": False, "id": None}
    try:
        async with _core._pool.acquire() as conn:
            _dedup = dedup_key.strip() if dedup_key else ""
            if _dedup:
                # Has a dedup key — use ON CONFLICT to skip duplicates.
                row = await conn.fetchrow(
                    """
                    INSERT INTO webhook_inbox
                        (source, event_type, dedup_key, store_id, payload, meta)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
                    ON CONFLICT (source, dedup_key) WHERE dedup_key IS NOT NULL
                    DO NOTHING
                    RETURNING id
                    """,
                    source, event_type or "", _dedup,
                    store_id or "",
                    json.dumps(payload, ensure_ascii=False, default=str),
                    json.dumps(meta or {}, ensure_ascii=False, default=str),
                )
            else:
                # No dedup key — always insert (no conflict possible on NULL).
                row = await conn.fetchrow(
                    """
                    INSERT INTO webhook_inbox
                        (source, event_type, dedup_key, store_id, payload, meta)
                    VALUES ($1, $2, NULL, $3, $4::jsonb, $5::jsonb)
                    RETURNING id
                    """,
                    source, event_type or "",
                    store_id or "",
                    json.dumps(payload, ensure_ascii=False, default=str),
                    json.dumps(meta or {}, ensure_ascii=False, default=str),
                )
        if row is None:
            return {"inserted": False, "id": None}
        return {"inserted": True, "id": int(row["id"])}
    except Exception as e:
        print(f"[db] inbox_insert error: {e}")
        return {"inserted": False, "id": None}


async def inbox_claim_batch(worker_id: str, limit: int = 20) -> list[dict]:
    """
    Atomic batch-claim: pick up to `limit` pending/retryable rows, mark them
    `processing`, and return them. Uses SELECT FOR UPDATE SKIP LOCKED so
    multiple drainer instances can run side-by-side without contention.
    """
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH cte AS (
                    SELECT id
                    FROM webhook_inbox
                    WHERE status IN ('pending', 'failed')
                    ORDER BY created_at
                    LIMIT $2
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE webhook_inbox w
                   SET status     = 'processing',
                       attempts   = w.attempts + 1,
                       claimed_by = $1,
                       claimed_at = NOW()
                  FROM cte
                 WHERE w.id = cte.id
              RETURNING w.id, w.source, w.event_type, w.dedup_key,
                        w.store_id, w.payload, w.meta, w.attempts
                """,
                worker_id, limit,
            )
        return [
            {
                "id":         int(r["id"]),
                "source":     r["source"],
                "event_type": r["event_type"] or "",
                "dedup_key":  r["dedup_key"] or "",
                "store_id":   r["store_id"] or "",
                "payload":    _coerce_jsonb(r["payload"]),
                "meta":       _coerce_jsonb(r["meta"]),
                "attempts":   int(r["attempts"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] inbox_claim_batch error: {e}")
        return []


async def inbox_mark_done(inbox_id: int) -> None:
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                "UPDATE webhook_inbox SET status='done', processed_at=NOW(), last_error=NULL "
                "WHERE id=$1",
                inbox_id,
            )
    except Exception as e:
        print(f"[db] inbox_mark_done error: {e}")


# Same retry ladder used for the outbox (kept here so both drainers behave the
# same way for ops/runbooks). Index = attempts after the failure.
_RETRY_BACKOFF_SECONDS = (5, 30, 120, 600, 1800)   # 5s, 30s, 2m, 10m, 30m
_MAX_ATTEMPTS = 5


async def inbox_mark_failed(inbox_id: int, error: str, attempts: int) -> None:
    """
    Record a processing failure. After _MAX_ATTEMPTS the row is parked as
    `dead` for human inspection — never silently dropped.
    """
    if not _core._pool:
        return
    final = attempts >= _MAX_ATTEMPTS
    status = "dead" if final else "failed"
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                "UPDATE webhook_inbox SET status=$2, last_error=$3 WHERE id=$1",
                inbox_id, status, (error or "")[:2000],
            )
    except Exception as e:
        print(f"[db] inbox_mark_failed error: {e}")


async def inbox_count_by_status() -> dict:
    """Health snapshot for /admin/db-test and a future ops dashboard."""
    if not _core._pool:
        return {}
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT status, COUNT(*) AS n FROM webhook_inbox GROUP BY status"
            )
        return {r["status"]: int(r["n"]) for r in rows}
    except Exception as e:
        print(f"[db] inbox_count_by_status error: {e}")
        return {}


async def prune_inbox_done(keep_last_days: int = 14) -> int:
    """Drop processed inbox rows older than N days. DEAD rows are kept."""
    if not _core._pool:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM webhook_inbox "
                "WHERE status='done' AND processed_at < NOW() - ($1 || ' days')::interval",
                str(int(keep_last_days)),
            )
        # asyncpg returns 'DELETE <rowcount>' on success
        try:
            return int(result.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_inbox_done error: {e}")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Outbox (durable outbound delivery queue)
# ─────────────────────────────────────────────────────────────────────────────

async def outbox_enqueue(kind: str, payload: dict, *, store_id: str = "") -> int | None:
    """Schedule an outbound side-effect (email, custom webhook, WhatsApp send)."""
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO outbox (kind, store_id, payload)
                VALUES ($1, $2, $3::jsonb)
                RETURNING id
                """,
                kind, store_id or "",
                json.dumps(payload, ensure_ascii=False, default=str),
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] outbox_enqueue error: {e}")
        return None


async def outbox_claim_batch(worker_id: str, limit: int = 20) -> list[dict]:
    """Same claim-pattern as the inbox, scoped to outbox rows due now."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH cte AS (
                    SELECT id
                    FROM outbox
                    WHERE status IN ('pending', 'failed')
                      AND next_attempt_at <= NOW()
                    ORDER BY next_attempt_at
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE outbox o
                   SET status   = 'processing',
                       attempts = o.attempts + 1
                  FROM cte
                 WHERE o.id = cte.id
              RETURNING o.id, o.kind, o.store_id, o.payload, o.attempts
                """,
                limit,
            )
        return [
            {
                "id":       int(r["id"]),
                "kind":     r["kind"],
                "store_id": r["store_id"] or "",
                "payload":  _coerce_jsonb(r["payload"]),
                "attempts": int(r["attempts"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] outbox_claim_batch error: {e}")
        return []


async def outbox_mark_sent(outbox_id: int) -> None:
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                "UPDATE outbox SET status='done', sent_at=NOW(), last_error=NULL WHERE id=$1",
                outbox_id,
            )
    except Exception as e:
        print(f"[db] outbox_mark_sent error: {e}")


async def outbox_mark_failed(outbox_id: int, error: str, attempts: int) -> None:
    """Apply exponential backoff or park as dead after MAX_ATTEMPTS."""
    if not _core._pool:
        return
    final = attempts >= _MAX_ATTEMPTS
    status = "dead" if final else "failed"
    delay_idx = min(attempts - 1, len(_RETRY_BACKOFF_SECONDS) - 1)
    delay_secs = _RETRY_BACKOFF_SECONDS[max(0, delay_idx)]
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox
                   SET status          = $2,
                       last_error      = $3,
                       next_attempt_at = NOW() + ($4 || ' seconds')::interval
                 WHERE id = $1
                """,
                outbox_id, status, (error or "")[:2000], str(delay_secs),
            )
    except Exception as e:
        print(f"[db] outbox_mark_failed error: {e}")


async def outbox_count_by_status() -> dict:
    if not _core._pool:
        return {}
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT status, COUNT(*) AS n FROM outbox GROUP BY status"
            )
        return {r["status"]: int(r["n"]) for r in rows}
    except Exception as e:
        print(f"[db] outbox_count_by_status error: {e}")
        return {}


async def prune_outbox_sent(keep_last_days: int = 7) -> int:
    if not _core._pool:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM outbox WHERE status='done' AND sent_at < NOW() - ($1 || ' days')::interval",
                str(int(keep_last_days)),
            )
        try:
            return int(result.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_outbox_sent error: {e}")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Widget outbox — per-session durable queue for messages destined to the
# widget (admin replies, post-chat bot follow-ups, CSAT prompts).
#
# Why this is its own table and not just `outbox`:
#   • Routing is by session_id, not by `kind`. The generic outbox is
#     drained by a worker; this queue is consumed inline by the per-
#     session SSE generator on flush-on-connect.
#   • No retry/backoff/DLQ — delivery is SSE, the only failure mode is
#     "client disconnected", and the next reconnect replays the same
#     pending rows.
#   • Different cleanup policy — delivered rows are pruned after 24h
#     instead of the outbox's 7 days.
# ─────────────────────────────────────────────────────────────────────────────

async def widget_outbox_enqueue(session_id: str, payload: dict) -> int | None:
    """
    Append one message for this session to the widget queue. Returns the
    new row id, or None if DB is unavailable (caller treats None as
    best-effort — the realtime NOTIFY will still fire for live SSE
    clients; only the catch-up-on-reconnect path is degraded).
    """
    if not _core._pool or not session_id:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO widget_outbox (session_id, payload)
                VALUES ($1, $2::jsonb)
                RETURNING id
                """,
                session_id,
                json.dumps(payload or {}, ensure_ascii=False, default=str),
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] widget_outbox_enqueue({session_id!r}) error: {e}")
        return None


async def widget_outbox_claim_pending(session_id: str, limit: int = 100) -> list[dict]:
    """
    Atomic claim-and-mark for the widget's flush-on-connect path. Picks
    up to `limit` undelivered rows for this session (oldest first), marks
    them delivered in the same transaction, and returns the payloads.

    `FOR UPDATE SKIP LOCKED` means two concurrent reconnects of the
    same session_id don't both deliver the same message — the second
    one gets nothing (correct: it's the same logical client).

    Trade-off: marking delivered BEFORE the SSE yield means a connection
    drop between this query and the actual yield loses those messages.
    The alternative (mark AFTER yield) double-delivers on reconnect. We
    accept the loss because:
      • The realtime NOTIFY fired at the time of the original write —
        a connected widget already saw the message live.
      • For a disconnected widget catching up, missing one message in
        the catch-up window is less disruptive than a duplicate.
      • Widget reconnects are rare enough that this is a noise-level
        edge case, not a steady-state property.
    """
    if not _core._pool or not session_id:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH cte AS (
                    SELECT id
                    FROM widget_outbox
                    WHERE session_id = $1 AND delivered_at IS NULL
                    ORDER BY created_at
                    LIMIT $2
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE widget_outbox w
                   SET delivered_at = NOW()
                  FROM cte
                 WHERE w.id = cte.id
              RETURNING w.id, w.payload
                """,
                session_id, limit,
            )
        return [_coerce_jsonb(r["payload"]) for r in rows]
    except Exception as e:
        print(f"[db] widget_outbox_claim_pending({session_id!r}) error: {e}")
        return []


async def widget_outbox_pending_count(session_id: str) -> int:
    """Diagnostic: how many undelivered rows are sitting for this session."""
    if not _core._pool or not session_id:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM widget_outbox "
                "WHERE session_id = $1 AND delivered_at IS NULL",
                session_id,
            )
        return int(row["n"]) if row else 0
    except Exception as e:
        print(f"[db] widget_outbox_pending_count error: {e}")
        return 0


async def prune_widget_outbox_delivered(keep_last_hours: int = 24) -> int:
    """
    Drop widget_outbox rows whose delivered_at is older than N hours.
    Pending rows (delivered_at IS NULL) are NEVER pruned — they would
    represent un-delivered messages and must survive until consumed.
    """
    if not _core._pool:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM widget_outbox "
                "WHERE delivered_at IS NOT NULL "
                "  AND delivered_at < NOW() - ($1 || ' hours')::interval",
                str(int(keep_last_hours)),
            )
        try:
            return int(result.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_widget_outbox_delivered error: {e}")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Leader election (DB-row lease)
# ─────────────────────────────────────────────────────────────────────────────
# Used by periodic loops so a multi-instance deploy doesn't double-run them
# (e.g. token-refresh racing between web instances).
#
# The model is a "renewable TTL lease":
#   • try_lead(name, holder, ttl): inserts/refreshes the lock row.
#     Returns True if THIS holder is now the leader for the next ttl seconds.
#   • The leader either calls try_lead() again before expiry (renew), or
#     lets it lapse so another instance takes over.
#   • No automatic release on crash — the TTL handles it. Pick a TTL that
#     is comfortably longer than the loop's iteration time.
#
# Why not pg_advisory_lock? Advisory locks are session-scoped, so they
# need a dedicated long-lived connection per leader, plus they're invisible
# from outside SQL. The leader_locks table is observable, debuggable, and
# survives pool-connection churn.

async def try_lead(name: str, holder_id: str, ttl_seconds: int = 300) -> bool:
    """
    Atomically acquire OR renew leadership of `name` for `ttl_seconds`.
    Returns True iff after this call, `holder_id` holds the lock.

    Behaviour matrix:
      • No existing row              → INSERT, this holder wins.
      • Existing row, expired        → UPDATE to this holder, win.
      • Existing row held by SAME id → UPDATE (renew), win.
      • Existing row held by OTHER + not expired → no change, lose.
    """
    if not _core._pool:
        # No DB → can't coordinate. Best to assume sole leadership so
        # standalone-DB-less mode keeps periodic jobs running.
        return True
    try:
        async with _core._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO leader_locks (name, holder, acquired_at, expires_at)
                VALUES ($1, $2, NOW(), NOW() + ($3 || ' seconds')::interval)
                ON CONFLICT (name) DO UPDATE
                  SET holder      = EXCLUDED.holder,
                      acquired_at = NOW(),
                      expires_at  = EXCLUDED.expires_at
                  WHERE leader_locks.expires_at < NOW()
                     OR leader_locks.holder = EXCLUDED.holder
                """,
                name, holder_id, str(int(ttl_seconds)),
            )
        # asyncpg returns 'INSERT 0 N' or 'UPDATE N'. N=1 means we own it.
        try:
            count = int(result.split()[-1])
        except Exception:
            return False
        return count == 1
    except Exception as e:
        print(f"[db] try_lead({name!r}) error: {e}")
        return False


async def release_leader(name: str, holder_id: str) -> None:
    """
    Voluntary release — clears the row if this holder still owns it.
    Idempotent; safe to call from a finally block on graceful shutdown.
    Optional: the TTL handles crashes; this just frees the slot sooner.
    """
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM leader_locks WHERE name=$1 AND holder=$2",
                name, holder_id,
            )
    except Exception as e:
        print(f"[db] release_leader({name!r}) error: {e}")


async def list_leader_locks() -> list[dict]:
    """Snapshot of who holds what — for /env-check style diagnostics."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name, holder, acquired_at, expires_at FROM leader_locks ORDER BY name"
            )
        return [
            {
                "name":        r["name"],
                "holder":      r["holder"],
                "acquired_at": r["acquired_at"].isoformat() if r["acquired_at"] else "",
                "expires_at":  r["expires_at"].isoformat()  if r["expires_at"]  else "",
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] list_leader_locks error: {e}")
        return []
