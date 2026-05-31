"""
Store Sync — fetches ALL products, categories, and articles from Salla
and builds a per-store knowledge base for the AI agent.

Multi-tenant: all functions accept a store_id parameter.
Cache is stored and retrieved via store_manager.
"""

import re
import asyncio
import datetime
import httpx

import store_manager as sm

BASE_API = "https://api.salla.dev/admin/v2"


# ── Salla API helpers ──────────────────────────────────────────────────────────

async def _fetch_all_pages(
    client: httpx.AsyncClient, url: str, headers: dict
) -> tuple:
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
    price_obj   = p.get("price") or {}
    sale_obj    = p.get("sale_price") or {}
    regular_obj = p.get("regular_price") or {}

    options_summary = []
    for opt in p.get("options") or []:
        opt_name = opt.get("name", "")
        values = [v.get("name", "") for v in (opt.get("values") or []) if v.get("name")]
        if opt_name and values:
            options_summary.append({"option": opt_name, "values": values})

    skus_summary = []
    for sku in (p.get("skus") or [])[:10]:
        sku_price = (sku.get("price") or {}).get("amount")
        sku_code  = sku.get("sku", "")
        unlimited = sku.get("unlimited_quantity", False)
        sku_qty   = sku.get("stock_quantity", 0)
        if sku_price:
            skus_summary.append({
                "sku": sku_code,
                "price": sku_price,
                "qty": "غير محدودة" if unlimited else sku_qty,
            })

    urls = p.get("urls") or {}
    customer_url = urls.get("customer") or p.get("url", "")

    # Best-effort image extraction
    images = p.get("images") or []
    thumbnail = p.get("thumbnail") or {}
    image_url = (
        (images[0].get("url") or images[0].get("src", "")) if images
        else thumbnail.get("url", "") or p.get("image", "") or p.get("cover", "")
    )

    return {
        "id":               p.get("id"),
        "name":             p.get("name", ""),
        "description":      _strip_html(p.get("description", ""))[:300],
        "price":            price_obj.get("amount", ""),
        "regular_price":    regular_obj.get("amount", ""),
        "sale_price":       sale_obj.get("amount", ""),
        "currency":         price_obj.get("currency", "SAR"),
        "status":           p.get("status", "sale"),
        "sku":              p.get("sku", ""),
        "quantity":         p.get("quantity", 0),
        "unlimited_quantity": p.get("unlimited_quantity", False),
        "categories":       [c.get("name", "") for c in (p.get("categories") or [])],
        "options":          options_summary,
        "skus":             skus_summary,
        "image":            image_url,
        "url":              customer_url,
        "type":             p.get("type", "product"),
    }


def _format_article(a: dict) -> dict:
    return {
        "id":      a.get("id"),
        "title":   a.get("title", ""),
        "excerpt": _strip_html(a.get("excerpt", "") or a.get("content", ""))[:300],
        "url":     a.get("url", ""),
    }


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(text.split()).strip()


# ── Main sync ──────────────────────────────────────────────────────────────────

async def _fetch_shipping_companies(client: httpx.AsyncClient, headers: dict, store_id: str) -> tuple:
    """Fetch /shipping/companies (active carriers + activation type)."""
    try:
        r = await client.get(
            "https://api.salla.dev/admin/v2/shipping/companies/",
            headers=headers, timeout=15,
        )
        if r.status_code == 200:
            raw = r.json().get("data") or []
            companies = [
                {
                    "id":              c.get("id"),
                    "name":            c.get("name", ""),
                    "slug":            c.get("slug") or "",
                    "activation_type": c.get("activation_type", ""),
                }
                for c in raw if c.get("name")
            ]
            return companies, None
        if r.status_code == 403:
            # Missing scope is non-fatal — the rest of the sync still works
            return [], "shipping.read scope missing (403) — shipping list not synced"
        return [], f"HTTP {r.status_code} from /shipping/companies: {r.text[:200]}"
    except Exception as e:
        return [], f"Exception fetching /shipping/companies: {type(e).__name__}: {e}"


async def _fetch_store_info(client: httpx.AsyncClient, headers: dict, store_id: str) -> tuple:
    """Fetch /store/info (returns the merchant's profile dict, or empty + error)."""
    try:
        r = await client.get(
            "https://api.salla.dev/admin/v2/store/info",
            headers=headers, timeout=15,
        )
        if r.status_code == 200:
            data = r.json().get("data") or {}
            # Extract only the fields we care about — keeps the cache small
            return {
                "id":          data.get("id"),
                "name":        data.get("name", ""),
                "entity":      data.get("entity", ""),
                "email":       data.get("email", ""),
                "avatar":      data.get("avatar", ""),
                "plan":        data.get("plan", ""),
                "type":        data.get("type", ""),
                "status":      data.get("status", ""),
                "verified":    bool(data.get("verified", False)),
                "currency":    data.get("currency", "SAR"),
                "domain":      data.get("domain", ""),
                "description": data.get("description", ""),
                "licenses":    data.get("licenses", {}) or {},
                "social":      data.get("social", {}) or {},
            }, None
        return {}, f"HTTP {r.status_code} from /store/info: {r.text[:200]}"
    except Exception as e:
        return {}, f"Exception fetching /store/info: {type(e).__name__}: {e}"


async def _do_sync(access_token: str, store_id: str) -> dict:
    """Inner sync — one attempt with the given token."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    base   = "https://api.salla.dev/admin/v2"
    errors = []

    async with httpx.AsyncClient(timeout=30) as client:
        # Run products, categories, store info, and shipping companies concurrently
        (
            (products_raw, prod_err),
            (categories_raw, cats_err),
            (store_info, info_err),
            (shipping_companies, ship_err),
        ) = await asyncio.gather(
            _fetch_all_pages(client, f"{base}/products",   headers),
            _fetch_all_pages(client, f"{base}/categories", headers),
            _fetch_store_info(client, headers, store_id),
            _fetch_shipping_companies(client, headers, store_id),
        )
        if prod_err:
            print(f"[store_sync:{store_id}] products error: {prod_err}")
            errors.append(prod_err)
        if cats_err:
            print(f"[store_sync:{store_id}] categories error: {cats_err}")
            errors.append(cats_err)
        if info_err:
            print(f"[store_sync:{store_id}] store_info error: {info_err}")
            errors.append(info_err)
        if ship_err:
            print(f"[store_sync:{store_id}] shipping error: {ship_err}")
            errors.append(ship_err)

        articles_raw = []
        for endpoint in [f"{base}/blogs/posts", f"{base}/blog/posts", f"{base}/blogs"]:
            try:
                r = await client.get(
                    endpoint, headers=headers, params={"per_page": 50}, timeout=15
                )
                if r.status_code == 200:
                    articles_raw = r.json().get("data", [])
                    if articles_raw:
                        break
            except Exception as e:
                print(f"[store_sync:{store_id}] articles error ({endpoint}): {e}")

    products   = [_format_product(p) for p in (products_raw or [])]
    categories = [
        {"id": c.get("id"), "name": c.get("name", "")}
        for c in (categories_raw or []) if c.get("name")
    ]
    articles = [_format_article(a) for a in articles_raw]

    return {
        "products":           products,
        "categories":         categories,
        "articles":           articles,
        "store_info":         store_info,
        "shipping_companies": shipping_companies or [],
        "products_count":     len(products),
        "last_sync":          datetime.datetime.utcnow().isoformat(),
        "last_sync_errors":   errors,
    }


async def sync_store(access_token: str, store_id: str = "default") -> dict:
    """
    Fetch all store data and save to store_manager cache.

    If the first attempt returns a 401 (expired token), automatically
    refreshes the token and retries once — so a sync triggered right after
    a 14-day token expiry will still succeed without manual intervention.

    Returns the structured data dict.
    """
    if not access_token:
        return {}

    data = await _do_sync(access_token, store_id)

    # Auto-refresh and retry on 401
    errors = data.get("last_sync_errors", [])
    if any("401" in str(e) for e in errors):
        try:
            from salla_oauth import refresh_access_token
            print(f"[store_sync:{store_id}] 401 detected — refreshing token and retrying …")
            new_token = await refresh_access_token(store_id)
            data      = await _do_sync(new_token, store_id)
        except Exception as exc:
            print(f"[store_sync:{store_id}] Token refresh during sync failed: {exc}")
            # Keep the original data (with the 401 error recorded)

    sm.set_cache(store_id, data)
    n_p = data.get("products_count", 0)
    n_c = len(data.get("categories", []))
    n_a = len(data.get("articles",   []))
    si  = data.get("store_info") or {}
    info_str = f"store='{si.get('name','?')}' ({si.get('plan','?')})" if si else "no store_info"
    n_s = len(data.get("shipping_companies") or [])
    print(
        f"[store_sync:{store_id}] ✅ Sync done — {n_p} products, {n_c} cats, "
        f"{n_a} articles, {n_s} shipping carriers, {info_str}"
    )
    return data


# ── Query helpers ──────────────────────────────────────────────────────────────

def get_store_data(store_id: str = "default") -> dict:
    """Return cached store data for the given store."""
    return sm.get_cache(store_id)


def load_cache(store_id: str = "default") -> dict:
    """Backward-compat stub — store_manager handles all cache loading at startup."""
    return sm.get_cache(store_id)


# ── Incremental product cache updates ─────────────────────────────────────────

async def patch_product_in_cache(
    store_id: str,
    product_id,
    *,
    delete: bool = False,
) -> bool:
    """
    Update **one product** in the store cache without a full re-sync.

    Called by webhook handlers for product.created / product.updated /
    product.deleted / product.status.updated / product.price.updated.

    Returns True if the cache was changed.
    """
    cache    = sm.get_cache(store_id)
    products = list(cache.get("products", []))
    pid_str  = str(product_id)

    if delete:
        before = len(products)
        products = [p for p in products if str(p.get("id")) != pid_str]
        if len(products) == before:
            return False  # wasn't in cache anyway
    else:
        # Fetch fresh data from Salla
        access_token = sm.get_access_token(store_id)
        if not access_token:
            return False

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{BASE_API}/products/{pid_str}",
                    headers=headers,
                )
                if r.status_code == 401:
                    # Token expired — refresh and retry once
                    from salla_oauth import refresh_access_token
                    new_tok = await refresh_access_token(store_id)
                    headers["Authorization"] = f"Bearer {new_tok}"
                    r = await client.get(
                        f"{BASE_API}/products/{pid_str}",
                        headers=headers,
                    )
                if r.status_code == 404:
                    # Product was deleted on Salla side
                    products = [p for p in products if str(p.get("id")) != pid_str]
                elif r.status_code == 200:
                    raw = r.json().get("data", {})
                    new_product = _format_product(raw)
                    idx = next(
                        (i for i, p in enumerate(products) if str(p.get("id")) == pid_str),
                        -1,
                    )
                    if idx >= 0:
                        products[idx] = new_product
                    else:
                        products.append(new_product)
                else:
                    return False
        except Exception as e:
            print(f"[store_sync:{store_id}] patch_product error for {pid_str}: {e}")
            return False

    cache["products"]       = products
    cache["products_count"] = len(products)
    sm.set_cache(store_id, cache)
    action = "deleted" if delete else "patched"
    print(f"[store_sync:{store_id}] ✅ Product {pid_str} {action} (cache now {len(products)} products)")
    return True


# ── Knowledge summary ──────────────────────────────────────────────────────────

def build_knowledge_summary(store_id: str = "default") -> str:
    """
    Build a concise Arabic text summary of the store catalogue
    for injection into the AI system prompt.
    """
    data = sm.get_cache(store_id)
    if not data:
        return ""

    lines = []

    cats = data.get("categories", [])
    if cats:
        cat_names = "، ".join(c["name"] for c in cats[:30] if c.get("name"))
        lines.append(f"تصنيفات المتجر: {cat_names}")

    products  = data.get("products", [])
    available = [p for p in products if p.get("status") != "hidden"]
    if available:
        lines.append(f"\nعدد المنتجات المتاحة: {len(available)} منتج\n")
        lines.append("=== قائمة المنتجات ===")
        for p in available:
            name      = p.get("name", "")
            price     = p.get("price", "")
            sale      = p.get("sale_price", "")
            currency  = p.get("currency", "SAR")
            desc      = p.get("description", "")[:150]
            cats_str  = "، ".join(p.get("categories", []))
            status    = p.get("status", "")
            qty       = p.get("quantity", 0)
            unlimited = p.get("unlimited_quantity", False)

            price_str = f"{price} {currency}"
            try:
                if sale and float(sale) > 0 and float(sale) < float(price or 0):
                    price_str = f"~~{price}~~ → {sale} {currency} (عرض خاص)"
            except (ValueError, TypeError):
                pass

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

            for opt in p.get("options", []):
                opt_name   = opt.get("option", "")
                opt_values = "، ".join(opt.get("values", [])[:10])
                if opt_name and opt_values:
                    lines.append(f"  {opt_name}: {opt_values}")

            skus = p.get("skus", [])
            if skus and len(skus) > 1:
                sku_prices = list({s["price"] for s in skus if s.get("price")})
                if len(sku_prices) > 1:
                    sku_str = " / ".join(str(x) for x in sorted(sku_prices))
                    lines.append(f"  أسعار الفاريانتس: {sku_str} {currency}")

    articles = data.get("articles", [])
    if articles:
        lines.append(f"\n=== مقالات المتجر ({len(articles)} مقال) ===")
        for a in articles[:15]:
            title   = a.get("title", "")
            excerpt = a.get("excerpt", "")[:120]
            lines.append(f"• {title}" + (f": {excerpt}" if excerpt else ""))

    return "\n".join(lines)
