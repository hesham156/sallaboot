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


# ── Order formatter ─────────────────────────────────────────────────────────────

def format_zid_order(o: dict) -> dict:
    """
    Transform a raw Zid order → the dashboard Order shape (Salla-compatible:
    id / reference_id / status{name,slug} / total{amount,currency} /
    date{date} / customer{first_name,last_name,...}).

    Zid's order payload varies by API version and payload_type, so each value
    tries a few likely keys. Verify against a live Zid store and tighten if a
    field comes back empty.
    """
    cust      = o.get("customer") if isinstance(o.get("customer"), dict) else {}
    cust_name = str(cust.get("name") or "").strip()

    status_blob = o.get("order_status") or o.get("status") or {}
    if isinstance(status_blob, dict):
        status_name = status_blob.get("name") or status_blob.get("code") or ""
        status_slug = status_blob.get("slug") or status_blob.get("code") or ""
    else:
        status_name = str(status_blob or "")
        status_slug = ""

    total_blob = o.get("order_total") or o.get("total") or o.get("amounts") or {}
    if isinstance(total_blob, dict):
        amount   = str(total_blob.get("value") or total_blob.get("amount") or "")
        currency = total_blob.get("currency") or o.get("currency") or "SAR"
    else:
        amount   = str(total_blob or "")
        currency = o.get("currency") or "SAR"

    return {
        "id":           o.get("id"),
        "reference_id": str(o.get("code") or o.get("reference_id") or o.get("id", "")),
        "status":       {"name": status_name, "slug": status_slug},
        "total":        {"amount": amount, "currency": currency},
        "date":         {"date": o.get("created_at") or o.get("created_at_humanize") or "",
                         "timezone": "UTC"},
        "customer": {
            "first_name": cust_name,
            "last_name":  "",
            "mobile":     cust.get("mobile") or cust.get("phone") or "",
            "email":      cust.get("email") or "",
        },
        "platform": "zid",
    }


# ── Incremental product patch ───────────────────────────────────────────────────

async def patch_zid_product(store_id: str, product: dict, deleted: bool = False):
    """
    Update/remove a single product in the in-memory cache + DB.
    Called from the Zid webhook handler (product.create|update|delete).
    """
    cache = sm.get_cache(store_id)
    if not cache:
        return

    store_url = (cache.get("store_info") or {}).get("domain", "")
    pid       = str(product.get("id", ""))
    products: list[dict] = cache.get("products") or []

    if deleted:
        cache["products"] = [p for p in products if str(p.get("id")) != pid]
    else:
        product["_store_url"] = store_url
        updated = format_zid_product(product)
        idx = next((i for i, p in enumerate(products) if str(p.get("id")) == pid), None)
        if idx is not None:
            products[idx] = updated
        else:
            products.append(updated)
        cache["products"] = products

    cache["products_count"] = len(cache["products"])
    sm.set_cache(store_id, cache)


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


async def poll_zid_abandoned_carts(per_page: int = 100) -> int:
    """
    Sweep every connected Zid store for abandoned carts and record newly-seen
    ones (dashboard + owner email + customer WhatsApp) — parity with Salla's
    abandoned.cart webhook. Zid doesn't push these, but exposes a list endpoint
    (a cart is abandoned after 10 min of inactivity), so we poll on a schedule.

    Returns the number of newly-recorded carts. Per-store failures are isolated.
    """
    # Lazy import to avoid a module-load cycle.
    from routers.webhooks import record_abandoned_cart, zid_cart_to_notification

    stores = await db.list_stores_with_integration("zid")
    if not stores:
        return 0
    total_new = 0
    for store_id, cfg in stores:
        access_token = (cfg or {}).get("access_token", "")
        auth_jwt     = (cfg or {}).get("authorization_jwt", "")
        zid_store_id = (cfg or {}).get("zid_store_id", "")
        if not access_token or not auth_jwt:
            continue
        try:
            client = ZidClient(access_token, auth_jwt, zid_store_id=zid_store_id, store_id=store_id)
            carts  = await client.get_abandoned_carts(per_page=per_page)
            for cart in carts:
                notification, phone = zid_cart_to_notification(cart)
                if notification["id"] and await record_abandoned_cart(store_id, notification, phone=phone):
                    total_new += 1
        except Exception as e:
            print(f"[zid_sync] abandoned-cart poll failed for {store_id!r}: {e}")
    if total_new:
        print(f"[zid_sync] 🛒 {total_new} new abandoned cart(s) recorded across {len(stores)} store(s)")
    return total_new


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
