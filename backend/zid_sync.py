"""
Zid data sync — mirrors shopify_sync.py for the Zid platform.

On first connect (and on-demand):
  • Fetches store info + all products from Zid
  • Stores in stores.cache_data so the AI bot has full product knowledge
  • Registers Zid webhooks for real-time incremental updates
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone

import database as db
import store_manager as sm
from zid_client import ZidClient


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


# ── Product formatter ──────────────────────────────────────────────────────────

def format_zid_product(p: dict) -> dict:
    """Transform raw Zid product JSON → cache_data product format."""
    name     = p.get("name") or p.get("title") or ""
    desc     = _strip_html(p.get("description") or p.get("short_description") or "")[:300]
    price    = str(p.get("price") or p.get("sale_price") or "0")
    old_price = str(p.get("old_price") or p.get("compare_price") or "")
    sku      = p.get("sku") or ""
    qty      = p.get("quantity") if p.get("quantity") is not None else p.get("available_quantity") or 0

    # Status
    published = p.get("is_published", True)
    in_stock  = (qty or 0) > 0 or p.get("unlimited_quantity")
    if not published:
        status = "hidden"
    elif in_stock:
        status = "sale"
    else:
        status = "out"

    # Image
    images = p.get("images") or []
    image_url = ""
    if images:
        first = images[0]
        image_url = first.get("url") or first.get("src") or (first if isinstance(first, str) else "")

    # Categories
    cats = p.get("categories") or []
    categories = [c.get("name", "") if isinstance(c, dict) else str(c) for c in cats]
    categories = [c for c in categories if c]

    # Variants / options
    variants = p.get("variants") or p.get("options") or []
    options_summary: list[dict] = []
    if isinstance(variants, list) and variants and isinstance(variants[0], dict):
        for v in variants[:10]:
            vname  = v.get("name") or v.get("option") or ""
            values = v.get("values") or []
            if vname and values:
                options_summary.append({"option": vname, "values": values})

    # URL
    store_url = p.get("_store_url", "")
    slug      = p.get("slug") or p.get("handle") or ""
    url       = f"{store_url}/products/{slug}" if store_url and slug else p.get("url") or ""

    try:
        sale_price = price if old_price and float(old_price) > float(price) else ""
    except (ValueError, TypeError):
        sale_price = ""

    return {
        "id":               str(p.get("id", "")),
        "name":             name,
        "description":      desc,
        "price":            price,
        "regular_price":    old_price or price,
        "sale_price":       sale_price,
        "currency":         "SAR",
        "status":           status,
        "sku":              sku,
        "quantity":         qty,
        "unlimited_quantity": bool(p.get("unlimited_quantity")),
        "categories":       categories,
        "options":          options_summary,
        "skus":             [],
        "image":            image_url,
        "url":              url,
        "type":             "product",
    }


# ── Full sync ──────────────────────────────────────────────────────────────────

async def sync_zid_store(
    store_id: str,
    access_token: str,
    authorization_jwt: str,
    zid_store_id: str = "",
) -> dict:
    """
    Full sync: fetch products + store info from Zid → cache_data.
    Called after OAuth callback and can be triggered manually.
    """
    client = ZidClient(access_token, authorization_jwt, zid_store_id=zid_store_id, store_id=store_id)
    errors: list[str] = []

    # ── Store info ────────────────────────────────────────────────────────────
    store_info: dict = {}
    store_url   = ""
    try:
        raw = await client.get_store()
        store_url = raw.get("url", "")
        store_info = {
            "id":          str(raw.get("id", zid_store_id)),
            "name":        raw.get("title", ""),
            "entity":      "",
            "email":       raw.get("email", ""),
            "avatar":      "",
            "plan":        "",
            "type":        "zid",
            "status":      "active",
            "verified":    True,
            "currency":    "SAR",
            "domain":      store_url,
            "description": "",
            "licenses":    {},
            "social":      {},
        }
    except Exception as e:
        errors.append(f"store_info: {e}")
        print(f"[zid_sync] store info error: {e}")

    # ── Products ──────────────────────────────────────────────────────────────
    raw_products: list[dict] = []
    try:
        raw_products = await client.get_all_products()
    except Exception as e:
        errors.append(f"products: {e}")
        print(f"[zid_sync] products error: {e}")

    products = []
    for p in raw_products:
        p["_store_url"] = store_url
        products.append(format_zid_product(p))

    # ── Save cache ────────────────────────────────────────────────────────────
    cache = {
        "products":           products,
        "categories":         [],
        "articles":           [],
        "store_info":         store_info,
        "shipping_companies": [],
        "brands":             [],
        "special_offers":     [],
        "branches":           [],
        "payment_methods":    [],
        "shipping_zones":     [],
        "products_count":     len(products),
        "last_sync":          datetime.now(timezone.utc).isoformat(),
        "last_sync_errors":   errors,
        "platform":           "zid",
    }
    sm.set_cache(store_id, cache)

    print(f"[zid_sync] ✅ store={store_id} products={len(products)} errors={errors or 'none'}")
    return {"products": len(products), "errors": errors}


# ── Webhook registration ───────────────────────────────────────────────────────

_WEBHOOK_EVENTS = [
    "order.create",
    "order.status.update",
    "product.create",
    "product.update",
    "product.delete",
    "customer.create",
]


async def register_zid_webhooks(
    access_token: str,
    authorization_jwt: str,
    zid_store_id: str,
    store_id: str,
    base_url: str,
) -> list[dict]:
    """Register Zid webhooks pointing to our handler endpoint."""
    client = ZidClient(access_token, authorization_jwt, zid_store_id=zid_store_id, store_id=store_id)
    results = []
    for event in _WEBHOOK_EVENTS:
        callback = f"{base_url}/webhooks/zid/{store_id}/{event.replace('.', '_')}"
        try:
            r = await client.create_webhook(event, callback)
            results.append({"event": event, "ok": True, "id": r.get("id")})
        except Exception as e:
            results.append({"event": event, "ok": False, "error": str(e)})
            print(f"[zid_sync] webhook {event} registration failed: {e}")
    return results
