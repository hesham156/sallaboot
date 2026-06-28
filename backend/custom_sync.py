"""
Custom-store sync — for merchants running a self-built / custom-coded store
that isn't on Salla, Zid or Shopify.

Unlike the other platforms, 7ayak (حياك) has no vendor API to pull from. Instead
the merchant's own backend PUSHES data to us:

  • Full catalog       → POST /webhooks/custom/{store_id}/catalog  → apply_catalog
  • Incremental events → POST /webhooks/custom/{store_id}/events   → process_custom_event
    (product.created|updated|deleted, order.created, order.status_updated,
     cart.abandoned)

This module owns the data-shaping half (raw JSON → cache_data product format and
→ the shared abandoned-cart notification shape). The HTTP/auth half lives in
routers/webhooks/custom.py. Mirrors zid_sync.py so the AI bot, dashboard and
notifications behave identically to the native platforms.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone

import store_manager as sm


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def _s(v) -> str:
    return "" if v is None else str(v)


# ── Product formatter ──────────────────────────────────────────────────────────

def format_custom_product(p: dict, currency: str = "SAR") -> dict:
    """
    Transform a raw custom-store product JSON → cache_data product format.

    Lenient by design: the merchant controls the payload, so we accept a few
    aliases per field (name/title, price/sale_price, quantity/stock, …) and
    fall back to sensible defaults. The output shape matches format_zid_product
    so store_brain + the agent treat it identically.
    """
    name      = p.get("name") or p.get("title") or ""
    desc      = _strip_html(p.get("description") or p.get("short_description") or "")[:300]
    price     = _s(p.get("price") if p.get("price") is not None else p.get("sale_price") or "0")
    old_price = _s(p.get("regular_price") or p.get("old_price") or p.get("compare_price") or "")
    sku       = p.get("sku") or ""
    qty       = p.get("quantity")
    if qty is None:
        qty = p.get("stock") if p.get("stock") is not None else p.get("available_quantity") or 0
    unlimited = bool(p.get("unlimited_quantity"))

    # Status — honour an explicit status, else derive from published + stock.
    explicit = (p.get("status") or "").strip().lower()
    published = p.get("is_published", p.get("published", True))
    in_stock  = (qty or 0) > 0 or unlimited
    if explicit in ("sale", "out", "hidden"):
        status = explicit
    elif not published:
        status = "hidden"
    elif in_stock:
        status = "sale"
    else:
        status = "out"

    # Image — accept a string or a list of strings / {url|src} dicts.
    image_url = ""
    img = p.get("image") or p.get("images") or ""
    if isinstance(img, str):
        image_url = img
    elif isinstance(img, list) and img:
        first = img[0]
        image_url = first.get("url") or first.get("src") if isinstance(first, dict) else _s(first)

    # Categories — list of strings or {name} dicts.
    cats = p.get("categories") or p.get("category") or []
    if isinstance(cats, str):
        cats = [cats]
    categories = [c.get("name", "") if isinstance(c, dict) else _s(c) for c in cats]
    categories = [c for c in categories if c]

    # Variants / options — [{option, values:[...]}].
    options_summary: list[dict] = []
    variants = p.get("options") or p.get("variants") or []
    if isinstance(variants, list) and variants and isinstance(variants[0], dict):
        for v in variants[:10]:
            vname  = v.get("option") or v.get("name") or ""
            values = v.get("values") or []
            if vname and values:
                options_summary.append({"option": vname, "values": values})

    try:
        sale_price = price if old_price and float(old_price) > float(price) else ""
    except (ValueError, TypeError):
        sale_price = ""

    return {
        "id":                 _s(p.get("id")),
        "name":               name,
        "description":        desc,
        "price":              price,
        "regular_price":      old_price or price,
        "sale_price":         sale_price,
        "currency":           currency or "SAR",
        "status":             status,
        "sku":                sku,
        "quantity":           qty,
        "unlimited_quantity": unlimited,
        "categories":         categories,
        "options":            options_summary,
        "skus":               [],
        "image":              image_url,
        "url":                p.get("url") or "",
        "type":               "product",
    }


# ── Full catalog ingest ─────────────────────────────────────────────────────────

def apply_catalog(store_id: str, payload: dict) -> dict:
    """
    Replace a custom store's cached catalog from a pushed payload and return a
    small summary. Mirrors sync_zid_store's cache shape so store_brain reads it
    the same way. Synchronous (no external fetch) — the merchant already sent
    everything in the request body.

    Expected payload:
        {
          "store":      {"name", "domain", "currency", "email", "description"},
          "products":   [ {...}, ... ],
          "categories": [ {"name", ...}, ... ]   # optional
        }
    """
    store_blob = payload.get("store") or {}
    currency   = (store_blob.get("currency") or "SAR").strip() or "SAR"

    raw_products = payload.get("products") or []
    products = [format_custom_product(p, currency=currency)
                for p in raw_products if isinstance(p, dict)]

    raw_cats = payload.get("categories") or []
    categories = []
    for c in raw_cats:
        if isinstance(c, dict) and c.get("name"):
            categories.append({"id": _s(c.get("id")), "name": c["name"]})
        elif isinstance(c, str) and c:
            categories.append({"id": "", "name": c})

    store_info = {
        "id":          _s(store_blob.get("id") or store_id),
        "name":        store_blob.get("name", ""),
        "entity":      "",
        "email":       store_blob.get("email", ""),
        "avatar":      store_blob.get("avatar", ""),
        "plan":        "",
        "type":        "custom",
        "status":      "active",
        "verified":    True,
        "currency":    currency,
        "domain":      store_blob.get("domain", "") or store_blob.get("url", ""),
        "description": store_blob.get("description", ""),
        "licenses":    {},
        "social":      {},
    }

    cache = {
        "products":           products,
        "categories":         categories,
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
        "last_sync_errors":   [],
        "platform":           "custom",
    }
    sm.set_cache(store_id, cache)
    sm.reset_agent(store_id)

    print(f"[custom_sync] ✅ catalog applied store={store_id} "
          f"products={len(products)} categories={len(categories)}")
    return {"products": len(products), "categories": len(categories)}


# ── Incremental product patch ───────────────────────────────────────────────────

def patch_custom_product(store_id: str, product: dict, deleted: bool = False) -> None:
    """
    Update/remove a single product in the cache. Called from the custom webhook
    handler (product.created|updated|deleted). Mirrors patch_zid_product.
    """
    cache = sm.get_cache(store_id)
    if not cache:
        return

    currency = (cache.get("store_info") or {}).get("currency", "SAR")
    pid      = _s(product.get("id"))
    products: list[dict] = cache.get("products") or []

    if deleted:
        cache["products"] = [p for p in products if _s(p.get("id")) != pid]
    else:
        updated = format_custom_product(product, currency=currency)
        idx = next((i for i, p in enumerate(products) if _s(p.get("id")) == pid), None)
        if idx is not None:
            products[idx] = updated
        else:
            products.append(updated)
        cache["products"] = products

    cache["products_count"] = len(cache["products"])
    sm.set_cache(store_id, cache)


# ── Abandoned-cart mapper ───────────────────────────────────────────────────────

def custom_cart_to_notification(cart: dict) -> tuple:
    """
    Map a custom-store abandoned cart → the shared abandoned-cart notification
    shape. Returns (notification, phone). Mirrors zid_cart_to_notification.
    """
    from routers.webhooks._base import _normalize_phone

    phone = _normalize_phone(_s(cart.get("customer_phone") or cart.get("phone")
                                or cart.get("mobile")))
    notification = {
        "id":             _s(cart.get("id")),
        "ts":             cart.get("updated_at") or cart.get("ts")
                          or (datetime.now(timezone.utc).isoformat()),
        "customer_name":  _s(cart.get("customer_name") or cart.get("name")).strip() or "—",
        "customer_phone": phone or "—",
        "customer_email": cart.get("customer_email") or cart.get("email") or "—",
        "total":          _s(cart.get("total") if cart.get("total") is not None
                             else cart.get("cart_total") or "—"),
        "currency":       cart.get("currency") or "SAR",
        "items_count":    int(cart.get("items_count") or cart.get("products_count") or 0),
        "age_minutes":    0,
        "checkout_url":   cart.get("checkout_url") or cart.get("url", ""),
        "status":         "active",
        "recovered":      False,
    }
    return notification, phone
