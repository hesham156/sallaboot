import os
import json
import anthropic
from groq import AsyncGroq
from salla_client import SallaClient
from store_sync import build_knowledge_summary, get_store_data

BASE_SYSTEM_PROMPT = """أنت مساعد ذكي لمتجر طباعة احترافي على منصة سلة. اسمك "مساعد المتجر".

خدمات المتجر تشمل:
- كروت شخصية وبزنس كارد
- بنرات وبوسترات ولافتات
- تيشيرتات وملابس مطبوعة
- فلايرات وكتالوجات وبروشورات
- أظرف وستيكرات ومواد تسويقية
- وجميع أنواع الطباعة الأخرى

قواعد مهمة:
1. تكلم دائماً بالعربية وبأسلوب ودي ومحترف
2. عند السؤال عن منتجات أو أسعار، استخدم الأدوات المتاحة لجلب البيانات الحقيقية
3. عند السؤال عن طلب، اطلب رقم الطلب ثم تتبعه بالأداة
4. إذا أراد العميل إرسال ملف تصميم، أخبره: "يمكنك إرفاق ملف التصميم مباشرة هنا في المحادثة"
5. للتسعير التقريبي، استخدم أداة حساب السعر
6. إذا احتاج العميل تدخل بشري أو كان الطلب معقداً، قل: "سأحيلك لفريق المبيعات، يرجى التواصل على واتساب أو البريد الإلكتروني"
7. لا تتكلم عن أي شيء خارج نطاق المتجر وخدمات الطباعة
8. عندك قاعدة بيانات كاملة لمنتجات المتجر، استخدمها للإجابة مباشرة دون الحاجة لاستدعاء أداة get_products في معظم الأحيان"""


def get_system_prompt() -> str:
    """Build dynamic system prompt with live store knowledge."""
    try:
        knowledge = build_knowledge_summary()
    except Exception:
        knowledge = ""
    if knowledge:
        # Keep total system prompt under ~6000 chars to stay within Groq free-tier TPM
        max_knowledge_chars = 5000
        if len(knowledge) > max_knowledge_chars:
            knowledge = knowledge[:max_knowledge_chars] + "\n… (المزيد من المنتجات متاحة، استخدم أداة get_products للبحث)"
        return BASE_SYSTEM_PROMPT + f"\n\n--- معلومات المتجر الحالية ---\n{knowledge}\n--- نهاية معلومات المتجر ---"
    return BASE_SYSTEM_PROMPT

TOOLS = [
    {
        "name": "get_products",
        "description": "جلب قائمة المنتجات والخدمات المتاحة في المتجر مع أسعارها. استخدمها عند سؤال العميل عن المنتجات أو الخدمات المتاحة.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "كلمة بحث لتصفية المنتجات (اختياري)",
                },
            },
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
    {
        "name": "track_order",
        "description": "تتبع حالة طلب بناءً على رقم الطلب أو رقم المرجع.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_reference": {
                    "type": "string",
                    "description": "رقم الطلب أو رقم المرجع الذي أعطاه العميل",
                },
            },
            "required": ["order_reference"],
        },
    },
    {
        "name": "calculate_print_quote",
        "description": "حساب سعر تقديري لطلبية طباعة بناءً على نوع المنتج والكمية والمواصفات.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_type": {
                    "type": "string",
                    "description": "نوع المنتج مثل: كروت، بنر، تيشيرت، فلاير، كتالوج",
                },
                "quantity": {"type": "integer", "description": "الكمية المطلوبة"},
                "size": {"type": "string", "description": "المقاس مثل: A4، A5، 9x5 سم (اختياري)"},
                "paper_type": {
                    "type": "string",
                    "description": "نوع الورق أو الخامة مثل: كوشيه، مطفي، فاخر (اختياري)",
                },
                "sides": {
                    "type": "string",
                    "enum": ["وجه واحد", "وجهين"],
                    "description": "الطباعة على وجه أو وجهين (اختياري)",
                },
            },
            "required": ["product_type", "quantity"],
        },
    },
]

# Approximate pricing table (SAR) — update to match actual pricing
PRICING = {
    "كروت": {"setup": 30, "unit": 0.35, "min_qty": 100},
    "بنر": {"setup": 0, "sqm": 30, "min_qty": 1},
    "تيشيرت": {"setup": 50, "unit": 20, "min_qty": 10},
    "فلاير": {"setup": 25, "unit": 0.25, "min_qty": 500},
    "كتالوج": {"setup": 60, "unit": 8, "min_qty": 50},
    "ستيكر": {"setup": 20, "unit": 0.15, "min_qty": 200},
    "بروشور": {"setup": 25, "unit": 0.4, "min_qty": 200},
    "لافتة": {"setup": 0, "sqm": 35, "min_qty": 1},
    "default": {"setup": 30, "unit": 0.5, "min_qty": 50},
}

ORDER_STATUS_AR = {
    "pending": "قيد الانتظار",
    "under_review": "قيد المراجعة",
    "processing": "جاري التجهيز",
    "in_shipping": "قيد الشحن",
    "completed": "مكتمل",
    "cancelled": "ملغي",
    "refunded": "مسترجع",
    "on_hold": "معلق",
}


class PrintingAgent:
    def __init__(self):
        groq_key = os.getenv("GROQ_API_KEY", "")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

        if groq_key:
            self.provider = "groq"
            self.groq_client = AsyncGroq(api_key=groq_key)
            self.ai = None
        elif anthropic_key:
            self.provider = "anthropic"
            self.ai = anthropic.Anthropic(api_key=anthropic_key)
            self.groq_client = None
        else:
            raise RuntimeError("يجب تعيين GROQ_API_KEY أو ANTHROPIC_API_KEY في متغيرات البيئة.")

        token = os.getenv("SALLA_ACCESS_TOKEN", "")
        self.salla = SallaClient(token) if token else None
        # session_id -> list of messages
        self.conversations: dict[str, list] = {}

    async def _run_tool(self, name: str, inputs: dict) -> str:
        try:
            if name == "get_products":
                keyword = inputs.get("keyword", "").strip().lower()
                # Try cached store data first (faster, no API call needed)
                store = get_store_data()
                cached_products = store.get("products", [])
                if cached_products:
                    if keyword:
                        filtered = [
                            p for p in cached_products
                            if keyword in p.get("name", "").lower()
                            or keyword in p.get("description", "").lower()
                            or any(keyword in c.lower() for c in p.get("categories", []))
                        ]
                    else:
                        filtered = cached_products
                    if filtered:
                        lines = []
                        for p in filtered[:15]:
                            price = p.get("price", "—")
                            currency = p.get("currency", "ريال")
                            cats = "، ".join(p.get("categories", []))
                            line = f"• {p.get('name', '')} — {price} {currency}"
                            if cats:
                                line += f" [{cats}]"
                            lines.append(line)
                        return "المنتجات المتاحة:\n" + "\n".join(lines)
                # Fall back to live API
                if not self.salla:
                    return "⚠️ لم يتم ربط المتجر بعد، يرجى التواصل مع الدعم."
                data = await self.salla.get_products(keyword=keyword or None)
                products = data.get("data", [])
                if not products:
                    return "لا توجد منتجات متاحة حالياً."
                lines = []
                for p in products[:12]:
                    name_ar = p.get("name", "منتج")
                    price = p.get("price", {})
                    amount = price.get("amount", "—")
                    currency = price.get("currency", "ريال")
                    pid = p.get("id", "")
                    lines.append(f"• {name_ar} — {amount} {currency}  (ID: {pid})")
                return "المنتجات المتاحة:\n" + "\n".join(lines)

            elif name == "get_product_details":
                if not self.salla:
                    return "⚠️ لم يتم ربط المتجر بعد."
                data = await self.salla.get_product(inputs["product_id"])
                p = data.get("data", {})
                if not p:
                    return "المنتج غير موجود."
                price = p.get("price", {})
                desc = p.get("description", "").strip() or "—"
                options = p.get("options", [])
                opts_text = ""
                if options:
                    opt_lines = [f"  - {o.get('name', '')}" for o in options[:5]]
                    opts_text = "\nالخيارات المتاحة:\n" + "\n".join(opt_lines)
                return (
                    f"**{p.get('name')}**\n"
                    f"السعر: {price.get('amount')} {price.get('currency', 'ريال')}\n"
                    f"الوصف: {desc}"
                    f"{opts_text}"
                )

            elif name == "track_order":
                if not self.salla:
                    return "⚠️ لم يتم ربط المتجر بعد."
                ref = inputs["order_reference"].strip()
                # Try by ID first, then by reference
                try:
                    data = await self.salla.get_order(ref)
                    order = data.get("data", {})
                except Exception:
                    data = await self.salla.search_orders_by_reference(ref)
                    orders = data.get("data", [])
                    order = orders[0] if orders else {}

                if not order:
                    return f"لم يتم إيجاد طلب برقم {ref}. تأكد من الرقم وحاول مرة أخرى."

                status_key = order.get("status", "")
                status_ar = ORDER_STATUS_AR.get(status_key, status_key)
                amounts = order.get("amounts", {})
                total = amounts.get("total", {}).get("amount", "—")
                currency = amounts.get("total", {}).get("currency", "ريال")
                date = order.get("date", {}).get("date", "—")
                return (
                    f"طلب رقم: {ref}\n"
                    f"الحالة: {status_ar}\n"
                    f"الإجمالي: {total} {currency}\n"
                    f"التاريخ: {date}"
                )

            elif name == "calculate_print_quote":
                ptype = inputs.get("product_type", "").strip()
                qty = int(inputs.get("quantity", 1))
                size = inputs.get("size", "")
                paper = inputs.get("paper_type", "")
                sides = inputs.get("sides", "وجه واحد")

                # Match product type to pricing key
                pricing = PRICING.get("default")
                for key in PRICING:
                    if key in ptype or ptype in key:
                        pricing = PRICING[key]
                        break

                min_qty = pricing["min_qty"]
                if qty < min_qty:
                    return (
                        f"الحد الأدنى للطلبية من {ptype} هو {min_qty} قطعة.\n"
                        f"يمكنك طلب {min_qty} قطعة أو أكثر."
                    )

                if "sqm" in pricing:
                    # area-based (banners/signs) — assume 1 sqm if no size
                    sqm = 1.0
                    if size:
                        try:
                            parts = size.replace("×", "x").split("x")
                            if len(parts) == 2:
                                sqm = float(parts[0]) * float(parts[1]) / 10000
                        except Exception:
                            pass
                    total = pricing["sqm"] * max(sqm, 1) * qty
                else:
                    total = pricing["setup"] + pricing["unit"] * qty

                # surcharge for double-sided
                if sides == "وجهين":
                    total *= 1.4

                details = []
                if size:
                    details.append(f"المقاس: {size}")
                if paper:
                    details.append(f"الخامة: {paper}")
                if sides:
                    details.append(f"الطباعة: {sides}")

                extra = ("  |  ".join(details) + "\n") if details else ""
                return (
                    f"**تقدير سعر {ptype}**\n"
                    f"الكمية: {qty:,} قطعة\n"
                    f"{extra}"
                    f"السعر التقريبي: **{total:,.2f} ريال**\n\n"
                    "⚠️ هذا تقدير مبدئي. للحصول على عرض سعر دقيق يرجى إرسال مواصفات التصميم."
                )

        except Exception as e:
            return f"حدث خطأ أثناء معالجة طلبك: {str(e)}"

        return "العملية غير معروفة."

    async def chat(self, message: str, session_id: str) -> str:
        if self.provider == "groq":
            return await self._chat_groq(message, session_id)
        return await self._chat_anthropic(message, session_id)

    # ── Groq (Llama 3) ────────────────────────────────────────────────────────────
    async def _chat_groq(self, message: str, session_id: str) -> str:
        history = self.conversations.setdefault(session_id, [])
        history.append({"role": "user", "content": message})

        # Convert TOOLS to Groq format (OpenAI-compatible)
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

        messages = [{"role": "system", "content": get_system_prompt()}] + [
            {"role": m["role"], "content": m["content"] if isinstance(m["content"], str) else str(m["content"])}
            for m in history
        ]

        tool_rounds = 0
        while True:
            response = await self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=groq_tools,
                tool_choice="auto",
                max_tokens=1024,
            )

            msg = response.choices[0].message

            if msg.tool_calls and tool_rounds < 3:
                tool_rounds += 1
                messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]})
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {}
                    result = await self._run_tool(tc.function.name, args)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
                continue

            reply = msg.content or "عذراً، لم أستطع معالجة طلبك."
            history.append({"role": "assistant", "content": reply})
            if len(history) > 30:
                self.conversations[session_id] = history[-30:]
            return reply

    # ── Anthropic (Claude) ────────────────────────────────────────────────────────
    async def _chat_anthropic(self, message: str, session_id: str) -> str:
        history = self.conversations.setdefault(session_id, [])
        history.append({"role": "user", "content": message})

        while True:
            response = self.ai.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=get_system_prompt(),
                tools=TOOLS,
                messages=history,
            )

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = await self._run_tool(block.name, block.input)
                        tool_results.append(
                            {"type": "tool_result", "tool_use_id": block.id, "content": result}
                        )
                history.append({"role": "assistant", "content": response.content})
                history.append({"role": "user", "content": tool_results})
                continue

            reply = "".join(b.text for b in response.content if hasattr(b, "text"))
            history.append({"role": "assistant", "content": response.content})
            if len(history) > 30:
                self.conversations[session_id] = history[-30:]
            return reply
