"""
Async PostgreSQL persistence layer — asyncpg connection pool.

All public functions silently no-op when DATABASE_URL is not configured,
so the app keeps working with in-memory / JSON-file fallback on local dev.

Usage:
    import database as db

    # Startup (in FastAPI lifespan / startup event):
    await db.init()

    # Fire-and-forget from sync code running inside the event loop:
    db.fire(db.save_store(store_id, tokens))
"""

import os
import json
import asyncio
import asyncpg
from typing import Optional

_pool: Optional[asyncpg.Pool] = None


# ── Init & schema ──────────────────────────────────────────────────────────────

async def init() -> bool:
    """
    Connect to PostgreSQL and create tables if they don't exist.
    Returns True on success, False if DATABASE_URL is missing or connection fails.
    """
    global _pool
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        print("[db] DATABASE_URL not set — using filesystem/memory fallback")
        return False

    # Railway sometimes gives postgres:// — asyncpg needs postgresql://
    dsn = dsn.replace("postgres://", "postgresql://", 1)

    try:
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, command_timeout=15)
        await _create_tables()
        print("[db] ✅ PostgreSQL connected and schema ready")
        return True
    except Exception as e:
        print(f"[db] ❌ PostgreSQL connection failed: {e}")
        _pool = None
        return False


async def _create_tables():
    async with _pool.acquire() as conn:
        await conn.execute("""
            -- Stores: tokens, AI config, product cache
            CREATE TABLE IF NOT EXISTS stores (
                store_id     TEXT PRIMARY KEY,
                tokens       JSONB NOT NULL DEFAULT '{}'::jsonb,
                ai_config    JSONB NOT NULL DEFAULT '{}'::jsonb,
                cache_data   JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );

            -- Conversations: full conversation state per session
            CREATE TABLE IF NOT EXISTS conversations (
                session_id   TEXT PRIMARY KEY,
                store_id     TEXT NOT NULL DEFAULT 'default',
                data         JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_conv_store_upd
                ON conversations (store_id, updated_at DESC);

            -- Abandoned carts from webhook notifications
            CREATE TABLE IF NOT EXISTS abandoned_carts (
                pk           BIGSERIAL PRIMARY KEY,
                store_id     TEXT NOT NULL,
                cart_id      TEXT NOT NULL,
                cart_data    JSONB NOT NULL DEFAULT '{}'::jsonb,
                recovered    BOOLEAN NOT NULL DEFAULT FALSE,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (store_id, cart_id)
            );
            CREATE INDEX IF NOT EXISTS idx_abn_store_crt
                ON abandoned_carts (store_id, created_at DESC);
        """)


def available() -> bool:
    """True if the DB pool is up and ready."""
    return _pool is not None


def fire(coro):
    """
    Schedule an async DB coroutine from synchronous code that is already
    running inside an asyncio event loop (e.g. FastAPI route handlers).
    Silently ignored when no event loop is running (unit tests / CLI scripts).
    """
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        pass  # No running loop — skip the write gracefully


# ── Stores ─────────────────────────────────────────────────────────────────────

async def load_all_stores() -> list:
    """
    Return all store rows from the DB.
    Each row: {store_id, tokens, ai_config, cache_data}
    """
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT store_id, tokens, ai_config, cache_data FROM stores"
            )
        return [
            {
                "store_id":  r["store_id"],
                "tokens":    dict(r["tokens"]),
                "ai_config": dict(r["ai_config"]),
                "cache":     dict(r["cache_data"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] load_all_stores error: {e}")
        return []


async def save_store(store_id: str, tokens: dict):
    """Upsert store tokens (access/refresh token, store name, etc.)."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stores (store_id, tokens, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (store_id) DO UPDATE
                  SET tokens = EXCLUDED.tokens, updated_at = NOW()
                """,
                store_id,
                json.dumps(tokens, ensure_ascii=False),
            )
    except Exception as e:
        print(f"[db] save_store({store_id!r}) error: {e}")


async def save_ai_config(store_id: str, ai_config: dict):
    """Upsert only the ai_config column, leaving tokens and cache unchanged."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stores (store_id, ai_config, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (store_id) DO UPDATE
                  SET ai_config = EXCLUDED.ai_config, updated_at = NOW()
                """,
                store_id,
                json.dumps(ai_config, ensure_ascii=False),
            )
    except Exception as e:
        print(f"[db] save_ai_config({store_id!r}) error: {e}")


async def save_cache(store_id: str, cache: dict):
    """Upsert only the product cache column."""
    if not _pool:
        return
    try:
        # Serialise with a default to handle datetime objects in cache
        payload = json.dumps(cache, ensure_ascii=False, default=str)
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stores (store_id, cache_data, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (store_id) DO UPDATE
                  SET cache_data = EXCLUDED.cache_data, updated_at = NOW()
                """,
                store_id,
                payload,
            )
    except Exception as e:
        print(f"[db] save_cache({store_id!r}) error: {e}")


# ── Conversations ──────────────────────────────────────────────────────────────

async def load_conversations(limit: int = 500) -> list:
    """
    Load the most recent `limit` conversations from the DB.
    Returns list of {session_id, store_id, data}.
    """
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
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
                "data":       dict(r["data"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] load_conversations error: {e}")
        return []


async def save_conversation(session_id: str, store_id: str, data: dict):
    """Upsert a full conversation state dict."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
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


# ── Abandoned carts ────────────────────────────────────────────────────────────

async def save_abandoned_cart(store_id: str, cart_id: str, cart_data: dict):
    """Insert a new abandoned cart notification (ignore duplicate cart_ids)."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO abandoned_carts (store_id, cart_id, cart_data)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (store_id, cart_id) DO NOTHING
                """,
                store_id,
                cart_id,
                json.dumps(cart_data, ensure_ascii=False, default=str),
            )
    except Exception as e:
        print(f"[db] save_abandoned_cart({cart_id!r}) error: {e}")


async def load_abandoned_carts(store_id: str) -> list:
    """Return all abandoned cart notifications for a store, newest first."""
    if not _pool:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT cart_id, cart_data, recovered
                FROM abandoned_carts
                WHERE store_id = $1
                ORDER BY created_at DESC
                LIMIT 500
                """,
                store_id,
            )
        result = []
        for r in rows:
            entry = dict(r["cart_data"])
            entry["recovered"] = r["recovered"]
            result.append(entry)
        return result
    except Exception as e:
        print(f"[db] load_abandoned_carts({store_id!r}) error: {e}")
        return []


async def mark_cart_recovered(store_id: str, cart_id: str):
    """Mark a specific abandoned cart as recovered in the DB."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "UPDATE abandoned_carts SET recovered = TRUE WHERE store_id = $1 AND cart_id = $2",
                store_id,
                cart_id,
            )
    except Exception as e:
        print(f"[db] mark_cart_recovered({cart_id!r}) error: {e}")
