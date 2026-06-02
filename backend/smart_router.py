"""
Pre-LLM fast path — "smart router".

Answers a slice of incoming messages DETERMINISTICALLY, without calling the
LLM, to cut cost and latency. The bot still feels natural because we only
short-circuit when we're highly confident:

    1. Greetings / thanks / farewell  → a warm canned reply
    2. Stored FAQ exact/fuzzy match    → the admin's own answer
    3. Informational intent            → call a no-argument tool directly
                                         (payment methods, shipping, branches,
                                          offers, brands, store contact)

🔴 SAFETY: this layer NEVER handles pricing, quotes, product recommendations,
order tracking, checkout, or anything that depends on specs / quantity / live
data. Those always fall through to the LLM + tools. When in doubt → return
None and let the model handle it. Wrong-but-confident is worse than a model call.

Public API:
    await route(message, store_id) -> dict | None
        {"type": "reply", "text": str, "source": str}   # return text directly
        {"type": "tool",  "tool": str, "source": str}    # caller runs no-arg tool
        None                                              # fall through to LLM
"""
from __future__ import annotations
import re
import time
import random
import database as db


# ── Arabic text normalisation ────────────────────────────────────────────────
_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_NON_WORD = re.compile(r"[^\w؀-ۿ]+")


def normalize(text: str) -> str:
    """Lowercase, strip tashkeel/tatweel, unify alef/ya/ta-marbuta, de-punctuate."""
    if not text:
        return ""
    t = _TASHKEEL.sub("", text)
    t = (t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
           .replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي"))
    t = _NON_WORD.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def _tokens(text: str) -> set[str]:
    return set(normalize(text).split())


# ── 1. Greetings / thanks / farewell ─────────────────────────────────────────
# A message is treated as a *pure* greeting only when nothing meaningful is
# left after removing greeting/filler tokens — so "مرحبا عايز اسعار كروت"
# still goes to the LLM (it carries a real request).
_GREET_TOKENS = {
    "سلام", "السلام", "عليكم", "وعليكم", "ورحمه", "الله", "وبركاته",
    "مرحبا", "مرحبتين", "اهلا", "اهلين", "هلا", "هلو", "هاي", "هالو",
    "صباح", "مساء", "الخير", "النور", "يا", "حياك", "حياكم", "السﻻم",
}
_THANKS_TOKENS = {
    "شكرا", "شكر", "مشكور", "مشكوره", "تسلم", "تسلمو", "تسلمون", "يعطيك",
    "يعطيكم", "العافيه", "ماقصرت", "ماقصرتو", "كثر", "خيرك", "جزاك",
    "جزيلا", "جزيلن", "الف", "يخليك", "يسعدك", "ايدك", "ربي",
}
_BYE_TOKENS = {"باي", "مع", "السلامه", "اللقاء", "امان", "نشوفكم", "تصبح", "تصبحون"}

_FILLER = {"يا", "لو", "سمحت", "من", "فضلك", "حبيبي", "استاذ", "اخي", "اختي", "."}

_GREET_REPLIES = [
    "أهلاً وسهلاً! 👋 كيف أقدر أساعدك اليوم؟",
    "حيّاك الله! 🌟 تحت أمرك، وش تحتاج؟",
    "مرحباً بك! 😊 كيف أخدمك؟",
    "أهلاً فيك! 👋 أنا جاهز أساعدك في أي استفسار.",
]
_THANKS_REPLIES = [
    "العفو! 🌟 أي خدمة ثانية؟",
    "تسلم! 😊 أنا في خدمتك دايماً.",
    "لا شكر على واجب! تحتاج شي ثاني؟",
    "حياك الله! 🙏 موجود لو احتجت أي شي.",
]
_BYE_REPLIES = [
    "في أمان الله! 👋 نسعد بخدمتك في أي وقت.",
    "مع السلامة! 🌟 لا تتردد ترجع لنا لو احتجت أي شي.",
    "إلى اللقاء! 😊 يومك سعيد.",
]


def _pure_match(message: str, vocab: set[str]) -> bool:
    """True if the message is essentially only tokens from `vocab` (+ filler)."""
    toks = _tokens(message)
    if not toks:
        return False
    hit = toks & vocab
    if not hit:
        return False
    leftover = toks - vocab - _FILLER - _GREET_TOKENS  # greetings ok as filler
    return len(leftover) == 0


def _match_smalltalk(message: str) -> dict | None:
    # Thanks before greeting (a "شكراً" mid-chat shouldn't read as hello)
    if _pure_match(message, _THANKS_TOKENS):
        return {"type": "reply", "text": random.choice(_THANKS_REPLIES), "source": "thanks"}
    if _pure_match(message, _BYE_TOKENS):
        return {"type": "reply", "text": random.choice(_BYE_REPLIES), "source": "farewell"}
    if _pure_match(message, _GREET_TOKENS):
        return {"type": "reply", "text": random.choice(_GREET_REPLIES), "source": "greeting"}
    return None


# ── 3. Informational intents → no-arg tools ──────────────────────────────────
# Strong, mostly multi-word phrases to avoid hijacking nuanced messages.
# Each maps to a tool that takes NO input. Pricing/product words are absent
# on purpose — those must reach the LLM.
_INTENTS = [
    ("get_payment_methods", [
        "طرق الدفع", "وسائل الدفع", "طريقه الدفع", "كيف ادفع", "كيف الدفع",
        "تقبلون تابي", "تقبلون تمارا", "في تابي", "في تمارا", "دفع عند الاستلام",
        "ابل باي", "مدى", "تحويل بنكي",
    ]),
    ("get_shipping_options", [
        "شركات الشحن", "شركه الشحن", "طريقه الشحن", "كيف الشحن", "كيف التوصيل",
        "تشحنون", "توصلون", "في توصيل", "مده الشحن", "كم ياخذ الشحن", "كم يوصل الطلب",
    ]),
    ("get_branches", [
        "وين فروعكم", "فروعكم", "عندكم فرع", "موقعكم", "وين مكانكم", "عنوان المحل",
        "استلام من المحل", "استلام من الفرع",
    ]),
    ("get_current_offers", [
        "في عروض", "العروض", "عندكم خصم", "في خصومات", "تخفيضات", "كوبون", "كود خصم",
    ]),
    ("get_brands", [
        "ايش الماركات", "الماركات", "العلامات التجاريه", "وش تبيعون ماركات",
    ]),
    ("get_store_contact_info", [
        "رقم الواتساب", "رقم التواصل", "حسابكم", "حساباتكم", "السجل التجاري",
        "الرقم الضريبي", "انستقرام", "تويتر", "عندكم تطبيق",
    ]),
]


def _match_intent(message: str) -> dict | None:
    norm = normalize(message)
    if not norm:
        return None
    # Keep it conservative: only short, focused messages get intent-routed.
    if len(norm.split()) > 9:
        return None
    for tool, phrases in _INTENTS:
        for p in phrases:
            if normalize(p) in norm:
                return {"type": "tool", "tool": tool, "source": f"intent:{tool}"}
    return None


# ── 2. Stored FAQ matching (per-store, TTL-cached) ───────────────────────────
_FAQ_CACHE: dict[str, tuple[float, list[dict]]] = {}
_FAQ_TTL = 60.0  # seconds


async def _get_faqs(store_id: str) -> list[dict]:
    """Return enabled FAQ entries [{q_norm, q_tokens, answer}] for a store."""
    now = time.time()
    hit = _FAQ_CACHE.get(store_id)
    if hit and now - hit[0] < _FAQ_TTL:
        return hit[1]
    faqs: list[dict] = []
    try:
        for e in await db.list_training(store_id):
            if e.get("kind") != "faq" or not e.get("enabled", True):
                continue
            q = (e.get("title") or "").strip()
            a = (e.get("content") or "").strip()
            if q and a:
                faqs.append({
                    "q_norm":   normalize(q),
                    "q_tokens": set(normalize(q).split()),
                    "answer":   a,
                })
    except Exception as exc:
        print(f"[smart_router] FAQ load failed for {store_id!r}: {exc}")
        faqs = []
    _FAQ_CACHE[store_id] = (now, faqs)
    return faqs


def invalidate_faq_cache(store_id: str | None = None):
    """Call after the admin edits FAQs so the router picks them up immediately."""
    if store_id is None:
        _FAQ_CACHE.clear()
    else:
        _FAQ_CACHE.pop(store_id, None)


async def _match_faq(message: str, store_id: str) -> dict | None:
    faqs = await _get_faqs(store_id)
    if not faqs:
        return None
    msg_norm   = normalize(message)
    msg_tokens = set(msg_norm.split())
    if len(msg_tokens) < 2:
        return None

    best, best_score = None, 0.0
    for f in faqs:
        if f["q_norm"] and f["q_norm"] == msg_norm:
            return {"type": "reply", "text": f["answer"], "source": "faq-exact"}
        union = msg_tokens | f["q_tokens"]
        if not union:
            continue
        jacc = len(msg_tokens & f["q_tokens"]) / len(union)
        if jacc > best_score:
            best, best_score = f, jacc
    # High threshold — only answer when the questions clearly line up.
    if best and best_score >= 0.6:
        return {"type": "reply", "text": best["answer"], "source": "faq-fuzzy"}
    return None


# ── Public entry point ───────────────────────────────────────────────────────
async def route(message: str, store_id: str) -> dict | None:
    """
    Try to answer `message` without the LLM. Returns a dict (see module
    docstring) or None to fall through. Never raises.
    """
    try:
        if not message or not message.strip():
            return None
        # 1) Greetings / thanks / farewell
        m = _match_smalltalk(message)
        if m:
            return m
        # 2) Stored FAQ (admin's own Q&A)
        m = await _match_faq(message, store_id)
        if m:
            return m
        # 3) Informational intent → no-arg tool
        m = _match_intent(message)
        if m:
            return m
    except Exception as exc:
        print(f"[smart_router] route error (falling through to LLM): {exc}")
    return None
