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


async def set_custom_knowledge(store_id: str, text: str) -> None:
    """Save the admin's custom knowledge text. Persisted in ai_config.

    Async because sm.set_ai_config awaits its DB write — propagating the
    await up so the HTTP handler (or bootstrap) blocks until the new
    knowledge is committed.
    """
    cfg = sm.get_ai_config(store_id) or {}
    cfg["custom_knowledge"] = (text or "").strip()
    await sm.set_ai_config(store_id, cfg)


# ── Overview / stats ────────────────────────────────────────────────────────

def get_store_info(store_id: str) -> dict:
    """Return the cached Salla /store/info response (or {} if not synced yet)."""
    return (sm.get_cache(store_id) or {}).get("store_info") or {}


def get_shipping_companies(store_id: str) -> list[dict]:
    """Return the cached /shipping/companies list (or [] if not synced yet)."""
    return (sm.get_cache(store_id) or {}).get("shipping_companies") or []


def get_brands(store_id: str) -> list[dict]:
    return (sm.get_cache(store_id) or {}).get("brands") or []


def get_special_offers(store_id: str) -> list[dict]:
    return (sm.get_cache(store_id) or {}).get("special_offers") or []


def get_branches(store_id: str) -> list[dict]:
    return (sm.get_cache(store_id) or {}).get("branches") or []


def get_payment_methods(store_id: str) -> list[dict]:
    return (sm.get_cache(store_id) or {}).get("payment_methods") or []


def get_shipping_zones(store_id: str) -> list[dict]:
    return (sm.get_cache(store_id) or {}).get("shipping_zones") or []


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
    store_info = cache.get("store_info") or {}

    prices = [pn for p in available if (pn := _price_num(p.get("price")))]
    # Prefer the currency from /store/info, then any product, then SAR default
    currency = (
        store_info.get("currency")
        or next((p.get("currency") for p in available if p.get("currency")), None)
        or "SAR"
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
        # ── Store profile (from /store/info) ──
        "store_name":         store_info.get("name", ""),
        "store_description":  store_info.get("description", ""),
        "store_domain":       store_info.get("domain", ""),
        "store_email":        store_info.get("email", ""),
        "store_avatar":       store_info.get("avatar", ""),
        "store_entity":       store_info.get("entity", ""),
        "store_plan":         store_info.get("plan", ""),
        "store_verified":     store_info.get("verified", False),
        "store_social":       store_info.get("social", {}),
        "store_licenses":     store_info.get("licenses", {}),
    }


def _build_store_profile_block(store_id: str) -> str:
    """
    Build the high-priority store-profile block that goes at the very top
    of the AI's system prompt. Includes the merchant's own description,
    contact channels, and any legal info that signals trust.
    """
    info = get_store_info(store_id)
    if not info:
        return ""

    lines = ["══ ملف المتجر ══"]
    name = info.get("name", "")
    if name:
        lines.append(f"اسم المتجر: {name}")

    entity_ar = {
        "person":  "متجر فردي",
        "company": "شركة",
        "charity": "جمعية خيرية",
        "firm":    "مؤسسة",
    }.get(info.get("entity", ""), info.get("entity", ""))
    if entity_ar:
        lines.append(f"الكيان: {entity_ar}")

    if info.get("verified"):
        lines.append("✓ متجر موثّق من سلة")

    currency = info.get("currency", "")
    if currency:
        lines.append(f"العملة: {currency}")

    domain = info.get("domain", "")
    if domain:
        lines.append(f"رابط المتجر: {domain}")

    description = (info.get("description") or "").strip()
    if description:
        lines.append(f"وصف المتجر: {description}")

    # Contact channels — the bot can share these when a customer asks
    social = info.get("social") or {}
    contacts = []
    if social.get("whatsapp"):
        contacts.append(f"واتساب: {social['whatsapp']}")
    if info.get("email"):
        contacts.append(f"البريد: {info['email']}")
    if contacts:
        lines.append("للتواصل المباشر: " + " | ".join(contacts))

    # Social links (suppress empty / placeholder values)
    social_pairs = []
    for key, label in [
        ("twitter",         "تويتر/X"),
        ("instagram",       "انستقرام"),
        ("facebook",        "فيسبوك"),
        ("snapchat",        "سناب شات"),
        ("youtube",         "يوتيوب"),
        ("telegram",        "تليجرام"),
        ("maroof",          "معروف"),
        ("appstore_link",   "تطبيق iOS"),
        ("googleplay_link", "تطبيق أندرويد"),
    ]:
        v = (social.get(key) or "").strip()
        if v and not v.endswith("/"):  # skip blank placeholders like "https://"
            social_pairs.append(f"{label}: {v}")
    if social_pairs:
        lines.append("الحسابات الرسمية: " + " | ".join(social_pairs))

    # Legal/trust signals
    lic = info.get("licenses") or {}
    licenses = []
    if lic.get("commercial_number"):
        licenses.append(f"سجل تجاري {lic['commercial_number']}")
    if lic.get("tax_number"):
        licenses.append(f"ضريبي {lic['tax_number']}")
    if lic.get("freelance_number"):
        licenses.append(f"عمل حر {lic['freelance_number']}")
    if licenses:
        lines.append("الترخيص: " + " | ".join(licenses))

    # Shipping carriers — read from cache (separate /shipping/companies fetch)
    carriers = get_shipping_companies(store_id)
    if carriers:
        names = [c.get("name", "") for c in carriers if c.get("name")]
        if names:
            lines.append(f"شركات الشحن المتاحة ({len(names)}): " + "، ".join(names))

    # Payment methods — high-signal for "كيف أدفع؟"
    payments = get_payment_methods(store_id)
    if payments:
        pnames = [p.get("name", "") for p in payments if p.get("name")]
        if pnames:
            lines.append(f"طرق الدفع المتاحة: " + "، ".join(pnames))

    # Active special offers — let the bot proactively mention them
    offers = [o for o in get_special_offers(store_id) if o.get("status") == "active" or not o.get("status")]
    if offers:
        offer_lines = []
        for o in offers[:6]:
            nm  = o.get("name", "")
            msg = o.get("message", "")
            label = nm or msg
            if label:
                offer_lines.append(label if not (nm and msg) else f"{nm} — {msg}")
        if offer_lines:
            lines.append("العروض الحالية: " + " | ".join(offer_lines))

    # Branches / pickup locations
    branches = get_branches(store_id)
    if branches:
        bnames = [
            (f"{b.get('name','')} ({b.get('city','')})" if b.get("city") else b.get("name", ""))
            for b in branches[:8] if b.get("name")
        ]
        if bnames:
            lines.append(f"الفروع ({len(branches)}): " + "، ".join(bnames))

    # Brands carried by the store
    brands = get_brands(store_id)
    if brands:
        bnames = [b.get("name", "") for b in brands[:15] if b.get("name")]
        if bnames:
            lines.append(f"الماركات المتوفرة: " + "، ".join(bnames))

    return "\n".join(lines)


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

async def get_knowledge_for_prompt_async(store_id: str) -> str:
    """
    Same as get_knowledge_for_prompt but additionally pulls bot_training
    rows from the DB. Async because DB lookups need awaiting.
    """
    import bot_training as bt
    base = get_knowledge_for_prompt(store_id)
    try:
        training = await bt.build_training_block(store_id)
    except Exception as exc:
        print(f"[store_brain] training block failed for {store_id!r}: {exc}")
        training = ""
    if training:
        # Training comes RIGHT AFTER store profile + custom knowledge so the
        # bot sees it before the bulkier product catalogue.
        return base + "\n\n" + training if base else training
    return base


def get_knowledge_for_prompt(store_id: str) -> str:
    """
    Build the full knowledge block the AI agent injects into its system
    prompt. Layers are added in priority order until the budget is hit.
    """
    blocks: list[str] = []
    budget_left = PROMPT_BUDGET_CHARS

    # ── 0. Store profile from Salla /store/info (highest signal) ──
    profile = _build_store_profile_block(store_id)
    if profile:
        blocks.append(profile)
        budget_left -= len(profile) + 2

    # ── 1. Custom knowledge (the admin's own words) ──
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
    store_info = get_store_info(store_id)
    carriers   = get_shipping_companies(store_id)
    return {
        "overview":           overview,
        "store_info":         store_info,
        "shipping_companies": carriers,
        "brands":             get_brands(store_id),
        "special_offers":     get_special_offers(store_id),
        "branches":           get_branches(store_id),
        "payment_methods":    get_payment_methods(store_id),
        "knowledge_chars":    len(knowledge),
        "knowledge_budget":   PROMPT_BUDGET_CHARS,
        "custom_knowledge":   _get_custom_knowledge(store_id),
        "knowledge_preview":  knowledge,
    }
