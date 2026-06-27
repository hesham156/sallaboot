"""database.carts — split out of the original single-file database.py."""
import json
import crypto as _crypto
from database import _core
from database._core import _coerce_jsonb




# ── Abandoned carts ────────────────────────────────────────────────────────────

async def save_abandoned_cart(store_id: str, cart_id: str, cart_data: dict) -> bool:
    """
    Insert a new abandoned cart notification (ignore duplicate cart_ids).
    Returns True only when a NEW row was inserted — callers use this to avoid
    re-notifying (email/WhatsApp) the same cart on every poll/retry.
    """
    if not _core._pool:
        return False
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.execute(
                """
                INSERT INTO abandoned_carts (store_id, cart_id, cart_data)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (store_id, cart_id) DO NOTHING
                """,
                store_id,
                cart_id,
                json.dumps(cart_data, ensure_ascii=False, default=str),
            )
        # asyncpg returns 'INSERT 0 1' on insert, 'INSERT 0 0' on conflict.
        return bool(r) and r.split()[-1] == "1"
    except Exception as e:
        print(f"[db] save_abandoned_cart({cart_id!r}) error: {e}")
        return False


async def list_stores_with_integration(platform: str) -> list:
    """
    Return [(store_id, integration_cfg_dict), …] for every store that has the
    given platform connected. Used by the abandoned-cart poller (and any other
    per-platform background sweep) to enumerate live integrations.
    """
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT store_id, integrations->$1 AS cfg FROM stores WHERE integrations ? $1",
                platform,
            )
        out = []
        for row in rows:
            cfg = row["cfg"]
            if isinstance(cfg, str):
                try:
                    cfg = json.loads(cfg)
                except Exception:
                    cfg = {}
            # Decrypt OAuth secrets so background sweeps get usable tokens
            # (mirror of save_integration; legacy plaintext passes through).
            cfg = _crypto.decrypt_fields(cfg or {}, _crypto.INTEGRATION_SECRET_FIELDS)
            out.append((row["store_id"], cfg))
        return out
    except Exception as e:
        print(f"[db] list_stores_with_integration({platform!r}) error: {e}")
        return []


async def load_abandoned_carts(store_id: str) -> list:
    """Return all abandoned cart notifications for a store, newest first."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
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
            entry = _coerce_jsonb(r["cart_data"])
            entry["recovered"] = r["recovered"]
            result.append(entry)
        return result
    except Exception as e:
        print(f"[db] load_abandoned_carts({store_id!r}) error: {e}")
        return []


async def mark_cart_recovered(store_id: str, cart_id: str):
    """Mark a specific abandoned cart as recovered in the DB."""
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                "UPDATE abandoned_carts SET recovered = TRUE WHERE store_id = $1 AND cart_id = $2",
                store_id,
                cart_id,
            )
    except Exception as e:
        print(f"[db] mark_cart_recovered({cart_id!r}) error: {e}")
