"""
customer_followup.py
─────────────────────────────────────────────────────────────────────────────
Customer segmentation and WhatsApp follow-up automation.

Segments:
  new       — first contact, no purchase, no price inquiry
  inquiry   — asked about products/prices but didn't buy
  hesitant  — showed purchase intent (price, specs, payment) but no order
  buyer     — has at least one Salla order
  loyal     — 2+ orders
  inactive  — no activity for >30 days

Follow-up config stored in ai_config under key "followup_config":
{
  "enabled": true,
  "segments": {
    "hesitant": {"enabled": true, "delay_hours": 48, "max_followups": 2,
                 "template": "hesitant_followup", "message": "...fallback text..."},
    "inquiry":  {"enabled": true, "delay_hours": 24, "max_followups": 1, ...},
    "buyer":    {"enabled": true, "delay_hours": 168, "max_followups": 1, ...},
    "inactive": {"enabled": false, "delay_hours": 720, "max_followups": 1, ...}
  }
}
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import database as db
import store_manager as sm
import whatsapp as wa
from log import get_logger

log = get_logger(__name__)

# ── Keyword patterns for rule-based classification ───────────────────────────

_PURCHASE_INTENT = re.compile(
    r"(سعر|كم\s*السعر|بكم|تكلفة|عرض\s*سعر|كمية|كميات|موصفات|مواصفات|"
    r"نوع\s*ورق|مقاس|تصميم|هل\s*يتوفر|متى|التوصيل|الشحن|الدفع|اشتري|"
    r"طلب\s*جديد|ابغى\s*اطلب|عايز\s*اطلب|ابي\s*اطلب)",
    re.IGNORECASE,
)

_GENERAL_INQUIRY = re.compile(
    r"(مرحبا|هلا|السلام|أهلاً|أهلا|كيف|ما\s*هو|وش\s*هو|ايش|ما\s*هي|"
    r"تعريف|معلومات|انواع|خدماتكم|منتجاتكم)",
    re.IGNORECASE,
)


def _classify_from_messages(messages: list[str]) -> str:
    """
    Rule-based classifier from a list of customer messages.
    Returns: 'hesitant' | 'inquiry' | 'new'
    """
    combined = " ".join(messages)
    if _PURCHASE_INTENT.search(combined):
        return "hesitant"
    if _GENERAL_INQUIRY.search(combined):
        return "inquiry"
    return "new"


def _get_followup_config(store_id: str) -> dict:
    """Return the store's follow-up config with sensible defaults."""
    cfg = sm.get_ai_config(store_id) or {}
    raw = cfg.get("followup_config") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}

    defaults = {
        "enabled": False,
        "segments": {
            "hesitant": {
                "enabled": True,
                "delay_hours": 48,
                "max_followups": 2,
                "template": "",
                "message": "مرحباً {name} 👋\nلاحظنا اهتمامك بمنتجاتنا ولم تكمل طلبك.\nهل تحتاج مساعدة أو معلومات إضافية؟",
            },
            "inquiry": {
                "enabled": True,
                "delay_hours": 24,
                "max_followups": 1,
                "template": "",
                "message": "مرحباً {name} 👋\nشكراً لتواصلك معنا! هل لديك أي استفسار إضافي؟",
            },
            "buyer": {
                "enabled": True,
                "delay_hours": 168,
                "max_followups": 1,
                "template": "",
                "message": "مرحباً {name} ❤️\nشكراً لثقتك بنا! كيف وجدت طلبك؟ يسعدنا خدمتك مجدداً.",
            },
            "inactive": {
                "enabled": False,
                "delay_hours": 720,
                "max_followups": 1,
                "template": "",
                "message": "مرحباً {name} 🌟\nاشتقنا إليك! عندنا عروض جديدة تستحق اهتمامك.",
            },
        },
    }
    # Deep-merge: keep defaults for missing keys
    merged = {**defaults, **raw}
    for seg, seg_def in defaults["segments"].items():
        merged["segments"][seg] = {**seg_def, **raw.get("segments", {}).get(seg, {})}
    return merged


def _save_followup_config(store_id: str, config: dict) -> None:
    cfg = sm.get_ai_config(store_id) or {}
    cfg["followup_config"] = config
    sm.update_ai_config(store_id, cfg)
    if db.available():
        db.fire(db.save_store(store_id, sm.get_store_info(store_id) or {}))


# ── Classify a customer from their conversation + Salla orders ────────────────

async def classify_customer(
    store_id: str,
    customer_id: str,
    customer_name: str = "",
    phone: str = "",
    email: str = "",
    order_count: int = 0,
    last_order_id: Optional[str] = None,
    last_order_at: Optional[datetime] = None,
    conv_messages: Optional[list[str]] = None,
    last_conv_id: Optional[str] = None,
    last_conv_at: Optional[datetime] = None,
) -> dict:
    """
    Classify a customer and upsert into customer_segments.
    Returns the saved segment row.
    """
    # Determine segment
    if order_count >= 2:
        segment = "loyal"
        reason  = f"لديه {order_count} طلبات"
    elif order_count == 1:
        segment = "buyer"
        reason  = "أتم طلباً واحداً"
    else:
        # No orders — classify from conversation
        msgs = conv_messages or []
        segment = _classify_from_messages(msgs)
        reason_map = {
            "hesitant": "أبدى اهتماماً بالشراء ولم يُكمل",
            "inquiry":  "استفسر عن المنتجات دون نية شراء واضحة",
            "new":      "تواصل جديد",
        }
        reason = reason_map.get(segment, "")

    # Compute next follow-up time
    cfg = _get_followup_config(store_id)
    next_followup = None
    if cfg.get("enabled") and segment in cfg["segments"]:
        seg_cfg = cfg["segments"][segment]
        if seg_cfg.get("enabled"):
            delay_h = seg_cfg.get("delay_hours", 24)
            next_followup = datetime.now(timezone.utc) + timedelta(hours=delay_h)

    data = {
        "customer_name":    customer_name,
        "phone":            phone,
        "email":            email,
        "segment":          segment,
        "segment_reason":   reason,
        "last_order_id":    last_order_id,
        "last_order_at":    last_order_at,
        "last_conv_id":     last_conv_id,
        "last_conv_at":     last_conv_at,
        "next_followup_at": next_followup,
    }
    row = await db.seg_upsert(store_id, customer_id, data)
    return row or data


async def classify_from_conversation(store_id: str, session_id: str,
                                     conv_data: dict) -> None:
    """
    Called after a conversation ends or is updated. Extracts customer info
    from the session data and classifies them.
    """
    try:
        customer_id = (
            str(conv_data.get("salla_customer_id") or "")
            or str(conv_data.get("customer_id") or "")
            or f"phone:{conv_data.get('customer_phone', '')}"
        )
        if not customer_id or customer_id == "phone:":
            return

        # customer_info is a nested dict inside the conversation data
        cust_info = conv_data.get("customer_info") or {}
        if isinstance(cust_info, str):
            try:
                import json as _json
                cust_info = _json.loads(cust_info)
            except Exception:
                cust_info = {}

        phone = str(
            cust_info.get("phone") or
            conv_data.get("customer_phone") or
            conv_data.get("wa_sender") or ""
        ).strip()
        name  = str(cust_info.get("name") or conv_data.get("customer_name") or "").strip()
        email = str(cust_info.get("email") or conv_data.get("customer_email") or "").strip()

        # Extract customer messages from the messages array
        messages_raw = conv_data.get("messages") or []
        customer_msgs = []
        for m in messages_raw:
            if isinstance(m, dict) and m.get("role") in ("user", "customer"):
                customer_msgs.append(str(m.get("content") or m.get("text") or ""))

        # Check Salla order history
        order_count   = int(conv_data.get("order_count") or 0)
        last_order_id = str(conv_data.get("last_order_id") or "") or None
        last_order_at = None
        if conv_data.get("last_order_at"):
            try:
                last_order_at = datetime.fromisoformat(str(conv_data["last_order_at"]))
            except Exception:
                pass

        await classify_customer(
            store_id      = store_id,
            customer_id   = customer_id,
            customer_name = name,
            phone         = phone,
            email         = email,
            order_count   = order_count,
            last_order_id = last_order_id,
            last_order_at = last_order_at,
            conv_messages = customer_msgs,
            last_conv_id  = session_id,
            last_conv_at  = datetime.now(timezone.utc),
        )
    except Exception as exc:
        log.error("followup_classify_error", extra={"error": str(exc)})


# ── Follow-up sender ──────────────────────────────────────────────────────────

async def send_followup(store_id: str, customer: dict) -> bool:
    """Send a follow-up WhatsApp message to one customer. Returns True on success."""
    try:
        wa_cfg    = sm.get_ai_config(store_id) or {}
        token     = (wa_cfg.get("whatsapp_token")    or "").strip()
        phone_id  = (wa_cfg.get("whatsapp_phone_id") or "").strip()
        enabled   = bool(wa_cfg.get("whatsapp_enabled"))

        if not (enabled and token and phone_id):
            return False

        phone = (customer.get("phone") or "").strip()
        if not phone:
            return False

        segment  = customer.get("segment", "new")
        cfg      = _get_followup_config(store_id)
        seg_cfg  = cfg.get("segments", {}).get(segment, {})

        if not seg_cfg.get("enabled"):
            return False

        max_fu   = seg_cfg.get("max_followups", 1)
        count    = customer.get("followup_count", 0)
        if count >= max_fu:
            # Pause — reached max
            await db.seg_pause(store_id, customer["customer_id"], True)
            return False

        name = (customer.get("customer_name") or "العميل").strip()

        # Try template first, fall back to plain text
        template_name = (seg_cfg.get("template") or "").strip()
        ok = False
        if template_name:
            ok = await wa.send_template(
                token=token, phone_id=phone_id, to=phone,
                template_name=template_name, language="ar",
                body_params=[name],
            )

        if not ok:
            message = (seg_cfg.get("message") or "").replace("{name}", name)
            if message:
                ok = await wa.send_text(token, phone_id, phone, message)

        if ok:
            # Schedule next follow-up (only if max not reached)
            delay_h = seg_cfg.get("delay_hours", 24)
            new_count = count + 1
            next_fu = None
            if new_count < max_fu:
                next_fu = datetime.now(timezone.utc) + timedelta(hours=delay_h)

            await db.seg_mark_followup_sent(
                store_id, customer["customer_id"], next_fu
            )
            log.info("followup_sent", extra={"phone": phone, "segment": segment, "store_id": store_id})

        return ok
    except Exception as exc:
        log.error("followup_send_error", extra={"error": str(exc)})
        return False


async def run_followup_pass() -> int:
    """
    Called by the lifecycle scheduler. Processes all due follow-ups across
    all stores. Returns the number of messages sent.
    """
    due = await db.seg_get_all_stores_due()
    if not due:
        return 0

    sent = 0
    for customer in due:
        store_id = customer.get("store_id", "")
        if not store_id:
            continue
        cfg = _get_followup_config(store_id)
        if not cfg.get("enabled"):
            continue
        ok = await send_followup(store_id, customer)
        if ok:
            sent += 1
    return sent


# ── Scan existing conversations to build initial segments ─────────────────────

async def scan_store_conversations(store_id: str, limit: int = 500) -> int:
    """
    One-time (or periodic) scan of a store's conversations to build/refresh
    the customer_segments table. Returns the number of rows upserted.
    """
    if not db.available():
        return 0
    try:
        pool = db._pool
        if not pool:
            return 0
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT session_id, data, updated_at
                FROM conversations
                WHERE store_id = $1
                  AND (
                    (data->>'salla_customer_id' IS NOT NULL AND data->>'salla_customer_id' <> '')
                    OR (data->'customer_info'->>'phone' IS NOT NULL AND data->'customer_info'->>'phone' <> '')
                    OR (data->>'wa_sender' IS NOT NULL AND data->>'wa_sender' <> '')
                  )
                ORDER BY updated_at DESC
                LIMIT $2
            """, store_id, limit)

        upserted = 0
        for row in rows:
            conv_data = dict(row["data"]) if row["data"] else {}
            conv_data["last_order_at"] = conv_data.get("last_order_at")
            await classify_from_conversation(store_id, row["session_id"], conv_data)
            upserted += 1
        return upserted
    except Exception as exc:
        log.error("followup_scan_error", extra={"error": str(exc)})
        return 0
