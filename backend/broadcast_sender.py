"""
Omni-channel broadcast sender.

Fans a single free-text message out to every CONNECTED channel's active
users. Complements wa_campaigns (which is WhatsApp *template* only): this is
free text, multi-channel, to people the store has already talked to.

Channels & policy
─────────────────
  widget     — website chat. No restriction. Delivered via the same durable
               path as an admin reply (conversation transcript + widget_outbox
               + realtime), so it shows up live and on reconnect.
  telegram   — free text to anyone who messaged the bot. No window.
  email      — to contacts that have an email. No window.
  whatsapp   — free text only inside Meta's 24h customer-care window, so we
               restrict to conversations active in the last 24h. For older
               audiences use a WhatsApp *template* campaign instead.
  messenger  — same 24h rule (Meta Messaging Platform).
  instagram  — same 24h rule.

Sending runs in the background via asyncio.create_task() so the HTTP
response is immediate; progress is written back to the broadcasts row
(status + total/sent/failed + per-channel breakdown).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import html as _html

import database as db
import store_manager as sm
import conversation_store as cs

# Conservative pacing so a big blast doesn't trip per-channel rate limits.
_SEND_DELAY = 0.20
_META_WINDOW_HOURS = 24   # WhatsApp / Messenger / Instagram free-text window

# Every channel we know how to broadcast on. `window` = hours back to limit
# recipients (None = no limit). `needs` = ai_config keys that must be present
# for the channel to be considered connected.
CHANNELS = ("widget", "telegram", "email", "whatsapp", "messenger", "instagram")

_CHANNEL_NEEDS = {
    "widget":    (),
    "telegram":  ("telegram_bot_token",),
    "email":     (),                                  # uses contacts + SMTP env
    "whatsapp":  ("whatsapp_token", "whatsapp_phone_id"),
    "messenger": ("page_token",),
    "instagram": ("page_token",),
}
_CHANNEL_WINDOW = {
    "widget": None, "telegram": None, "email": None,
    "whatsapp": _META_WINDOW_HOURS, "messenger": _META_WINDOW_HOURS,
    "instagram": _META_WINDOW_HOURS,
}


def available_channels(store_id: str) -> list[str]:
    """Channels whose credentials are configured for this store."""
    cfg = sm.get_ai_config(store_id) or {}
    out = []
    for ch in CHANNELS:
        needs = _CHANNEL_NEEDS[ch]
        if ch == "instagram" and not cfg.get("instagram_enabled"):
            continue
        if all((cfg.get(k) or "").strip() for k in needs):
            out.append(ch)
    return out


async def audience_counts(store_id: str) -> dict:
    """Per-channel recipient counts for the compose-screen preview."""
    counts: dict = {}
    for ch in available_channels(store_id):
        if ch == "email":
            recips = await db.broadcast_email_recipients(store_id)
        else:
            recips = await db.broadcast_channel_recipients(
                store_id, ch, within_hours=_CHANNEL_WINDOW[ch])
        counts[ch] = len(recips)
    return counts


# ── Per-channel delivery ────────────────────────────────────────────────────

async def _send_one(store_id: str, channel: str, cfg: dict,
                    recipient: dict, message: str) -> bool:
    try:
        if channel in ("widget", "web"):
            # Same path as an admin reply: persists + enqueues + realtime.
            await cs.add_message(recipient["session_id"], role="admin",
                                 content=message, store_id=store_id)
            return True

        if channel == "telegram":
            import telegram as tg
            return await tg.send_text(
                (cfg.get("telegram_bot_token") or "").strip(),
                recipient["recipient"], message)

        if channel == "whatsapp":
            import whatsapp as wa
            return await wa.send_text(
                (cfg.get("whatsapp_token") or "").strip(),
                (cfg.get("whatsapp_phone_id") or "").strip(),
                recipient["recipient"], message)

        if channel in ("messenger", "instagram"):
            import messenger as ms
            return await ms.send_text(
                (cfg.get("page_token") or "").strip(),
                (cfg.get("page_id") or "").strip(),
                recipient["recipient"], message, channel=channel)

        if channel == "email":
            import notifications as notif
            store_name = (sm.get_store_info(store_id) or {}).get("store_name") or "متجرنا"
            subject = f"رسالة من {store_name}"
            body = "<br>".join(_html.escape(line) for line in message.splitlines())
            html = (f'<div style="font-family:Tajawal,Arial,sans-serif;'
                    f'direction:rtl;text-align:right">{body}</div>')
            return await notif._send_email(recipient["recipient"], subject, html)
    except Exception as exc:
        print(f"[broadcast] send error ({channel}): {exc}")
    return False


async def _send_channel(store_id: str, channel: str, cfg: dict,
                        message: str) -> tuple[int, int]:
    """Send to every recipient of one channel. Returns (sent, failed)."""
    if channel == "email":
        recips = await db.broadcast_email_recipients(store_id)
    else:
        recips = await db.broadcast_channel_recipients(
            store_id, channel, within_hours=_CHANNEL_WINDOW[channel])
    sent = failed = 0
    for r in recips:
        ok = await _send_one(store_id, channel, cfg, r, message)
        sent += 1 if ok else 0
        failed += 0 if ok else 1
        await asyncio.sleep(_SEND_DELAY)
    return sent, failed


# ── Orchestration ───────────────────────────────────────────────────────────

async def run_broadcast(broadcast_id: int) -> None:
    """Background task: deliver a broadcast across its selected channels."""
    bc = None
    try:
        # broadcast_get needs store_id; fetch via a store-less lookup helper.
        async with db._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM broadcasts WHERE id = $1",
                                      int(broadcast_id))
        if not row:
            print(f"[broadcast] {broadcast_id} not found")
            return
        bc = db._broadcast_row(row)
    except Exception as exc:
        print(f"[broadcast] load {broadcast_id} failed: {exc}")
        return

    store_id = bc["store_id"]
    message  = bc["message"]
    cfg      = sm.get_ai_config(store_id) or {}
    connected = set(available_channels(store_id))
    channels  = [c for c in bc["channels"] if c in connected]

    await db.broadcast_update(broadcast_id, status="sending")

    per_channel: dict = {}
    total = sent = failed = 0
    for ch in channels:
        s, f = await _send_channel(store_id, ch, cfg, message)
        per_channel[ch] = {"sent": s, "failed": f}
        total += s + f
        sent  += s
        failed += f
        # Persist incrementally so the UI shows live progress on long runs.
        await db.broadcast_update(broadcast_id, total=total, sent=sent,
                                  failed=failed, per_channel=per_channel)

    final_status = "sent" if failed == 0 or sent > 0 else "failed"
    await db.broadcast_update(
        broadcast_id, status=final_status, total=total, sent=sent,
        failed=failed, per_channel=per_channel,
        sent_at=_dt.datetime.now(_dt.timezone.utc),
    )
    print(f"[broadcast] {broadcast_id} done — {sent}/{total} sent, "
          f"{failed} failed across {channels}")
