"""database.conversations — split out of the original single-file database.py."""
import json
from database import _core
from database._core import _coerce_jsonb




# ── Bot ROI: orders the bot generated ───────────────────────────────────────

async def record_bot_order(store_id: str, session_id: str, order_ref: str,
                           amount: float, currency: str = "SAR",
                           kind: str = "checkout") -> None:
    """
    Record an order the bot created, for the ROI dashboard. Idempotent on
    (store_id, order_ref) so re-recording the same order doesn't double-count.
    Best-effort — never raises.
    """
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_orders (store_id, session_id, order_ref, amount, currency, kind)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (store_id, order_ref) DO NOTHING
                """,
                store_id, session_id or "", str(order_ref or ""),
                float(amount or 0), currency or "SAR", kind or "checkout",
            )
    except Exception as e:
        print(f"[db] record_bot_order error: {e}")


async def get_weekly_roi(store_id: str) -> dict:
    """
    Bot revenue + order counts for THIS week vs the PREVIOUS week, for the
    weekly report's week-over-week comparison.
    """
    empty = {"rev_this": 0.0, "ord_this": 0, "rev_prev": 0.0, "ord_prev": 0, "currency": "SAR"}
    if not _core._pool:
        return empty
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                  COALESCE(SUM(amount) FILTER (WHERE created_at >= NOW() - interval '7 days'), 0) AS rev_this,
                  COUNT(*)            FILTER (WHERE created_at >= NOW() - interval '7 days')        AS ord_this,
                  COALESCE(SUM(amount) FILTER (WHERE created_at >= NOW() - interval '14 days'
                                               AND created_at <  NOW() - interval '7 days'), 0)     AS rev_prev,
                  COUNT(*)            FILTER (WHERE created_at >= NOW() - interval '14 days'
                                               AND created_at <  NOW() - interval '7 days')         AS ord_prev,
                  MAX(currency) AS currency
                FROM bot_orders
                WHERE store_id = $1
                """,
                store_id,
            )
        if not row:
            return empty
        return {
            "rev_this": round(float(row["rev_this"] or 0), 2),
            "ord_this": int(row["ord_this"] or 0),
            "rev_prev": round(float(row["rev_prev"] or 0), 2),
            "ord_prev": int(row["ord_prev"] or 0),
            "currency": row["currency"] or "SAR",
        }
    except Exception as e:
        print(f"[db] get_weekly_roi error: {e}")
        return empty


async def get_bot_roi(store_id: str, days: int = 30) -> dict:
    """
    Aggregate bot-generated revenue for the last `days`. Returns
    {revenue, orders, currency, avg_order} for the window + all-time totals.
    """
    empty = {"revenue": 0.0, "orders": 0, "currency": "SAR", "avg_order": 0.0,
             "revenue_all": 0.0, "orders_all": 0}
    if not _core._pool:
        return empty
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                  COALESCE(SUM(amount) FILTER (WHERE created_at >= NOW() - ($2 || ' days')::interval), 0) AS revenue,
                  COUNT(*)            FILTER (WHERE created_at >= NOW() - ($2 || ' days')::interval)        AS orders,
                  COALESCE(SUM(amount), 0) AS revenue_all,
                  COUNT(*)                 AS orders_all,
                  MAX(currency)            AS currency
                FROM bot_orders
                WHERE store_id = $1
                """,
                store_id, str(int(days)),
            )
        if not row:
            return empty
        revenue = float(row["revenue"] or 0)
        orders  = int(row["orders"] or 0)
        return {
            "revenue":     round(revenue, 2),
            "orders":      orders,
            "currency":    row["currency"] or "SAR",
            "avg_order":   round(revenue / orders, 2) if orders else 0.0,
            "revenue_all": round(float(row["revenue_all"] or 0), 2),
            "orders_all":  int(row["orders_all"] or 0),
        }
    except Exception as e:
        print(f"[db] get_bot_roi error: {e}")
        return empty


# ── Conversation lookups by customer ────────────────────────────────────────

async def find_session_by_salla_customer(store_id: str, salla_customer_id: str) -> str | None:
    """
    Find the most-recently-active session for a given Salla customer in a
    store. Uses a JSONB path query so it doesn't need a dedicated column —
    cheap enough at small scale; add an expression index on
    (store_id, data->>'salla_customer_id') if this gets slow.
    """
    if not _core._pool or not salla_customer_id:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT session_id FROM conversations
                WHERE store_id = $1
                  AND data->>'salla_customer_id' = $2
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                store_id, str(salla_customer_id),
            )
        return row["session_id"] if row else None
    except Exception as e:
        print(f"[db] find_session_by_salla_customer error: {e}")
        return None


# ── Conversations ──────────────────────────────────────────────────────────────

async def load_conversations(limit: int = 500) -> list:
    """
    Load the most recent `limit` conversations from the DB.
    Returns list of {session_id, store_id, data}.
    """
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, store_id, data
                FROM conversations
                ORDER BY updated_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [
            {
                "session_id": r["session_id"],
                "store_id":   r["store_id"],
                "data":       _coerce_jsonb(r["data"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] load_conversations error: {e}")
        return []


async def load_store_conversations(store_id: str, limit: int = 2000) -> list:
    """
    Load the most recent `limit` conversations for a specific store from the DB.
    Returns list of {session_id, store_id, data}.
    """
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, store_id, data
                FROM conversations
                WHERE store_id = $1
                ORDER BY updated_at DESC
                LIMIT $2
                """,
                store_id,
                limit,
            )
        return [
            {
                "session_id": r["session_id"],
                "store_id":   r["store_id"],
                "data":       _coerce_jsonb(r["data"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] load_store_conversations({store_id!r}) error: {e}")
        return []



async def load_conversation(session_id: str) -> dict | None:
    """Load a specific conversation from the DB. Returns None if missing."""
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM conversations WHERE session_id = $1",
                session_id,
            )
        if not row:
            return None
        return _coerce_jsonb(row["data"])
    except Exception as e:
        print(f"[db] load_conversation({session_id!r}) error: {e}")
        return None



async def save_conversation(session_id: str, store_id: str, data: dict):
    """Upsert a full conversation state dict."""
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO conversations (session_id, store_id, data, updated_at)
                VALUES ($1, $2, $3::jsonb, NOW())
                ON CONFLICT (session_id) DO UPDATE
                  SET data = EXCLUDED.data, store_id = EXCLUDED.store_id,
                      updated_at = NOW()
                """,
                session_id,
                store_id,
                json.dumps(data, ensure_ascii=False, default=str),
            )
    except Exception as e:
        print(f"[db] save_conversation({session_id!r}) error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Dirty-conversation tracking (replaces the in-memory _dirty_sessions set)
# ─────────────────────────────────────────────────────────────────────────────

async def mark_conversation_dirty(session_id: str) -> None:
    """
    Set conversations.dirty_at on the existing row so the periodic flusher
    can find it. No-op when DB is unavailable or the row doesn't exist yet
    (the next save_conversation will create it and the next mark_dirty will
    succeed).
    """
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                "UPDATE conversations SET dirty_at = NOW() WHERE session_id = $1",
                session_id,
            )
    except Exception as e:
        print(f"[db] mark_conversation_dirty error: {e}")


async def fetch_dirty_sessions(limit: int = 200) -> list[str]:
    """Return up to `limit` session_ids that need a flush, oldest first."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id
                FROM conversations
                WHERE dirty_at IS NOT NULL
                ORDER BY dirty_at
                LIMIT $1
                """,
                limit,
            )
        return [r["session_id"] for r in rows]
    except Exception as e:
        print(f"[db] fetch_dirty_sessions error: {e}")
        return []


async def clear_conversation_dirty(session_ids: list[str]) -> None:
    """Clear dirty_at on the given session_ids after a successful save."""
    if not _core._pool or not session_ids:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                "UPDATE conversations SET dirty_at = NULL WHERE session_id = ANY($1::text[])",
                session_ids,
            )
    except Exception as e:
        print(f"[db] clear_conversation_dirty error: {e}")
