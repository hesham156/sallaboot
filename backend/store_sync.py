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

import database as db
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

async def _fetch_simple_list(
    client: httpx.AsyncClient, headers: dict, path: str, store_id: str,
    label: str, params: dict | None = None,
) -> tuple:
    """
    Generic GET → data[] helper used for the small auxiliary endpoints
    (brands, special offers, branches, payment methods, shipping zones).
    Returns (items, error). 403 is non-fatal so missing scopes degrade
    gracefully without breaking the rest of the sync.
    """
    try:
        r = await client.get(
            f"https://api.salla.dev/admin/v2{path}",
            headers=headers, params=params or {}, timeout=15,
        )
        if r.status_code == 200:
            return (r.json().get("data") or []), None
        if r.status_code == 403:
            return [], f"{label} scope missing (403) — skipped"
        return [], f"HTTP {r.status_code} from {path}: {r.text[:200]}"
    except Exception as e:
        return [], f"Exception fetching {path}: {type(e).__name__}: {e}"


def _format_brand(b: dict) -> dict:
    return {
        "id":          b.get("id"),
        "name":        b.get("name", ""),
        "description": _strip_html(b.get("description", ""))[:200],
        "logo":        (b.get("logo") or {}).get("url") if isinstance(b.get("logo"), dict) else (b.get("logo") or ""),
        "banner":      (b.get("banner") or {}).get("url") if isinstance(b.get("banner"), dict) else (b.get("banner") or ""),
        "url":         b.get("url", ""),
    }


def _format_offer(o: dict) -> dict:
    return {
        "id":            o.get("id"),
        "name":          o.get("name", ""),
        "type":          o.get("type", ""),
        "message":       o.get("message", ""),
        "applied_to":    o.get("applied_to", ""),
        "start_date":    (o.get("start_date") or {}).get("date") if isinstance(o.get("start_date"), dict) else (o.get("start_date") or ""),
        "end_date":      (o.get("end_date") or {}).get("date") if isinstance(o.get("end_date"), dict) else (o.get("end_date") or ""),
        "status":        o.get("status", ""),
    }


def _format_branch(b: dict) -> dict:
    loc = b.get("location") or {}
    return {
        "id":         b.get("id"),
        "name":       b.get("name", ""),
        "city":       b.get("city", ""),
        "country":    b.get("country", ""),
        "address":    b.get("address_description", "") or b.get("address", ""),
        "phone":      b.get("contacts", {}).get("phone", "") if isinstance(b.get("contacts"), dict) else "",
        "lat":        loc.get("latitude") if isinstance(loc, dict) else None,
        "lng":        loc.get("longitude") if isinstance(loc, dict) else None,
        "is_default": bool(b.get("is_default", False)),
        "type":       b.get("type", ""),
        "status":     b.get("status", ""),
    }


def _format_payment_method(p: dict) -> dict:
    return {
        "id":        p.get("id"),
        "name":      p.get("name", ""),
        "name_en":   p.get("name_en", ""),
        "slug":      p.get("slug", ""),
        "logo":      p.get("logo", ""),
    }


def _format_shipping_zone(z: dict) -> dict:
    return {
        "id":        z.get("id"),
        "name":      z.get("name", ""),
        "country":   z.get("country", ""),
        "cities":    z.get("cities") or [],
        "status":    z.get("status", ""),
    }


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
        # Run all sync requests concurrently — total latency = slowest single fetch
        (
            (products_raw, prod_err),
            (categories_raw, cats_err),
            (store_info, info_err),
            (shipping_companies, ship_err),
            (brands_raw, brand_err),
            (offers_raw, offer_err),
            (branches_raw, branch_err),
            (payment_methods_raw, pay_err),
            (shipping_zones_raw, zone_err),
        ) = await asyncio.gather(
            _fetch_all_pages(client, f"{base}/products",   headers),
            _fetch_all_pages(client, f"{base}/categories", headers),
            _fetch_store_info(client, headers, store_id),
            _fetch_shipping_companies(client, headers, store_id),
            _fetch_simple_list(client, headers, "/brands",            store_id, "brands.read",   {"per_page": 50}),
            _fetch_simple_list(client, headers, "/specialoffers",     store_id, "offers.read",   {"per_page": 50}),
            _fetch_simple_list(client, headers, "/branches",          store_id, "branches.read", {"per_page": 50}),
            _fetch_simple_list(client, headers, "/payment/methods",   store_id, "payments.read"),
            _fetch_simple_list(client, headers, "/shipping/zones",    store_id, "shipping.read", {"per_page": 50}),
        )
        if prod_err:   errors.append(prod_err);   print(f"[store_sync:{store_id}] products: {prod_err}")
        if cats_err:   errors.append(cats_err);   print(f"[store_sync:{store_id}] categories: {cats_err}")
        if info_err:   errors.append(info_err);   print(f"[store_sync:{store_id}] store_info: {info_err}")
        if ship_err:   errors.append(ship_err);   print(f"[store_sync:{store_id}] shipping: {ship_err}")
        # Auxiliary endpoints — log but don't pollute the user-facing errors list
        for label, err in [("brands", brand_err), ("offers", offer_err),
                            ("branches", branch_err), ("payment_methods", pay_err),
                            ("shipping_zones", zone_err)]:
            if err:
                print(f"[store_sync:{store_id}] {label}: {err}")

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
        "brands":             [_format_brand(b)          for b in (brands_raw or [])],
        "special_offers":     [_format_offer(o)          for o in (offers_raw or [])],
        "branches":           [_format_branch(b)         for b in (branches_raw or [])],
        "payment_methods":    [_format_payment_method(p) for p in (payment_methods_raw or [])],
        "shipping_zones":     [_format_shipping_zone(z)  for z in (shipping_zones_raw or [])],
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

    # Update store metadata in store_manager from the freshly-fetched
    # /store/info. We refresh name, domain, avatar, and URL together so
    # the admin dashboard's "النطاق" / "Logo" columns aren't permanently
    # empty for stores that installed before we started capturing these.
    si = data.get("store_info") or {}
    fresh_name   = (si.get("name")   or "").strip()
    fresh_domain = (si.get("domain") or "").strip()
    fresh_avatar = (si.get("avatar") or "").strip()
    fresh_url    = (si.get("url")    or "").strip()
    if fresh_name or fresh_domain or fresh_avatar or fresh_url:
        tokens = dict(sm.get_store_info(store_id) or {})
        changed = False
        if fresh_name   and tokens.get("store_name")   != fresh_name:
            tokens["store_name"]   = fresh_name;   changed = True
        if fresh_domain and tokens.get("store_domain") != fresh_domain:
            tokens["store_domain"] = fresh_domain; changed = True
        if fresh_avatar and tokens.get("store_avatar") != fresh_avatar:
            tokens["store_avatar"] = fresh_avatar; changed = True
        if fresh_url    and tokens.get("store_url")    != fresh_url:
            tokens["store_url"]    = fresh_url;    changed = True
        if changed:
            sm.update_store_info(store_id, tokens)
            if db.available():
                db.fire(db.save_store(store_id, tokens))

    n_p = data.get("products_count", 0)
    n_c = len(data.get("categories", []))
    n_a = len(data.get("articles",   []))
    si  = data.get("store_info") or {}
    info_str = f"store='{si.get('name','?')}' ({si.get('plan','?')})" if si else "no store_info"
    print(
        f"[store_sync:{store_id}] ✅ Sync done — {n_p} products, {n_c} cats, "
        f"{n_a} articles, {len(data.get('shipping_companies') or [])} carriers, "
        f"{len(data.get('brands') or [])} brands, "
        f"{len(data.get('special_offers') or [])} offers, "
        f"{len(data.get('branches') or [])} branches, "
        f"{len(data.get('payment_methods') or [])} payment methods, {info_str}"
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
