"""
Store-brain — builds a structured "memory" the AI agent can use to answer
customer questions accurately about a specific store.

Layers of knowledge (combined into the system prompt):

  1. Store overview      — total products, categories, currency, price range.
                            ~200 chars. Always included.
  2. Custom knowledge    — free-text the admin types in the dashboard
                            (FAQs, return policy, working hours, branding,
                             unique selling points). Up to ~3000 chars.
                            Always included if set.
  3. Category map        — per-category product counts and price ranges,
                            with a few example products each. Lets the AI
                            understand the catalog shape even when the
                            full product list won't fit in the prompt.
  4. Top products        — fills remaining prompt budget with the most
                            popular / latest products.

The agent calls `get_knowledge_for_prompt(store_id)` for system prompt
injection, and `get_overview(store_id)` / `search_by_category(...)` as
tool calls during conversation when it needs more detail.
"""

from __future__ import annotations
from collections import defaultdict

import store_manager as sm


# Prompt budget — model dependent. Groq/Anthropic/OpenAI all comfortably
# accept 8K+ tokens in system prompts, so 12K chars (~3K tokens) of
# knowledge is safe and leaves room for the rest of the prompt and history.
PROMPT_BUDGET_CHARS = 12000
CUSTOM_KNOWLEDGE_CAP = 3000


# ── Helpers ──────────────────────────────────────────────────────────────────

def _price_num(p) -> float | None:
    """Coerce a price (str/int/float/dict) to a float, or None on failure."""
    if p is None:
        return None
    if isinstance(p, dict):
        p = p.get("amount")
    try:
        n = float(p)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _get_custom_knowledge(store_id: str) -> str:
    """Read the admin's custom knowledge text from ai_config."""
    cfg = sm.get_ai_config(store_id) or {}
    text = (cfg.get("custom_knowledge") or "").strip()
    if len(text) > CUSTOM_KNOWLEDGE_CAP:
        text = text[:CUSTOM_KNOWLEDGE_CAP] + "\n… (تم اقتطاع باقي الذاكرة)"
    return text


def set_custom_knowledge(store_id: str, text: str) -> None:
    """Save the admin's custom knowledge text. Persisted in ai_config."""
    cfg = sm.get_ai_config(store_id) or {}
    cfg["custom_knowledge"] = (text or "").strip()
    sm.set_ai_config(store_id, cfg)


# ── Overview / stats ────────────────────────────────────────────────────────

def get_overview(store_id: str) -> dict:
    """
    Compute a quick numeric overview of the store's catalog.
    Used both for the admin "AI brain" dashboard and the AI tool of the
    same name.
    """
    cache = sm.get_cache(store_id) or {}
    products  = cache.get("products", [])
    available = [p for p in products if p.get("status") != "hidden"]
    categories = cache.get("categories", [])
    last_sync  = cache.get("last_sync", "never")

    prices = [pn for p in available if (pn := _price_num(p.get("price")))]
    currency = next(
        (p.get("currency", "SAR") for p in available if p.get("currency")),
        "SAR",
    )

    cat_counts: dict[str, int] = defaultdict(int)
    for p in available:
        for c in (p.get("categories") or []):
            cat_counts[c] += 1
    top_cats = sorted(cat_counts.items(), key=lambda kv: -kv[1])[:10]

    return {
        "total_products":     len(products),
        "available_products": len(available),
        "categories":         len(categories),
        "currency":           currency,
        "min_price":          round(min(prices), 2) if prices else None,
        "max_price":          round(max(prices), 2) if prices else None,
        "avg_price":          round(sum(prices) / len(prices), 2) if prices else None,
        "top_categories":     [{"name": n, "count": c} for n, c in top_cats],
        "last_sync":          last_sync,
    }


# ── Category map (mid-level summary) ────────────────────────────────────────

def _build_category_map(store_id: str, max_examples_per_cat: int = 3) -> str:
    """
    Per-category lines: 'كروت شخصية (12 منتج، 5-150 ريال): مثل …'
    Compact and high-signal — gives the AI a navigable map of the catalog.
    """
    cache = sm.get_cache(store_id) or {}
    products = [p for p in cache.get("products", []) if p.get("status") != "hidden"]
    if not products:
        return ""

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in products:
        for c in (p.get("categories") or ["غير مصنّف"]):
            by_cat[c].append(p)

    currency = next(
        (p.get("currency", "SAR") for p in products if p.get("currency")),
        "SAR",
    )

    lines = []
    # Sort categories by product count (biggest first)
    for cat_name, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        prices = [pn for p in items if (pn := _price_num(p.get("price")))]
        if prices:
            lo, hi = min(prices), max(prices)
            price_part = f"{lo:g}-{hi:g} {currency}"
        else:
            price_part = ""

        names = [p.get("name", "") for p in items[:max_examples_per_cat] if p.get("name")]
        examples = " | ".join(names)

        line = f"• {cat_name} ({len(items)} منتج"
        if price_part:
            line += f"، {price_part}"
        line += ")"
        if examples:
            line += f": {examples}"
        lines.append(line)

    return "\n".join(lines)


# ── Top-products block (fills remaining prompt budget) ───────────────────────

def _build_top_products(store_id: str, budget_chars: int) -> str:
    """
    List as many products as fit in `budget_chars` with name+price+status.
    Stops cleanly at a product boundary.
    """
    cache = sm.get_cache(store_id) or {}
    products = [p for p in cache.get("products", []) if p.get("status") != "hidden"]
    if not products or budget_chars <= 100:
        return ""

    lines: list[str] = []
    used = 0
    for p in products:
        name = p.get("name", "")
        if not name:
            continue
        price = _price_num(p.get("price"))
        sale  = _price_num(p.get("sale_price"))
        currency = p.get("currency", "SAR")
        if sale and price and sale < price:
            price_str = f"~~{price:g}~~ → {sale:g} {currency}"
        elif price:
            price_str = f"{price:g} {currency}"
        else:
            price_str = "السعر عند الطلب"

        unlimited = p.get("unlimited_quantity")
        qty = p.get("quantity", 0)
        avail = "✅" if (unlimited or qty > 0) else "⛔ نفد"

        line = f"• {name} — {price_str} {avail}"
        if used + len(line) + 1 > budget_chars:
            lines.append(f"… (+{len(products) - len(lines)} منتج آخر متاح عبر suggest_products)")
            break
        lines.append(line)
        used += len(line) + 1

    return "\n".join(lines)


# ── Search-by-category tool helper ──────────────────────────────────────────

def search_by_category(store_id: str, category_name: str, limit: int = 20) -> list[dict]:
    """
    Return all products in a category (case-insensitive substring match).
    Used by the agent's `search_by_category` tool.
    """
    cache = sm.get_cache(store_id) or {}
    products = [p for p in cache.get("products", []) if p.get("status") != "hidden"]
    needle = (category_name or "").strip().lower()
    if not needle:
        return []

    out = []
    for p in products:
        cats = [c.lower() for c in (p.get("categories") or [])]
        if any(needle in c or c in needle for c in cats):
            out.append({
                "id":       str(p.get("id", "")),
                "name":     p.get("name", ""),
                "price":    p.get("price"),
                "currency": p.get("currency", "SAR"),
                "url":      p.get("url", ""),
            })
        if len(out) >= limit:
            break
    return out


# ── Main public API: prompt builder ─────────────────────────────────────────

def get_knowledge_for_prompt(store_id: str) -> str:
    """
    Build the full knowledge block the AI agent injects into its system
    prompt. Layers are added in priority order until the budget is hit.
    """
    blocks: list[str] = []
    budget_left = PROMPT_BUDGET_CHARS

    # ── 1. Custom knowledge (highest priority — the admin's own words) ──
    custom = _get_custom_knowledge(store_id)
    if custom:
        section = f"══ معلومات خاصة بالمتجر (من الإدارة) ══\n{custom}\n══ نهاية المعلومات الخاصة ══"
        blocks.append(section)
        budget_left -= len(section)

    # ── 2. Overview ──
    ov = get_overview(store_id)
    if ov["available_products"] > 0:
        ov_lines = [
            "══ نظرة عامة على المتجر ══",
            f"عدد المنتجات المتاحة: {ov['available_products']} منتج"
            + (f" (من إجمالي {ov['total_products']})" if ov['total_products'] != ov['available_products'] else ""),
            f"عدد التصنيفات: {ov['categories']}",
        ]
        if ov["min_price"] is not None:
            ov_lines.append(
                f"نطاق الأسعار: {ov['min_price']:g} - {ov['max_price']:g} {ov['currency']}"
                f"  (متوسط: {ov['avg_price']:g})"
            )
        if ov["top_categories"]:
            top3 = "، ".join(f"{c['name']} ({c['count']})" for c in ov["top_categories"][:5])
            ov_lines.append(f"أكثر التصنيفات: {top3}")
        section = "\n".join(ov_lines)
        blocks.append(section)
        budget_left -= len(section) + 2

    # ── 3. Category map ──
    cat_map = _build_category_map(store_id)
    if cat_map and budget_left > 500:
        # Leave at least 500 chars for top products
        cap = min(len(cat_map), budget_left - 500)
        if cap < len(cat_map):
            cat_map = cat_map[:cap].rsplit("\n", 1)[0] + "\n… (المزيد عبر search_by_category)"
        section = f"══ خريطة التصنيفات ══\n{cat_map}"
        blocks.append(section)
        budget_left -= len(section) + 2

    # ── 4. Top products block ──
    if budget_left > 200:
        top = _build_top_products(store_id, budget_left - 100)
        if top:
            section = f"══ المنتجات المتاحة ══\n{top}\n══ نهاية الكتالوج ══"
            blocks.append(section)

    return "\n\n".join(blocks)


def preview_knowledge(store_id: str) -> dict:
    """Used by the admin 'AI Memory' page to show what the bot will see."""
    knowledge = get_knowledge_for_prompt(store_id)
    overview  = get_overview(store_id)
    return {
        "overview":         overview,
        "knowledge_chars":  len(knowledge),
        "knowledge_budget": PROMPT_BUDGET_CHARS,
        "custom_knowledge": _get_custom_knowledge(store_id),
        "knowledge_preview": knowledge,
    }
