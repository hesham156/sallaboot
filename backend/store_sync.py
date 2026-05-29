"""
Store Sync — fetches ALL products, categories, and articles from Salla
and builds a knowledge base for the AI agent.
"""

import os
import json
import asyncio
import httpx
from pathlib import Path
from typing import Optional

CACHE_FILE = Path(__file__).parent / "store_cache.json"

_store_data: dict = {}


def get_store_data() -> dict:
    return _store_data


async def _fetch_all_pages(client: httpx.AsyncClient, url: str, headers: dict) -> list:
    """Fetch all pages from a paginated Salla endpoint."""
    items = []
    page = 1
    while True:
        try:
            r = await client.get(url, headers=headers, params={"per_page": 50, "page": page}, timeout=15)
            if r.status_code != 200:
                break
            data = r.json()
            batch = data.get("data", [])
            if not batch:
                break
            items.extend(batch)
            # Check if there are more pages
            pagination = data.get("pagination", {})
            if page >= pagination.get("totalPages", 1):
                break
            page += 1
        except Exception:
            break
    return items


def _format_product(p: dict) -> dict:
    """Extract essential product info."""
    price = p.get("price", {})
    return {
        "id": p.get("id"),
        "name": p.get("name", ""),
        "description": _strip_html(p.get("description", "")),
        "price": price.get("amount", ""),
        "currency": price.get("currency", "ريال"),
        "sku": p.get("sku", ""),
        "quantity": p.get("quantity", 0),
        "categories": [c.get("name", "") for c in p.get("categories", [])],
        "url": p.get("url", ""),
    }


def _format_article(a: dict) -> dict:
    """Extract essential article info."""
    return {
        "id": a.get("id"),
        "title": a.get("title", ""),
        "excerpt": _strip_html(a.get("excerpt", "") or a.get("content", ""))[:300],
        "url": a.get("url", ""),
    }


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    import re
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(text.split()).strip()


async def sync_store(access_token: str) -> dict:
    """Fetch all store data and return as structured dict."""
    global _store_data

    if not access_token:
        return {}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    base = "https://api.salla.dev/admin/v2"

    async with httpx.AsyncClient(timeout=20) as client:
        # Fetch products, categories, articles in parallel
        products_task = _fetch_all_pages(client, f"{base}/products", headers)
        categories_task = _fetch_all_pages(client, f"{base}/categories", headers)

        products_raw, categories_raw = await asyncio.gather(
            products_task, categories_task, return_exceptions=True
        )

        # Fetch articles/blog posts
        articles_raw = []
        for endpoint in [f"{base}/blogs/posts", f"{base}/blog/posts", f"{base}/blogs"]:
            try:
                r = await client.get(endpoint, headers=headers, params={"per_page": 50})
                if r.status_code == 200:
                    articles_raw = r.json().get("data", [])
                    break
            except Exception:
                continue

    products = [_format_product(p) for p in (products_raw or []) if isinstance(products_raw, list)]
    categories = [{"id": c.get("id"), "name": c.get("name", "")} for c in (categories_raw or []) if isinstance(categories_raw, list)]
    articles = [_format_article(a) for a in articles_raw]

    _store_data = {
        "products": products,
        "categories": categories,
        "articles": articles,
        "products_count": len(products),
        "last_sync": __import__("datetime").datetime.utcnow().isoformat(),
    }

    # Save to file for persistence
    try:
        CACHE_FILE.write_text(json.dumps(_store_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return _store_data


def load_cache() -> dict:
    """Load previously cached store data from file."""
    global _store_data
    try:
        if CACHE_FILE.exists():
            _store_data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return _store_data


def build_knowledge_summary() -> str:
    """Build a concise text summary of the store for the AI system prompt."""
    data = _store_data
    if not data:
        return ""

    lines = []

    # Categories
    cats = data.get("categories", [])
    if cats:
        cat_names = "، ".join(c["name"] for c in cats[:20] if c.get("name"))
        lines.append(f"تصنيفات المتجر: {cat_names}")

    # Products
    products = data.get("products", [])
    if products:
        lines.append(f"\nعدد المنتجات: {len(products)} منتج\n")
        lines.append("قائمة المنتجات:")
        for p in products:
            name = p.get("name", "")
            price = p.get("price", "")
            currency = p.get("currency", "ريال")
            desc = p.get("description", "")[:120]
            cats_str = "، ".join(p.get("categories", []))
            line = f"• {name}"
            if price:
                line += f" — {price} {currency}"
            if cats_str:
                line += f" [{cats_str}]"
            if desc:
                line += f"\n  {desc}"
            lines.append(line)

    # Articles
    articles = data.get("articles", [])
    if articles:
        lines.append(f"\nمقالات المتجر ({len(articles)} مقال):")
        for a in articles[:10]:
            title = a.get("title", "")
            excerpt = a.get("excerpt", "")[:100]
            lines.append(f"• {title}: {excerpt}")

    return "\n".join(lines)
