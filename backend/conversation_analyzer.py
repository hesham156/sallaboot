"""
conversation_analyzer.py
─────────────────────────────────────────────────────────────────────────────
Lightweight analytics engine for stored conversations.

Provides:
  • analyze_insights(conversations) → InsightsResult dict
      - top_questions     : most common question topics
      - non_purchase      : why customers didn't complete a purchase
      - at_risk_customers : angry / frustrated / about-to-churn customers
      - sentiment_summary : overall mood breakdown

All analysis uses keyword matching (Arabic + English) — no external AI call.
"""

from __future__ import annotations
import re
from collections import defaultdict
from typing import Any

# ── Topic taxonomy ────────────────────────────────────────────────────────────
# Each topic has a label, icon, and list of keyword triggers (regex fragments).

TOPIC_RULES: list[dict] = [
    {
        "id": "pricing",
        "label": "الأسعار والتسعير",
        "icon": "💰",
        "keywords": [
            r"سع[ر|ا]", r"بكم", r"بقد", r"تكلف", r"كلف", r"ثمن", r"تسعير",
            r"price", r"cost", r"how much", r"كم الثمن", r"كم السعر",
        ],
    },
    {
        "id": "shipping",
        "label": "الشحن والتوصيل",
        "icon": "🚚",
        "keywords": [
            r"شح[ن|نة]", r"توصيل", r"تسليم", r"متى يوصل", r"وين يوصل",
            r"delivery", r"shipping", r"الشحن غالي", r"شحن مجاني",
        ],
    },
    {
        "id": "availability",
        "label": "توفر المنتج",
        "icon": "📦",
        "keywords": [
            r"متوفر", r"عندكم", r"يتوفر", r"ما فيه", r"نفد", r"خلص", r"غير موجود",
            r"available", r"in stock", r"out of stock",
        ],
    },
    {
        "id": "design",
        "label": "التصميم والمواصفات",
        "icon": "🎨",
        "keywords": [
            r"تصميم", r"لون", r"مقاس", r"حجم", r"طباعة", r"خط", r"شكل",
            r"design", r"size", r"color", r"print", r"logo",
        ],
    },
    {
        "id": "order_status",
        "label": "حالة الطلب",
        "icon": "📋",
        "keywords": [
            r"طلب[ي|ي]", r"وين طلبي", r"حالة الطلب", r"تتبع", r"متى يوصل",
            r"order status", r"track", r"delivery status",
        ],
    },
    {
        "id": "discount",
        "label": "العروض والخصومات",
        "icon": "🏷️",
        "keywords": [
            r"خصم", r"عرض", r"تخفيض", r"كوبون", r"كود", r"أوفر",
            r"discount", r"coupon", r"promo", r"offer", r"sale",
        ],
    },
    {
        "id": "quality",
        "label": "الجودة والمواد",
        "icon": "⭐",
        "keywords": [
            r"جودة", r"خامة", r"نوعية", r"متانة", r"أصلي",
            r"quality", r"material", r"durable", r"authentic",
        ],
    },
    {
        "id": "payment",
        "label": "الدفع والفوترة",
        "icon": "💳",
        "keywords": [
            r"دفع", r"فيزا", r"ماستر", r"مدى", r"تحويل", r"آبل باي", r"فاتور",
            r"payment", r"pay", r"invoice", r"receipt",
        ],
    },
    {
        "id": "return",
        "label": "الإرجاع والاستبدال",
        "icon": "↩️",
        "keywords": [
            r"ارجاع", r"إرجاع", r"استبدال", r"استرداد", r"ارد", r"راح ارجع",
            r"return", r"refund", r"exchange",
        ],
    },
]

# ── Non-purchase reason rules ─────────────────────────────────────────────────

NON_PURCHASE_REASONS: list[dict] = [
    {
        "id": "price_high",
        "label": "السعر مرتفع",
        "icon": "💸",
        "keywords": [
            r"غال[ي|ية]", r"غلي", r"مرتفع", r"كثير", r"أغلى", r"ما يستاهل",
            r"expensive", r"too much", r"overpriced",
        ],
    },
    {
        "id": "shipping_cost",
        "label": "الشحن غالي",
        "icon": "📦",
        "keywords": [
            r"الشحن غال", r"توصيل غال", r"شحن كثير", r"شحن مرتفع",
            r"shipping expensive", r"delivery cost",
        ],
    },
    {
        "id": "out_of_stock",
        "label": "المنتج غير متوفر",
        "icon": "🚫",
        "keywords": [
            r"غير متوفر", r"ما في", r"نفد", r"خلص", r"ما يتوفر",
            r"out of stock", r"not available", r"unavailable",
        ],
    },
    {
        "id": "postponed",
        "label": "تأجيل القرار",
        "icon": "⏳",
        "keywords": [
            r"سأفكر", r"بفكر", r"لاحقاً", r"بعدين", r"ما قررت", r"ما زبط",
            r"later", r"think about", r"not now", r"maybe",
        ],
    },
    {
        "id": "no_design",
        "label": "ما عنده تصميم",
        "icon": "🎨",
        "keywords": [
            r"ما عندي تصميم", r"بدون تصميم", r"ما عنده لوقو",
            r"no design", r"no logo",
        ],
    },
    {
        "id": "competitor",
        "label": "اشترى من مكان ثاني",
        "icon": "🏪",
        "keywords": [
            r"اشتريت من", r"وجدته في", r"عند غيركم", r"مكان ثاني",
            r"found it elsewhere", r"competitor",
        ],
    },
]

# ── Sentiment rules ───────────────────────────────────────────────────────────

ANGRY_KEYWORDS = [
    r"غاضب", r"زعلان", r"محبط", r"مزعج", r"سيء", r"خدمة رديئة", r"مش راضي",
    r"مشكلة", r"خطأ", r"غلط", r"مو صح", r"كلام فارغ", r"هراء", r"ما ساعد",
    r"angry", r"frustrated", r"terrible", r"worst", r"disgusting", r"useless",
    r"waste", r"never again",
]

SATISFIED_KEYWORDS = [
    r"شكراً", r"ممتاز", r"رائع", r"عجبني", r"جيد", r"تمام", r"حلو", r"يعجبني",
    r"الله يعطيكم العافية", r"تسلم",
    r"great", r"excellent", r"perfect", r"thanks", r"awesome", r"love it",
]


# ── Helper ────────────────────────────────────────────────────────────────────

def _matches_any(text: str, patterns: list[str]) -> bool:
    tl = text.lower()
    return any(re.search(p, tl) for p in patterns)


def _user_text(conv: dict) -> str:
    """Concatenate all user messages in a conversation."""
    return " ".join(
        m["content"]
        for m in conv.get("messages", [])
        if m.get("role") == "user"
    )


def _had_checkout(conv: dict) -> bool:
    """Return True if the conversation resulted in a completed checkout."""
    comp = conv.get("last_component") or {}
    if isinstance(comp, dict) and comp.get("type") == "checkout":
        return True
    # Also check assistant messages for checkout confirmation text
    for m in conv.get("messages", []):
        if m.get("role") == "assistant" and "رابط الدفع" in m.get("content", ""):
            return True
    return False


def _sentiment(text: str) -> str:
    """Return 'happy' | 'angry' | 'neutral'."""
    if _matches_any(text, ANGRY_KEYWORDS):
        return "angry"
    if _matches_any(text, SATISFIED_KEYWORDS):
        return "happy"
    return "neutral"


# ── Main analyser ─────────────────────────────────────────────────────────────

def analyze_insights(conversations: dict[str, dict]) -> dict[str, Any]:
    """
    Analyse a store's conversations dict and return insights.

    Returns:
    {
      "top_questions": [
          {"id", "label", "icon", "count", "percent", "examples": [str]}
      ],
      "non_purchase": [
          {"id", "label", "icon", "count", "percent"}
      ],
      "at_risk_customers": [
          {"session_id", "signal", "last_message", "ts", "customer_name", "customer_phone"}
      ],
      "sentiment_summary": {"happy", "neutral", "angry", "total"},
      "conversion": {
          "total_convs", "with_checkout", "without_checkout", "conversion_rate"
      }
    }
    """
    topic_counts:  dict[str, int]         = defaultdict(int)
    topic_examples: dict[str, list[str]]  = defaultdict(list)
    reason_counts: dict[str, int]         = defaultdict(int)
    at_risk: list[dict]                   = []
    sentiment_counts = {"happy": 0, "neutral": 0, "angry": 0}

    total_convs    = len(conversations)
    with_checkout  = 0

    for sid, conv in conversations.items():
        user_text = _user_text(conv)
        if not user_text.strip():
            continue

        # ── Checkout detection ──────────────────────────────────────────────
        checked_out = _had_checkout(conv)
        if checked_out:
            with_checkout += 1

        # ── Topic tagging ───────────────────────────────────────────────────
        for rule in TOPIC_RULES:
            if _matches_any(user_text, rule["keywords"]):
                topic_counts[rule["id"]] += 1
                if len(topic_examples[rule["id"]]) < 3:
                    # grab the first matching user message as example
                    for m in conv.get("messages", []):
                        if m.get("role") == "user" and _matches_any(
                            m["content"], rule["keywords"]
                        ):
                            snippet = m["content"][:80].replace("\n", " ")
                            topic_examples[rule["id"]].append(snippet)
                            break

        # ── Non-purchase reasons (only for convs WITHOUT checkout) ──────────
        if not checked_out:
            for rule in NON_PURCHASE_REASONS:
                if _matches_any(user_text, rule["keywords"]):
                    reason_counts[rule["id"]] += 1

        # ── Sentiment ───────────────────────────────────────────────────────
        mood = _sentiment(user_text)
        sentiment_counts[mood] += 1

        # Low rating → at risk
        rating = conv.get("rating")
        if rating and rating <= 2:
            mood = "angry"  # override

        # ── At-risk detection ───────────────────────────────────────────────
        cinfo    = conv.get("customer_info") or {}
        msgs     = conv.get("messages", [])
        last_msg = msgs[-1] if msgs else {}

        is_at_risk = False
        signal     = ""

        if mood == "angry":
            is_at_risk = True
            signal     = "تعبير عن عدم الرضا"
        elif rating and rating <= 2:
            is_at_risk = True
            signal     = f"تقييم منخفض ({rating}★)"
        elif not conv.get("bot_enabled", True) and not checked_out:
            # Admin took over but no order was placed
            is_at_risk = True
            signal     = "تدخل الإدارة بدون إتمام شراء"

        if is_at_risk:
            at_risk.append({
                "session_id":     sid,
                "signal":         signal,
                "last_message":   last_msg.get("content", "")[:120],
                "last_role":      last_msg.get("role", ""),
                "ts":             conv.get("last_activity", ""),
                "customer_name":  cinfo.get("name", "—"),
                "customer_phone": cinfo.get("phone", "—"),
                "rating":         rating,
            })

    # ── Sort & compute percentages ──────────────────────────────────────────
    top_questions = sorted(
        [
            {
                "id":      r["id"],
                "label":   r["label"],
                "icon":    r["icon"],
                "count":   topic_counts[r["id"]],
                "percent": round(topic_counts[r["id"]] / total_convs * 100, 1)
                           if total_convs else 0,
                "examples": topic_examples[r["id"]],
            }
            for r in TOPIC_RULES
            if topic_counts[r["id"]] > 0
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    non_purchase_total = sum(reason_counts.values()) or 1
    non_purchase = sorted(
        [
            {
                "id":      r["id"],
                "label":   r["label"],
                "icon":    r["icon"],
                "count":   reason_counts[r["id"]],
                "percent": round(reason_counts[r["id"]] / non_purchase_total * 100, 1),
            }
            for r in NON_PURCHASE_REASONS
            if reason_counts[r["id"]] > 0
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    # Sort at-risk by timestamp (newest first)
    at_risk.sort(key=lambda x: x["ts"], reverse=True)

    without_checkout = total_convs - with_checkout
    conversion_rate  = round(with_checkout / total_convs * 100, 1) if total_convs else 0

    return {
        "top_questions":     top_questions,
        "non_purchase":      non_purchase,
        "at_risk_customers": at_risk[:50],   # cap at 50
        "sentiment_summary": {
            **sentiment_counts,
            "total": total_convs,
        },
        "conversion": {
            "total_convs":      total_convs,
            "with_checkout":    with_checkout,
            "without_checkout": without_checkout,
            "conversion_rate":  conversion_rate,
        },
    }
