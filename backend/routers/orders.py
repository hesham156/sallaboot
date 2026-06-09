"""Orders and abandoned carts routes."""
from fastapi import APIRouter, HTTPException

import database as db
import store_manager as sm

router = APIRouter()


# ── Abandoned carts ───────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/abandoned-carts")
async def store_abandoned_carts(store_id: str, source: str = "cache"):
    if source == "api":
        token = sm.get_access_token(store_id)
        if not token:
            raise HTTPException(400, f"No access token for store '{store_id}'")
        from salla_client import SallaClient
        client = SallaClient(token, store_id=store_id)
        try:
            data  = await client.get_abandoned_carts(per_page=50)
            carts = data.get("data", [])
            return {"source": "api", "carts": carts, "count": len(carts)}
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {e}")

    carts = await db.load_abandoned_carts(store_id) if db.available() else []
    return {"source": "db", "carts": carts, "count": len(carts)}


@router.post("/admin/{store_id}/abandoned-carts/{cart_id}/recover")
async def mark_cart_recovered(store_id: str, cart_id: str):
    await db.mark_cart_recovered(store_id, cart_id)
    return {"status": "ok", "cart_id": cart_id, "recovered": True}


# ── Orders ────────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/orders")
async def store_orders(
    store_id: str,
    page:      int = 1,
    per_page:  int = 20,
    keyword:   str = "",
    status:    str = "",
):
    token = sm.get_access_token(store_id)
    if not token:
        raise HTTPException(400, f"No access token for store '{store_id}'")
    from salla_client import SallaClient
    client = SallaClient(token, store_id=store_id)
    try:
        data = await client.get_orders(
            per_page=per_page,
            page=page,
            keyword=keyword or None,
            status=status or None,
        )
        return data
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.get("/admin/{store_id}/orders/{order_id}")
async def store_order_detail(store_id: str, order_id: str):
    token = sm.get_access_token(store_id)
    if not token:
        raise HTTPException(400, f"No access token for store '{store_id}'")
    from salla_client import SallaClient
    client = SallaClient(token, store_id=store_id)
    try:
        return await client.get_order(order_id)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")
