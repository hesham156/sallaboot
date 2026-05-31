import os
import re as _re
import json
import anthropic
from anthropic import AsyncAnthropic
from groq import AsyncGroq
from openai import AsyncOpenAI
from salla_client import SallaClient
from store_sync import build_knowledge_summary, get_store_data
import conversation_store as cs
import store_manager as sm
import pricing_calculator as pc
import store_brain as brain

# ── System prompt ──────────────────────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """أنت مساعد مبيعات ذكي لمتجر طباعة احترافي على منصة سلة. اسمك "مساعد المتجر".

مهمتك الأساسية: مساعدة العميل في اختيار المنتج المناسب وإتمام الطلب بسلاسة.

═══ سلوك المبيعات الاحترافي ═══
• فور أن تفهم احتياج العميل → استخدم suggest_products فوراً (لا تنتظر)
• دائماً اعرض 2-3 خيارات وليس خياراً واحداً
• بعد اختيار العميل → اسأل: الكمية؟ المواصفات؟ (مقاس، ورق، لون، وجهين/وجه)
• إذا اختار منتجاً → add_to_cart
• اقترح منتجات مكملة (bundle): "معك كروت شخصية، هل تحتاج مظاريف أو فلايرات؟"
• عند إتمام الطلب:
  ١. اجمع: الاسم + رقم الجوال + البريد الإلكتروني → set_customer_info
  ٢. اعرض ملخص الطلب: كل منتج، كميته، سعره، الإجمالي
  ٣. انتظر تأكيد العميل
  ٤. بعد التأكيد → checkout

═══ حساب الأسعار الدقيقة (مهم جداً) ═══
عند طلب تسعير دقيق للطباعة، استخدم calculate_advanced_quote (الأفضل والأدق).
الخطوات:
  ١. اسأل العميل: نوع الطباعة (رول/ديجيتال/أوفست/UV DTF) + المقاس (عرض×ارتفاع بالسم) + الكمية
  ٢. للديجيتال/الأوفست: استخدم get_printing_options الأول لمعرفة أنواع الورق المتاحة
  ٣. اقترح على العميل أنواع الورق من القائمة المتاحة فقط
  ٤. مرّر القيم لـ calculate_advanced_quote
  ٥. اعرض على العميل: السعر النهائي + المساحة/الشيتات + أي توفير حصل من تدوير التصميم

استخدم calculate_print_quote فقط للتقديرات السريعة بدون مقاسات محددة.

═══ قواعد المحادثة ═══
• تكلم دائماً بالعربية بأسلوب ودي ومبهج
• اسم المتجر ووصفه موجودين في "ملف المتجر" أعلى الـ prompt — استخدمهم بطبيعية
• لو سأل العميل عن واتساب/سوشيال/تطبيق/سجل تجاري → get_store_contact_info
• لو سأل العميل عن شركات الشحن/التوصيل → get_shipping_options
• لتتبع طلب موجود استخدم track_order
• إذا طلب العميل فاتورة أو إيصال → استخدم get_order_invoice (يقبل رقم الطلب أو رقم الفاتورة)
• عندما يعطيك العميل رقم جواله أو اسمه → استخدم lookup_customer فوراً لجلب بياناته من سلة
  - هذا يُغني عن سؤاله عن الاسم/الإيميل مرة أخرى وينجز الطلب بشكل أسرع
• ملف التصميم؟ قل: "يمكنك إرفاق ملف التصميم مباشرة هنا في المحادثة 📎"
• لا تتكلم عن أي شيء خارج نطاق المتجر"""


async def get_system_prompt_async(store_id: str = "default") -> str:
    """
    Async system-prompt builder. Includes the bot_training rows the admin
    added through "تدريب البوت" (instructions, FAQs, uploaded reference
    files). Falls back to the sync version if anything goes wrong.
    """
    try:
        knowledge = await brain.get_knowledge_for_prompt_async(store_id)
    except Exception as exc:
        print(f"[agent] get_knowledge_for_prompt_async failed for {store_id!r}: {exc}")
        knowledge = ""
    if knowledge:
        return BASE_SYSTEM_PROMPT + "\n\n" + knowledge
    return get_system_prompt(store_id)


def get_system_prompt(store_id: str = "default") -> str:
    """
    Sync system-prompt builder (no training material). Used as a fallback
    when the async path can't be taken — kept for backward compat.
    """
    try:
        knowledge = brain.get_knowledge_for_prompt(store_id)
    except Exception as exc:
        print(f"[agent] brain.get_knowledge_for_prompt failed for {store_id!r}: {exc}")
        knowledge = ""
    if not knowledge:
        # Legacy fallback
        try:
            legacy = build_knowledge_summary(store_id)
            if legacy:
                max_chars = 4500
                if len(legacy) > max_chars:
                    legacy = legacy[:max_chars] + "\n… (مزيد من المنتجات — استخدم suggest_products)"
                knowledge = f"══ كتالوج المتجر ══\n{legacy}\n══ نهاية الكتالوج ══"
        except Exception:
            pass
    if knowledge:
        return BASE_SYSTEM_PROMPT + "\n\n" + knowledge
    return BASE_SYSTEM_PROMPT


# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS = [
    # ── Store knowledge / discovery ────────────────────────────────────────
    {
        "name": "get_store_contact_info",
        "description": (
            "اعرض بيانات التواصل والحسابات الرسمية للمتجر "
            "(واتساب، إيميل، تويتر، انستقرام، فيسبوك، يوتيوب، تطبيقات iOS/أندرويد، إلخ) "
            "بالإضافة لبيانات الترخيص والسجل التجاري. "
            "استخدمها لما يسأل العميل: ايش رقم الواتساب؟ / فين متابعتكم؟ / "
            "السجل التجاري كام؟ / عندكم تطبيق؟"
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_shipping_options",
        "description": (
            "اعرض شركات الشحن المتاحة لهذا المتجر (سمسا، أرامكس، DHL، البريد السعودي، إلخ) "
            "مع نوع التفعيل (يدوي أو عبر API). "
            "استخدمها لما يسأل العميل: ايش شركات الشحن؟ / تشحنون بسمسا؟ / "
            "كم سعر الشحن؟ / فيه شحن سريع؟"
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_store_overview",
        "description": (
            "اعرض نظرة عامة سريعة على المتجر: عدد المنتجات، عدد التصنيفات، "
            "نطاق الأسعار، أكثر التصنيفات منتجاتاً. استخدمها عندما يسأل العميل "
            "أسئلة عامة مثل: ايش عندكم؟ / ايش الأقسام؟ / ايش أرخص حاجة؟"
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_by_category",
        "description": (
            "ابحث عن جميع المنتجات في تصنيف معين. مفيد لما يسأل العميل "
            "عن قسم محدد مثل: 'ايش عندكم في كروت شخصية؟' أو 'وريني البنرات'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category_name": {"type": "string", "description": "اسم التصنيف (مطابقة جزئية)"},
            },
            "required": ["category_name"],
        },
    },
    {
        "name": "suggest_products",
        "description": (
            "ابحث واقترح منتجات مناسبة لاحتياج العميل. "
            "استخدم هذه الأداة فور فهم ما يريده العميل. "
            "تُعيد قائمة بأفضل 4 منتجات مع صورها وأسعارها."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "needs": {
                    "type": "string",
                    "description": "وصف ما يحتاجه العميل (مثل: كروت شخصية، بنرات، تيشيرتات)",
                },
                "budget": {
                    "type": "string",
                    "description": "الميزانية التقريبية إن ذُكرت (اختياري)",
                },
            },
            "required": ["needs"],
        },
    },
    {
        "name": "get_product_details",
        "description": "جلب تفاصيل منتج معين بما فيها الأسعار والمواصفات والخيارات المتاحة.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "معرف المنتج في سلة"},
            },
            "required": ["product_id"],
        },
    },
    # ── Cart ───────────────────────────────────────────────────────────────
    {
        "name": "add_to_cart",
        "description": (
            "أضف منتجاً لسلة تسوق العميل. "
            "استخدمها بعد اختيار العميل للمنتج وتحديد الكمية."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "معرف المنتج"},
                "product_name": {"type": "string", "description": "اسم المنتج"},
                "quantity": {"type": "integer", "description": "الكمية المطلوبة"},
                "price": {
                    "type": "string",
                    "description": "سعر الوحدة الواحدة (من بيانات المتجر أو حاسبة السعر)",
                },
                "notes": {
                    "type": "string",
                    "description": "ملاحظات خاصة: مواصفات التصميم، ألوان، مقاسات، وغيرها",
                },
            },
            "required": ["product_id", "product_name", "quantity"],
        },
    },
    {
        "name": "view_cart",
        "description": "اعرض محتويات سلة تسوق العميل الحالية والإجمالي.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "remove_from_cart",
        "description": "أزل منتجاً من سلة التسوق.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "معرف المنتج المراد حذفه"},
            },
            "required": ["product_id"],
        },
    },
    # ── Checkout ───────────────────────────────────────────────────────────
    {
        "name": "set_customer_info",
        "description": (
            "احفظ بيانات العميل (اسم + جوال + إيميل) لإتمام الطلب. "
            "استخدم هذه الأداة قبل checkout. "
            "اجمع المعلومات بشكل طبيعي في المحادثة."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name":  {"type": "string", "description": "الاسم الكامل للعميل"},
                "phone": {"type": "string", "description": "رقم الجوال"},
                "email": {"type": "string", "description": "البريد الإلكتروني"},
            },
            "required": ["name", "phone"],
        },
    },
    {
        "name": "checkout",
        "description": (
            "أنشئ الطلب في سلة وأرسل رابط الدفع. "
            "استخدم هذه الأداة بعد: ١) تأكيد محتوى السلة ٢) جمع بيانات العميل ٣) موافقة العميل."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_notes": {
                    "type": "string",
                    "description": "ملاحظات عامة على الطلب (اختياري)",
                },
            },
        },
    },
    # ── Support ────────────────────────────────────────────────────────────
    {
        "name": "track_order",
        "description": (
            "تتبع حالة طلب موجود وعرض تفاصيله الكاملة: الحالة، المنتجات، الشحن، ورابط التتبع. "
            "يقبل رقم الطلب/المرجع أو رقم جوال العميل. "
            "استخدمها عندما يسأل العميل: وين طلبي؟ / ما حالة طلبي؟ / طلبي وصل؟"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_reference": {
                    "type": "string",
                    "description": "رقم الطلب أو رقم المرجع (مثال: ORD-12345 أو 12345)",
                },
                "customer_phone": {
                    "type": "string",
                    "description": "رقم جوال العميل للبحث عن طلباته (بديل عن رقم الطلب)",
                },
            },
        },
    },
    {
        "name": "get_order_invoice",
        "description": (
            "اجلب فاتورة طلب معين وعرض تفاصيلها الكاملة: رقم الفاتورة، التاريخ، المنتجات، "
            "المجموع، الضريبة، الشحن، الإجمالي، وطريقة الدفع. "
            "استخدمها عندما يطلب العميل: فاتورتي / إيصال الطلب / أبغى فاتورة ضريبية. "
            "يقبل رقم الطلب أو رقم الفاتورة مباشرةً."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_reference": {
                    "type": "string",
                    "description": "رقم الطلب أو مرجعه (مثال: 12345 أو ORD-12345) — يُستخدم للبحث عن الفاتورة",
                },
                "invoice_id": {
                    "type": "integer",
                    "description": "رقم الفاتورة مباشرةً إن كان العميل يعرفه (اختياري)",
                },
            },
        },
    },
    {
        "name": "lookup_customer",
        "description": (
            "ابحث عن عميل في سلة وجلب بياناته الكاملة: الاسم، الجوال، الإيميل، البلد، "
            "عدد طلباته، ورصيد المحفظة إن طُلب. "
            "استخدمها في أي من هذه الحالات: "
            "١) العميل أعطاك رقم جواله أو اسمه وتريد التحقق من وجوده في سلة. "
            "٢) قبل إنشاء الطلب للتأكد من هوية العميل وملء بياناته تلقائياً. "
            "٣) عندما تحتاج customer_id لـ Salla لإكمال أي عملية."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": "رقم جوال العميل للبحث (بدون مفتاح الدولة)",
                },
                "customer_id": {
                    "type": "integer",
                    "description": "معرّف العميل في سلة إن كان متاحاً (البحث المباشر الأسرع)",
                },
                "name": {
                    "type": "string",
                    "description": "اسم العميل للبحث (اختياري، يُستخدم إن لم يتوفر الجوال)",
                },
                "include_stats": {
                    "type": "boolean",
                    "description": "هل تريد إحصائيات الطلبات والرصيد؟ (اختياري، افتراضي false)",
                },
            },
        },
    },
    {
        "name": "get_abandoned_carts",
        "description": (
            "ابحث في السلات المتروكة لمعرفة ما إذا كان العميل قد ترك منتجات من قبل. "
            "استخدم هذه الأداة عندما يذكر العميل أنه أضاف منتجات سابقاً ولم يكمل الطلب، "
            "أو عندما يسأل عن سلته السابقة. تُعيد الرابط المباشر لإكمال الدفع."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_phone": {
                    "type": "string",
                    "description": "رقم جوال العميل للبحث في السلات المتروكة (اختياري)",
                },
            },
        },
    },
    {
        "name": "calculate_print_quote",
        "description": "احسب سعراً تقديرياً مبدئياً للطباعة بناءً على نوع المنتج والكمية (تقدير سريع). للحساب الدقيق استخدم calculate_advanced_quote.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_type": {"type": "string", "description": "نوع المنتج: كروت، بنر، تيشيرت، فلاير، إلخ"},
                "quantity": {"type": "integer", "description": "الكمية"},
                "size": {"type": "string", "description": "المقاس (اختياري)"},
                "paper_type": {"type": "string", "description": "نوع الورق/الخامة (اختياري)"},
                "sides": {
                    "type": "string",
                    "enum": ["وجه واحد", "وجهين"],
                    "description": "وجه أو وجهين (اختياري)",
                },
            },
            "required": ["product_type", "quantity"],
        },
    },
    # ── Advanced printing calculator (uses store-specific pricing config) ─────
    {
        "name": "get_printing_options",
        "description": (
            "اعرض الخيارات المتاحة لحساب أسعار الطباعة من إعدادات هذا المتجر: "
            "أنواع الطباعة المفعّلة (رول/ديجيتال/أوفست/UV DTF)، أنواع الورق، "
            "مقاسات الشيتات، والإضافات. استخدمها قبل calculate_advanced_quote "
            "عشان تعرف الخيارات المتاحة وتقترح على العميل."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "calculate_advanced_quote",
        "description": (
            "احسب سعراً دقيقاً للطباعة باستخدام إعدادات أسعار المتجر الحقيقية. "
            "اسأل العميل عن: نوع الطباعة (رول/ديجيتال/أوفست/UV DTF)، المقاس "
            "(عرض × ارتفاع بالسم)، الكمية، ونوع الورق إن لزم. "
            "للديجيتال يمكن إضافة: بصمة، سبوت UV، إضافات. "
            "للأوفست: نوع القص، ثنية، تخريم. "
            "استخدم get_printing_options الأول عشان تعرف الخيارات المتاحة."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "printing_type": {
                    "type": "string",
                    "enum": ["roll", "digital", "offset", "uvdtf"],
                    "description": "نوع الطباعة: roll=رول | digital=ديجيتال | offset=أوفست | uvdtf=UV DTF",
                },
                "width":    {"type": "number",  "description": "عرض التصميم بالسم"},
                "height":   {"type": "number",  "description": "ارتفاع التصميم بالسم"},
                "quantity": {"type": "integer", "description": "الكمية المطلوبة"},
                "paper_type": {
                    "type": "string",
                    "description": "اسم نوع الورق من القائمة المتاحة (للديجيتال أو الأوفست). استخدم get_printing_options لمعرفة الأسماء.",
                },
                "sheet_size": {
                    "type": "string",
                    "description": "اسم مقاس الشيت من القائمة المتاحة (للديجيتال فقط).",
                },
                "roll_width": {
                    "type": "number",
                    "description": "عرض الرول بالسم (للرول فقط، اختياري — افتراضي من الإعدادات).",
                },
                "addons": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "أسماء الإضافات المطلوبة من القائمة المتاحة (للديجيتال فقط).",
                },
                "foil_width":  {"type": "number", "description": "عرض البصمة بالسم (ديجيتال، اختياري)"},
                "foil_height": {"type": "number", "description": "ارتفاع البصمة بالسم (ديجيتال، اختياري)"},
                "spot_uv":     {"type": "boolean", "description": "إضافة سبوت يو في (ديجيتال، اختياري)"},
                "cutting": {
                    "type": "string",
                    "enum": ["normal", "diecut"],
                    "description": "نوع القص (أوفست): normal=قص عادي، diecut=قص داي كت",
                },
                "folding":  {"type": "boolean", "description": "ثنية (أوفست، اختياري)"},
                "punching": {"type": "boolean", "description": "تخريم (أوفست، اختياري)"},
            },
            "required": ["printing_type", "width", "height", "quantity"],
        },
    },
]

# ── Pricing table ──────────────────────────────────────────────────────────────
PRICING = {
    "كروت": {"setup": 30, "unit": 0.35, "min_qty": 100},
    "بنر":  {"setup": 0,  "sqm":  30,   "min_qty": 1},
    "تيشيرت": {"setup": 50, "unit": 20,   "min_qty": 10},
    "فلاير":  {"setup": 25, "unit": 0.25, "min_qty": 500},
    "كتالوج": {"setup": 60, "unit": 8,    "min_qty": 50},
    "ستيكر":  {"setup": 20, "unit": 0.15, "min_qty": 200},
    "بروشور": {"setup": 25, "unit": 0.4,  "min_qty": 200},
    "لافتة":  {"setup": 0,  "sqm":  35,   "min_qty": 1},
    "default": {"setup": 30, "unit": 0.5, "min_qty": 50},
}

ORDER_STATUS_AR = {
    "pending":      "قيد الانتظار",
    "under_review": "قيد المراجعة",
    "processing":   "جاري التجهيز",
    "in_shipping":  "قيد الشحن",
    "completed":    "مكتمل",
    "cancelled":    "ملغي",
    "refunded":     "مسترجع",
    "on_hold":      "معلق",
}


# ── Helper: strip Llama tool-call syntax that leaks into content ───────────────
_FUNC_TAG   = _re.compile(r"<function=[^>]*>.*?</?\s*function\s*/?>",  _re.DOTALL | _re.IGNORECASE)
_FUNC_OPEN  = _re.compile(r"<function=[^>]*/?>.*",                     _re.DOTALL | _re.IGNORECASE)
_PREFIX_RE  = _re.compile(r"^(تم الرد سابقاً[:\s]*|الرد السابق[:\s]*|Previously[:\s]*)", _re.IGNORECASE)


def _clean_reply(text: str) -> str:
    """Remove Llama-leaked <function=...> tags and other artefacts from the reply."""
    if not text:
        return ""
    text = _FUNC_TAG.sub("", text)    # complete <function=...>...</function>
    text = _FUNC_OPEN.sub("", text)   # unclosed <function=...> to end of string
    text = _PREFIX_RE.sub("", text)   # hallucinated "تم الرد سابقاً:" prefix
    return text.strip()


# ── Agent ──────────────────────────────────────────────────────────────────────

class PrintingAgent:
    def __init__(self, store_id: str = "default", access_token: str = ""):
        self.store_id = store_id

        # Per-store AI config takes priority over env vars.
        # IMPORTANT: if ANY per-store key is configured, use ONLY per-store keys —
        # do NOT mix with env vars.  Mixing causes provider switching to fail:
        # e.g. user clears Groq and sets OpenAI, but groq_key = "" or GROQ_ENV_VAR
        # would fall back to the env var and silently keep using Groq.
        ai_cfg = sm.get_ai_config(store_id) if store_id else {}
        has_per_store_key = bool(
            ai_cfg.get("groq_api_key")      or
            ai_cfg.get("anthropic_api_key") or
            ai_cfg.get("openai_api_key")
        )

        if has_per_store_key:
            # Per-store config is explicit — respect exactly what the admin set
            groq_key      = ai_cfg.get("groq_api_key",      "").strip()
            anthropic_key = ai_cfg.get("anthropic_api_key", "").strip()
            openai_key    = ai_cfg.get("openai_api_key",    "").strip()
        else:
            # No per-store keys at all — fall back to global env vars
            groq_key      = os.getenv("GROQ_API_KEY",      "")
            anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
            openai_key    = os.getenv("OPENAI_API_KEY",    "")

        self._bot_name = ai_cfg.get("bot_name", "").strip()

        # Per-store model override — sensible defaults per provider
        cfg_model = ai_cfg.get("ai_model", "").strip()
        self._groq_model      = (cfg_model if ai_cfg.get("groq_api_key")      else "") or "llama-3.3-70b-versatile"
        self._anthropic_model = (cfg_model if ai_cfg.get("anthropic_api_key") else "") or "claude-sonnet-4-6"
        self._openai_model    = (cfg_model if ai_cfg.get("openai_api_key")    else "") or "gpt-4o-mini"

        # Provider priority: Groq → Anthropic → OpenAI (fallback to env vars)
        if groq_key:
            self.provider       = "groq"
            self.groq_client    = AsyncGroq(api_key=groq_key)
            self.ai             = None
            self.openai_client  = None
        elif anthropic_key:
            self.provider       = "anthropic"
            self.ai             = AsyncAnthropic(api_key=anthropic_key)
            self.groq_client    = None
            self.openai_client  = None
        elif openai_key:
            self.provider       = "openai"
            self.openai_client  = AsyncOpenAI(api_key=openai_key)
            self.ai             = None
            self.groq_client    = None
        else:
            raise RuntimeError(
                "يجب تعيين GROQ_API_KEY أو ANTHROPIC_API_KEY أو OPENAI_API_KEY "
                "في إعدادات المتجر أو متغيرات البيئة."
            )

        token      = access_token or os.getenv("SALLA_ACCESS_TOKEN", "")
        self.salla = SallaClient(token, store_id=store_id) if token else None

    # ── Tool runner ────────────────────────────────────────────────────────────
    async def _run_tool(self, name: str, inputs: dict, session_id: str = "") -> str:
        try:
            # ── get_store_contact_info ──────────────────────────────────────
            if name == "get_store_contact_info":
                info = brain.get_store_info(self.store_id)
                if not info:
                    return "⚠️ بيانات المتجر لم تُحمَّل بعد. يرجى عمل مزامنة من لوحة التحكم."

                lines = [f"📇 **بيانات التواصل — {info.get('name', 'المتجر')}**"]
                if info.get("verified"):
                    lines.append("✓ متجر موثّق من سلة")
                if info.get("domain"):
                    lines.append(f"🌐 الموقع: {info['domain']}")
                if info.get("email"):
                    lines.append(f"📧 البريد: {info['email']}")

                social = info.get("social") or {}
                if social.get("whatsapp"):
                    lines.append(f"💬 واتساب: {social['whatsapp']}")

                social_map = [
                    ("twitter",         "🐦 تويتر/X"),
                    ("instagram",       "📷 انستقرام"),
                    ("facebook",        "📘 فيسبوك"),
                    ("snapchat",        "👻 سناب شات"),
                    ("youtube",         "▶️ يوتيوب"),
                    ("telegram",        "✈️ تليجرام"),
                    ("maroof",          "🏅 معروف"),
                    ("appstore_link",   "🍎 تطبيق iOS"),
                    ("googleplay_link", "🤖 تطبيق أندرويد"),
                ]
                for key, label in social_map:
                    v = (social.get(key) or "").strip()
                    if v and v not in ("https://", "http://"):
                        lines.append(f"{label}: {v}")

                lic = info.get("licenses") or {}
                if any(lic.values()):
                    lines.append("\n📋 **الترخيص:**")
                    if lic.get("commercial_number"):
                        lines.append(f"• السجل التجاري: {lic['commercial_number']}")
                    if lic.get("tax_number"):
                        lines.append(f"• الرقم الضريبي: {lic['tax_number']}")
                    if lic.get("freelance_number"):
                        lines.append(f"• رخصة العمل الحر: {lic['freelance_number']}")

                return "\n".join(lines)

            # ── get_shipping_options ────────────────────────────────────────
            elif name == "get_shipping_options":
                carriers = brain.get_shipping_companies(self.store_id)
                if not carriers:
                    return ("⚠️ لم يتم تحميل قائمة شركات الشحن بعد. "
                            "ربما يحتاج المتجر لتفعيل صلاحية shipping.read.")
                lines = [f"🚚 **شركات الشحن المتاحة ({len(carriers)})**"]
                for c in carriers:
                    name = c.get("name", "")
                    act  = c.get("activation_type", "")
                    badge = "🔗 مفعّل عبر API" if act == "api" else "📝 يدوي"
                    lines.append(f"• {name} — {badge}")
                lines.append("")
                lines.append("_ملاحظة: التسعير الفعلي للشحن يتحدّد عند إتمام الطلب حسب الوزن والمنطقة._")
                return "\n".join(lines)

            # ── get_store_overview ──────────────────────────────────────────
            elif name == "get_store_overview":
                ov = brain.get_overview(self.store_id)
                if ov["available_products"] == 0:
                    return "⚠️ لا توجد منتجات محملة بعد. يرجى عمل مزامنة المتجر."
                lines = [
                    f"📊 **نظرة عامة على المتجر**",
                    f"• المنتجات المتاحة: {ov['available_products']} منتج",
                    f"• التصنيفات: {ov['categories']}",
                ]
                if ov["min_price"] is not None:
                    lines.append(
                        f"• نطاق الأسعار: {ov['min_price']:g} - {ov['max_price']:g} {ov['currency']} "
                        f"(متوسط: {ov['avg_price']:g})"
                    )
                if ov["top_categories"]:
                    cats = "، ".join(
                        f"{c['name']} ({c['count']})" for c in ov["top_categories"][:8]
                    )
                    lines.append(f"• أكبر التصنيفات: {cats}")
                return "\n".join(lines)

            # ── search_by_category ──────────────────────────────────────────
            elif name == "search_by_category":
                cat_name = (inputs.get("category_name") or "").strip()
                if not cat_name:
                    return "⚠️ يرجى تحديد اسم التصنيف."
                items = brain.search_by_category(self.store_id, cat_name, limit=10)
                if not items:
                    return f"لم أجد منتجات في تصنيف '{cat_name}'. جرّب اسم تصنيف آخر."
                lines = [f"وجدت {len(items)} منتج في تصنيف '{cat_name}':"]
                for p in items:
                    price = p.get("price")
                    if isinstance(price, dict):
                        price = price.get("amount", "")
                    cur = p.get("currency", "SAR")
                    lines.append(f"• [{p['id']}] {p['name']} — {price} {cur}")
                # Also surface as a product_cards component so the widget renders them visually
                if session_id:
                    store = get_store_data(self.store_id)
                    cards = []
                    for it in items[:6]:
                        full = next(
                            (p for p in store.get("products", []) if str(p.get("id")) == it["id"]),
                            None,
                        )
                        if full:
                            cards.append(_product_card(full))
                    if cards:
                        cs.set_last_component(session_id, {
                            "type": "product_cards", "products": cards,
                        })
                return "\n".join(lines)

            # ── suggest_products ────────────────────────────────────────────
            elif name == "suggest_products":
                needs   = inputs.get("needs", "").strip().lower()
                budget  = inputs.get("budget", "")
                store   = get_store_data(self.store_id)
                prods   = store.get("products", [])
                if not prods:
                    return "⚠️ لا توجد منتجات محملة بعد."

                # Score each product by keyword match
                scored = []
                keywords = needs.split()
                for p in prods:
                    if p.get("status") == "hidden":
                        continue
                    score = 0
                    text  = " ".join([
                        p.get("name", ""),
                        p.get("description", ""),
                        " ".join(p.get("categories", [])),
                    ]).lower()
                    for kw in keywords:
                        if kw in text:
                            score += 2
                    if p.get("status") == "sale":
                        score += 1
                    scored.append((score, p))

                scored.sort(key=lambda x: -x[0])
                top = [p for score, p in scored if score >= 0][:4]
                if not top:
                    top = prods[:4]

                # Build text summary for LLM
                lines = [f"وجدت {len(top)} منتجات تناسب طلبك:"]
                for p in top:
                    price_str = f"{p.get('price')} {p.get('currency','SAR')}"
                    # Safe price comparison — price may be string, int, float, or dict
                    try:
                        raw_price = p.get("price") or 0
                        raw_sale  = p.get("sale_price") or 0
                        # Salla API sometimes nests price as {"amount": n, "currency": "SAR"}
                        if isinstance(raw_price, dict):
                            raw_price = raw_price.get("amount", 0)
                        if isinstance(raw_sale, dict):
                            raw_sale = raw_sale.get("amount", 0)
                        if raw_sale and float(raw_sale) < float(raw_price):
                            price_str = f"~~{p['price']}~~ → {p['sale_price']} {p.get('currency','SAR')}"
                    except (ValueError, TypeError):
                        pass   # keep original price_str
                    avail = "✅" if (p.get("unlimited_quantity") or (p.get("quantity", 0) > 0)) else "⛔"
                    lines.append(f"• [{p['id']}] {p['name']} — {price_str} {avail}")

                # Store as component for widget
                if session_id:
                    cs.set_last_component(session_id, {
                        "type": "product_cards",
                        "products": [_product_card(p) for p in top],
                    })

                return "\n".join(lines)

            # ── get_product_details ─────────────────────────────────────────
            elif name == "get_product_details":
                pid = str(inputs["product_id"])
                # Try cache first
                store = get_store_data(self.store_id)
                cached = next((p for p in store.get("products", []) if str(p.get("id")) == pid), None)
                if cached:
                    opts = "\n".join(
                        f"  {o['option']}: {', '.join(o['values'][:6])}"
                        for o in cached.get("options", [])
                    )
                    return (
                        f"**{cached['name']}**\n"
                        f"السعر: {cached['price']} {cached.get('currency','SAR')}\n"
                        f"الحالة: {'متوفر' if cached.get('status')=='sale' else 'نفد'}\n"
                        f"الوصف: {cached.get('description','')}\n"
                        f"{opts}"
                    )
                # Fallback to API
                if not self.salla:
                    return "⚠️ لم يتم ربط المتجر بعد."
                data = await self.salla.get_product(pid)
                p = data.get("data", {})
                if not p:
                    return "المنتج غير موجود."
                return (
                    f"**{p.get('name')}**\n"
                    f"السعر: {p.get('price',{}).get('amount')} ريال\n"
                    f"الوصف: {p.get('description','')[:200]}"
                )

            # ── add_to_cart ─────────────────────────────────────────────────
            elif name == "add_to_cart":
                if not session_id:
                    return "⚠️ session_id مفقود."
                pid      = str(inputs["product_id"])
                pname    = inputs["product_name"]
                qty      = max(1, int(inputs.get("quantity", 1)))
                price    = str(inputs.get("price", ""))
                notes    = inputs.get("notes", "")
                currency = "SAR"

                # If price not provided, look up in cache
                if not price:
                    store = get_store_data(self.store_id)
                    prod  = next((p for p in store.get("products", []) if str(p.get("id")) == pid), None)
                    if prod:
                        price    = str(prod.get("price", ""))
                        currency = prod.get("currency", "SAR")

                # Get image for widget
                store  = get_store_data(self.store_id)
                prod   = next((p for p in store.get("products", []) if str(p.get("id")) == pid), {})
                image  = prod.get("image", "")
                url    = prod.get("url", "")

                cs.cart_add(session_id, {
                    "product_id": pid,
                    "name":       pname,
                    "quantity":   qty,
                    "price":      price,
                    "currency":   currency,
                    "notes":      notes,
                    "image":      image,
                    "url":        url,
                })

                cart  = cs.get_cart(session_id)
                total = cs.cart_total(session_id)
                # Update component with current cart
                cs.set_last_component(session_id, {
                    "type":  "cart",
                    "items": cart,
                    "total": f"{total:.2f}",
                    "currency": currency,
                })
                # ── Persist cart immediately so it survives server restarts ──
                await cs.flush(session_id)
                return f"✅ أُضيف '{pname}' (الكمية: {qty:,}) للسلة. السلة تحتوي الآن على {len(cart)} منتج، الإجمالي: {total:.2f} {currency}"

            # ── view_cart ───────────────────────────────────────────────────
            elif name == "view_cart":
                if not session_id:
                    return "⚠️ session_id مفقود."
                cart  = cs.get_cart(session_id)
                total = cs.cart_total(session_id)
                if not cart:
                    return "السلة فارغة. أخبرني ما الذي تريد طلبه!"
                lines = ["محتوى السلة الحالية:"]
                currency = "SAR"
                for item in cart:
                    currency = item.get("currency", "SAR")
                    sub  = float(item.get("price", 0) or 0) * item.get("quantity", 1)
                    line = f"• {item['name']} × {item['quantity']:,} = {sub:.2f} {currency}"
                    if item.get("notes"):
                        line += f"\n  📝 {item['notes']}"
                    lines.append(line)
                lines.append(f"\nالإجمالي: **{total:.2f} {currency}**")
                cs.set_last_component(session_id, {
                    "type":  "cart",
                    "items": cart,
                    "total": f"{total:.2f}",
                    "currency": currency,
                })
                return "\n".join(lines)

            # ── remove_from_cart ────────────────────────────────────────────
            elif name == "remove_from_cart":
                if not session_id:
                    return "⚠️ session_id مفقود."
                pid     = str(inputs["product_id"])
                removed = cs.cart_remove(session_id, pid)
                if removed:
                    cart  = cs.get_cart(session_id)
                    total = cs.cart_total(session_id)
                    cs.set_last_component(session_id, {
                        "type":  "cart",
                        "items": cart,
                        "total": f"{total:.2f}",
                        "currency": "SAR",
                    })
                    # Persist updated cart immediately
                    await cs.flush(session_id)
                    return f"✅ تم حذف المنتج من السلة. الإجمالي الجديد: {total:.2f} ريال"
                return "⚠️ المنتج غير موجود في السلة."

            # ── set_customer_info ───────────────────────────────────────────
            elif name == "set_customer_info":
                if not session_id:
                    return "⚠️ session_id مفقود."
                info = {
                    "name":  inputs.get("name", ""),
                    "phone": inputs.get("phone", ""),
                    "email": inputs.get("email", ""),
                }
                cs.set_customer_info(session_id, info)

                # ── Auto-enrich: try to find this customer in Salla ──────────────
                # Silently look up by phone so checkout can use salla_customer_id
                # and skip re-sending raw name/phone/email to the order API.
                if self.salla and info.get("phone"):
                    try:
                        resp  = await self.salla.get_customer_by_phone(info["phone"])
                        found = resp.get("data", [])
                        if isinstance(found, list) and found:
                            c = found[0]
                        elif isinstance(found, dict) and found.get("id"):
                            c = found
                        else:
                            c = {}
                        if c.get("id"):
                            # Enrich silently — don't override values the bot explicitly set
                            enriched = dict(info)
                            enriched["salla_customer_id"] = c["id"]
                            if not enriched.get("email") and c.get("email"):
                                enriched["email"] = c["email"]
                            if not enriched.get("name"):
                                fn = c.get("first_name", "")
                                ln = c.get("last_name", "")
                                full = f"{fn} {ln}".strip()
                                if full:
                                    enriched["name"] = full
                            cs.set_customer_info(session_id, enriched)
                            print(f"[set_customer_info] ✅ enriched with salla_id={c['id']} "
                                  f"for session {session_id}")
                    except Exception as _e:
                        print(f"[set_customer_info] auto-lookup skipped: {_e}")

                # ── Persist customer data immediately ─────────────────────────────────
                # Without this a restart between info collection and the next
                # add_message() call would silently lose the customer fields.
                await cs.flush(session_id)

                return f"✅ تم حفظ بيانات العميل: {info['name']} / {info['phone']}"

            # ── checkout ────────────────────────────────────────────────────
            elif name == "checkout":
                if not session_id:
                    return "⚠️ session_id مفقود."
                cart     = cs.get_cart(session_id)
                customer = cs.get_customer_info(session_id)
                total    = cs.cart_total(session_id)

                if not cart:
                    return "⚠️ السلة فارغة! أضف منتجات أولاً."
                if not customer.get("phone"):
                    return "⚠️ يرجى توفير رقم الجوال أولاً."

                order_notes = inputs.get("order_notes", "")

                # Build global notes from per-item specs
                specs = [
                    f"{item['name']}: {item['notes']}"
                    for item in cart if item.get("notes")
                ]
                if specs:
                    order_notes = (order_notes + "\n" if order_notes else "") + "مواصفات:\n" + "\n".join(specs)

                if self.salla:
                    try:
                        # ── Phase 1: create a bare order (no items yet) ──────
                        # We pass an empty items list; salla accepts it as draft.
                        # If the API requires at least one item, we pass the
                        # first cart product and then add the rest in phase 2.
                        first_item = cart[0]
                        bootstrap_items = [{
                            "id":       str(first_item["product_id"]),
                            "quantity": first_item["quantity"],
                        }]

                        resp = await self.salla.create_order(
                            bootstrap_items, customer, order_notes
                        )
                        order     = resp.get("data", {})
                        order_id  = order.get("id")
                        order_ref = order.get("reference_id", str(order_id))
                        pay_url   = (order.get("urls") or {}).get("customer", "")
                        amounts   = order.get("amounts", {})
                        total_str = (amounts.get("total") or {}).get("amount", f"{total:.2f}")
                        currency  = (amounts.get("total") or {}).get("currency", "SAR")

                        # ── Phase 2: add remaining items via POST /orders/items ──
                        item_errors: list[str] = []
                        if order_id and len(cart) > 1:
                            for item in cart[1:]:   # first item already in order
                                try:
                                    pid = int(item["product_id"])
                                    qty = int(item.get("quantity", 1))

                                    # Extract options from cart item if present
                                    raw_options = item.get("options") or []
                                    salla_options = []
                                    for opt in raw_options:
                                        # Support both dict {id, value} and raw strings
                                        if isinstance(opt, dict) and opt.get("id"):
                                            salla_options.append({
                                                "id":    int(opt["id"]),
                                                "value": opt.get("value", []),
                                            })

                                    await self.salla.create_order_item(
                                        order_id=int(order_id),
                                        identifier=pid,
                                        quantity=qty,
                                        identifier_type="id",
                                        options=salla_options if salla_options else None,
                                        name=item.get("name") or None,
                                        price=float(item["price"]) if item.get("price") else None,
                                    )
                                except Exception as ie:
                                    item_errors.append(
                                        f"• {item.get('name','منتج')}: {type(ie).__name__}"
                                    )
                                    print(f"[checkout] create_order_item failed for "
                                          f"order {order_id}, product {item.get('product_id')}: {ie}")

                        # ── Respond to user ──────────────────────────────────
                        if pay_url:
                            component = {
                                "type":      "checkout",
                                "url":       pay_url,
                                "total":     total_str,
                                "currency":  currency,
                                "order_ref": order_ref,
                            }
                            cs.set_last_component(session_id, component)
                            cs.cart_clear(session_id)
                            # Persist cleared cart + checkout component before returning
                            # (protects against a crash between here and add_message)
                            await cs.flush(session_id)

                            reply = (
                                f"✅ تم إنشاء الطلب رقم #{order_ref} بنجاح!\n"
                                f"الإجمالي: {total_str} {currency}\n"
                                f"رابط الدفع: {pay_url}"
                            )
                            if item_errors:
                                reply += (
                                    "\n\n⚠️ لم يُضف بعض المنتجات تلقائياً، "
                                    "يُرجى إضافتها يدوياً:\n" + "\n".join(item_errors)
                                )
                            return reply
                        else:
                            cs.cart_clear(session_id)
                            await cs.flush(session_id)
                            reply = f"✅ تم إنشاء الطلب رقم #{order_ref}. الإجمالي: {total:.2f} ريال"
                            if item_errors:
                                reply += "\n\n⚠️ تعذّر إضافة بعض المنتجات:\n" + "\n".join(item_errors)
                            return reply

                    except Exception as e:
                        # Fallback: show direct product links
                        currency = cart[0].get("currency", "SAR") if cart else "SAR"
                        links = "\n".join(
                            f"• {item['name']}: {item.get('url','—')}"
                            for item in cart if item.get("url")
                        )
                        cs.set_last_component(session_id, {
                            "type":  "checkout_fallback",
                            "items": cart,
                            "total": f"{total:.2f}",
                            "currency": currency,
                            "error": str(e),
                        })
                        return (
                            f"⚠️ تعذّر إنشاء الطلب تلقائياً ({type(e).__name__}). "
                            f"يمكنك الطلب مباشرة من روابط المنتجات:\n{links}"
                        )
                else:
                    # No Salla connection — show product links
                    currency = cart[0].get("currency", "SAR") if cart else "SAR"
                    links = "\n".join(
                        f"• {item['name']}: {item.get('url','—')}"
                        for item in cart if item.get("url")
                    )
                    return (
                        f"ملخص طلبك (الإجمالي: {total:.2f} {currency}):\n{links}\n"
                        "اضغط على الرابط لإتمام الطلب مباشرة."
                    )


            # ── lookup_customer ──────────────────────────────────────────────────────
            elif name == "lookup_customer":
                if not self.salla:
                    return "⚠️ لم يتم ربط المتجر بعد."

                cid_raw       = inputs.get("customer_id")
                phone         = (inputs.get("phone") or "").strip()
                search_name   = (inputs.get("name")  or "").strip()
                include_stats = bool(inputs.get("include_stats", False))

                if not cid_raw and not phone and not search_name:
                    return "⚠️ يرجى تزويدي برقم الجوال أو اسم العميل للبحث."

                customer: dict = {}

                # 1. Direct lookup by Salla customer_id (fastest)
                if cid_raw:
                    try:
                        fields = ["orders_count", "orders_amount", "wallet_balance"] \
                                 if include_stats else []
                        resp     = await self.salla.get_customer(int(cid_raw), fields=fields or None)
                        customer = resp.get("data", {})
                    except Exception:
                        pass

                # 2. Search by phone keyword
                if not customer and phone:
                    try:
                        resp  = await self.salla.get_customer_by_phone(phone)
                        found = resp.get("data", [])
                        if isinstance(found, list) and found:
                            customer = found[0]
                        elif isinstance(found, dict) and found.get("id"):
                            customer = found
                        # If found, fetch full record with optional stats
                        if customer.get("id") and include_stats:
                            fields = ["orders_count", "orders_amount", "wallet_balance"]
                            resp2    = await self.salla.get_customer(int(customer["id"]), fields=fields)
                            customer = resp2.get("data", customer)
                    except Exception:
                        pass

                # 3. Search by name keyword
                if not customer and search_name:
                    try:
                        resp  = await self.salla.get_customer_by_phone(search_name)  # keyword
                        found = resp.get("data", [])
                        if isinstance(found, list) and found:
                            customer = found[0]
                        elif isinstance(found, dict) and found.get("id"):
                            customer = found
                    except Exception:
                        pass

                if not customer:
                    hint = phone or search_name or str(cid_raw)
                    return (
                        f"لم أجد عميلاً بـ {hint} في سلة. 😔\n"
                        "لعله عميل جديد — سأجمع بياناته وأنشئ له حساباً تلقائياً عند إتمام الطلب."
                    )

                # ── Enrich session with the Salla customer data ────────────────
                fn       = customer.get("first_name", "")
                ln       = customer.get("last_name",  "")
                full_name = f"{fn} {ln}".strip()
                mob_code  = customer.get("mobile_code", "966")
                mob       = str(customer.get("mobile", ""))
                email     = customer.get("email", "")
                salla_id  = customer.get("id")

                # Save into session so checkout picks up salla_customer_id
                if session_id and salla_id:
                    existing = cs.get_customer_info(session_id) or {}
                    merged = {
                        "name":               existing.get("name")  or full_name,
                        "phone":              existing.get("phone") or mob,
                        "email":              existing.get("email") or email,
                        "salla_customer_id":  salla_id,
                    }
                    cs.set_customer_info(session_id, merged)
                    # Persist salla_customer_id immediately so checkout can use it
                    # even if the server restarts before the next message
                    await cs.flush(session_id)

                # ── Format response ──────────────────────────────────
                lines = [
                    f"✅ وُجد العميل في سلة:",
                    f"👤 الاسم: {full_name or '—'}",
                    f"📱 الجوال: +{mob_code}{mob}",
                ]
                if email:
                    lines.append(f"📧 الإيميل: {email}")

                city    = customer.get("city", "")
                country = customer.get("country", "")
                if city or country:
                    lines.append(f"📍 المدينة: {city}{', ' + country if country else ''}")

                gender_ar = {"male": "ذكر", "female": "أنثى"}.get(
                    (customer.get("gender") or "").lower(), ""
                )
                if gender_ar:
                    lines.append(f"💳 الجنس: {gender_ar}")

                # Optional stats fields
                if include_stats:
                    orders_count = customer.get("orders_count")
                    orders_amt   = customer.get("orders_amount")
                    wallet       = customer.get("wallet_balance")
                    currency     = customer.get("currency", "SAR")
                    if orders_count is not None:
                        lines.append(f"📦 عدد الطلبات: {orders_count}")
                    if orders_amt is not None:
                        lines.append(f"💰 إجمالي الشراء: {orders_amt} {currency}")
                    if wallet is not None:
                        lines.append(f"💛 رصيد المحفظة: {wallet} {currency}")

                lines.append(f"\n🔑 Salla ID: {salla_id} (تم حفظه تلقائياً لإنجاز الطلب بسرعة)")

                return "\n".join(lines)

            # ── get_order_invoice ────────────────────────────────────────────
            elif name == "get_order_invoice":
                if not self.salla:
                    return "⚠️ لم يتم ربط المتجر بعد."

                invoice_id_raw = inputs.get("invoice_id")
                order_ref      = (inputs.get("order_reference") or "").strip()

                invoice: dict = {}

                # Step 1: direct invoice_id lookup
                if invoice_id_raw:
                    try:
                        resp    = await self.salla.get_invoice(int(invoice_id_raw))
                        invoice = resp.get("data", {})
                    except Exception:
                        pass

                # Step 2: find invoice via order reference
                if not invoice and order_ref:
                    order: dict = {}
                    # 2a. direct order ID
                    try:
                        d     = await self.salla.get_order(order_ref)
                        order = d.get("data", {})
                    except Exception:
                        pass
                    # 2b. search by reference string
                    if not order:
                        try:
                            d      = await self.salla.get_orders(reference_id=order_ref, per_page=5)
                            orders = d.get("data", [])
                            order  = orders[0] if orders else {}
                        except Exception:
                            pass
                    # 2c. keyword search
                    if not order:
                        try:
                            d      = await self.salla.get_orders(keyword=order_ref, per_page=5)
                            orders = d.get("data", [])
                            order  = orders[0] if orders else {}
                        except Exception:
                            pass

                    if order:
                        oid = order.get("id")
                        # Try to list invoices for the found order
                        if oid:
                            try:
                                inv_list = await self.salla.list_order_invoices(int(oid))
                                inv_data = inv_list.get("data", [])
                                if isinstance(inv_data, list) and inv_data:
                                    first_inv_id = inv_data[0].get("id")
                                elif isinstance(inv_data, dict):
                                    first_inv_id = inv_data.get("id")
                                else:
                                    first_inv_id = None
                                if first_inv_id:
                                    resp    = await self.salla.get_invoice(int(first_inv_id))
                                    invoice = resp.get("data", {})
                            except Exception:
                                pass

                        # Fallback: check if order itself carries invoice data
                        if not invoice:
                            raw_inv = order.get("invoice") or order.get("invoices")
                            if isinstance(raw_inv, dict) and raw_inv.get("id"):
                                try:
                                    resp    = await self.salla.get_invoice(int(raw_inv["id"]))
                                    invoice = resp.get("data", {})
                                except Exception:
                                    pass
                            elif isinstance(raw_inv, list) and raw_inv:
                                try:
                                    resp    = await self.salla.get_invoice(int(raw_inv[0]["id"]))
                                    invoice = resp.get("data", {})
                                except Exception:
                                    pass

                if not invoice:
                    hint = order_ref or str(invoice_id_raw or "")
                    return (
                        f"لم أجد فاتورة للطلب {hint}. 😔\n"
                        "تأكد من الرقم وحاول مرة أخرى، أو أفدني برقم الفاتورة مباشرةً."
                    )

                # ── Format invoice for the customer ──────────────────────────
                inv_num   = invoice.get("invoice_number", "—")
                inv_type  = invoice.get("type", "فاتورة")
                inv_date  = invoice.get("date", "—")
                pay_meth  = invoice.get("payment_method", "—")
                order_id_ = invoice.get("order_id", "—")

                def _amt(obj) -> str:
                    """Extract 'amount currency' string from a Salla amount dict."""
                    if not obj:
                        return "—"
                    if isinstance(obj, dict):
                        a = obj.get("amount", obj.get("total", ""))
                        c = obj.get("currency", "SAR")
                        return f"{a} {c}"
                    return str(obj)

                sub_total     = _amt(invoice.get("sub_total") or invoice.get("subtotal"))
                shipping_cost = _amt(invoice.get("shipping_cost") or {})
                discount      = _amt(invoice.get("discount"))
                tax_obj       = invoice.get("tax") or {}
                tax_pct       = tax_obj.get("percent", 0)
                tax_amount    = _amt(tax_obj.get("amount"))
                total         = _amt(invoice.get("total"))

                PAY_AR = {
                    "credit_card": "بطاقة ائتمان",
                    "bank":        "تحويل بنكي",
                    "cash":        "نقداً",
                    "cod":         "دفع عند الاستلام",
                    "tamara":      "تمارا",
                    "tabby":       "تابي",
                    "mada":        "مدى",
                    "apple_pay":   "Apple Pay",
                    "stcpay":      "STC Pay",
                }
                pay_ar = PAY_AR.get(pay_meth, pay_meth)

                lines = [
                    f"🧾 **{inv_type} رقم {inv_num}**",
                    f"📅 التاريخ: {inv_date}",
                    f"📦 رقم الطلب: #{order_id_}",
                    f"💳 طريقة الدفع: {pay_ar}",
                    "",
                    "📋 **المنتجات:**",
                ]

                for it in invoice.get("items", []):
                    it_name = it.get("name", "منتج")
                    it_qty  = it.get("quantity", 1)
                    it_tot  = _amt(it.get("total"))
                    it_sku  = it.get("sku", "")
                    sku_str = f" ({it_sku})" if it_sku else ""
                    lines.append(f"• {it_name}{sku_str} × {it_qty:,} ← {it_tot}")

                lines += [
                    "",
                    f"💰 المجموع الفرعي: {sub_total}",
                    f"🚚 الشحن: {shipping_cost}",
                    f"🏷️ الخصم: {discount}",
                    f"📊 الضريبة ({tax_pct}%): {tax_amount}",
                    f"💵 **الإجمالي: {total}**",
                ]

                qr = invoice.get("qr_code")
                if qr:
                    lines.append(f"\n📱 QR Code: {qr}")

                return "\n".join(lines)

            # ── track_order ─────────────────────────────────────────────────
            elif name == "track_order":
                if not self.salla:
                    return "⚠️ لم يتم ربط المتجر بعد."

                ref   = (inputs.get("order_reference") or "").strip()
                phone = (inputs.get("customer_phone")  or "").strip()

                if not ref and not phone:
                    return "⚠️ يرجى تزويدي برقم الطلب أو رقم الجوال للبحث."

                order = {}

                # 1. Try direct order-ID lookup
                if ref:
                    try:
                        data  = await self.salla.get_order(ref)
                        order = data.get("data", {})
                    except Exception:
                        pass

                # 2. Search by reference string
                if not order and ref:
                    try:
                        data   = await self.salla.get_orders(reference_id=ref, per_page=5)
                        orders = data.get("data", [])
                        order  = orders[0] if orders else {}
                    except Exception:
                        pass

                # 3. Search by keyword (catches phone, name, reference)
                if not order:
                    keyword = phone or ref
                    try:
                        data   = await self.salla.get_orders(keyword=keyword, per_page=5)
                        orders = data.get("data", [])
                        order  = orders[0] if orders else {}
                    except Exception:
                        pass

                if not order:
                    hint = f"رقم الطلب: {ref}" if ref else f"الجوال: {phone}"
                    return (
                        f"لم أجد طلباً بـ {hint}. 😔\n"
                        "تأكد من الرقم وحاول مرة أخرى، أو تواصل مع فريق الدعم."
                    )

                # ── Format the order nicely ────────────────────────────────
                order_id  = str(order.get("id", ""))
                order_ref = order.get("reference_id", order_id)
                raw_status = order.get("status", {})
                if isinstance(raw_status, dict):
                    status_slug = raw_status.get("slug", "")
                    status_name = raw_status.get("name", "")
                else:
                    status_slug = str(raw_status)
                    status_name = ORDER_STATUS_AR.get(status_slug, status_slug)

                status_ar = ORDER_STATUS_AR.get(status_slug, status_name or status_slug)

                # Status emoji
                status_emoji = {
                    "pending":      "⏳",
                    "under_review": "🔍",
                    "processing":   "⚙️",
                    "in_shipping":  "🚚",
                    "completed":    "✅",
                    "cancelled":    "❌",
                    "refunded":     "↩️",
                    "on_hold":      "⏸️",
                }.get(status_slug, "📦")

                # Amounts
                amounts  = order.get("amounts", {})
                total_d  = amounts.get("total") or {}
                total    = total_d.get("amount", "—") if isinstance(total_d, dict) else str(total_d or "—")
                currency = total_d.get("currency", "SAR") if isinstance(total_d, dict) else "SAR"

                # Date
                date_d = order.get("date") or {}
                date   = date_d.get("date", "—")[:10] if isinstance(date_d, dict) else str(date_d or "—")[:10]

                # Items
                items   = order.get("products") or order.get("items") or []
                item_lines = []
                for it in items[:5]:
                    iname = it.get("name", "—")
                    iqty  = it.get("quantity", 1)
                    item_lines.append(f"  • {iname} × {iqty}")

                # Shipping
                shipping    = order.get("shipping") or {}
                ship_number = shipping.get("tracking_number", "") or shipping.get("number", "")
                ship_co     = (shipping.get("company") or {}).get("name", "") if isinstance(shipping.get("company"), dict) else str(shipping.get("company", "") or "")
                ship_url    = shipping.get("tracking_link", "") or shipping.get("url", "")

                # Payment
                payment  = order.get("payment_method", "")
                if isinstance(payment, dict):
                    payment = payment.get("name", "")

                # Build text response
                lines = [
                    f"🛍️ **طلبك رقم #{order_ref}**",
                    f"{status_emoji} الحالة: **{status_ar}**",
                    f"📅 تاريخ الطلب: {date}",
                    f"💰 الإجمالي: {total} {currency}",
                ]
                if payment:
                    lines.append(f"💳 طريقة الدفع: {payment}")
                if item_lines:
                    lines.append(f"📦 المنتجات ({len(items)}):")
                    lines.extend(item_lines)
                if ship_co or ship_number:
                    ship_info = f"🚚 الشحن: {ship_co}" if ship_co else "🚚 الشحن"
                    if ship_number:
                        ship_info += f" | رقم التتبع: {ship_number}"
                    lines.append(ship_info)
                if ship_url:
                    lines.append(f"🔗 تتبع الشحنة: {ship_url}")

                # Set widget component so the frontend can show an order card
                if session_id:
                    cs.set_last_component(session_id, {
                        "type":        "order_status",
                        "order_id":    order_id,
                        "order_ref":   order_ref,
                        "status":      status_ar,
                        "status_slug": status_slug,
                        "status_emoji":status_emoji,
                        "total":       total,
                        "currency":    currency,
                        "date":        date,
                        "items":       [{"name": it.get("name",""), "qty": it.get("quantity",1)} for it in items[:5]],
                        "tracking_number": ship_number,
                        "tracking_url":    ship_url,
                        "shipping_company": ship_co,
                    })

                return "\n".join(lines)

            # ── get_abandoned_carts ─────────────────────────────────────────
            elif name == "get_abandoned_carts":
                if not self.salla:
                    return "⚠️ لم يتم ربط المتجر بعد."
                try:
                    data  = await self.salla.get_abandoned_carts(per_page=10)
                    carts = data.get("data", [])
                except Exception as e:
                    return f"⚠️ تعذّر جلب السلات المتروكة: {type(e).__name__}: {e}"

                if not carts:
                    return "لا توجد سلات متروكة حالياً."

                # Optional phone filter
                phone_filter = inputs.get("customer_phone", "").strip()
                if phone_filter:
                    carts = [
                        c for c in carts
                        if phone_filter in str((c.get("customer") or {}).get("mobile", ""))
                    ]
                    if not carts:
                        return f"لا توجد سلة متروكة مرتبطة بالرقم {phone_filter}."

                lines = [f"السلات المتروكة ({len(carts)}):"]
                for c in carts[:5]:
                    customer = c.get("customer") or {}
                    total    = c.get("total") or {}
                    amt      = total.get("amount", "—") if isinstance(total, dict) else str(total or "—")
                    cur      = total.get("currency", "SAR") if isinstance(total, dict) else "SAR"
                    age      = c.get("age_in_minutes", 0)
                    age_str  = (f"{age // 1440} يوم" if age >= 1440
                                else f"{age // 60} ساعة" if age >= 60
                                else f"{age} دقيقة")
                    checkout = c.get("checkout_url", "")
                    name_str = customer.get("name", "—")
                    lines.append(
                        f"• {name_str} | الإجمالي: {amt} {cur} | منذ {age_str}"
                        + (f"\n  رابط إكمال الطلب: {checkout}" if checkout else "")
                    )
                return "\n".join(lines)

            # ── get_printing_options ─────────────────────────────────────────
            elif name == "get_printing_options":
                ai_cfg = sm.get_ai_config(self.store_id) if self.store_id else {}
                pricing_cfg = ai_cfg.get("pricing_config") or {}
                opts = pc.list_available_options(pricing_cfg)
                if not opts["enabled_types"]:
                    return "⚠️ لا توجد أنواع طباعة مفعّلة. يرجى تواصل مع التاجر لإعداد الأسعار."
                type_labels = {"roll": "رول", "digital": "ديجيتال", "offset": "أوفست", "uvdtf": "UV DTF"}
                lines = ["الخيارات المتاحة للتسعير:"]
                lines.append("• أنواع الطباعة: " + "، ".join(type_labels.get(t, t) for t in opts["enabled_types"]))
                if opts["digital_papers"]:
                    lines.append("• أنواع ورق الديجيتال: " + "، ".join(opts["digital_papers"]))
                if opts["digital_sheets"]:
                    lines.append("• مقاسات الشيتات: " + "، ".join(opts["digital_sheets"]))
                if opts["digital_addons"]:
                    lines.append("• إضافات الديجيتال: " + "، ".join(opts["digital_addons"]))
                if opts["offset_papers"]:
                    lines.append("• أنواع ورق الأوفست: " + "، ".join(opts["offset_papers"]))
                return "\n".join(lines)

            # ── calculate_advanced_quote ─────────────────────────────────────
            elif name == "calculate_advanced_quote":
                ai_cfg = sm.get_ai_config(self.store_id) if self.store_id else {}
                pricing_cfg = ai_cfg.get("pricing_config") or {}
                result = pc.calculate_quote(
                    printing_type = inputs["printing_type"],
                    config        = pricing_cfg,
                    width         = float(inputs.get("width", 0)),
                    height        = float(inputs.get("height", 0)),
                    quantity      = int(inputs.get("quantity", 0)),
                    roll_width    = inputs.get("roll_width"),
                    paper_type    = inputs.get("paper_type"),
                    sheet_size    = inputs.get("sheet_size"),
                    addons        = inputs.get("addons") or [],
                    foil_width    = float(inputs.get("foil_width", 0) or 0),
                    foil_height   = float(inputs.get("foil_height", 0) or 0),
                    spot_uv       = bool(inputs.get("spot_uv", False)),
                    cutting       = inputs.get("cutting", "normal"),
                    folding       = bool(inputs.get("folding", False)),
                    punching      = bool(inputs.get("punching", False)),
                )
                if "error" in result:
                    return f"⚠️ {result['error']}"

                # Build a friendly Arabic summary for the customer
                t = result["type"]
                cur = result.get("currency", "SAR")
                lines = []
                if t == "roll":
                    lines.append(f"📐 **تسعير طباعة رول**")
                    lines.append(f"المقاس: تصميم {inputs['width']}×{inputs['height']} سم")
                    lines.append(f"الكمية: {inputs['quantity']:,} قطعة")
                    lines.append(f"المساحة: {result['area_m2']} م²")
                    lines.append(f"الطول المستهلك: {result['length_meters']} م")
                elif t == "digital":
                    lines.append(f"📐 **تسعير طباعة ديجيتال**")
                    lines.append(f"الخامة: {result['paper_name']}  |  مقاس الشيت: {result['sheet_size']}")
                    lines.append(f"التصميم: {inputs['width']}×{inputs['height']} سم  |  الكمية: {inputs['quantity']:,}")
                    lines.append(f"عدد القطع في الشيت: {result['per_sheet']}")
                    lines.append(f"عدد الشيتات: {result['sheets_needed']} + {result['waste_sheets']} هالك = {result['total_sheets']} شيت")
                    if result.get("foil_cost", 0) > 0:
                        lines.append(f"بصمة: {result['foil_cost']} ريال (قالب {result['mold_price']} + تبصيم {result['stamping_cost']})")
                    if result.get("spot_uv_cost", 0) > 0:
                        lines.append(f"سبوت يو في: {result['spot_uv_cost']} ريال")
                elif t == "offset":
                    lines.append(f"📐 **تسعير طباعة أوفست**")
                    lines.append(f"الخامة: {result['paper_name']}  |  المضاعف: {result['multiplier']}")
                    lines.append(f"التصميم: {inputs['width']}×{inputs['height']} سم  |  الكمية: {inputs['quantity']:,}")
                    lines.append(f"سعر الـ1000: {result['price_per_1000']} ريال  |  سعر الحبة: {result['price_per_unit']} ريال")
                elif t == "uvdtf":
                    lines.append(f"📐 **تسعير طباعة UV DTF**")
                    lines.append(f"التصميم: {inputs['width']}×{inputs['height']} سم  |  الكمية: {inputs['quantity']:,}")
                    lines.append(f"عدد القطع في الصف: {result['items_per_row']}  |  عدد الصفوف: {result['total_rows']}")
                    lines.append(f"الأمتار المستهلكة: {result['meters_consumed']} م  |  سعر المتر: {result['unit_price']} ريال")

                # Common pricing breakdown
                lines.append("")
                lines.append(f"💰 السعر قبل الضريبة: {result['price_before_tax']} {cur}")
                lines.append(f"الضريبة: {result['tax_amount']} {cur}")
                if result.get("discount_percent", 0) > 0:
                    lines.append(f"خصم الكمية: -{result['discount_amount']} {cur} ({result['discount_percent']}%)")
                lines.append(f"━━━━━━━━━━━━━━━━━━")
                lines.append(f"💵 **السعر النهائي: {result['final_price']:,.2f} {cur}**")
                if result.get("is_rotated"):
                    lines.append(f"_(تم تدوير التصميم تلقائياً لتوفير الخامة)_")
                return "\n".join(lines)

            # ── calculate_print_quote (legacy quick estimate) ────────────────
            elif name == "calculate_print_quote":
                ptype = inputs.get("product_type", "").strip()
                qty   = max(1, int(inputs.get("quantity", 1)))
                size  = inputs.get("size", "")
                paper = inputs.get("paper_type", "")
                sides = inputs.get("sides", "وجه واحد")

                pricing = PRICING.get("default")
                for key in PRICING:
                    if key in ptype or ptype in key:
                        pricing = PRICING[key]
                        break

                min_qty = pricing["min_qty"]
                if qty < min_qty:
                    return f"الحد الأدنى {min_qty} قطعة. يمكنك طلب {min_qty} أو أكثر."

                if "sqm" in pricing:
                    sqm = 1.0
                    if size:
                        try:
                            parts = size.replace("×","x").split("x")
                            if len(parts) == 2:
                                sqm = float(parts[0]) * float(parts[1]) / 10000
                        except Exception:
                            pass
                    total = pricing["sqm"] * max(sqm, 1) * qty
                else:
                    total = pricing["setup"] + pricing["unit"] * qty

                if sides == "وجهين":
                    total *= 1.4

                details = " | ".join(filter(None, [size and f"مقاس: {size}", paper and f"خامة: {paper}", sides]))
                return (
                    f"**تقدير سعر {ptype}**\n"
                    f"الكمية: {qty:,} | {details}\n"
                    f"السعر التقريبي: **{total:,.2f} ريال**\n"
                    "⚠️ هذا تقدير مبدئي. للحصول على عرض دقيق أرسل مواصفات التصميم."
                )

        except Exception as e:
            return f"حدث خطأ: {type(e).__name__}: {str(e)}"

        return "العملية غير معروفة."

    # ── Chat entry point ───────────────────────────────────────────────────────
    async def chat(self, message: str, session_id: str) -> str:
        if self.provider == "groq":
            return await self._chat_groq(message, session_id)
        if self.provider == "openai":
            return await self._chat_openai(message, session_id)
        return await self._chat_anthropic(message, session_id)

    # ── Groq (Llama 3.3-70b) ──────────────────────────────────────────────────
    async def _chat_groq(self, message: str, session_id: str) -> str:
        await cs.add_message(session_id, "user", message, self.store_id)
        history = cs.get_groq_history(session_id)

        groq_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in TOOLS
        ]

        messages = [{"role": "system", "content": await get_system_prompt_async(self.store_id)}] + history

        tool_rounds = 0
        while True:
            response = await self.groq_client.chat.completions.create(
                model=self._groq_model,
                messages=messages,
                tools=groq_tools,
                tool_choice="auto",
                max_tokens=1024,
            )

            msg = response.choices[0].message

            if msg.tool_calls and tool_rounds < 5:
                tool_rounds += 1
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ],
                })
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {}
                    result = await self._run_tool(tc.function.name, args, session_id)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(result),
                    })
                continue

            reply = _clean_reply(msg.content or "")
            if not reply:
                reply = "عذراً، لم أستطع معالجة طلبك."
            await cs.add_message(session_id, "assistant", reply, self.store_id)
            return reply

    # ── OpenAI (GPT) ──────────────────────────────────────────────────────────
    async def _chat_openai(self, message: str, session_id: str) -> str:
        """
        OpenAI-compatible chat with tool use.
        Uses the same OpenAI function-calling format as Groq — the two APIs
        are fully wire-compatible so the implementation is nearly identical.
        """
        await cs.add_message(session_id, "user", message, self.store_id)
        history = cs.get_groq_history(session_id)

        # Convert tools to OpenAI function-calling format
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name":        t["name"],
                    "description": t["description"],
                    "parameters":  t["input_schema"],
                },
            }
            for t in TOOLS
        ]

        messages = [{"role": "system", "content": await get_system_prompt_async(self.store_id)}] + history

        tool_rounds = 0
        while True:
            response = await self.openai_client.chat.completions.create(
                model=self._openai_model,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
                max_tokens=1024,
            )

            msg = response.choices[0].message

            if msg.tool_calls and tool_rounds < 5:
                tool_rounds += 1
                messages.append({
                    "role":       "assistant",
                    "content":    msg.content or "",
                    "tool_calls": [
                        {
                            "id":       tc.id,
                            "type":     "function",
                            "function": {
                                "name":      tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {}
                    result = await self._run_tool(tc.function.name, args, session_id)
                    messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.id,
                        "content":      str(result),
                    })
                continue

            reply = _clean_reply(msg.content or "")
            if not reply:
                reply = "عذراً، لم أستطع معالجة طلبك. حاول مرة أخرى."
            await cs.add_message(session_id, "assistant", reply, self.store_id)
            return reply

    # ── Anthropic (Claude) ────────────────────────────────────────────────────
    async def _chat_anthropic(self, message: str, session_id: str) -> str:
        await cs.add_message(session_id, "user", message, self.store_id)
        # get_groq_history returns [{role, content: str}] — valid for Anthropic too
        # (Anthropic accepts plain string content; tool-call turns are ephemeral
        #  per request and are NOT persisted to the conversation store)
        history = cs.get_groq_history(session_id)

        tool_rounds = 0
        while True:
            response = await self.ai.messages.create(
                model=self._anthropic_model,
                max_tokens=1024,
                system=await get_system_prompt_async(self.store_id),
                tools=TOOLS,
                messages=history,
            )

            if response.stop_reason == "tool_use" and tool_rounds < 5:
                tool_rounds += 1
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = await self._run_tool(block.name, block.input, session_id)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                # Append assistant turn (with tool_use blocks) + tool results in
                # Anthropic format so the model sees what it called and got back
                history.append({"role": "assistant", "content": response.content})
                history.append({"role": "user",      "content": tool_results})
                continue

            # Extract text from the final response (may be empty on edge cases)
            reply = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
            if not reply:
                reply = "عذراً، لم أستطع معالجة طلبك. حاول مرة أخرى."

            await cs.add_message(session_id, "assistant", reply, self.store_id)
            return reply


# ── Helpers ────────────────────────────────────────────────────────────────────

def _product_card(p: dict) -> dict:
    """Build a minimal product card dict for the widget."""
    price_display = f"{p.get('price','')} {p.get('currency','SAR')}"
    if p.get("sale_price"):
        try:
            raw_price = p.get("price") or 0
            raw_sale  = p.get("sale_price") or 0
            if isinstance(raw_price, dict):
                raw_price = raw_price.get("amount", 0)
            if isinstance(raw_sale, dict):
                raw_sale = raw_sale.get("amount", 0)
            if float(raw_sale) < float(raw_price):
                price_display = f"{p['sale_price']} {p.get('currency','SAR')}"
        except (ValueError, TypeError):
            pass
    return {
        "id":          str(p.get("id", "")),
        "name":        p.get("name", ""),
        "price":       str(p.get("price", "")),
        "sale_price":  str(p.get("sale_price", "") or ""),
        "currency":    p.get("currency", "SAR"),
        "price_display": price_display,
        "image":       p.get("image", ""),
        "url":         p.get("url", ""),
        "description": p.get("description", "")[:100],
        "available":   p.get("status") == "sale" or p.get("unlimited_quantity", False),
    }
