"""Shared webhook infrastructure: the APIRouter, audit logging, and the
cross-channel helpers (phone/name extraction, WhatsApp sends, abandoned-cart
recording, CSAT parsing) reused by the Salla, Meta, Telegram, Shopify and Zid
modules. Split out of the original single-file routers/webhooks.py."""
from __future__ import annotations
import asyncio
import datetime as _dt
import secrets as _secrets
from fastapi import APIRouter
import database as db
import notifications as _notif
import store_manager as sm
import log as _logmod

log = _logmod.get_logger("backend.webhooks")


router = APIRouter()


# Store IDs that are reserved and must never be used as real Salla
# merchant IDs (kept in sync with main._RESERVED_IDS). The marketing
# demo store ("sallabot") is also reserved — see bootstrap.py.
_RESERVED_IDS = {"super", "admin", "stores", "auth", "default", "sallabot"}


# ─────────────────────────────────────────────────────────────────────────
# Helpers — signature verification + audit logging
# ─────────────────────────────────────────────────────────────────────────

def _log_event(store_id: str, event: str, status: str, detail: str = "",
                sig_status: str = "", body_head: str = "",
                content_type: str = "", user_agent: str = ""):
    """
    Fire-and-forget webhook log row. Writes to webhook_log table so the
    full audit trail survives every Railway redeploy. Errors are logged
    by the db.fire callback (no silent loss).
    """
    db.fire(db.log_webhook(
        store_id=store_id, event=event, status=status, detail=detail,
        sig_status=sig_status, body_head=body_head,
        content_type=content_type, user_agent=user_agent,
    ))


# ── WhatsApp shared helpers ───────────────────────────────────────────────────

def _extract_phone(data: dict) -> str:
    """
    Extract a dialable phone number from a Salla customer/order dict.
    Salla sends mobile_code (+966) + mobile (5xxxxxxxx) separately.
    Falls back to phone / mobile fields as-is.
    """
    if not data:
        return ""
    mobile_code = str(data.get("mobile_code") or "").strip().lstrip("+")
    mobile      = str(data.get("mobile")      or "").strip()
    if mobile_code and mobile:
        return f"+{mobile_code}{mobile}"
    phone = str(data.get("phone") or data.get("mobile") or "").strip()
    # Normalize Saudi numbers without country code
    if phone.startswith("05") and len(phone) == 10:
        phone = "+966" + phone[1:]
    return phone


def _extract_name(data: dict) -> str:
    first = (data.get("first_name") or "").strip()
    last  = (data.get("last_name")  or "").strip()
    return (first + " " + last).strip()


async def _wa_send(store_id: str, cfg: dict, phone: str, text: str) -> None:
    """Send a WhatsApp text if the store has WhatsApp configured."""
    if not phone:
        return
    token    = (cfg.get("whatsapp_token")    or "").strip()
    phone_id = (cfg.get("whatsapp_phone_id") or "").strip()
    enabled  = bool(cfg.get("whatsapp_enabled"))
    if not (token and phone_id and enabled):
        return
    import whatsapp as wa
    try:
        await wa.send_text(token, phone_id, phone, text)
        print(f"[webhook] WhatsApp sent to {phone} for store {store_id!r}")
    except Exception as exc:
        print(f"[webhook] WhatsApp send failed for {phone}: {exc}")


async def _recovery_coupon_line(store_id: str, cfg: dict) -> str:
    """
    Issue a one-use, 24h recovery coupon for an abandoned cart (only when the
    merchant opted into AI coupons) and return a WhatsApp-ready line. Best-effort:
    returns "" on any failure so the reminder still goes out without a coupon.

    Caps mirror agent._issue_coupon so the cart channel can't hand out a bigger
    discount than the in-chat one. Requires the coupons.read_write scope.
    """
    if not cfg.get("coupons_enabled"):
        return ""
    token = sm.get_access_token(store_id)
    if not token:
        return ""
    try:
        pct       = max(1, min(int(cfg.get("coupon_max_percent", 15) or 15), 90))
        cap       = float(cfg.get("coupon_max_discount_value", 200) or 200)
        min_order = float(cfg.get("coupon_min_order", 0) or 0)
    except (TypeError, ValueError):
        pct, cap, min_order = 15, 200.0, 0.0

    expiry_dt = (_dt.datetime.utcnow() + _dt.timedelta(days=1)).replace(
        hour=23, minute=59, second=59, microsecond=0)
    code = "CART" + _secrets.token_hex(3).upper()
    try:
        from salla_client import SallaClient
        client = SallaClient(token, store_id=store_id)
        await client.create_coupon(
            code=code, amount=pct, coupon_type="percentage",
            expiry_date=expiry_dt.strftime("%Y-%m-%d %H:%M:%S"),
            maximum_amount=cap, minimum_amount=(min_order or None),
            usage_limit=1, usage_limit_per_user=1,
        )
    except Exception as exc:
        print(f"[cart-coupon] failed store={store_id!r}: {exc}")
        return ""

    line = f"هدية خاصة لإتمام طلبك: استخدم كود *{code}* لخصم {pct}٪"
    if min_order:
        line += f" (للطلبات من {int(min_order)} ريال فأكثر)"
    line += " — صالح ٢٤ ساعة فقط ⏳"
    return line


async def record_abandoned_cart(store_id: str, notification: dict, *, phone: str = "") -> bool:
    """
    Persist an abandoned cart and — ONLY when it's newly seen — email the owner
    and WhatsApp the customer a recovery reminder. Shared by every platform
    (Salla webhook, Shopify poller, …) so the dashboard + notifications behave
    identically. Returns True if the cart was newly recorded.

    The newly-seen gate (db.save_abandoned_cart returns False on conflict) is
    what makes the Shopify poller safe to run every few minutes without
    re-spamming the same customer.
    """
    cart_id = str(notification.get("id", ""))
    if not cart_id:
        return False
    if not await db.save_abandoned_cart(store_id, cart_id, notification):
        return False  # already recorded — don't double-notify

    total_str = f"{notification.get('total', '—')} {notification.get('currency', 'SAR')}"
    _log_event(store_id, "abandoned.cart", "ok",
               f"cart_id={cart_id}  customer={notification.get('customer_name', '—')}  total={total_str}")
    print(f"[abandoned_cart] 🛒 {cart_id!r} — {notification.get('customer_name', '—')} — "
          f"{total_str} — store={store_id!r}")

    asyncio.create_task(_notif.notify(store_id, "abandoned_cart", {
        "customer_name": notification.get("customer_name", "—"),
        "cart_total":    total_str,
    }))

    # WhatsApp recovery reminder to the customer
    if phone and phone != "—":
        cfg        = sm.get_ai_config(store_id) or {}
        store_info = sm.get_store_info(store_id) or {}
        store_name = store_info.get("store_name", "متجرنا")
        name       = (notification.get("customer_name") or "").strip() or "عزيزي العميل"
        checkout   = notification.get("checkout_url", "")

        msg = (
            f"مرحباً {name} 👋\n"
            f"لاحظنا أنك تركت سلة التسوق في {store_name} بدون إتمام الطلب.\n\n"
            f"إجمالي سلتك: *{total_str}*\n"
        )
        coupon_line = await _recovery_coupon_line(store_id, cfg)
        if coupon_line:
            msg += f"\n🎁 {coupon_line}\n"
        if checkout:
            msg += f"\nأكمل طلبك الآن: {checkout}"
        msg += "\n\nنحن هنا لمساعدتك إذا كان لديك أي استفسار 😊"
        asyncio.create_task(_wa_send(store_id, cfg, phone, msg))

    return True


def shopify_checkout_to_notification(checkout: dict) -> tuple:
    """
    Map a Shopify abandoned checkout → the shared abandoned-cart notification
    shape. Returns (notification, phone). Used by the Shopify poller.
    """
    customer = checkout.get("customer") or {}
    name = (
        _extract_name(customer)
        or (checkout.get("billing_address") or {}).get("name", "")
        or "—"
    )
    phone = _normalize_phone(
        checkout.get("phone")
        or customer.get("phone")
        or (checkout.get("billing_address") or {}).get("phone")
        or (checkout.get("shipping_address") or {}).get("phone")
        or ""
    )
    notification = {
        "id":             str(checkout.get("id") or checkout.get("token") or ""),
        "ts":             checkout.get("updated_at") or checkout.get("created_at")
                          or (_dt.datetime.utcnow().isoformat() + "Z"),
        "customer_name":  name,
        "customer_phone": phone or "—",
        "customer_email": checkout.get("email") or customer.get("email") or "—",
        "total":          str(checkout.get("total_price") or "—"),
        "currency":       checkout.get("currency") or checkout.get("presentment_currency") or "SAR",
        "items_count":    len(checkout.get("line_items") or []),
        "age_minutes":    0,
        "checkout_url":   checkout.get("abandoned_checkout_url", ""),
        "status":         "active",
        "recovered":      False,
    }
    return notification, phone


def zid_cart_to_notification(cart: dict) -> tuple:
    """
    Map a Zid abandoned cart (list endpoint shape) → the shared abandoned-cart
    notification shape. Returns (notification, phone). Used by the Zid poller.
    """
    phone = _normalize_phone(cart.get("customer_mobile") or "")
    notification = {
        "id":             str(cart.get("id") or ""),
        "ts":             cart.get("updated_at") or (_dt.datetime.utcnow().isoformat() + "Z"),
        "customer_name":  (cart.get("customer_name") or "").strip() or "—",
        "customer_phone": phone or "—",
        "customer_email": cart.get("customer_email") or "—",
        "total":          str(cart.get("cart_total") if cart.get("cart_total") is not None
                              else (cart.get("cart_total_string") or "—")),
        "currency":       cart.get("currency_code") or "SAR",
        "items_count":    int(cart.get("products_count") or 0),
        "age_minutes":    0,
        "checkout_url":   cart.get("url", ""),
        "status":         "active",
        "recovered":      False,
    }
    return notification, phone


# ─────────────────────────────────────────────────────────────────────────
# Phone normalisation shared by Shopify + Zid handlers
# ─────────────────────────────────────────────────────────────────────────

def _normalize_phone(raw: str) -> str:
    """
    Best-effort E.164 normaliser for Shopify/Zid customer phones.
    Salla sends mobile_code+mobile separately (handled by _extract_phone);
    Shopify/Zid send a single string that's usually already E.164 but may
    be a bare Saudi number.
    """
    p = (raw or "").strip().replace(" ", "").replace("-", "")
    if not p:
        return ""
    if p.startswith("+"):
        return p
    if p.startswith("00"):
        return "+" + p[2:]
    if p.startswith("966"):
        return "+" + p
    if p.startswith("05") and len(p) == 10:
        return "+966" + p[1:]
    if p.startswith("5") and len(p) == 9:
        return "+966" + p
    return p


# ─────────────────────────────────────────────────────────────────────────
# WhatsApp message handler (called by the inbox drainer)
# ─────────────────────────────────────────────────────────────────────────

def _parse_csat_reply(interactive_id: str, text: str) -> int:
    """
    Decode a WhatsApp CSAT reply to its 1-5 rating, or 0 if it doesn't
    look like one. Accepts:
      • interactive list reply id "csat:N"
      • the literal Arabic label ("راضٍ تماماً" → 5, …)
      • a plain number 1-5
    """
    if interactive_id and interactive_id.startswith("csat:"):
        try:
            n = int(interactive_id.split(":", 1)[1])
            return n if 1 <= n <= 5 else 0
        except (ValueError, IndexError):
            return 0
    t = (text or "").strip()
    if not t:
        return 0
    if t.isdigit():
        n = int(t)
        return n if 1 <= n <= 5 else 0
    label_map = {
        "راضٍ تماماً":     5, "راض تماما":      5, "راضٍ تماما":  5,
        "راضٍ":            4, "راض":           4,
        "محايد":          3,
        "غير راضٍ":        2, "غير راض":       2,
        "غير راضٍ تماماً": 1, "غير راض تماما": 1, "غير راضٍ تماما": 1,
    }
    for k, v in label_map.items():
        if k in t:
            return v
    return 0
