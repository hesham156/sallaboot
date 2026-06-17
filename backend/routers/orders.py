"""Orders and abandoned carts routes."""
from fastapi import APIRouter, HTTPException

import database as db
import store_manager as sm

router = APIRouter()


async def _get_shopify_creds(store_id: str) -> tuple[str, str] | None:
    """Returns (shop, access_token) if this store has a live Shopify integration."""
    integrations = await db.get_integrations(store_id)
    s = integrations.get("shopify", {})
    shop  = s.get("shop", "")
    token = s.get("access_token", "")
    return (shop, token) if shop and token else None


# ── Abandoned carts ───────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/abandoned-carts")
async def store_abandoned_carts(store_id: str, source: str = "cache"):
    # If this store uses Shopify, never fall back to Salla tokens
    shopify_creds = await _get_shopify_creds(store_id)
    if shopify_creds:
        # Shopify doesn't push abandoned-cart webhooks to us yet — return DB cache
        # (will be empty until Shopify checkout webhooks are wired up)
        carts = await db.load_abandoned_carts(store_id) if db.available() else []
        return {"source": "db", "platform": "shopify", "carts": carts, "count": len(carts)}

    if source == "api":
        token = sm.get_access_token(store_id)
        if not token:
            raise HTTPException(400, f"No access token for store '{store_id}'")
        from salla_client import SallaClient
        client = SallaClient(token, store_id=store_id)
        try:
            data  = await client.get_abandoned_carts(per_page=50)
            carts = data.get("data", [])
            return {"source": "api", "platform": "salla", "carts": carts, "count": len(carts)}
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {e}")

    carts = await db.load_abandoned_carts(store_id) if db.available() else []
    return {"source": "db", "platform": "salla", "carts": carts, "count": len(carts)}


@router.post("/admin/{store_id}/abandoned-carts/{cart_id}/recover")
async def mark_cart_recovered(store_id: str, cart_id: str):
    await db.mark_cart_recovered(store_id, cart_id)
    return {"status": "ok", "cart_id": cart_id, "recovered": True}


# ── Orders ────────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/orders")
async def store_orders(
    store_id:  str,
    page:      int = 1,
    per_page:  int = 20,
    keyword:   str = "",
    status:    str = "",
    page_info: str = "",   # Shopify cursor pagination
):
    # ── Shopify store ─────────────────────────────────────────────────────────
    shopify_creds = await _get_shopify_creds(store_id)
    if shopify_creds:
        from shopify_client import ShopifyClient
        from shopify_sync import format_shopify_order
        shop, access_token = shopify_creds
        client = ShopifyClient(shop, access_token, store_id=store_id)
        try:
            raw = await client.get_orders(
                limit=per_page,
                page_info=page_info or None,
                status="any",
                financial_status=status or None,
            )
            orders = [format_shopify_order(o) for o in raw["orders"]]
            return {
                "data":            orders,
                "platform":        "shopify",
                "next_page_info":  raw.get("next_page_info"),
                "pagination": {
                    "per_page":     per_page,
                    "current_page": page,
                    "total":        None,  # Shopify doesn't return total on paginated calls
                },
            }
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {e}")

    # ── Salla store ───────────────────────────────────────────────────────────
    token = sm.get_access_token(store_id)
    if not token:
        raise HTTPException(400, f"No access token for store '{store_id}'")
    from salla_client import SallaClient
    client = SallaClient(token, store_id=store_id)
    try:
        return await client.get_orders(
            per_page=per_page,
            page=page,
            keyword=keyword or None,
            status=status or None,
        )
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.get("/admin/{store_id}/orders/{order_id}")
async def store_order_detail(store_id: str, order_id: str):
    # ── Shopify store ─────────────────────────────────────────────────────────
    shopify_creds = await _get_shopify_creds(store_id)
    if shopify_creds:
        from shopify_client import ShopifyClient
        from shopify_sync import format_shopify_order
        shop, access_token = shopify_creds
        client = ShopifyClient(shop, access_token, store_id=store_id)
        try:
            raw = await client.get_order(order_id)
            return {"data": format_shopify_order(raw), "platform": "shopify"}
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {e}")

    # ── Salla store ───────────────────────────────────────────────────────────
    token = sm.get_access_token(store_id)
    if not token:
        raise HTTPException(400, f"No access token for store '{store_id}'")
    from salla_client import SallaClient
    client = SallaClient(token, store_id=store_id)
    try:
        return await client.get_order(order_id)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")
