"""
Shopify data sync — mirrors what store_sync.py does for Salla.

On first connect (and on-demand):
  • Fetches all products + shop info from Shopify
  • Stores in stores.cache_data so the AI bot has full product knowledge
  • Registers Shopify webhooks for real-time incremental updates

Incremental updates (via webhooks) handled in routers/webhooks.py.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone

import database as db
import store_manager as sm
from shopify_client import ShopifyClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


# ── Product formatter ─────────────────────────────────────────────────────────

def format_shopify_product(p: dict, currency: str = "") -> dict:
    """Transform raw Shopify product JSON → cache_data product format."""
    variants = p.get("variants") or []
    images   = p.get("images") or []
    options  = p.get("options") or []
    shop     = p.get("_shop", "")   # injected by caller

    first_v       = variants[0] if variants else {}
    price_str     = first_v.get("price", "0") or "0"
    compare_price = first_v.get("compare_at_price") or ""

    # Options (Size, Color, etc.) — skip Shopify's fake "Title" default
    options_summary = []
    for opt in options:
        name = opt.get("name", "")
        vals = [v for v in (opt.get("values") or []) if v and v.lower() != "default title"]
        if name and name.lower() != "title" and vals:
            options_summary.append({"option": name, "values": vals})

    # SKU / variant summary (max 10)
    skus_summary = []
    for v in variants[:10]:
        vp  = v.get("price", "")
        sku = v.get("sku", "")
        qty = v.get("inventory_quantity", 0)
        pol = v.get("inventory_policy", "deny")
        skus_summary.append({
            "sku":   sku,
            "price": vp,
            "qty":   "غير محدودة" if pol == "continue" else qty,
        })

    # Inventory status
    track = first_v.get("inventory_management") == "shopify"
    total_qty = sum(v.get("inventory_quantity", 0) for v in variants)
    pol   = first_v.get("inventory_policy", "deny")
    if p.get("status") == "active":
        status = "sale" if (not track or pol == "continue" or total_qty > 0) else "out"
    else:
        status = "hidden"

    image_url = images[0].get("src", "") if images else ""

    # Use Shopify tags as categories (best we can without fetching collections)
    categories = [t.strip() for t in (p.get("tags") or "").split(",") if t.strip()]

    handle = p.get("handle", "")
    url    = f"https://{shop}/products/{handle}" if shop and handle else ""

    try:
        sale_price = price_str if compare_price and float(compare_price) > float(price_str) else ""
    except (ValueError, TypeError):
        sale_price = ""

    return {
        "id":               str(p.get("id", "")),
        "name":             p.get("title", ""),
        "description":      _strip_html(p.get("body_html", ""))[:300],
        "price":            price_str,
        "regular_price":    compare_price or price_str,
        "sale_price":       sale_price,
        "currency":         currency,
        "status":           status,
        "sku":              first_v.get("sku", ""),
        "quantity":         total_qty,
        "unlimited_quantity": pol == "continue",
        "categories":       categories,
        "options":          options_summary,
        "skus":             skus_summary,
        "image":            image_url,
        "url":              url,
        "type":             "product",
    }


# ── Shopify → Salla-compatible order format ───────────────────────────────────

_FINANCIAL_STATUS_AR = {
    "paid":            "مدفوع",
    "partially_paid":  "مدفوع جزئياً",
    "refunded":        "مسترجع",
    "pending":         "معلّق",
    "voided":          "ملغى",
    "partially_refunded": "مسترجع جزئياً",
    "unpaid":          "غير مدفوع",
}

_FULFILLMENT_STATUS_AR = {
    "fulfilled":         "مُنجَز",
    "partial":           "منجز جزئياً",
    "unfulfilled":       "قيد التنفيذ",
    "restocked":         "مُعاد للمخزن",
    None:                "قيد التنفيذ",
}


def format_shopify_order(o: dict) -> dict:
    """Transform Shopify order JSON → Salla-compatible order shape."""
    customer = o.get("customer") or {}
    fname    = customer.get("first_name", "")
    lname    = customer.get("last_name", "")
    cname    = f"{fname} {lname}".strip() or customer.get("email", "") or "زبون"

    fin_status = o.get("financial_status", "")
    ful_status = o.get("fulfillment_status")
    status_ar  = _FULFILLMENT_STATUS_AR.get(ful_status, "قيد التنفيذ")
    if fin_status == "paid":
        status_ar = f"مدفوع — {status_ar}"

    items = o.get("line_items") or []
    items_summary = [
        {
            "name":      i.get("title", ""),
            "quantity":  i.get("quantity", 1),
            "price":     i.get("price", "0"),
        }
        for i in items
    ]

    address = o.get("shipping_address") or o.get("billing_address") or {}

    return {
        "id":           o.get("id"),
        "reference_id": o.get("name", f"#{o.get('order_number', o.get('id', ''))}"),
        "date":         {"date": o.get("created_at", ""), "timezone": "UTC"},
        "status": {
            "id":    o.get("financial_status", ""),
            "name":  status_ar,
            "color": "#22c55e" if fin_status == "paid" else "#f59e0b",
        },
        "payment": {
            "method": o.get("payment_gateway", ""),
            "status": _FINANCIAL_STATUS_AR.get(fin_status, fin_status),
        },
        "customer": {
            "id":     customer.get("id"),
            "name":   cname,
            "mobile": customer.get("phone", "") or address.get("phone", ""),
            "email":  customer.get("email", ""),
        },
        "amounts": {
            "total": {
                "amount":   o.get("total_price", "0"),
                "currency": o.get("currency", ""),
            },
            "subtotal": {
                "amount":   o.get("subtotal_price", "0"),
                "currency": o.get("currency", ""),
            },
        },
        "items":    items_summary,
        "notes":    o.get("note", ""),
        "tags":     o.get("tags", ""),
        "platform": "shopify",
    }


# ── Catalogue-context formatters (→ the shared cache shapes the bot reads) ─────

def _format_location(loc: dict) -> dict:
    addr = " ".join(p for p in [loc.get("address1", ""), loc.get("address2", "")] if p).strip()
    return {
        "id":      loc.get("id"),
        "name":    loc.get("name", ""),
        "city":    loc.get("city", ""),
        "country": loc.get("country_name") or loc.get("country", ""),
        "address": addr,
        "phone":   loc.get("phone", ""),
    }


def _format_shipping_zone(z: dict) -> dict:
    countries = z.get("countries") or []
    country_names = [c.get("name", "") for c in countries if c.get("name")]
    provinces = [
        p.get("name", "")
        for c in countries
        for p in (c.get("provinces") or [])
        if p.get("name")
    ]
    return {
        "id":      z.get("id"),
        "name":    z.get("name", ""),
        "country": ", ".join(country_names),
        "cities":  provinces,
        "status":  "active",
    }


def _format_price_rule(r: dict) -> dict | None:
    """Map a Shopify price rule → the shared offer shape. Returns None if expired."""
    ends_at = r.get("ends_at")
    if ends_at:
        try:
            if datetime.fromisoformat(ends_at.replace("Z", "+00:00")) < datetime.now(timezone.utc):
                return None
        except Exception:
            pass
    vtype = r.get("value_type", "")
    raw   = str(r.get("value", "")).lstrip("-")
    if vtype == "percentage":
        message = f"خصم {raw}%"
    elif vtype == "fixed_amount":
        message = f"خصم {raw}"
    else:
        message = r.get("title", "")
    return {
        "id":         r.get("id"),
        "name":       r.get("title", ""),
        "type":       vtype,
        "message":    message,
        "applied_to": r.get("target_selection", ""),
        "start_date": r.get("starts_at", "") or "",
        "end_date":   ends_at or "",
    }


# ── Full sync ─────────────────────────────────────────────────────────────────

async def sync_shopify_store(store_id: str, shop: str, access_token: str) -> dict:
    """
    Full sync: fetch products + store info from Shopify → cache_data.
    Called after OAuth callback and can be triggered manually from the dashboard.
    """
    client = ShopifyClient(shop, access_token, store_id=store_id)
    errors: list[str] = []

    # ── Shop info ─────────────────────────────────────────────────────────────
    shop_info: dict = {}
    currency = ""
    try:
        raw = await client.get_shop()
        currency = raw.get("currency", "")
        shop_info = {
            "id":          str(raw.get("id", "")),
            "name":        raw.get("name", shop),
            "entity":      "",
            "email":       raw.get("email", ""),
            "avatar":      raw.get("logo", ""),
            "plan":        raw.get("plan_name", ""),
            "type":        "shopify",
            "status":      "active",
            "verified":    True,
            "currency":    currency,
            "domain":      raw.get("domain", shop),
            "description": raw.get("description", ""),
            "licenses":    {},
            "social":      {},
        }
    except Exception as e:
        errors.append(f"shop_info: {e}")
        print(f"[shopify_sync] shop info error: {e}")

    # ── Products ──────────────────────────────────────────────────────────────
    raw_products: list[dict] = []
    try:
        raw_products = await client.get_all_products()
    except Exception as e:
        errors.append(f"products: {e}")
        print(f"[shopify_sync] products error: {e}")

    products = []
    for p in raw_products:
        p["_shop"] = shop
        products.append(format_shopify_product(p, currency=currency))

    # ── Branches / shipping / offers (parity with Salla's catalogue sync, so
    #    the bot can answer "where are you?" / "how do you ship?" / "any offers?").
    #    Each is best-effort: a missing scope (403) must not break the product sync.
    branches: list[dict] = []
    try:
        branches = [_format_location(loc) for loc in await client.get_locations()]
    except Exception as e:
        errors.append(f"locations: {e}")
        print(f"[shopify_sync] locations error: {e}")

    shipping_zones: list[dict] = []
    try:
        shipping_zones = [_format_shipping_zone(z) for z in await client.get_shipping_zones()]
    except Exception as e:
        errors.append(f"shipping_zones: {e}")
        print(f"[shopify_sync] shipping_zones error: {e}")

    special_offers: list[dict] = []
    try:
        special_offers = [_format_price_rule(r) for r in await client.get_price_rules()]
        special_offers = [o for o in special_offers if o]   # drop expired
    except Exception as e:
        errors.append(f"price_rules: {e}")
        print(f"[shopify_sync] price_rules error: {e}")

    # ── Save cache ────────────────────────────────────────────────────────────
    cache = {
        "products":           products,
        "categories":         [],
        "articles":           [],
        "store_info":         shop_info,
        "shipping_companies": [],
        "brands":             [],
        "special_offers":     special_offers,
        "branches":           branches,
        "payment_methods":    [],   # Shopify has no clean REST list of enabled gateways
        "shipping_zones":     shipping_zones,
        "products_count":     len(products),
        "last_sync":          datetime.now(timezone.utc).isoformat(),
        "last_sync_errors":   errors,
        "platform":           "shopify",
    }
    sm.set_cache(store_id, cache)

    print(f"[shopify_sync] ✅ store={store_id} products={len(products)} errors={errors or 'none'}")
    return {"products": len(products), "errors": errors}


# ── Incremental product patch ─────────────────────────────────────────────────

async def patch_shopify_product(store_id: str, product: dict, deleted: bool = False):
    """
    Update/remove a single product in the in-memory cache + DB.
    Called from the Shopify webhook handler.
    """
    cache = sm.get_cache(store_id)
    if not cache:
        return

    shop     = (cache.get("store_info") or {}).get("domain", "")
    currency = (cache.get("store_info") or {}).get("currency", "")
    pid      = str(product.get("id", ""))
    products: list[dict] = cache.get("products") or []

    if deleted:
        cache["products"] = [p for p in products if str(p.get("id")) != pid]
    else:
        product["_shop"] = shop
        updated = format_shopify_product(product, currency=currency)
        idx = next((i for i, p in enumerate(products) if str(p.get("id")) == pid), None)
        if idx is not None:
            products[idx] = updated
        else:
            products.append(updated)
        cache["products"] = products

    cache["products_count"] = len(cache["products"])
    sm.set_cache(store_id, cache)


# ── Webhook registration ──────────────────────────────────────────────────────

_WEBHOOK_TOPICS = [
    "products/create",
    "products/update",
    "products/delete",
    "orders/create",
    "orders/updated",
    "fulfillments/create",
    "customers/create",
    "app/uninstalled",
]


async def poll_abandoned_checkouts(lookback_hours: int = 48) -> int:
    """
    Sweep every connected Shopify store for abandoned checkouts and record the
    newly-seen ones (dashboard row + owner email + customer WhatsApp) — the
    parity equivalent of Salla's abandoned.cart webhook. Shopify has no
    abandoned webhook, so this is polled on a schedule by lifecycle.

    Returns the number of newly-recorded carts. Per-store failures are isolated.
    """
    from datetime import timedelta
    # Lazy import to avoid a module-load cycle (webhooks → store_sync → …).
    from routers.webhooks import record_abandoned_cart, shopify_checkout_to_notification

    stores = await db.list_stores_with_integration("shopify")
    if not stores:
        return 0
    created_min = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    total_new = 0
    for store_id, cfg in stores:
        shop  = (cfg or {}).get("shop", "")
        token = (cfg or {}).get("access_token", "")
        if not shop or not token:
            continue
        try:
            client    = ShopifyClient(shop, token, store_id=store_id)
            checkouts = await client.get_abandoned_checkouts(created_at_min=created_min)
            for co in checkouts:
                notification, phone = shopify_checkout_to_notification(co)
                if notification["id"] and await record_abandoned_cart(store_id, notification, phone=phone):
                    total_new += 1
        except Exception as e:
            print(f"[shopify_sync] abandoned-cart poll failed for {store_id!r}: {e}")
    if total_new:
        print(f"[shopify_sync] 🛒 {total_new} new abandoned checkout(s) recorded across {len(stores)} store(s)")
    return total_new


async def register_shopify_webhooks(shop: str, access_token: str, store_id: str, base_url: str):
    """Register all required Shopify webhooks pointing to our handler endpoint."""
    client = ShopifyClient(shop, access_token, store_id=store_id)
    callback_base = f"{base_url}/webhooks/shopify/{store_id}"
    results = []
    for topic in _WEBHOOK_TOPICS:
        try:
            r = await client.register_webhook(topic, f"{callback_base}/{topic.replace('/', '_')}")
            results.append({"topic": topic, "ok": True, "id": (r.get("webhook") or {}).get("id")})
        except Exception as e:
            results.append({"topic": topic, "ok": False, "error": str(e)})
            print(f"[shopify_sync] webhook {topic} registration failed: {e}")
    return results
