"""
notifications.py — Email & Webhook notifications for store owners.

Channels supported:
  • Email via Resend API (https://resend.com) — no extra Python package needed,
    uses httpx which is already in requirements.txt.
  • Webhook POST to a custom URL (e.g. Slack incoming webhook, Zapier, etc.)

Notification triggers:
  • new_conversation  — a customer just started chatting
  • abandoned_cart    — a cart was abandoned (from Salla webhook)
  • low_rating        — customer rated the bot ≤ 2 stars

Per-store config lives in ai_config['notifications']:
  {
    "email_enabled":       true,
    "email_address":       "owner@store.com",
    "webhook_url":         "https://hooks.slack.com/...",   # optional
    "on_new_conversation": true,
    "on_abandoned_cart":   true,
    "on_low_rating":       true,
    "quiet_hours_start":   22,    # int 0-23, optional
    "quiet_hours_end":     8,
  }

Usage:
  import notifications as notif
  await notif.notify(store_id, "new_conversation", ctx)
"""
from __future__ import annotations
import os
import asyncio
import datetime as dt
import httpx
import store_manager as sm
import database as db

# ── Resend sender ──────────────────────────────────────────────────────────────
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL     = os.getenv("NOTIFY_FROM_EMAIL", "نظام حياك <noreply@sallabot.app>")
BASE_URL       = os.getenv("BASE_URL", "https://sallabot.app")


# ── Email templates ────────────────────────────────────────────────────────────

def _html_wrapper(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',Tahoma,Arial,sans-serif;background:#f1f5f9;
       direction:rtl;color:#1e293b;padding:32px 16px}}
  .wrap{{max-width:580px;margin:0 auto}}
  .card{{background:#fff;border-radius:16px;overflow:hidden;
         box-shadow:0 2px 16px rgba(0,0,0,.08)}}
  .header{{background:linear-gradient(135deg,#0d9488,#06b6d4);
           padding:28px 32px;color:#fff}}
  .header h1{{font-size:20px;font-weight:800;margin-bottom:4px}}
  .header p{{font-size:13px;opacity:.85}}
  .body{{padding:28px 32px}}
  .body p{{font-size:15px;line-height:1.7;color:#334155;margin-bottom:12px}}
  .meta{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
         padding:14px 18px;margin:16px 0;font-size:13px;color:#475569}}
  .meta b{{color:#1e293b}}
  .btn{{display:inline-block;background:linear-gradient(135deg,#0d9488,#06b6d4);
        color:#fff;text-decoration:none;border-radius:10px;padding:12px 24px;
        font-weight:700;font-size:14px;margin-top:8px}}
  .footer{{padding:20px 32px;font-size:12px;color:#94a3b8;border-top:1px solid #f1f5f9}}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="header">
      <h1>💬 حياك</h1>
      <p>{title}</p>
    </div>
    <div class="body">
      {body}
    </div>
    <div class="footer">
      رسالة تلقائية من حياك — لإيقاف الإشعارات افتح لوحة التحكم ← الإعدادات ← الإشعارات
    </div>
  </div>
</div>
</body>
</html>"""


def _template_new_conversation(store_name: str, customer_name: str,
                                session_id: str, store_id: str,
                                first_msg: str = "") -> tuple[str, str]:
    subject = f"🔔 محادثة جديدة في {store_name}"
    body = f"""
<p>مرحباً،</p>
<p>بدأ عميل محادثة جديدة مع بوت متجرك <b>{store_name}</b>.</p>
<div class="meta">
  <div><b>العميل:</b> {customer_name or "زائر"}</div>
  {"<div><b>أول رسالة:</b> " + first_msg[:120] + "</div>" if first_msg else ""}
</div>
<p>يمكنك مشاهدة المحادثة والرد عليها من لوحة التحكم:</p>
<a class="btn" href="{BASE_URL}/store/{store_id}/conversations">فتح المحادثات ←</a>
"""
    return subject, _html_wrapper(f"محادثة جديدة من {customer_name or 'زائر'}", body)


def _template_abandoned_cart(store_name: str, customer_name: str,
                              cart_total: str, store_id: str) -> tuple[str, str]:
    subject = f"🛒 سلة متروكة في {store_name} — {cart_total}"
    body = f"""
<p>مرحباً،</p>
<p>ترك أحد العملاء سلة في متجرك <b>{store_name}</b> دون إتمام الطلب.</p>
<div class="meta">
  <div><b>العميل:</b> {customer_name or "زائر"}</div>
  <div><b>إجمالي السلة:</b> {cart_total}</div>
</div>
<p>يمكنك تتبع السلات المتروكة وإرسال تذكير للعميل:</p>
<a class="btn" href="{BASE_URL}/store/{store_id}/carts">فتح السلات المتروكة ←</a>
"""
    return subject, _html_wrapper("سلة متروكة — فرصة بيع!", body)


def _template_low_rating(store_name: str, customer_name: str,
                          rating: int, comment: str, store_id: str) -> tuple[str, str]:
    stars = "⭐" * rating + "☆" * (5 - rating)
    subject = f"⚠️ تقييم منخفض في {store_name} — {stars}"
    body = f"""
<p>مرحباً،</p>
<p>حصل البوت على تقييم منخفض من أحد العملاء في متجرك <b>{store_name}</b>.</p>
<div class="meta">
  <div><b>العميل:</b> {customer_name or "زائر"}</div>
  <div><b>التقييم:</b> {stars} ({rating}/5)</div>
  {"<div><b>التعليق:</b> " + comment + "</div>" if comment else ""}
</div>
<p>راجع المحادثة لمعرفة ما يمكن تحسينه:</p>
<a class="btn" href="{BASE_URL}/store/{store_id}/conversations">مراجعة المحادثات ←</a>
"""
    return subject, _html_wrapper("تقييم منخفض — يحتاج مراجعة", body)


def _template_llm_budget_warning(store_name: str, store_id: str,
                                   threshold: int, used_today: int,
                                   daily_budget: int, percent_used: float) -> tuple[str, str]:
    """
    Heads-up that the daily LLM token budget is being consumed quickly.
    Three escalating tones: 80% (yellow heads-up), 90% (orange warning),
    100% (red — bot is now refusing).
    """
    if threshold >= 100:
        emoji, headline, cta = "🛑", "حد الاستهلاك اليومي اكتمل", (
            "البوت الآن لا يردّ تلقائياً على العملاء حتى منتصف الليل بتوقيت UTC. "
            "ارفع الحد لو احتجت تشغيله فوراً، أو انتظر إعادة التعيين."
        )
    elif threshold >= 90:
        emoji, headline, cta = "🟠", "اقتربت من حد الاستهلاك اليومي", (
            "تبقّى أقل من 10% من ميزانية اليوم. لو الحركة عالية، اعتبر رفع الحد قبل الوصول للسقف."
        )
    else:
        emoji, headline, cta = "🟡", "تنبيه استهلاك ذكاء اصطناعي", (
            "استهلكت 80% من ميزانية اليوم. تابع المعدل من لوحة التحكم."
        )

    subject = f"{emoji} {store_name} — استخدام البوت تجاوز {threshold}%"
    body = f"""
<p>مرحباً،</p>
<p>{headline} في متجر <b>{store_name}</b>.</p>
<div class="meta">
  <div><b>الاستخدام اليوم:</b> {used_today:,} توكن</div>
  <div><b>الحد اليومي:</b> {daily_budget:,} توكن</div>
  <div><b>النسبة:</b> {percent_used}%</div>
</div>
<p>{cta}</p>
<a class="btn" href="{BASE_URL}/store/{store_id}/llm-usage">إدارة الاستهلاك ←</a>
"""
    return subject, _html_wrapper(f"تنبيه استهلاك — تجاوز {threshold}%", body)


# ── Send helpers ───────────────────────────────────────────────────────────────

async def _send_email(to: str, subject: str, html: str) -> bool:
    """Send email via Resend API. Returns True on success."""
    if not RESEND_API_KEY or not to:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={"from": FROM_EMAIL, "to": [to], "subject": subject, "html": html},
            )
        if r.status_code in (200, 201):
            return True
        print(f"[notifications] Resend error {r.status_code}: {r.text[:200]}")
        return False
    except Exception as exc:
        print(f"[notifications] Email send failed: {exc}")
        return False


async def _send_webhook(url: str, payload: dict) -> bool:
    """POST a JSON payload to a custom webhook URL (Slack, Zapier, etc.)."""
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
        return r.status_code < 400
    except Exception as exc:
        print(f"[notifications] Webhook POST failed: {exc}")
        return False


def _in_quiet_hours(start: int, end: int) -> bool:
    """Return True if current UTC hour falls in the quiet window."""
    h = dt.datetime.utcnow().hour
    if start < end:
        return start <= h < end
    return h >= start or h < end   # crosses midnight


# ── Public API ─────────────────────────────────────────────────────────────────

def get_settings(store_id: str) -> dict:
    """Return notification settings for a store (with defaults)."""
    cfg = sm.get_ai_config(store_id)
    n   = cfg.get("notifications") or {}
    return {
        "email_enabled":        bool(n.get("email_enabled", False)),
        "email_address":        n.get("email_address", "") or "",
        "webhook_url":          n.get("webhook_url",   "") or "",
        "on_new_conversation":  bool(n.get("on_new_conversation", True)),
        "on_abandoned_cart":    bool(n.get("on_abandoned_cart",   True)),
        "on_low_rating":        bool(n.get("on_low_rating",       True)),
        "quiet_hours_enabled":  bool(n.get("quiet_hours_enabled", False)),
        "quiet_hours_start":    int(n.get("quiet_hours_start", 22)),
        "quiet_hours_end":      int(n.get("quiet_hours_end",    8)),
    }


def save_settings(store_id: str, settings: dict) -> None:
    """Persist notification settings into the store's ai_config."""
    cfg = dict(sm.get_ai_config(store_id))
    cfg["notifications"] = settings
    sm.set_ai_config(store_id, cfg)


async def notify(store_id: str, event: str, ctx: dict) -> None:
    """
    Schedule notification delivery for a store event.

    What changed in Phase 1: this function no longer sends — it ENQUEUES into
    the durable outbox. The drainer picks up the row and invokes
    `deliver_outbox_row()` below. Two reasons:
      • Surviving restarts: previously asyncio.create_task(notify(...)) lost
        notifications if the process died before httpx finished.
      • Backoff & DLQ: failed sends now retry with exponential backoff
        instead of silently disappearing on the first 502 from Resend.

    Never raises — failure to enqueue is logged loudly but isn't the
    caller's problem (most call sites are deep in a webhook handler).
    """
    try:
        n = get_settings(store_id)

        if not n["email_enabled"] and not n["webhook_url"]:
            return  # nothing configured

        if n["quiet_hours_enabled"] and _in_quiet_hours(
            n["quiet_hours_start"], n["quiet_hours_end"]
        ):
            return

        # Event-type gating. llm_budget_warning is ALWAYS on — there's no
        # per-store toggle because losing track of an over-budget store
        # is worse than a noisy mailbox. If a store owner really doesn't
        # want these, they can disable email/webhook entirely.
        gate_key = {
            "new_conversation": "on_new_conversation",
            "abandoned_cart":   "on_abandoned_cart",
            "low_rating":       "on_low_rating",
        }.get(event)
        if event == "llm_budget_warning":
            pass  # bypass gating — always notify
        elif not gate_key or not n[gate_key]:
            return

        # Always enqueue the smallest payload that the drainer can rebuild
        # from. Templates are rebuilt at delivery time so a per-store rename
        # picked up by the drainer reflects fresh store_name.
        await db.outbox_enqueue(
            kind     = "notify_event",
            store_id = store_id,
            payload  = {"event": event, "ctx": ctx},
        )

    except Exception as exc:
        print(f"[notifications] enqueue error for {event}: {exc}")


async def deliver_outbox_row(store_id: str, payload: dict) -> None:
    """
    Drainer-side delivery for a 'notify_event' outbox row. Raises on send
    failure (caught by the drainer → retry with backoff or DLQ). Returns
    normally when every configured channel succeeded OR when none were
    applicable at delivery time (settings were turned off since enqueue).
    """
    event = payload.get("event", "")
    ctx   = payload.get("ctx", {}) or {}

    n = get_settings(store_id)
    if not n["email_enabled"] and not n["webhook_url"]:
        return  # nothing configured — silent ok

    info       = sm.get_store_info(store_id) or {}
    store_name = info.get("store_name") or f"متجر {store_id}"

    subject = html = ""
    wh_payload: dict = {"event": event, "store_id": store_id, "store_name": store_name}

    if event == "new_conversation":
        subject, html = _template_new_conversation(
            store_name    = store_name,
            customer_name = ctx.get("customer_name", ""),
            session_id    = ctx.get("session_id", ""),
            store_id      = store_id,
            first_msg     = ctx.get("first_message", ""),
        )
    elif event == "abandoned_cart":
        subject, html = _template_abandoned_cart(
            store_name    = store_name,
            customer_name = ctx.get("customer_name", ""),
            cart_total    = ctx.get("cart_total", "—"),
            store_id      = store_id,
        )
    elif event == "low_rating":
        subject, html = _template_low_rating(
            store_name    = store_name,
            customer_name = ctx.get("customer_name", ""),
            rating        = int(ctx.get("rating", 1)),
            comment       = ctx.get("comment", ""),
            store_id      = store_id,
        )
    elif event == "llm_budget_warning":
        subject, html = _template_llm_budget_warning(
            store_name   = store_name,
            store_id     = store_id,
            threshold    = int(ctx.get("threshold", 80)),
            used_today   = int(ctx.get("used_today", 0)),
            daily_budget = int(ctx.get("daily_budget", 0)),
            percent_used = float(ctx.get("percent_used", 0)),
        )
    else:
        return  # unknown event → silent ok

    wh_payload.update(ctx)

    errors: list[str] = []
    if n["email_enabled"] and n["email_address"] and subject:
        if not await _send_email(n["email_address"], subject, html):
            errors.append("email")
    if n["webhook_url"]:
        if not await _send_webhook(n["webhook_url"], wh_payload):
            errors.append("webhook")
    if errors:
        # Drainer treats this as a retryable failure
        raise RuntimeError(f"channels failed: {','.join(errors)}")
