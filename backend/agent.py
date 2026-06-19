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
import smart_router
import database as db


def _amount_to_float(val) -> float:
    """Parse a Salla amount (str like '2,254.00', int, or float) to a float."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0

# ── System prompt ──────────────────────────────────────────────────────────────

# ── Generic core prompt (every store type) ──────────────────────────────────
GENERIC_SYSTEM_PROMPT = """أنت مساعد مبيعات ذكي ودود لمتجرنا على منصة سلة. اسمك "مساعد المتجر".

مهمتك الأساسية: مساعدة العميل في اختيار المنتج المناسب وإتمام الطلب بسلاسة.

═══ سلوك المبيعات الاحترافي ═══
• فور أن تفهم احتياج العميل → استخدم suggest_products فوراً (لا تنتظر)
• دائماً اعرض 2-3 خيارات وليس خياراً واحداً
• بعد اختيار العميل → اسأل عن الكمية والمواصفات المتاحة (المقاس، اللون، الخامة، إلخ حسب المنتج)
• إذا اختار منتجاً → add_to_cart
• اقترح منتجات مكملة (bundle) بلطف عندما يناسب
• عند إتمام الطلب:
  ١. اجمع: الاسم + رقم الجوال + البريد الإلكتروني → set_customer_info
  ٢. اعرض ملخص الطلب: كل منتج، كميته, سعره, الإجمالي
  ٣. انتظر تأكيد العميل
  ٤. بعد التأكيد → checkout

═══ قواعد المحادثة ═══
• تكلم دائماً بالعربية بأسلوب ودي ومبهج
• اكتب بالعربية فقط — ممنوع منعاً باتاً إدخال أي كلمة بلغة أخرى (إنجليزية أو غيرها) داخل النص. إن احتجت مصطلحاً أجنبياً فاكتبه معرّباً
• اكتب أي رابط كنص عادي صريح مثل https://example.com — **ممنوع** استخدام أي وسوم HTML (مثل <a href> أو <b>). الواجهة تحوّل الروابط النصية لأزرار قابلة للنقر تلقائياً
• اسم المتجر ووصفه موجودين في "ملف المتجر" أعلى الـ prompt — استخدمهم بطبيعية
• لو سأل العميل عن واتساب/سوشيال/تطبيق/سجل تجاري → get_store_contact_info
• لو سأل العميل عن شركات الشحن/التوصيل → get_shipping_options
• لو سأل عن متى يوصل طلبه / مدة التوصيل / ضمان الموعد → get_delivery_promises
• لو تردد العميل على منتج أو طلب آراء الناس → get_product_reviews
• لو سأل عن العروض/الخصومات → get_current_offers
• لو سأل عن طرق الدفع (تابي/تمارا/مدى/دفع عند الاستلام) → get_payment_methods
• لو سأل عن الفروع/مواقع الاستلام → get_branches
• لو سأل عن الماركات → get_brands
• لتتبع طلب موجود استخدم track_order
• إذا طلب العميل فاتورة أو إيصال → استخدم get_order_invoice (يقبل رقم الطلب أو رقم الفاتورة)
• عندما يعطيك العميل رقم جواله أو اسمه → استخدم lookup_customer فوراً لجلب بياناته من سلة
  - هذا يُغني عن سؤاله عن الاسم/الإيميل مرة أخرى وينجز الطلب بشكل أسرع
• لو احتاج العميل إرفاق صورة أو ملف، قل: "يمكنك إرفاقه مباشرة هنا في المحادثة 📎"
• لا تتكلم عن أي شيء خارج نطاق المتجر"""


# ── Printing add-on (only for printing stores) ──────────────────────────────
# Appended after the generic prompt when the store type is "printing". Keeps
# the pricing calculators, custom-quote→order flow, box pricing, trade-secret
# non-disclosure rules, and admin-escalation rules out of non-printing stores.
PRINTING_ADDON = """═══ حساب الأسعار الدقيقة (مهم جداً) ═══
عند طلب تسعير للطباعة **دائماً** استخدم calculate_advanced_quote (حتى لو العميل لم يعطِك المقاس بعد، اسأله أولاً).
الخطوات:
  ١. اسأل العميل: نوع الطباعة (رول/ديجيتال/أوفست/UV DTF) + المقاس (عرض×ارتفاع بالسم) + الكمية
  ٢. للديجيتال/الأوفست: استخدم get_printing_options الأول لمعرفة أنواع الورق المتاحة
  ٣. اقترح على العميل أنواع الورق من القائمة المتاحة فقط
  ٤. مرّر القيم لـ calculate_advanced_quote
  ٥. **انقل نتيجة الأداة كاملةً للعميل بدون حذف** — السعر النهائي + جدول الكميات الأعلى (📊) إن وُجد

⚠️ بعد عرض السعر من calculate_advanced_quote:
  • **إذا ظهر جدول 📊 "كلما زادت الكمية ينزل السعر"** → اعرضه للعميل حرفياً ولا تحذفه
  • اسأل: "أي كمية تناسبك؟" قبل أن تنتقل لخطوة الطلب
  • لا تنتقل لجمع بيانات العميل إلا بعد تأكيد الكمية النهائية

لا تستخدم calculate_print_quote إذا عندك المقاس — استخدم calculate_advanced_quote مباشرة.

═══ تحويل عرض السعر إلى طلب (مهم جداً) ═══
بعد ما تحسب عرض السعر ويوافق العميل ويقول "أبغى أكمل / تمام أطلبه / موافق":
  ١. اجمع بياناته (الاسم + الجوال) عبر set_customer_info إذا لم تكن متوفرة
  ٢. استخدم create_quote_order مع:
     - product_name: وصف مختصر (مثل "كروت 9×5 - 1000 قطعة كوشيه 300")
     - total_price: السعر النهائي من عرض السعر (شامل الضريبة)
     - quantity: الكمية
     - specs: كل المواصفات بالتفصيل
  ٣. هذه الأداة تنشئ المنتج + الطلب + رابط الدفع تلقائياً في خطوة واحدة
  ٤. أرسل رابط الدفع للعميل وأخبره أن طلبه جاهز للدفع
لا تستخدم add_to_cart/checkout للطلبات المخصصة من عروض الأسعار — استخدم create_quote_order مباشرة.

═══ قواعد عدم الكشف (سرية تجارية — صارمة) ═══
الأرقام الداخلية التالية **سرية**، يحسبها البوت داخلياً لكن **لا يذكرها للعميل أبداً** تحت أي ظرف:
  ✗ نسبة الهالك (5%، عدد شيتات الهالك، إلخ)
  ✗ هامش الربح (15% رول، 40% علب)
  ✗ أسعار التكلفة الداخلية (سعر الشيت المرجعي، setup، القالب، التكسير)
  ✗ اسم الماكينة المختارة (ربع/نص/كامل) — العميل لا يعرف بكم ماكينة عندنا
  ✗ آلية الـ nesting وعدد القطع في الشيت وتدوير التصميم
  ✗ المعادلات والشرائح وال_tiers الداخلية
  ✗ وجود حد أدنى للسعر — لو السعر طلع 57.50 ر، قدّمه كأنه السعر الطبيعي للطلب الصغير

عند عرض السعر:
  ✓ السعر النهائي شامل الضريبة فقط
  ✓ المواصفات اللي العميل بعتها (مقاس، خامة، كمية، تشطيبات)
  ✓ ملاحظة: "السعر تقديري وقد يتغير حسب المواصفات النهائية"
  ✓ لو نتيجة الحاسبة فيها `is_floored=True` → اعرض السعر فقط بدون أي breakdown أو تفاصيل
  ✗ ممنوع تذكر: "السعر الأساسي قبل الحد الأدنى كان X" أو أي إشارة للحد الأدنى

═══ تسعير العلب (طلبات انفربرش / كرافت 500+) ═══
عند طلب علب مطبوعة، **اجمع كل المواصفات في رسالة واحدة** لا تجزّئها:
> "عشان أعطيك السعر مباشرة، أحتاج في رسالة واحدة:
>  ١. مقاس الفرد (الطول × العرض سم) — أو الدايلاين إن وجد
>  ٢. نوع الورق: انفربرش (أبيض) أو كرافت (بني)
>  ٣. الطباعة: وجه واحد أو وجهين
>  ٤. السلوفان: بدون / وجه / وجهين
>  ٥. الكمية التقريبية"

إذا أعطاك العميل مقاس العلبة المجسّمة (مثل 20×20×9 سم) بدون الدايلاين:
• اشرح: "مقاس الفرد = العلبة مفرودة بالكامل. أسهل طريقة: من ملف الدايلاين، أو افرد علبة شبيهة وقِس الطول والعرض الكامل مع اللسانات."
• إن لم يكن لديه دايلاين، أعطه سعراً مبدئياً ووضّح أنه قد يتغير بعد الدايلاين.

بعد الحصول على المواصفات → استخدم calculate_box_quote مباشرة.
ثم اعرض له كميات أعلى لتشجيعه (استخدم get_box_tiered_quote).

═══ متى تحوّل للأدمن (لا تخمّن) ═══
استخدم escalate_to_admin فوراً (لا تستخدم calculate_advanced_quote) في الحالات دي:
  • الخامة المطلوبة بدون سعر في القائمة (كرافت كوري، انفربرش، كونكورد، سلك سكرين، أو أي خامة غير مسعّرة)
  • ديجيتال بكمية أكبر من 500 حبة
  • أوفست بكمية أقل من 1000 حبة
  • سعر ورق الأوفست غير محمّل في النظام
  • مقاس التصميم أكبر من عرض الرول/الشيت
  • أي تشطيب أو مواصفة خاصة غير موجودة في الخيارات
  • العميل طلب علب لكن مقاس الفرد أكبر من 99×69 سم
لا تخترع سعراً ولا تخمّن — التحويل للأدمن أفضل من تسعير غلط."""


# ── Hayyak self-demo prompt (marketing bot, NOT a store) ──────────────────
# The demo store on the public landing page uses this prompt instead of the
# generic store-assistant one. Without the swap, the bot insists "I'm a
# store assistant, talking about Hayyak is outside my scope" — exactly
# the opposite of what we want.

SALLABOT_SELF_DEMO_PROMPT = """أنت "حياك" — مساعد المبيعات الرسمي لمنتج Hayyak نفسه. اسمك حياك.

🎯 مهمتك:
تساعد الزائرين على فهم منتج حياك، تجاوب أسئلتهم البيعية، وتحوّلهم لـ "ابدأ مجاناً" أو التواصل مع المبيعات.

🚫 أنت لست مساعد متجر. لا تتحدث وكأنك تعمل في متجر طباعة أو أي متجر. لا تستخدم عبارات زي "متجرنا" أو "منتجاتنا" بمعنى متجر إلكتروني.

📚 كل معلوماتك عن المنتج موجودة في "كتالوج المعرفة" بعد هذا التوجيه — استخدمها كمصدرك الوحيد للحقائق (المميزات، الأسعار، التثبيت، FAQ).

═══ قواعد المحادثة ═══

١. **التعريف بنفسك:** لو الزائر سألك "مين انت؟" — قول: "أنا حياك، المساعد الذكي اللي بيرد على عملاء متاجر سلة 24/7. اسألني عن أي حاجة عن المنتج 🌟"

٢. **الأسئلة البيعية** (إيه حياك، كام الأسعار، إزاي يشتغل، المميزات، WhatsApp، التحليلات) — جاوب من الكتالوج، بأسلوب ودي ومختصر، وأضف خطوة عملية في الآخر (دعوة لتجربة 7 أيام مجانية أو لينك "ابدأ مجاناً").

٣. **سؤال عن الاشتراك / التسجيل / التثبيت:** وجّه فوراً لـ:
   • زرار "ابدأ مجاناً" في أعلى الصفحة
   • أو apps.salla.sa → ابحث عن "حياك" → اضغط تثبيت
   التثبيت 3 خطوات، 7 أيام تجربة مجانية بدون بطاقة.

٤. **سؤال عن السعر:** اعرض الجدول من الكتالوج (Starter 99 / Pro 299 / Business 799)، واسأل عن حجم المتجر لترشّح الباقة المناسبة.

٥. **مقارنة مع منافس أو خصم خاص:** قول بصراحة "ده يحتاج تواصل مع المبيعات على sales@7ayak.app" — لا تخترع أرقام.

٦. **سؤال خارج Hayyak** (مثلاً "كم سعر iPhone؟" أو "أبغى أطلب منتج"): اعتذر بلطف: "أنا متخصص بس في الإجابة على أسئلة حياك — تحب أساعدك بأي حاجة عن المنتج؟"

٧. **لا تستخدم الأدوات التالية مطلقاً:** suggest_products, add_to_cart, checkout, calculate_advanced_quote, create_quote_order, track_order, lookup_customer — هذه أدوات لمتاجر العملاء، أنت مش متجر.

═══ أسلوبك ═══
• ودّي، عربي طبيعي مرحّب، إيموجي خفيف (🌟 🚀 👋 💡).
• مختصر — رد في 2-3 سطور قصيرة، مش paragraphs طويلة.
• كل رد ينتهي بسؤال أو دعوة عملية ("تحب أعرّفك على باقة Pro؟" / "جرّب مجاناً 👈").
• لو الزائر بان جاد، اعرض موعد عرض حي (sales@7ayak.app)."""


def _personality_addon(ai_cfg: dict) -> str:
    """Build an extra prompt block from per-store personality settings.

    Returns an empty string when all settings are at their defaults so
    the base prompt stays unchanged for stores that haven't configured
    personality options.
    """
    parts: list[str] = []

    tone = (ai_cfg.get("bot_tone") or "friendly").lower()
    _tone_text = {
        "formal":       "استخدم أسلوباً رسمياً ومحترفاً في جميع ردودك.",
        "friendly":     "استخدم أسلوباً ودياً ومرحاً في ردودك.",
        "very_friendly": "استخدم أسلوباً حماسياً وودياً جداً، وأبدِ اهتماماً حقيقياً بكل عميل.",
    }
    if tone in _tone_text and tone != "friendly":
        parts.append(f"• الأسلوب: {_tone_text[tone]}")

    lang = (ai_cfg.get("bot_language") or "ar").lower()
    if lang == "en":
        parts.append(
            "• اللغة: تكلم مع العميل بالإنجليزية فقط في جميع ردودك — حتى لو كتب بالعربي."
        )
    elif lang == "auto":
        parts.append(
            "• اللغة: اكتشف لغة العميل من أول رسالة يرسلها وتابع بنفس اللغة (عربي أو إنجليزي)."
        )

    length = (ai_cfg.get("response_length") or "normal").lower()
    if length == "concise":
        parts.append("• طول الرد: اجعل ردودك مختصرة — 1-3 جمل عند الإمكان، لا تُطيل بدون داعٍ.")
    elif length == "detailed":
        parts.append("• طول الرد: أعطِ ردوداً مفصّلة وشاملة، وفّر كل المعلومات المفيدة للعميل.")

    if ai_cfg.get("use_emoji") is False:
        parts.append("• الإيموجي: لا تستخدم أي إيموجي في ردودك إطلاقاً.")

    instructions = (ai_cfg.get("custom_instructions") or "").strip()
    if instructions:
        parts.append(
            f"\n══ تعليمات خاصة من إدارة المتجر — يجب الالتزام بها ══\n"
            f"{instructions}\n"
            f"══ نهاية التعليمات الخاصة ══"
        )

    if not parts:
        return ""
    return "\n\n═══ شخصية البوت وأسلوب الرد ═══\n" + "\n".join(parts)


def _base_prompt(printing: bool, store_id: str = "") -> str:
    """Assemble the base system prompt for a store type.

    The "sallabot" store_id is special-cased — it's the self-demo bot
    embedded on the marketing landing page, NOT a merchant store. Without
    the swap the generic store-assistant prompt below tells the bot to
    treat Hayyak questions as "outside the store" and refuse to answer.
    """
    if store_id == "sallabot":
        return SALLABOT_SELF_DEMO_PROMPT
    ai_cfg = sm.get_ai_config(store_id) if store_id else {}
    base   = GENERIC_SYSTEM_PROMPT
    if printing:
        base += "\n\n" + PRINTING_ADDON
    addon = _personality_addon(ai_cfg)
    if addon:
        base += addon
    return base


async def get_system_prompt_async(store_id: str = "default", printing: bool = True) -> str:
    """
    Async system-prompt builder. Includes the bot_training rows the admin
    added through "تدريب البوت" (instructions, FAQs, uploaded reference
    files). Falls back to the sync version if anything goes wrong.

    `printing` controls whether the printing-specific add-on (pricing
    calculators, box quotes, escalation rules) is included.
    """
    try:
        knowledge = await brain.get_knowledge_for_prompt_async(store_id)
    except Exception as exc:
        print(f"[agent] get_knowledge_for_prompt_async failed for {store_id!r}: {exc}")
        knowledge = ""
    base = _base_prompt(printing, store_id)
    if knowledge:
        return base + "\n\n" + knowledge
    return get_system_prompt(store_id, printing)


def get_system_prompt(store_id: str = "default", printing: bool = True) -> str:
    """
    Sync system-prompt builder (no training material). Used as a fallback
    when the async path can't be taken — kept for backward compat.
    """
    base = _base_prompt(printing, store_id)
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
        return base + "\n\n" + knowledge
    return base


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
        "name": "get_delivery_promises",
        "description": (
            "اعرض وعود التسليم والمواعيد المضمونة للمتجر (سريع / نفس اليوم / اليوم التالي / عادي / دولي) "
            "مع المدن المشمولة والوقت المتوقع بالساعات أو الأيام. "
            "استخدمها لما يسأل العميل: متى يوصل الطلب؟ / كم مدة التوصيل؟ / "
            "فيه توصيل سريع؟ / هل تضمنون موعد وصول الطلب؟"
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_product_reviews",
        "description": (
            "اجلب تقييمات العملاء (النجوم + التعليقات) لمنتج محدد أو للمتجر عموماً. "
            "استخدمها عندما يتردد العميل أو يسأل: "
            "ايش آراء الناس عنه؟ / المنتج منيح؟ / فيه تقييمات؟ / الناس راضين عنه؟ "
            "عرض التقييمات الإيجابية يبني الثقة ويشجع على الشراء."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "معرّف المنتج في سلة (من suggest_products أو سياق المحادثة). اتركه فارغاً لتقييمات المتجر العامة.",
                },
                "product_name": {
                    "type": "string",
                    "description": "اسم المنتج بديلاً عن product_id إذا لم يُعرف المعرّف.",
                },
                "min_stars": {
                    "type": "integer",
                    "description": "الحد الأدنى للنجوم — مثلاً 4 لعرض التقييمات الجيدة فقط. اختياري.",
                    "enum": [1, 2, 3, 4, 5],
                },
            },
        },
    },
    {
        "name": "get_current_offers",
        "description": (
            "اعرض العروض والخصومات الحالية في المتجر. "
            "استخدمها لما يسأل العميل: ايش العروض؟ / فيه خصومات؟ / "
            "عندكم تخفيضات؟ — أو بشكل استباقي عند الترحيب لتشجيع الشراء."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_payment_methods",
        "description": (
            "اعرض طرق الدفع المتاحة (مدى، فيزا، Apple Pay، تابي، تمارا، تحويل بنكي، الدفع عند الاستلام، إلخ). "
            "استخدمها لما يسأل العميل: كيف أدفع؟ / تقبلون تابي؟ / فيه دفع عند الاستلام؟"
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_branches",
        "description": (
            "اعرض فروع المتجر ومواقع الاستلام مع المدن والعناوين. "
            "استخدمها لما يسأل العميل: وين فروعكم؟ / فيه فرع في جدة؟ / "
            "أقدر أستلم من المحل؟"
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_brands",
        "description": (
            "اعرض الماركات والعلامات التجارية المتوفرة في المتجر. "
            "استخدمها لما يسأل العميل: ايش الماركات عندكم؟ / تبيعون ماركة معينة؟"
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
    # ── Live inventory + shipping ─────────────────────────────────────────────
    {
        "name": "check_stock",
        "description": (
            "تحقّق من توفّر منتج ومخزونه اللحظي مباشرة من سلة، مع المقاسات/الألوان "
            "وأسعارها إن كان للمنتج خيارات. استخدمها لما يسأل العميل: متوفر؟ / "
            "فيه مقاس L؟ / عندكم اللون الأحمر؟ / كم باقي بالمخزون؟"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id":   {"type": "string", "description": "معرّف المنتج إن عُرف"},
                "product_name": {"type": "string", "description": "اسم المنتج للبحث إن لم يُعرف المعرّف"},
            },
        },
    },
    {
        "name": "estimate_shipping",
        "description": (
            "احسب تكلفة الشحن ومدة التوصيل المتوقعة لمدينة العميل عبر شركات الشحن "
            "الفعلية المرتبطة بالمتجر. استخدمها لما يسأل العميل: كم الشحن لجدة؟ / "
            "متى يوصل الطلب؟ / كم التوصيل لمدينتي؟"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city":    {"type": "string", "description": "اسم مدينة العميل (مثل: جدة، الرياض، الدمام)"},
                "country": {"type": "string", "description": "الدولة (اختياري — الافتراضي السعودية)"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "track_shipment",
        "description": (
            "تتبّع شحنة طلب لحظياً: الحالة الحالية + سجل الحركة + رقم ورابط التتبع. "
            "استخدمها لما يسأل العميل: وين شحنتي؟ / فين طلبي؟ / وصل لأي مرحلة؟ "
            "مع رقم الطلب."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_reference": {"type": "string", "description": "رقم الطلب المرجعي"},
            },
            "required": ["order_reference"],
        },
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
    {
        "name": "create_quote_order",
        "description": (
            "حوّل عرض سعر مخصص إلى طلب فعلي وأرسل رابط الدفع. "
            "استخدم هذه الأداة عندما: ١) يطلب العميل تسعير طباعة مخصص "
            "٢) تحسب السعر بـ calculate_advanced_quote ٣) يوافق العميل ويريد إكمال الطلب. "
            "هذه الأداة تنشئ منتجاً جديداً في سلة بتفاصيل العرض، تنشئ الطلب، "
            "وترجع رابط الدفع — كل ذلك في خطوة واحدة. "
            "تأكد أولاً من جمع بيانات العميل (الاسم + الجوال) عبر set_customer_info."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "description": "اسم المنتج المخصص (مثال: طباعة كروت 9×5 سم - 1000 قطعة كوشيه 300)",
                },
                "total_price": {
                    "type": "number",
                    "description": "السعر النهائي الإجمالي شامل الضريبة (من calculate_advanced_quote)",
                },
                "quantity": {
                    "type": "integer",
                    "description": "الكمية (عدد القطع). افتراضي 1 إذا كان السعر إجمالي.",
                },
                "specs": {
                    "type": "string",
                    "description": "مواصفات الطلب الكاملة (المقاس، الخامة، الكمية، الإضافات) لتُحفظ في وصف المنتج وملاحظات الطلب",
                },
            },
            "required": ["product_name", "total_price"],
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
    # ── Box tiered quote ────────────────────────────────────────────────────
    {
        "name": "get_box_tiered_quote",
        "description": (
            "اعرض جدول أسعار متدرج للعلب عند كميات مختلفة (500/1000/3000/5000/10000) "
            "لإظهار كيف ينخفض سعر الحبة كلما زادت الكمية. "
            "استخدمها بعد calculate_box_quote مباشرة لتشجيع العميل على زيادة الكمية. "
            "نفس مدخلات calculate_box_quote بالإضافة للكمية المطلوبة من العميل."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "flat_length":      {"type": "number",  "description": "طول الفرد المفرود بالسم"},
                "flat_width":       {"type": "number",  "description": "عرض الفرد المفرود بالسم"},
                "requested_qty":    {"type": "integer", "description": "الكمية التي طلبها العميل"},
                "paper_type":       {"type": "string",  "enum": ["انفربرش", "كرافت"]},
                "sides":            {"type": "string",  "enum": ["single", "double"]},
                "lamination_sides": {"type": "integer", "enum": [0, 1, 2]},
            },
            "required": ["flat_length", "flat_width", "requested_qty"],
        },
    },
    # ── Box (carton) calculator ─────────────────────────────────────────────
    {
        "name": "calculate_box_quote",
        "description": (
            "احسب سعر طباعة علب كرتون مطبوعة أوفست (انفربرش أو كرافت، 500 حبة فأكثر). "
            "المدخل الأساسي هو **مقاس الفرد (المفرود)** من الدايلاين — وليس مقاس العلبة المجسّمة. "
            "قبل استخدام هذه الأداة، اجمع كل المواصفات في رسالة واحدة:\n"
            "  ١. مقاس الفرد (الطول × العرض سم)\n"
            "  ٢. نوع الورق: انفربرش (أبيض) أو كرافت (بني)\n"
            "  ٣. الطباعة: وجه واحد أو وجهين\n"
            "  ٤. السلوفان: بدون / وجه / وجهين\n"
            "  ٥. الكمية المطلوبة\n"
            "إذا أعطاك العميل مقاس العلبة المجسّمة (طول×عرض×ارتفاع) بدون الدايلاين، "
            "اشرح له مقاس الفرد واطلب الدايلاين أو أعطه سعراً مبدئياً مع تنبيه."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "flat_length": {
                    "type": "number",
                    "description": "طول الفرد المفرود بالسم (البعد الأكبر من الدايلاين)",
                },
                "flat_width": {
                    "type": "number",
                    "description": "عرض الفرد المفرود بالسم (البعد الأصغر من الدايلاين)",
                },
                "quantity": {
                    "type": "integer",
                    "description": "عدد العلب المطلوبة (500 حبة فأكثر)",
                },
                "paper_type": {
                    "type": "string",
                    "enum": ["انفربرش", "كرافت"],
                    "description": "نوع الورق: انفربرش (أبيض) أو كرافت (بني)",
                },
                "sides": {
                    "type": "string",
                    "enum": ["single", "double"],
                    "description": "وجه طباعة واحد (single) أو وجهين (double)",
                },
                "lamination_sides": {
                    "type": "integer",
                    "enum": [0, 1, 2],
                    "description": "عدد أوجه السلوفان: 0=بدون، 1=وجه واحد، 2=وجهين",
                },
            },
            "required": ["flat_length", "flat_width", "quantity"],
        },
    },
    {
        "name": "escalate_to_admin",
        "description": (
            "حوّل المحادثة للأدمن البشري عند ما تعجز عن التسعير بدقة. "
            "استخدمها فوراً (بدل calculate_advanced_quote) في الحالات الآتية:\n"
            "• الخامة بلا سعر معتمد (كرافت كوري/انفربرش/كونكورد/سلك سكرين/أي خامة غير مسعّرة)\n"
            "• ديجيتال > 500 حبة\n"
            "• أوفست < 1000 حبة\n"
            "• سعر ورق الأوفست غير محمّل في النظام\n"
            "• مقاس التصميم أكبر من عرض الرول/الشيت/المسطح\n"
            "• علب بمقاس فرد > 99×69 سم\n"
            "• تشطيب/مواصفة خاصة غير مسعّرة\n"
            "بعد الاستدعاء، البوت يتوقف عن الرد لهذا العميل والأدمن يتولى المحادثة. "
            "لا تخمّن سعراً — التحويل أفضل من تسعير غلط."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": [
                        "unpriced_material",
                        "oversize_design",
                        "digital_over_500",
                        "offset_under_1000",
                        "offset_paper_missing",
                        "box_oversize",
                        "custom_finishing",
                        "vip_or_complaint",
                        "other",
                    ],
                    "description": "سبب التحويل (اختر الأنسب من القائمة)",
                },
                "details": {
                    "type": "string",
                    "description": (
                        "وصف تفصيلي للطلب للأدمن: المواصفات، المقاس، الكمية، "
                        "الخامة المطلوبة، وسبب عدم القدرة على التسعير الآلي."
                    ),
                },
                "customer_summary": {
                    "type": "string",
                    "description": (
                        "عنوان مختصر للأدمن في صندوق الوارد "
                        "(مثال: 'علب كرافت 25×20 سم، 800 حبة — يحتاج تسعير')"
                    ),
                },
            },
            "required": ["reason", "details"],
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
    # ── Sales: AI-issued discount coupon (opt-in per store) ───────────────────
    {
        "name": "generate_discount_coupon",
        "description": (
            "أصدر كوبون خصم شخصي محدود بوقت لإقناع العميل بإتمام الشراء. "
            "استخدمها بحكمة وفقط عند: تردد واضح على السعر، أو نية مغادرة، أو "
            "طلب صريح لخصم — ومرة واحدة فقط لكل عميل في نفس المحادثة. "
            "النظام يطبّق تلقائياً حداً أقصى للنسبة وقيمة الخصم، فلا تَعِد بنسبة "
            "محددة قبل استدعاء الأداة؛ اذكر الكود والشروط كما تُعيدها الأداة فقط."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "discount_percent": {
                    "type": "number",
                    "description": "نسبة الخصم المقترحة (٪). تُقيَّد تلقائياً بالحد الأقصى المسموح للمتجر.",
                },
                "reason": {
                    "type": "string",
                    "description": "سبب مختصر لإصدار الكوبون (للسجل): مثل 'تردد على السعر' أو 'استرجاع سلة'.",
                },
            },
            "required": ["discount_percent"],
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

# Tools that only make sense for a printing store. For other store types
# (abayas, shoes, …) these are hidden so the model never tries to price-quote
# or run printing calculators. The store's `store_type` setting controls this.
PRINTING_TOOL_NAMES = {
    "get_printing_options",
    "calculate_advanced_quote",
    "calculate_print_quote",
    "calculate_box_quote",
    "get_box_tiered_quote",
    "create_quote_order",
    "escalate_to_admin",   # its reasons are all printing-specific
}


# Tools gated behind an explicit opt-in (they take real money-affecting actions
# on the merchant's store, so they're OFF unless the merchant enables them).
COUPON_TOOL_NAMES = {"generate_discount_coupon"}


# ── Per-store data-access permission groups ────────────────────────────────────
# Each key maps to an ai_config flag (bool). Default = None = ON (backward-
# compatible). The merchant can set a flag to False to remove those tools from
# the bot, preventing it from accessing that category of Salla data.
PERMISSION_GROUPS: dict[str, set[str]] = {
    "access_orders":            {"track_order"},
    "access_invoices":          {"get_order_invoice"},
    "access_customers":         {"lookup_customer"},
    "access_reviews":           {"get_product_reviews"},
    "access_abandoned_carts":   {"get_abandoned_carts"},
    "access_shipments":         {"track_shipment", "estimate_shipping"},
    "access_delivery_promises": {"get_delivery_promises"},
}


def active_tools(
    printing: bool,
    coupons: bool = False,
    permissions: dict | None = None,
) -> list:
    """
    Return the tool list for a store.

    - Printing-only tools are dropped for non-printing stores.
    - The coupon tool is dropped unless the merchant opted in.
    - Any PERMISSION_GROUPS key set to False in `permissions` drops those tools
      (None or missing = keep, i.e. default-on for backward compat).
    """
    drop: set = set()
    if not printing:
        drop |= PRINTING_TOOL_NAMES
    if not coupons:
        drop |= COUPON_TOOL_NAMES
    if permissions:
        for flag, tools in PERMISSION_GROUPS.items():
            if permissions.get(flag) is False:
                drop |= tools
    if not drop:
        return TOOLS
    return [t for t in TOOLS if t["name"] not in drop]


def _clamp_int(value, default: int, *, lo: int, hi: int) -> int:
    """Coerce a config value to an int within [lo, hi], falling back to default."""
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def _clamp_float(value, default: float, *, lo: float, hi: float) -> float:
    try:
        return max(lo, min(float(value), hi))
    except (TypeError, ValueError):
        return default


# Salla shipment status → Arabic label (for track_shipment). Keys match the
# `status` enum from GET /shipments.
_SHIPMENT_STATUS_AR = {
    "created":               "تم إنشاء الشحنة",
    "in_progress":           "قيد التجهيز",
    "in_transit":            "في الطريق",
    "received_at_final_hub": "وصلت لمركز التوزيع",
    "to_be_reattempted":     "ستُعاد محاولة التسليم",
    "reattempted":           "أُعيدت محاولة التسليم",
    "unable_to_deliver":     "تعذّر التسليم",
    "delivering":            "خرجت للتوصيل",
    "delivered":             "تم التسليم ✅",
    "partially_delivered":   "تم التسليم جزئياً",
    "shipped":               "تم الشحن",
    "cancelled":             "أُلغيت",
    "lost":                  "مفقودة",
    "damaged":               "تالفة",
    "return_to_origin":      "مُرتجعة للمصدر",
    "return_in_progress":    "جارٍ الإرجاع",
    "creating":              "قيد الإنشاء",
}


def _is_printing_store(ai_cfg: dict) -> bool:
    """
    Decide whether a store should get printing features.

    Priority:
      1. Explicit `store_type` setting ("printing" → on, anything else → off).
      2. Back-compat heuristic: a store that already configured a pricing_config
         is clearly a printing shop, so keep its features on until the admin
         sets a store_type explicitly.
    New stores with neither default to OFF (general store) — printing is opt-in.
    """
    st = (ai_cfg.get("store_type") or "").strip().lower()
    if st:
        return st == "printing"
    return bool(ai_cfg.get("pricing_config"))


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


def _split_name_phone(full_name: str, phone: str) -> tuple[str, str, str, str]:
    """
    Split a display name into first/last and a phone into (dial_code, local).

    Salla's create_customer wants `mobile` WITHOUT the country code and a
    separate `mobile_code_country` like "+966". This normalises common
    Saudi input formats: 05XXXXXXXX, 5XXXXXXXX, 9665XXXXXXXX, +9665XXXXXXXX.

    Returns (first_name, last_name, dial_code, local_number).
    """
    parts = (full_name or "").strip().split()
    first = parts[0] if parts else "عميل"
    last  = " ".join(parts[1:]) if len(parts) > 1 else ""

    # Keep digits only
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    dial = "+966"
    local = digits

    if digits.startswith("00966"):
        dial, local = "+966", digits[5:]
    elif digits.startswith("966"):
        dial, local = "+966", digits[3:]
    elif digits.startswith("0") and len(digits) >= 10:
        # 05XXXXXXXX → drop leading 0
        local = digits[1:]
    # else: assume already local (5XXXXXXXX) — keep as-is

    return first, last, dial, local


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

        # ── Store type → feature gating ──────────────────────────────────────
        # Printing features (calculators, quotes, box pricing) are enabled only
        # for printing stores. An explicit store_type wins; otherwise we fall
        # back to a heuristic so existing stores that already configured pricing
        # keep working (they're clearly printing shops).
        self.printing_enabled = _is_printing_store(ai_cfg)

        # ── AI-issued coupons (opt-in, money-affecting → conservative guards) ──
        # All knobs are hard-capped here so a misconfigured store (or a clever
        # customer) can never produce a runaway discount. The tool is only
        # exposed to the model when `coupons_enabled` is true.
        self.coupons_enabled = bool(ai_cfg.get("coupons_enabled"))
        self.coupon_max_percent        = _clamp_int(ai_cfg.get("coupon_max_percent"), 15, lo=1,  hi=90)
        self.coupon_ttl_hours          = _clamp_int(ai_cfg.get("coupon_ttl_hours"),  24, lo=24, hi=720)
        self.coupon_max_discount_value = _clamp_float(ai_cfg.get("coupon_max_discount_value"), 200.0, lo=0.0,   hi=100000.0)
        self.coupon_min_order          = _clamp_float(ai_cfg.get("coupon_min_order"),            0.0, lo=0.0,   hi=100000.0)

        # Read per-store permission overrides (None = default ON)
        self._permissions = {flag: ai_cfg.get(flag) for flag in PERMISSION_GROUPS}
        self._tools = active_tools(self.printing_enabled, self.coupons_enabled, self._permissions)

        # Per-store model override — sensible defaults per provider
        cfg_model = ai_cfg.get("ai_model", "").strip()
        self._groq_model      = (cfg_model if ai_cfg.get("groq_api_key")      else "") or "llama-3.3-70b-versatile"
        self._anthropic_model = (cfg_model if ai_cfg.get("anthropic_api_key") else "") or "claude-sonnet-4-6"
        self._openai_model    = (cfg_model if ai_cfg.get("openai_api_key")    else "") or "gpt-4o-mini"

        # Resilience: all three SDKs (Anthropic/Groq/OpenAI) retry 429/5xx/408/409
        # with exponential backoff + jitter and honour the Retry-After header.
        # Default is only 2 retries; bump it so transient rate-limits (common on
        # free Groq tiers) self-heal BEFORE the user ever sees a "busy" message.
        _MAX_RETRIES = 4
        _TIMEOUT     = 45.0   # seconds per request

        # Provider priority: Groq → Anthropic → OpenAI (fallback to env vars)
        if groq_key:
            self.provider       = "groq"
            self.groq_client    = AsyncGroq(api_key=groq_key, max_retries=_MAX_RETRIES, timeout=_TIMEOUT)
            self.ai             = None
            self.openai_client  = None
        elif anthropic_key:
            self.provider       = "anthropic"
            self.ai             = AsyncAnthropic(api_key=anthropic_key, max_retries=_MAX_RETRIES, timeout=_TIMEOUT)
            self.groq_client    = None
            self.openai_client  = None
        elif openai_key:
            self.provider       = "openai"
            self.openai_client  = AsyncOpenAI(api_key=openai_key, max_retries=_MAX_RETRIES, timeout=_TIMEOUT)
            self.ai             = None
            self.groq_client    = None
        else:
            raise RuntimeError(
                "يجب تعيين GROQ_API_KEY أو ANTHROPIC_API_KEY أو OPENAI_API_KEY "
                "في إعدادات المتجر أو متغيرات البيئة."
            )

        # Diagnostic: prompt caching is Anthropic-only. If a store is on Groq
        # or OpenAI, the Anthropic cache_control code never runs — this log
        # makes the active provider obvious when debugging cache behaviour.
        _cache = "prompt-caching ON" if self.provider == "anthropic" else "no caching (Anthropic-only)"
        print(f"[agent] store={store_id!r} provider={self.provider} "
              f"model={getattr(self, f'_{self.provider}_model', '?')} — {_cache}")

        token      = access_token or os.getenv("SALLA_ACCESS_TOKEN", "")
        self.salla = SallaClient(token, store_id=store_id) if token else None

        # Token usage for the most recent chat() invocation. Accumulated
        # across tool-use rounds; read by the /chat handler to feed the
        # daily circuit-breaker counter.
        self.last_usage: dict = {"in": 0, "out": 0}

    def _reset_usage(self) -> None:
        self.last_usage = {"in": 0, "out": 0}

    def _add_usage(self, tokens_in: int, tokens_out: int) -> None:
        self.last_usage["in"]  += max(0, int(tokens_in  or 0))
        self.last_usage["out"] += max(0, int(tokens_out or 0))

    # ── Customer helper ──────────────────────────────────────────────────────────
    async def _ensure_salla_customer(self, session_id: str, customer: dict) -> dict:
        """
        Guarantee the conversation has a Salla customer_id before placing an
        order. Salla's order API requires name+mobile+EMAIL when no id is
        given; using an existing customer.id sidesteps that. So if we don't
        have an id yet, find the customer by phone (or create them) and store
        the resulting id back on the session.

        Returns the (possibly updated) customer_info dict. Never raises.
        """
        if not self.salla or not customer:
            return customer
        if customer.get("salla_customer_id"):
            return customer

        phone = (customer.get("phone") or "").strip()
        if not phone:
            return customer

        first, last, dial, local = _split_name_phone(customer.get("name", ""), phone)

        async def _find_id() -> int | None:
            """Search by several phone forms — Salla keyword matching is picky."""
            for term in {local, phone, dial + local, local.lstrip("0")}:
                if not term:
                    continue
                try:
                    resp  = await self.salla.get_customer_by_phone(term)
                    found = resp.get("data", [])
                    c = (found[0] if isinstance(found, list) and found
                         else found if isinstance(found, dict) else {})
                    if isinstance(c, dict) and c.get("id"):
                        return c["id"]
                except Exception:
                    continue
            return None

        cid = None
        try:
            # 1) Find existing customer first
            cid = await _find_id()

            # 2) Not found → create them
            if not cid:
                try:
                    cresp = await self.salla.create_customer(
                        first_name=first, last_name=last,
                        mobile=local, mobile_code_country=dial,
                        email=customer.get("email", ""),
                    )
                    cid = (cresp.get("data") or {}).get("id")
                except Exception as ce:
                    # Most common: mobile/email already exists (duplicate) →
                    # the customer DOES exist, so re-search to grab their id.
                    print(f"[_ensure_salla_customer] create failed ({ce}); re-searching")
                    cid = await _find_id()

            if cid:
                customer = dict(customer)
                customer["salla_customer_id"] = cid
                await cs.set_customer_info(session_id, customer)
                await cs.flush(session_id)
                print(f"[_ensure_salla_customer] using salla_customer_id={cid}")
            else:
                print("[_ensure_salla_customer] could not resolve a customer id")
        except Exception as e:
            print(f"[_ensure_salla_customer] failed (will fall back to raw fields): {e}")

        return customer

    # ── AI-issued discount coupon ───────────────────────────────────────────────
    async def _issue_coupon(self, inputs: dict, session_id: str) -> str:
        """
        Create a single, one-use, time-boxed percentage coupon on the merchant's
        Salla store and return its code + terms for the model to present.

        Guards (all enforced server-side, never trusted to the model):
          • Only runs when the merchant opted in (`coupons_enabled`).
          • Percentage clamped to `coupon_max_percent`.
          • SAR value capped via `maximum_amount` (`coupon_max_discount_value`).
          • One coupon per chat session — a repeat call returns the same code.
          • usage_limit = 1 so a leaked code can't be reused.
        """
        if not self.coupons_enabled:
            return "ميزة كوبونات الخصم غير مفعّلة لهذا المتجر."
        if not self.salla:
            return "تعذّر إصدار كوبون الآن — المتجر غير مربوط بسلة."

        # One coupon per session: reuse the previously-issued code if any.
        conv = cs.all_conversations().get(session_id) or {}
        prev = conv.get("issued_coupon")
        if prev:
            return (
                f"سبق إصدار كوبون لك في هذه المحادثة: *{prev['code']}* "
                f"(خصم {prev['percent']}٪، صالح حتى {prev['expiry']}). استخدمه عند الدفع."
            )

        pct = _clamp_int(inputs.get("discount_percent"), self.coupon_max_percent,
                         lo=1, hi=self.coupon_max_percent)

        import datetime as _d
        import secrets as _s
        ttl_days  = max(1, round(self.coupon_ttl_hours / 24))
        expiry_dt = (_d.datetime.utcnow() + _d.timedelta(days=ttl_days)).replace(
            hour=23, minute=59, second=59, microsecond=0)
        # Salla requires expiry_date to be at least one day later than today.
        code = "AI" + _s.token_hex(3).upper()   # e.g. AI4F9C2A

        try:
            await self.salla.create_coupon(
                code=code,
                amount=pct,
                coupon_type="percentage",
                expiry_date=expiry_dt.strftime("%Y-%m-%d %H:%M:%S"),
                maximum_amount=self.coupon_max_discount_value,
                minimum_amount=(self.coupon_min_order or None),
                usage_limit=1,
                usage_limit_per_user=1,
            )
        except Exception as exc:
            # 403 = merchant didn't grant coupons.read_write; others = transient.
            print(f"[coupon] create failed store={self.store_id!r} reason={inputs.get('reason','')!r}: {exc}")
            return "تعذّر إصدار الكوبون حالياً. يمكنك المتابعة وسيساعدك فريقنا إن احتجت."

        expiry_date = expiry_dt.strftime("%Y-%m-%d")
        issued = {"code": code, "percent": pct, "expiry": expiry_date}
        if session_id in cs.all_conversations():
            cs.all_conversations()[session_id]["issued_coupon"] = issued
            cs.mark_dirty(session_id)
            try:
                await cs.flush(session_id)
            except Exception:
                pass
        print(f"[coupon] issued {code} ({pct}%) store={self.store_id!r} session={session_id!r}")

        terms = f"كود الخصم: *{code}* — خصم {pct}٪"
        if self.coupon_min_order:
            terms += f" على الطلبات من {int(self.coupon_min_order)} ريال فأكثر"
        terms += (
            f"، بحد أقصى {int(self.coupon_max_discount_value)} ريال، "
            f"صالح حتى {expiry_date}، لاستخدام واحد فقط. "
            "أبلغ العميل بالكود وشجّعه على إتمام الطلب."
        )
        return terms

    # ── Live inventory + shipping ───────────────────────────────────────────────
    async def _check_stock(self, inputs: dict) -> str:
        """Live per-variant (or product-level) stock + price straight from Salla."""
        if not self.salla:
            return "⚠️ لم يتم ربط المتجر بعد."
        pid   = str(inputs.get("product_id") or "").strip()
        pname = (inputs.get("product_name") or "").strip()

        store = get_store_data(self.store_id)
        prods = store.get("products", []) or []
        prod  = None
        if pid:
            prod = next((p for p in prods if str(p.get("id")) == pid), None)
        if not prod and pname:
            nl = pname.lower()
            prod = (next((p for p in prods if nl == (p.get("name", "") or "").lower()), None)
                    or next((p for p in prods if nl in (p.get("name", "") or "").lower()), None))
        if not prod and pid:
            prod = {"id": pid, "name": pname or f"#{pid}"}
        if not prod:
            return "لم أجد هذا المنتج. اذكر اسمه بدقة أكثر أو استخدم suggest_products أولاً."

        product_id = prod.get("id")
        pdisplay   = prod.get("name", f"#{product_id}")

        try:
            vdata    = await self.salla.get_product_variants(product_id)
            variants = vdata.get("data", []) or []
        except Exception as exc:
            print(f"[check_stock] variants failed pid={product_id}: {exc}")
            variants = []

        if not variants:
            # Simple product (no options) — fall back to cached availability.
            if prod.get("unlimited_quantity"):
                return f"✅ {pdisplay}: متوفر."
            q = prod.get("quantity")
            if isinstance(q, (int, float)) and q > 0:
                return f"✅ {pdisplay}: متوفر ({int(q)} قطعة في المخزون)."
            if q == 0:
                return f"⛔ {pdisplay}: غير متوفر حالياً (نفد المخزون)."
            return f"{pdisplay}: لم أتمكن من تأكيد المخزون اللحظي، تواصل معنا للتأكيد."

        # Resolve option-value ids → human labels (best-effort, from raw product).
        label_map: dict = {}
        try:
            pd = await self.salla.get_product(product_id)
            for o in (pd.get("data", {}).get("options") or []):
                for v in (o.get("values") or []):
                    if v.get("id") is not None:
                        label_map[v["id"]] = v.get("name") or str(v["id"])
        except Exception:
            pass

        lines = [f"📦 توفّر **{pdisplay}** (لحظي):"]
        any_avail = False
        for v in variants[:12]:
            labels = [str(label_map.get(x, "")) for x in (v.get("related_option_values") or [])]
            labels = [l for l in labels if l]
            label  = " / ".join(labels) if labels else (v.get("sku") or f"#{v.get('id')}")
            stock  = v.get("stock_quantity")
            price  = (v.get("price") or {}).get("amount")
            if isinstance(stock, (int, float)) and stock > 0:
                any_avail = True
                extra = f" — {price} ريال" if price else ""
                lines.append(f"• {label}: ✅ متوفر ({int(stock)}){extra}")
            else:
                lines.append(f"• {label}: ⛔ غير متوفر")
        if not any_avail:
            lines.append("\nجميع الخيارات غير متوفرة حالياً.")
        return "\n".join(lines)

    async def _estimate_shipping(self, inputs: dict) -> str:
        """Live carrier rates + ETA to the customer's city via Salla estimate-rate."""
        if not self.salla:
            return "⚠️ لم يتم ربط المتجر بعد."
        city    = (inputs.get("city") or "").strip()
        country = (inputs.get("country") or "").strip()
        if not city:
            return "اذكر اسم مدينتك لأحسب لك تكلفة الشحن ومدة التوصيل."

        try:
            country_id = await self.salla.resolve_country_id(country)
            city_id    = await self.salla.resolve_city_id(country_id, city) if country_id else None
        except Exception as exc:
            print(f"[estimate_shipping] geo resolve failed: {exc}")
            country_id = city_id = None

        if not (country_id and city_id):
            # Couldn't pin the city → generic carrier list rather than a dead end.
            carriers = brain.get_shipping_companies(self.store_id) or []
            names = "، ".join(c.get("name", "") for c in carriers[:6] if c.get("name"))
            if names:
                return (f"نشحن عبر: {names}. لمعرفة التكلفة الدقيقة لـ «{city}» تأكد من "
                        "اسم المدينة، أو أكمل الطلب لعرض خيارات الشحن وأسعارها.")
            return f"تعذّر تحديد مدينة «{city}». تأكد من الاسم وحاول مجدداً."

        try:
            data  = await self.salla.estimate_shipping_rates(city_id, country_id)
            rates = data.get("data", []) or []
        except Exception as exc:
            print(f"[estimate_shipping] estimate failed city={city_id}: {exc}")
            return "تعذّر جلب أسعار الشحن لحظياً. حاول لاحقاً أو أكمل الطلب لعرض الخيارات."

        if not rates:
            return f"لا توجد خيارات شحن متاحة إلى {city} حالياً."

        rates.sort(key=lambda r: float((r.get("total") or {}).get("amount") or 1e9))
        lines = [f"🚚 خيارات الشحن إلى {city}:"]
        for r in rates[:6]:
            title = r.get("title", "شركة شحن")
            total = r.get("total") or {}
            amt   = total.get("amount")
            cur   = total.get("currency", "SAR")
            days  = (r.get("working_days") or "").strip()
            line  = f"• {title}: {amt} {cur}"
            if days:
                line += f" — {days}"
            cod = next((s for s in (r.get("services") or []) if s.get("name") == "cod"), None)
            cod_amt = ((cod or {}).get("amount") or {}).get("amount")
            if cod_amt:
                line += f" (الدفع عند الاستلام +{cod_amt})"
            lines.append(line)
        return "\n".join(lines)

    async def _track_shipment(self, inputs: dict) -> str:
        """Resolve order → shipment → live tracking (status + history + link)."""
        if not self.salla:
            return "⚠️ لم يتم ربط المتجر بعد."
        ref = (inputs.get("order_reference") or "").strip()
        if not ref:
            return "اذكر رقم الطلب لأتتبّع شحنتك."

        order: dict = {}
        try:
            order = (await self.salla.get_order(ref)).get("data", {}) or {}
        except Exception:
            pass
        if not order:
            try:
                rows  = (await self.salla.get_orders(reference_id=ref, per_page=5)).get("data", [])
                order = rows[0] if rows else {}
            except Exception:
                pass
        order_id = order.get("id")
        if not order_id:
            return f"لم أجد طلباً برقم {ref}. تأكد من الرقم وحاول مجدداً."

        try:
            shipments = (await self.salla.get_shipments(order_id=order_id, per_page=10)).get("data", []) or []
        except Exception as exc:
            print(f"[track_shipment] list shipments failed order={order_id}: {exc}")
            shipments = []

        outbound = [s for s in shipments if s.get("type") != "return"] or shipments
        if not outbound:
            st = order.get("status") or {}
            st_name = st.get("name", "") if isinstance(st, dict) else str(st)
            return (f"طلبك #{ref}: لم تُجهَّز الشحنة بعد. "
                    f"الحالة الحالية: {st_name or '—'}. سنُعلمك فور شحنه.")

        ship    = outbound[0]
        ship_id = ship.get("id")
        tracking: dict = {}
        try:
            tracking = (await self.salla.get_shipment_tracking(ship_id)).get("data", {}) or {}
        except Exception:
            tracking = ship   # fall back to the shipment summary

        status  = tracking.get("status") or ship.get("status") or "—"
        courier = tracking.get("courier_name") or ship.get("courier_name") or ""
        tnum    = tracking.get("tracking_number") or ship.get("tracking_number") or ""
        tlink   = tracking.get("tracking_link") or ship.get("tracking_link") or ""

        lines = [f"🚚 تتبّع شحنة الطلب #{ref}:", f"الحالة: {_SHIPMENT_STATUS_AR.get(status, status)}"]
        if courier:
            lines.append(f"شركة الشحن: {courier}")
        if tnum and str(tnum) != "0":
            lines.append(f"رقم التتبع: {tnum}")

        history = tracking.get("history") or []
        if history:
            lines.append("\nآخر التحديثات:")
            for h in history[:4]:
                hs   = _SHIPMENT_STATUS_AR.get(h.get("status", ""), h.get("status", ""))
                note = (h.get("note") or "").strip()
                ca   = h.get("create_at") or {}
                when = (ca.get("date", "")[:16] if isinstance(ca, dict) else "")
                seg  = f"• {hs}"
                if note:
                    seg += f" — {note}"
                if when:
                    seg += f" ({when})"
                lines.append(seg)
        if tlink:
            lines.append(f"\nرابط التتبع: {tlink}")
        return "\n".join(lines)

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

            # ── get_current_offers ──────────────────────────────────────────
            elif name == "get_current_offers":
                offers = brain.get_special_offers(self.store_id)
                active = [o for o in offers if o.get("status") in ("", "active", None)]
                if not active:
                    return "لا توجد عروض نشطة حالياً. تابعنا للاطلاع على أحدث الخصومات! 🎁"
                lines = [f"🎁 **العروض الحالية ({len(active)})**"]
                for o in active[:10]:
                    nm  = o.get("name", "")
                    msg = o.get("message", "")
                    end = o.get("end_date", "")
                    line = f"• {nm}" if nm else "• عرض"
                    if msg:
                        line += f" — {msg}"
                    if end:
                        line += f" (حتى {str(end)[:10]})"
                    lines.append(line)
                return "\n".join(lines)

            # ── get_payment_methods ─────────────────────────────────────────
            elif name == "get_payment_methods":
                methods = brain.get_payment_methods(self.store_id)
                if not methods:
                    return ("⚠️ لم يتم تحميل طرق الدفع بعد. "
                            "قد يحتاج المتجر لتفعيل صلاحية payments.read.")
                names = [m.get("name", "") for m in methods if m.get("name")]
                return "💳 **طرق الدفع المتاحة:**\n" + "\n".join(f"• {n}" for n in names)

            # ── get_branches ────────────────────────────────────────────────
            elif name == "get_branches":
                branches = brain.get_branches(self.store_id)
                if not branches:
                    return ("لا توجد فروع مسجّلة. الطلب يتم أونلاين والتوصيل عبر شركات الشحن. "
                            "ربما يحتاج المتجر لتفعيل صلاحية branches.read.")
                lines = [f"🏬 **فروعنا ({len(branches)})**"]
                for b in branches[:12]:
                    nm   = b.get("name", "")
                    city = b.get("city", "")
                    addr = b.get("address", "")
                    phone = b.get("phone", "")
                    parts = [f"📍 {nm}"]
                    if city: parts.append(city)
                    line = " — ".join(parts)
                    if addr: line += f"\n  {addr}"
                    if phone: line += f"\n  ☎️ {phone}"
                    lines.append(line)
                return "\n".join(lines)

            # ── get_brands ──────────────────────────────────────────────────
            elif name == "get_brands":
                brands = brain.get_brands(self.store_id)
                if not brands:
                    return "لا توجد ماركات مسجّلة بشكل منفصل. تصفح منتجاتنا للاطلاع على المتوفر."
                names = [b.get("name", "") for b in brands if b.get("name")]
                return f"🏷️ **الماركات المتوفرة ({len(names)}):**\n" + "، ".join(names)

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
                        await cs.set_last_component(session_id, {
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
                    await cs.set_last_component(session_id, {
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

                await cs.cart_add(session_id, {
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
                await cs.set_last_component(session_id, {
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
                await cs.set_last_component(session_id, {
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
                removed = await cs.cart_remove(session_id, pid)
                if removed:
                    cart  = cs.get_cart(session_id)
                    total = cs.cart_total(session_id)
                    await cs.set_last_component(session_id, {
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
                await cs.set_customer_info(session_id, info)

                # ── Find-or-create the customer in Salla ─────────────────────────
                # 1) Look up by phone. If found → store salla_customer_id.
                # 2) If NOT found → create a new customer record in the store's
                #    customer base, then store the new id. This means every
                #    chatbot lead becomes a real Salla customer the merchant
                #    can see, segment, and remarket to.
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
                            # Existing customer — enrich silently
                            enriched = dict(info)
                            enriched["salla_customer_id"] = c["id"]
                            if not enriched.get("email") and c.get("email"):
                                enriched["email"] = c["email"]
                            if not enriched.get("name"):
                                full = f"{c.get('first_name','')} {c.get('last_name','')}".strip()
                                if full:
                                    enriched["name"] = full
                            await cs.set_customer_info(session_id, enriched)
                            print(f"[set_customer_info] ✅ matched existing salla_id={c['id']}")
                        else:
                            # New lead — create the customer in Salla
                            first, last, dial, local = _split_name_phone(
                                info.get("name", ""), info.get("phone", "")
                            )
                            try:
                                cresp = await self.salla.create_customer(
                                    first_name=first, last_name=last,
                                    mobile=local, mobile_code_country=dial,
                                    email=info.get("email", ""),
                                )
                                newc = cresp.get("data", {})
                                if newc.get("id"):
                                    enriched = dict(info)
                                    enriched["salla_customer_id"] = newc["id"]
                                    await cs.set_customer_info(session_id, enriched)
                                    print(f"[set_customer_info] 🆕 created salla customer "
                                          f"id={newc['id']} for session {session_id}")
                            except Exception as ce:
                                # 422 = duplicate email/mobile race, or missing scope —
                                # non-fatal, checkout still works with raw fields.
                                print(f"[set_customer_info] create_customer skipped: {ce}")
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
                        # ── Phase 1: create order with the first cart item ───
                        # create_order now sends the correct `products` array
                        # (identifier_type/identifier/quantity). The rest of
                        # the cart is added via POST /orders/items in phase 2.
                        first_item = cart[0]
                        bootstrap_items = [{
                            "product_id": first_item["product_id"],
                            "quantity":   first_item["quantity"],
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
                            await cs.set_last_component(session_id, component)
                            await cs.cart_clear(session_id)
                            # Persist cleared cart + checkout component before returning
                            # (protects against a crash between here and add_message)
                            await cs.flush(session_id)
                            # ROI tracking — attribute this order's revenue to the bot
                            await db.record_bot_order(
                                self.store_id, session_id, order_ref,
                                _amount_to_float(total_str), currency, kind="checkout")

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
                            await cs.cart_clear(session_id)
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
                        await cs.set_last_component(session_id, {
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

            # ── create_quote_order ───────────────────────────────────────────
            elif name == "create_quote_order":
                if not session_id:
                    return "⚠️ session_id مفقود."
                if not self.salla:
                    return "⚠️ لم يتم ربط المتجر بعد — لا يمكن إنشاء الطلب."

                product_name = (inputs.get("product_name") or "").strip()
                total_price  = inputs.get("total_price")
                print_qty    = max(1, int(inputs.get("quantity", 1) or 1))  # the PRINT quantity (a spec)
                specs        = (inputs.get("specs") or "").strip()

                if not product_name or total_price is None:
                    return "⚠️ اسم المنتج والسعر مطلوبان لإنشاء الطلب."

                customer = cs.get_customer_info(session_id)
                if not customer.get("phone") and not customer.get("salla_customer_id"):
                    return "⚠️ يرجى تزويدي باسمك ورقم جوالك أولاً لإتمام الطلب."

                # Ensure we have a Salla customer_id. Creating an order with raw
                # customer fields requires name+mobile+EMAIL (all three). Using
                # an existing customer.id avoids the email requirement. So if we
                # don't yet have an id, create/find the customer now.
                customer = await self._ensure_salla_customer(session_id, customer)

                # If we still couldn't get an id AND have no email, the raw-fields
                # order would fail Salla validation — ask for the email instead.
                if not customer.get("salla_customer_id") and not customer.get("email"):
                    return ("ممتاز! بس محتاج بريدك الإلكتروني عشان أكمّل الطلب وأرسل "
                            "لك رابط الدفع. ممكن تزوّدني به؟ 📧")

                try:
                    total_price = float(total_price)
                except (ValueError, TypeError):
                    return "⚠️ السعر غير صالح."

                # IMPORTANT pricing model for custom print jobs:
                # The quote total (e.g. 103.50) is the price of the WHOLE job
                # (the full 1000 pieces), NOT a per-unit price. So we create
                # the product priced at the full total and order ONE unit of
                # it. The print quantity (1000) is a spec captured in the name
                # / description / notes — not the order line quantity.
                # (Previously we did total ÷ qty, which created a 0.10 product
                #  and a wrong order total.)
                job_price = round(total_price, 2)
                # Make sure the piece count is visible in the product name
                if str(print_qty) not in product_name:
                    product_name = f"{product_name} — {print_qty:,} قطعة"

                try:
                    # ── 1. Create a custom product carrying the quote ────────
                    prod_resp = await self.salla.create_product(
                        name=product_name,
                        price=job_price,
                        product_type="service",      # printing = service, no shipping weight
                        unlimited_quantity=True,
                        description=specs or product_name,
                        status="sale",
                    )
                    product = prod_resp.get("data", {})
                    new_pid = product.get("id")
                    if not new_pid:
                        raise RuntimeError("لم يُرجع سلة معرف المنتج الجديد")

                    # ── 1b. Attach an image so the product isn't `hidden` ────
                    # Salla keeps image-less products hidden, and hidden
                    # products can't be ordered. Use the store logo (or a
                    # neutral placeholder) so the product becomes orderable.
                    try:
                        store_info = brain.get_store_info(self.store_id)
                        img_url = (store_info.get("avatar") or "").strip() or \
                                  "https://cdn.assets.salla.network/prod/admin/cp/assets/images/placeholder.png"
                        await self.salla.attach_product_image_url(new_pid, img_url, alt=product_name)
                    except Exception as img_e:
                        print(f"[create_quote_order] image attach failed (non-fatal): {img_e}")

                    # ── 2. Create the order with that product (qty = 1 job) ──
                    order_notes = (
                        f"طلب عرض سعر مخصص — {print_qty:,} قطعة.\n{specs}"
                        if specs else f"طلب عرض سعر مخصص — {print_qty:,} قطعة."
                    )
                    order_resp = await self.salla.create_order(
                        [{"product_id": new_pid, "quantity": 1}],
                        customer,
                    )
                    order     = order_resp.get("data", {})
                    order_id  = order.get("id")
                    order_ref = order.get("reference_id", str(order_id))

                    # Record the specs on the order timeline (POST /orders has
                    # no `notes` field, so we add them as an order history note).
                    if order_id:
                        try:
                            await self.salla.add_order_note(order_id, order_notes)
                        except Exception as ne:
                            print(f"[create_quote_order] add_order_note failed (non-fatal): {ne}")
                    pay_url   = (order.get("urls") or {}).get("customer", "")
                    amounts   = order.get("amounts", {})
                    total_str = (amounts.get("total") or {}).get("amount", f"{total_price:.2f}")
                    currency  = (amounts.get("total") or {}).get("currency", "SAR")

                    # ROI tracking — custom quote→order revenue attributed to bot
                    await db.record_bot_order(
                        self.store_id, session_id, order_ref,
                        _amount_to_float(total_str), currency, kind="quote")

                    if pay_url:
                        await cs.set_last_component(session_id, {
                            "type":      "checkout",
                            "url":       pay_url,
                            "total":     total_str,
                            "currency":  currency,
                            "order_ref": order_ref,
                        })
                        await cs.flush(session_id)
                        return (
                            f"✅ تم إنشاء طلبك المخصص رقم #{order_ref} بنجاح!\n"
                            f"📦 {product_name}\n"
                            f"الإجمالي: {total_str} {currency}\n"
                            f"💳 رابط الدفع: {pay_url}"
                        )
                    return (
                        f"✅ تم إنشاء طلبك المخصص رقم #{order_ref}.\n"
                        f"الإجمالي: {total_str} {currency}. سيتواصل معك الفريق لإتمام الدفع."
                    )

                except Exception as e:
                    # Log the FULL Salla error (scope/validation) for the admin.
                    print(f"[create_quote_order] FAILED store={self.store_id}: {e}")
                    # Customer-facing message: do NOT instruct the bot to hand off
                    # to support (that caused a deflection cascade). Keep it short
                    # and reassuring; the order details are already in the chat
                    # transcript for the admin to action.
                    return (
                        "تم تسجيل تفاصيل طلبك وسأجهّزه لك حالاً 📝 "
                        "(SYSTEM_NOTE للمساعد: فشل الإنشاء التلقائي للطلب — "
                        "لا تعرض بيانات الدعم، فقط طمئن العميل أن طلبه مسجّل "
                        "وسيتم تجهيزه. السبب التقني مسجّل في اللوج للأدمن.)"
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
                    await cs.set_customer_info(session_id, merged)
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
                    await cs.set_last_component(session_id, {
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

            # ── get_delivery_promises ────────────────────────────────────────
            elif name == "get_delivery_promises":
                if not self.salla:
                    return "⚠️ لم يتم ربط المتجر بعد."
                try:
                    data     = await self.salla.get_delivery_promises()
                    promises = data.get("data", []) or []
                except Exception as exc:
                    print(f"[get_delivery_promises] {exc}")
                    return "تعذّر جلب مواعيد التسليم حالياً، تواصل مع المتجر للاستفسار."

                if not promises:
                    return "لا توجد وعود تسليم محددة لهذا المتجر حالياً."

                unit_ar = {"hours": "ساعة", "days": "يوم"}
                lines   = ["📅 **مواعيد التسليم المتاحة:**"]
                for p in promises[:8]:
                    p_name   = p.get("name", "")
                    desc     = p.get("description", "")
                    dt       = p.get("delivery_time") or {}
                    dt_from  = dt.get("from")
                    dt_to    = dt.get("to")
                    dt_unit  = unit_ar.get(dt.get("type", ""), dt.get("type", ""))
                    location = p.get("location") or {}
                    cities   = location.get("cities") or []
                    city_names = [c.get("name", "") for c in cities
                                  if c.get("name") and c.get("id") not in (-1, None)]
                    inactive = "" if p.get("status") else " _(غير مفعّل حالياً)_"
                    line = f"• **{p_name}**{inactive}"
                    if dt_from is not None and dt_to is not None:
                        line += f": {dt_from}–{dt_to} {dt_unit}"
                    if desc:
                        line += f" — {desc}"
                    if city_names:
                        line += f"\n  المدن: {', '.join(city_names[:5])}"
                    lines.append(line)
                return "\n".join(lines)

            # ── get_product_reviews ──────────────────────────────────────────
            elif name == "get_product_reviews":
                if not self.salla:
                    return "⚠️ لم يتم ربط المتجر بعد."

                pid       = str(inputs.get("product_id") or "").strip()
                min_stars = inputs.get("min_stars")

                # Resolve product_id from product_name if not supplied directly
                if not pid and inputs.get("product_name"):
                    pname = (inputs["product_name"] or "").lower()
                    store = get_store_data(self.store_id) if self.store_id else {}
                    prod  = next(
                        (p for p in (store.get("products") or [])
                         if pname in (p.get("name") or "").lower()),
                        None,
                    )
                    if prod:
                        pid = str(prod.get("id", ""))

                stars = ([str(s) for s in range(int(min_stars), 6)]
                         if min_stars else None)
                try:
                    data    = await self.salla.get_product_reviews(
                        product_id=pid or None,
                        stars=stars,
                        review_type="rating",
                        publish=True,
                        per_page=10,
                    )
                    reviews = data.get("data", []) or []
                except Exception as exc:
                    print(f"[get_product_reviews] {exc}")
                    return "تعذّر جلب التقييمات حالياً."

                if not reviews:
                    return "لا توجد تقييمات منشورة لهذا المنتج بعد. كن أول من يقيّم! ⭐"

                reviews.sort(key=lambda r: -(r.get("rating") or 0))
                total = len(reviews)
                avg   = round(sum(r.get("rating", 0) for r in reviews) / total, 1)
                lines = [f"⭐ **تقييمات العملاء — المعدل: {avg}/5 ({total} تقييم)**"]
                for r in reviews[:5]:
                    stars_n  = int(r.get("rating") or 0)
                    stars_s  = "⭐" * stars_n
                    content  = (r.get("content") or "").strip()
                    customer = r.get("customer") or {}
                    cname    = customer.get("name") or "عميل"
                    city     = customer.get("city") or ""
                    line     = f"{stars_s} **{cname}**"
                    if city:
                        line += f" ({city})"
                    if content:
                        line += f'\n  _"{content[:120]}"_'
                    lines.append(line)
                return "\n".join(lines)

            # ── generate_discount_coupon ────────────────────────────────────
            elif name == "generate_discount_coupon":
                return await self._issue_coupon(inputs, session_id)

            # ── check_stock / estimate_shipping / track_shipment ────────────
            elif name == "check_stock":
                return await self._check_stock(inputs)

            elif name == "estimate_shipping":
                return await self._estimate_shipping(inputs)

            elif name == "track_shipment":
                return await self._track_shipment(inputs)

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

                ptype = inputs["printing_type"]
                qty   = int(inputs.get("quantity", 0))
                cur   = result.get("currency", "SAR")
                lines = []

                # ── Main result block (public-safe — no internal fields) ──────
                if ptype == "roll":
                    lines.append(f"📐 **تسعير طباعة رول**")
                    lines.append(f"المقاس: {inputs['width']}×{inputs['height']} سم  |  الكمية: {qty:,} قطعة")
                elif ptype == "digital":
                    lines.append(f"📐 **تسعير طباعة ديجيتال**")
                    lines.append(f"الخامة: {result['paper_name']}  |  مقاس الشيت: {result['sheet_size']}")
                    lines.append(f"التصميم: {inputs['width']}×{inputs['height']} سم  |  الكمية: {qty:,}")
                    # Foil / Spot UV costs are customer-facing add-on prices (not internal)
                    if result.get("foil_cost", 0) > 0:
                        lines.append(f"بصمة: {result['foil_cost']:,.2f} {cur}")
                    if result.get("spot_uv_cost", 0) > 0:
                        lines.append(f"سبوت يو في: {result['spot_uv_cost']:,.2f} {cur}")
                elif ptype == "offset":
                    lines.append(f"📐 **تسعير طباعة أوفست**")
                    lines.append(f"الخامة: {result['paper_name']}")
                    lines.append(f"التصميم: {inputs['width']}×{inputs['height']} سم  |  الكمية: {qty:,}")
                    lines.append(f"سعر الحبة: {result['price_per_unit']:.4f} {cur}")
                elif ptype == "uvdtf":
                    lines.append(f"📐 **تسعير طباعة UV DTF**")
                    lines.append(f"التصميم: {inputs['width']}×{inputs['height']} سم  |  الكمية: {qty:,}")
                    lines.append(f"الأمتار المستهلكة: {result['meters_consumed']} م")

                if not result.get("is_floored"):
                    lines.append(f"الضريبة (15%): {result['tax_amount']:,.2f} {cur}")
                    if result.get("discount_percent", 0) > 0:
                        lines.append(f"خصم الكمية: -{result['discount_amount']:,.2f} {cur} ({result['discount_percent']}%)")
                lines.append(f"━━━━━━━━━━━━")
                lines.append(f"💵 **السعر النهائي: {result['final_price']:,.2f} {cur}**")
                if result.get("is_rotated"):
                    lines.append(f"_(تم اختيار أفضل اتجاه تلقائياً لتوفير الخامة)_")

                # ── Tiered upsell: 2-3 higher qty anchors ─────────────────────
                # Build the shared kwargs for the tiered calculator
                tiered_kwargs = {k: v for k, v in {
                    "width":       float(inputs.get("width",  0)),
                    "height":      float(inputs.get("height", 0)),
                    "roll_width":  inputs.get("roll_width"),
                    "paper_type":  inputs.get("paper_type"),
                    "sheet_size":  inputs.get("sheet_size"),
                    "addons":      inputs.get("addons") or [],
                    "foil_width":  float(inputs.get("foil_width",  0) or 0),
                    "foil_height": float(inputs.get("foil_height", 0) or 0),
                    "spot_uv":     bool(inputs.get("spot_uv", False)),
                    "cutting":     inputs.get("cutting", "normal"),
                    "folding":     bool(inputs.get("folding", False)),
                    "punching":    bool(inputs.get("punching", False)),
                }.items() if v is not None and v != [] and v is not False}

                try:
                    tiers = pc.calculate_tiered_quote(
                        ptype, pricing_cfg, qty, **tiered_kwargs
                    )
                    # Only show tiers above the requested qty that have lower unit cost
                    above = [t for t in tiers if not t.get("is_requested") and not t["raw"].get("error")]
                    if above:
                        lines.append("")
                        lines.append("📊 **كلما زادت الكمية ينزل السعر:**")
                        for tier in above[:3]:
                            tier_qty   = tier["qty"]
                            tier_total = tier["final_price"]
                            if tier.get("price_per_unit") is not None:
                                lines.append(
                                    f"  • {tier_qty:,} قطعة → **{tier_total:,.2f} {cur}** "
                                    f"({tier['price_per_unit']:.4f}/حبة)"
                                )
                            else:
                                lines.append(f"  • {tier_qty:,} قطعة → **{tier_total:,.2f} {cur}**")
                        lines.append("أي كمية تناسبك أكثر؟")
                except Exception:
                    pass  # tiered display is best-effort — don't break the main result

                return "\n".join(lines)

            # ── get_box_tiered_quote ─────────────────────────────────────────────
            elif name == "get_box_tiered_quote":
                ai_cfg      = sm.get_ai_config(self.store_id) if self.store_id else {}
                pricing_cfg = ai_cfg.get("pricing_config") or {}

                flat_length   = float(inputs.get("flat_length",   0) or 0)
                flat_width    = float(inputs.get("flat_width",    0) or 0)
                requested_qty = int(inputs.get("requested_qty",   0) or 0)
                paper_type    = (inputs.get("paper_type") or "انفربرش")
                sides         = (inputs.get("sides")       or "single")
                lam_sides     = int(inputs.get("lamination_sides", 0) or 0)

                if flat_length <= 0 or flat_width <= 0 or requested_qty <= 0:
                    return "⚠️ يرجى تزويدي بمقاس الفرد والكمية."

                tiers = pc.calculate_tiered_box_quotes(
                    pricing_cfg,
                    flat_length=flat_length,
                    flat_width=flat_width,
                    requested_qty=requested_qty,
                    paper_type=paper_type,
                    sides=sides,
                    lamination_sides=lam_sides,
                )

                valid = [t for t in tiers if not t.get("error")]
                if not valid:
                    return "⚠️ لم أستطع حساب الأسعار. تأكد من المواصفات."

                cur = "SAR"
                lines = [
                    f"📊 **أسعار علب {paper_type} — فرد {flat_length}×{flat_width} سم**",
                    f"{'الكمية':>8} | {'سعر الحبة':>10} | {'الإجمالي':>12}",
                    "—" * 38,
                ]
                for t in valid:
                    marker = " ◄ طلبك" if t.get("is_requested") else ""
                    lines.append(
                        f"{t['qty']:>8,} | {t['price_per_unit']:>9.2f} {cur} "
                        f"| {t['final_price']:>11,.2f} {cur}{marker}"
                    )
                lines.append("")
                # Find max savings vs requested qty
                req = next((t for t in valid if t.get("is_requested")), None)
                top = valid[-1]
                if req and top and req["qty"] != top["qty"] and req["price_per_unit"] and top["price_per_unit"]:
                    saving_pct = round((1 - top["price_per_unit"] / req["price_per_unit"]) * 100)
                    lines.append(
                        f"تلاحظ أن سعر الحبة ينزل من **{req['price_per_unit']:.2f}** "
                        f"إلى **{top['price_per_unit']:.2f}** ريال — "
                        f"توفير {saving_pct}% عند {top['qty']:,} حبة. "
                        f"أي كمية تناسبك؟"
                    )
                return "\n".join(lines)

            # ── calculate_box_quote ──────────────────────────────────────────────
            elif name == "calculate_box_quote":
                ai_cfg      = sm.get_ai_config(self.store_id) if self.store_id else {}
                pricing_cfg = ai_cfg.get("pricing_config") or {}

                flat_length = float(inputs.get("flat_length", 0) or 0)
                flat_width  = float(inputs.get("flat_width",  0) or 0)
                quantity    = int(inputs.get("quantity",      0) or 0)
                paper_type  = (inputs.get("paper_type") or "انفربرش")
                sides       = (inputs.get("sides")       or "single")
                lam_sides   = int(inputs.get("lamination_sides", 0) or 0)

                if flat_length <= 0 or flat_width <= 0 or quantity <= 0:
                    return "⚠️ يرجى تزويدي بمقاس الفرد (الطول والعرض) والكمية."

                result = pc.calculate_box_quote(
                    pricing_cfg,
                    flat_length=flat_length,
                    flat_width=flat_width,
                    quantity=quantity,
                    paper_type=paper_type,
                    sides=sides,
                    lamination_sides=lam_sides,
                )

                if result.get("needs_escalation"):
                    # Auto-escalate: flat size is too large for our presses
                    await cs.escalate_session(
                        session_id,
                        reason="box_oversize",
                        details=(
                            f"علب {paper_type} — فرد {flat_length}×{flat_width} سم، "
                            f"كمية {quantity} — مقاس أكبر من الماكينة الكاملة 99×69"
                        ),
                        customer_summary=f"علب {flat_length}×{flat_width} سم، {quantity} حبة — مقاس كبير",
                    )
                    await cs.flush(session_id)
                    return (
                        "المقاس المطلوب أكبر من ماكيناتنا القياسية ويحتاج خامة خاصة. "
                        "تم تحويل طلبك لفريق المتجر — سيتم التواصل معك لتأكيد السعر والتفاصيل. 📋"
                    )

                if "error" in result:
                    return f"⚠️ {result['error']}"

                # Format the result for the customer
                cur = result.get("currency", "SAR")
                lam_label = {0: "بدون سلوفان", 1: "سلوفان وجه", 2: "سلوفان وجهين"}.get(lam_sides, "")
                sides_label = "وجهين" if sides == "double" else "وجه واحد"

                lines = [
                    f"📦 **تسعير علب {paper_type}**",
                    f"الفرد: {flat_length}×{flat_width} سم | الكمية: {quantity:,} حبة",
                    f"الطباعة: {sides_label}" + (f" | {lam_label}" if lam_label and lam_sides > 0 else ""),
                    "",
                    f"💵 سعر الحبة: {result['final_per_unit']} {cur}",
                    f"💰 الإجمالي شامل الضريبة: **{result['final_price']:,.2f} {cur}**",
                ]
                if not result.get("is_floored"):
                    lines.append(
                        f"  (قبل الضريبة: {result['price_before_tax']:,.2f} | "
                        f"الضريبة 15%: {result['tax_amount']:,.2f})"
                    )
                lines.append("")
                lines.append("ملاحظة: السعر تقديري وقد يتغير بعد مراجعة الدايلاين النهائي.")
                return "\n".join(lines)

            # ── escalate_to_admin ─────────────────────────────────────────────
            elif name == "escalate_to_admin":
                if not session_id:
                    return "⚠️ session_id مفقود."
                reason  = (inputs.get("reason")  or "other").strip()
                details = (inputs.get("details") or "").strip()
                summary = (inputs.get("customer_summary") or "").strip()

                await cs.escalate_session(
                    session_id,
                    reason=reason,
                    details=details,
                    customer_summary=summary,
                )
                # Persist immediately so admin dashboard reflects the takeover
                # even if the server restarts before the next message.
                await cs.flush(session_id)

                # Show a takeover banner in the widget so the customer
                # understands why the AI suddenly stopped responding.
                await cs.set_last_component(session_id, {
                    "type":    "admin_takeover",
                    "reason":  reason,
                    "message": "تم تحويل طلبك لفريق المتجر للمراجعة",
                })

                # Friendly handoff to the customer. The internal reason +
                # details are persisted via escalate_session() above and the
                # admin sees them through the dashboard API — do NOT leak
                # them in the tool result (the LLM would repeat them to the
                # customer in the final reply).
                print(
                    f"[escalate_to_admin] session={session_id} reason={reason} "
                    f"details={details!r} summary={summary!r}"
                )
                return (
                    "تم تسجيل طلبك وتحويله لفريق المتجر للمراجعة. "
                    "سيتم التواصل معك خلال وقت قصير لتأكيد التفاصيل والسعر النهائي. "
                    "شكراً لصبرك! 🌟"
                )

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

    # ── Per-session customer context ────────────────────────────────────────────
    def _customer_context(self, session_id: str) -> str:
        """
        Build a short Arabic block describing the CURRENT logged-in customer so
        the bot greets them by name and personalises the conversation. Returns
        "" for anonymous visitors (no Salla id and no name).

        Kept separate from the cached system prompt: it's injected as its own
        (uncached) block per request so the big static prompt stays cacheable.
        """
        if not session_id:
            return ""
        try:
            c = cs.get_customer_info(session_id) or {}
        except Exception:
            return ""
        if not c:
            return ""

        name    = (c.get("name") or "").strip()
        has_id  = bool(c.get("salla_customer_id"))
        # Only personalise when we actually know who they are.
        if not has_id and not name:
            return ""

        lines = ["══ بيانات العميل الحالي (للتخصيص — لا تذكر أنك تقرؤها من نظام) ══"]
        if has_id:
            lines.append("• العميل مسجّل دخوله في المتجر ومعروف لدينا.")
        else:
            lines.append("• زائر غير مسجّل — تعامل بترحيب عام.")
        if name:
            lines.append(f"• الاسم: {name} — ناده باسمه ورحّب به بحرارة.")
        if c.get("phone"):
            lines.append(f"• الجوال محفوظ ({c['phone']}) — لا تطلبه منه مرة أخرى.")
        if c.get("email"):
            lines.append(f"• البريد محفوظ ({c['email']}) — لا تطلبه منه مرة أخرى.")
        if c.get("city"):
            lines.append(f"• المدينة: {c['city']}.")

        oc = c.get("orders_count")
        if oc is not None:
            try:
                ocn = int(oc)
                if ocn > 0:
                    extra = f" (إجمالي مشترياته {c['orders_amount']})" if c.get("orders_amount") else ""
                    lines.append(
                        f"• عميل عائد لديه {ocn} طلب سابق{extra} — رحّب بعودته وقدّم له اهتماماً مميزاً."
                    )
                else:
                    lines.append("• عميل جديد لم يطلب من قبل — شجّعه بلطف على أول طلب.")
            except (ValueError, TypeError):
                pass

        return "\n".join(lines)

    # ── Chat entry point ───────────────────────────────────────────────────────
    async def chat(self, message: str, session_id: str) -> str:
        # Zero the usage counter so the caller (chat handler) reads only the
        # tokens this turn consumed, even after fast-path or exception paths.
        self._reset_usage()

        # ── Pre-LLM fast path ────────────────────────────────────────────────
        # Try to answer greetings / stored FAQs / informational intents WITHOUT
        # calling the LLM (cheaper + faster). Strictly scoped to stable factual
        # queries — pricing/quotes/recommendations always fall through. Any miss
        # or error returns None and the normal LLM flow runs.
        try:
            fp = await smart_router.route(message, self.store_id)
        except Exception as exc:
            print(f"[agent] fast-path skipped: {exc}")
            fp = None

        if fp:
            if fp["type"] == "tool":
                reply = await self._run_tool(fp["tool"], {}, session_id)
            else:
                reply = fp.get("text", "")
            # Persist user+assistant ONLY when we actually answer here, so an
            # empty tool result can fall through to the LLM without the user
            # message being recorded twice.
            if reply:
                await cs.add_message(session_id, "user", message, self.store_id)
                await cs.add_message(session_id, "assistant", reply, self.store_id)
                print(f"[fast-path] {fp.get('source')} — answered without LLM")
                return reply

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
            for t in self._tools
        ]

        _sys_prompt = await get_system_prompt_async(self.store_id, self.printing_enabled)
        _cust_ctx   = self._customer_context(session_id)
        if _cust_ctx:
            _sys_prompt = _sys_prompt + "\n\n" + _cust_ctx
        messages = [{"role": "system", "content": _sys_prompt}] + history

        tool_rounds = 0
        while True:
            response = await self.groq_client.chat.completions.create(
                model=self._groq_model,
                messages=messages,
                tools=groq_tools,
                tool_choice="auto",
                max_tokens=1024,
            )

            _u = getattr(response, "usage", None)
            if _u:
                self._add_usage(getattr(_u, "prompt_tokens", 0), getattr(_u, "completion_tokens", 0))

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
            for t in self._tools
        ]

        _sys_prompt = await get_system_prompt_async(self.store_id, self.printing_enabled)
        _cust_ctx   = self._customer_context(session_id)
        if _cust_ctx:
            _sys_prompt = _sys_prompt + "\n\n" + _cust_ctx
        messages = [{"role": "system", "content": _sys_prompt}] + history

        tool_rounds = 0
        while True:
            response = await self.openai_client.chat.completions.create(
                model=self._openai_model,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
                max_tokens=1024,
            )

            _u = getattr(response, "usage", None)
            if _u:
                self._add_usage(getattr(_u, "prompt_tokens", 0), getattr(_u, "completion_tokens", 0))

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

        # ── Prompt caching ─────────────────────────────────────────────────────
        # Three-layer caching strategy:
        #
        #   Layer 1 — Automatic (top-level cache_control): caches the growing
        #             conversation history automatically. The cache breakpoint
        #             advances to the latest message each turn, so every prior
        #             turn is read from cache on the next request.
        #
        #   Layer 2 — Explicit on system: the ~3-4k token system prompt is
        #             identical every request for the same store. Marked with
        #             cache_control so it is written once and read on every turn.
        #
        #   Layer 3 — Explicit on last tool: caches all 20+ tool definitions
        #             (~2k tokens) which never change within a session.
        #
        # Net effect: only new user/assistant messages are billed at full rate;
        # everything else is read from cache at 10% of input token cost.
        system_text = await get_system_prompt_async(self.store_id, self.printing_enabled)
        cached_system = [{
            "type":          "text",
            "text":          system_text,
            "cache_control": {"type": "ephemeral"},
        }]
        # Per-customer context goes in its OWN block AFTER the cached one and
        # WITHOUT cache_control — so the big static prompt stays cached while
        # each customer's small personalised note is sent fresh (cheap).
        cust_ctx = self._customer_context(session_id)
        if cust_ctx:
            cached_system.append({"type": "text", "text": cust_ctx})
        # Cache_control on the last ACTIVE tool (the tool list differs by store
        # type, so index off self._tools, not the global TOOLS).
        tools = self._tools
        cached_tools = [
            *tools[:-1],
            {**tools[-1], "cache_control": {"type": "ephemeral"}},
        ]

        tool_rounds = 0
        while True:
            response = await self.ai.messages.create(
                model=self._anthropic_model,
                max_tokens=1024,
                system=cached_system,
                tools=cached_tools,
                messages=history,
                # Automatic caching: advances the cache breakpoint to the last
                # message each turn so conversation history is cached.
                extra_body={"cache_control": {"type": "ephemeral"}},
            )

            # Log cache usage (remove in production if noisy) and feed the
            # daily budget counter. Anthropic uses input_tokens/output_tokens
            # (note: input_tokens already EXCLUDES the cached portion, so we
            # don't need to subtract cache_read_input_tokens here).
            usage = getattr(response, "usage", None)
            if usage:
                cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
                cache_read  = getattr(usage, "cache_read_input_tokens",     0) or 0
                if cache_write or cache_read:
                    print(f"[cache] write={cache_write} read={cache_read} "
                          f"saved≈{cache_read*0.9:.0f} tokens")
                self._add_usage(
                    getattr(usage, "input_tokens",  0),
                    getattr(usage, "output_tokens", 0),
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
