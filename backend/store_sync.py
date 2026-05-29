"""
Store Sync — fetches ALL products, categories, and articles from Salla
and builds a knowledge base for the AI agent.

Salla API docs: https://docs.salla.dev/5394168e0
Pagination key: data.pagination.totalPages (camelCase)
"""

import os
import json
import asyncio
import httpx
from pathlib import Path

CACHE_FILE = Path(__file__).parent / "store_cache.json"

_store_data: dict = {}


def get_store_data() -> dict:
    return _store_data


async def _fetch_all_pages(
    client: httpx.AsyncClient, url: str, headers: dict
) -> tuple[list, str | None]:
    """
    Fetch all pages from a paginated Salla endpoint (50 items/page).
    Returns (items, error_message). error_message is None on success.
    """
    items = []
    page = 1
    while True:
        try:
            r = await client.get(
                url,
                headers=headers,
                params={"per_page": 50, "page": page},
                timeout=20,
            )
            if r.status_code == 401:
                return items, f"401 Unauthorized — token expired or invalid (url={url})"
            if r.status_code != 200:
                return items, f"HTTP {r.status_code} from {url}: {r.text[:200]}"
            data = r.json()
            batch = data.get("data", [])
            if not batch:
                break
            items.extend(batch)
            pagination = data.get("pagination") or {}
            total_pages = pagination.get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1
        except Exception as e:
            return items, f"Exception fetching {url} page {page}: {type(e).__name__}: {e}"
    return items, None


def _format_product(p: dict) -> dict:
    """Extract essential product info including options (sizes, colors, etc.)."""
    price_obj = p.get("price") or {}
    sale_obj = p.get("sale_price") or {}
    regular_obj = p.get("regular_price") or {}

    # Build options summary: [{name, values: [...]}]
    options_summary = []
    for opt in p.get("options") or []:
        opt_name = opt.get("name", "")
        values = [v.get("name", "") for v in (opt.get("values") or []) if v.get("name")]
        if opt_name and values:
            options_summary.append({"option": opt_name, "values": values})

    # Build SKU variants (only if they differ in price)
    skus_summary = []
    for sku in (p.get("skus") or [])[:10]:
        sku_price = (sku.get("price") or {}).get("amount")
        sku_code = sku.get("sku", "")
        sku_qty = sku.get("stock_quantity", 0)
        unlimited = sku.get("unlimited_quantity", False)
        if sku_price:
            skus_summary.append({
                "sku": sku_code,
                "price": sku_price,
                "qty": "غير محدودة" if unlimited else sku_qty,
            })

    # Customer-facing URL
    urls = p.get("urls") or {}
    customer_url = urls.get("customer") or p.get("url", "")

    return {
        "id": p.get("id"),
        "name": p.get("name", ""),
        "description": _strip_html(p.get("description", ""))[:300],
        "price": price_obj.get("amount", ""),
        "regular_price": regular_obj.get("amount", ""),
        "sale_price": sale_obj.get("amount", ""),
        "currency": price_obj.get("currency", "SAR"),
        "status": p.get("status", "sale"),          # sale | out | hidden
        "sku": p.get("sku", ""),
        "quantity": p.get("quantity", 0),
        "unlimited_quantity": p.get("unlimited_quantity", False),
        "categories": [c.get("name", "") for c in (p.get("categories") or [])],
        "options": options_summary,
        "skus": skus_summary,
        "url": customer_url,
        "type": p.get("type", "product"),
    }


def _format_article(a: dict) -> dict:
    """Extract essential article/blog-post info."""
    return {
        "id": a.get("id"),
        "title": a.get("title", ""),
        "excerpt": _strip_html(a.get("excerpt", "") or a.get("content", ""))[:300],
        "url": a.get("url", ""),
    }


def _strip_html(text: str) -> str:
    """Remove HTML tags and normalise whitespace."""
    import re
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(text.split()).strip()


async def sync_store(access_token: str) -> dict:
    """Fetch all store data and return as structured dict. Saves to cache file."""
    global _store_data

    if not access_token:
        return {}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    base = "https://api.salla.dev/admin/v2"

    errors = []

    async with httpx.AsyncClient(timeout=30) as client:
        # Fetch products and categories in parallel
        (products_raw, prod_err), (categories_raw, cats_err) = await asyncio.gather(
            _fetch_all_pages(client, f"{base}/products", headers),
            _fetch_all_pages(client, f"{base}/categories", headers),
        )
        if prod_err:
            print(f"[store_sync] products error: {prod_err}")
            errors.append(prod_err)
        if cats_err:
            print(f"[store_sync] categories error: {cats_err}")
            errors.append(cats_err)

        # Fetch blog articles (try multiple known endpoints)
        articles_raw = []
        for endpoint in [f"{base}/blogs/posts", f"{base}/blog/posts", f"{base}/blogs"]:
            try:
                r = await client.get(endpoint, headers=headers, params={"per_page": 50}, timeout=15)
                if r.status_code == 200:
                    articles_raw = r.json().get("data", [])
                    if articles_raw:
                        break
            except Exception as e:
                print(f"[store_sync] articles error ({endpoint}): {e}")

    products = [_format_product(p) for p in (products_raw or [])]
    categories = [
        {"id": c.get("id"), "name": c.get("name", "")}
        for c in (categories_raw or [])
        if c.get("name")
    ]
    articles = [_format_article(a) for a in articles_raw]

    import datetime
    _store_data = {
        "products": products,
        "categories": categories,
        "articles": articles,
        "products_count": len(products),
        "last_sync": datetime.datetime.utcnow().isoformat(),
        "last_sync_errors": errors,
    }

    # Persist to file
    try:
        CACHE_FILE.write_text(
            json.dumps(_store_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    return _store_data


def load_cache() -> dict:
    """Load previously cached store data from file (called on startup)."""
    global _store_data
    try:
        if CACHE_FILE.exists():
            _store_data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return _store_data


def build_knowledge_summary() -> str:
    """
    Build a concise Arabic text summary of the whole store catalogue
    for injection into the AI system prompt.
    """
    data = _store_data
    if not data:
        return ""

    lines = []

    # ── Categories ──────────────────────────────────────────────────────────────
    cats = data.get("categories", [])
    if cats:
        cat_names = "، ".join(c["name"] for c in cats[:30] if c.get("name"))
        lines.append(f"تصنيفات المتجر: {cat_names}")

    # ── Products ────────────────────────────────────────────────────────────────
    products = data.get("products", [])
    available = [p for p in products if p.get("status") != "hidden"]
    if available:
        lines.append(f"\nعدد المنتجات المتاحة: {len(available)} منتج\n")
        lines.append("=== قائمة المنتجات ===")
        for p in available:
            name     = p.get("name", "")
            price    = p.get("price", "")
            sale     = p.get("sale_price", "")
            currency = p.get("currency", "SAR")
            desc     = p.get("description", "")[:150]
            cats_str = "، ".join(p.get("categories", []))
            status   = p.get("status", "")
            qty      = p.get("quantity", 0)
            unlimited = p.get("unlimited_quantity", False)

            # Price line
            price_str = f"{price} {currency}"
            if sale and float(sale) > 0 and float(sale) < float(price or 0):
                price_str = f"~~{price}~~ → {sale} {currency} (عرض خاص)"

            # Availability
            if status == "out":
                avail_str = "⛔ نفد المخزون"
            elif unlimited:
                avail_str = "✅ متوفر"
            else:
                avail_str = f"✅ متوفر ({qty} قطعة)" if qty else "⛔ نفد المخزون"

            line = f"• {name} — {price_str} | {avail_str}"
            if cats_str:
                line += f" | [{cats_str}]"
            lines.append(line)

            if desc:
                lines.append(f"  الوصف: {desc}")

            # Options (sizes, colors, paper types, etc.)
            for opt in p.get("options", []):
                opt_name   = opt.get("option", "")
                opt_values = "، ".join(opt.get("values", [])[:10])
                if opt_name and opt_values:
                    lines.append(f"  {opt_name}: {opt_values}")

            # SKU variants with different prices
            skus = p.get("skus", [])
            if skus and len(skus) > 1:
                sku_prices = list({s["price"] for s in skus if s.get("price")})
                if len(sku_prices) > 1:
                    sku_str = " / ".join(str(x) for x in sorted(sku_prices))
                    lines.append(f"  أسعار الفاريانتس: {sku_str} {currency}")

    # ── Articles / Blog ─────────────────────────────────────────────────────────
    articles = data.get("articles", [])
    if articles:
        lines.append(f"\n=== مقالات المتجر ({len(articles)} مقال) ===")
        for a in articles[:15]:
            title   = a.get("title", "")
            excerpt = a.get("excerpt", "")[:120]
            lines.append(f"• {title}" + (f": {excerpt}" if excerpt else ""))

    return "\n".join(lines)
