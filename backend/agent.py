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

═══ قواعد المحادثة ═══
• تكلم دائماً بالعربية بأسلوب ودي ومبهج
• للأسعار التقريبية استخدم calculate_print_quote
• لتتبع طلب موجود استخدم track_order
• ملف التصميم؟ قل: "يمكنك إرفاق ملف التصميم مباشرة هنا في المحادثة 📎"
• لا تتكلم عن أي شيء خارج نطاق المتجر"""


def get_system_prompt(store_id: str = "default") -> str:
    try:
        knowledge = build_knowledge_summary(store_id)
    except Exception:
        knowledge = ""
    if knowledge:
        max_chars = 4500
        if len(knowledge) > max_chars:
            knowledge = knowledge[:max_chars] + "\n… (مزيد من المنتجات — استخدم suggest_products للبحث)"
        return BASE_SYSTEM_PROMPT + f"\n\n══ كتالوج المتجر ══\n{knowledge}\n══ نهاية الكتالوج ══"
    return BASE_SYSTEM_PROMPT


# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS = [
    # ── Discovery ──────────────────────────────────────────────────────────
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
        "description": "احسب سعراً تقديرياً للطباعة بناءً على نوع المنتج والكمية.",
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
            # ── suggest_products ────────────────────────────────────────────
            if name == "suggest_products":
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

                items = [
                    {"product_id": item["product_id"], "quantity": item["quantity"]}
                    for item in cart
                ]
                notes = inputs.get("order_notes", "")

                # Build notes from cart items with specs
                specs = [
                    f"{item['name']}: {item['notes']}"
                    for item in cart if item.get("notes")
                ]
                if specs:
                    notes = (notes + "\n" if notes else "") + "مواصفات:\n" + "\n".join(specs)

                if self.salla:
                    try:
                        resp     = await self.salla.create_order(items, customer, notes)
                        order    = resp.get("data", {})
                        order_id = str(order.get("id", ""))
                        order_ref = order.get("reference_id", order_id)
                        pay_url  = (order.get("urls") or {}).get("customer", "")
                        amounts  = order.get("amounts", {})
                        total_str = (amounts.get("total") or {}).get("amount", f"{total:.2f}")
                        currency  = (amounts.get("total") or {}).get("currency", "SAR")

                        if pay_url:
                            cs.set_last_component(session_id, {
                                "type":      "checkout",
                                "url":       pay_url,
                                "total":     total_str,
                                "currency":  currency,
                                "order_ref": order_ref,
                            })
                            cs.cart_clear(session_id)
                            return (
                                f"✅ تم إنشاء الطلب رقم #{order_ref} بنجاح!\n"
                                f"الإجمالي: {total_str} {currency}\n"
                                f"رابط الدفع: {pay_url}"
                            )
                        else:
                            cs.cart_clear(session_id)
                            return f"✅ تم إنشاء الطلب رقم #{order_ref}. الإجمالي: {total:.2f} ريال"

                    except Exception as e:
                        # Fallback: show product links
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

            # ── calculate_print_quote ────────────────────────────────────────
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
        cs.add_message(session_id, "user", message, self.store_id)
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

        messages = [{"role": "system", "content": get_system_prompt(self.store_id)}] + history

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
            cs.add_message(session_id, "assistant", reply, self.store_id)
            return reply

    # ── OpenAI (GPT) ──────────────────────────────────────────────────────────
    async def _chat_openai(self, message: str, session_id: str) -> str:
        """
        OpenAI-compatible chat with tool use.
        Uses the same OpenAI function-calling format as Groq — the two APIs
        are fully wire-compatible so the implementation is nearly identical.
        """
        cs.add_message(session_id, "user", message, self.store_id)
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

        messages = [{"role": "system", "content": get_system_prompt(self.store_id)}] + history

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
            cs.add_message(session_id, "assistant", reply, self.store_id)
            return reply

    # ── Anthropic (Claude) ────────────────────────────────────────────────────
    async def _chat_anthropic(self, message: str, session_id: str) -> str:
        cs.add_message(session_id, "user", message, self.store_id)
        # get_groq_history returns [{role, content: str}] — valid for Anthropic too
        # (Anthropic accepts plain string content; tool-call turns are ephemeral
        #  per request and are NOT persisted to the conversation store)
        history = cs.get_groq_history(session_id)

        tool_rounds = 0
        while True:
            response = await self.ai.messages.create(
                model=self._anthropic_model,
                max_tokens=1024,
                system=get_system_prompt(self.store_id),
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

            cs.add_message(session_id, "assistant", reply, self.store_id)
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
