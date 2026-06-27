"""Telegram Bot webhook ingest + message/media handlers.

Split out of the original single-file routers/webhooks.py."""
from __future__ import annotations
import asyncio
import datetime as _dt
import hmac
import json as _json
from fastapi import HTTPException, Request
import conversation_store as cs
import database as db
import store_manager as sm
from routers.webhooks._base import (
    router,
    _log_event,
    _parse_csat_reply,
)



# ─────────────────────────────────────────────────────────────────────────
# Telegram Bot API webhook
# ─────────────────────────────────────────────────────────────────────────
# setWebhook (routers.channels) points each bot at
#   {BASE_URL}/telegram/webhook/{store_id}
# Telegram echoes the per-store secret in the X-Telegram-Bot-Api-Secret-Token
# header — that's what proves an inbound call really came from Telegram for
# THIS store (Telegram has no body HMAC).
# ─────────────────────────────────────────────────────────────────────────

@router.post("/telegram/webhook/{store_id}")
async def telegram_webhook(store_id: str, request: Request):
    """
    Telegram per-store webhook receiver — insert-then-ack (mirrors Meta).
    Verifies the secret-token header against the store's saved secret, then
    queues each message to webhook_inbox for out-of-band processing. Always
    returns 200 fast so Telegram doesn't retry.
    """
    import telegram as tg

    cfg    = sm.get_ai_config(store_id) or {}
    secret = (cfg.get("telegram_secret") or "").strip()
    sent   = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    # No secret on file → this store has no Telegram connection. Unknown/forged.
    if not secret:
        raise HTTPException(404, "No active Telegram channel for this store")
    if not hmac.compare_digest(secret, sent):
        _log_event(store_id, "telegram.message", "rejected", "secret token mismatch")
        raise HTTPException(403, "invalid telegram secret token")

    body = await request.body()
    try:
        payload = _json.loads(body)
    except Exception:
        return {"status": "ignored"}

    queued = 0
    for msg in tg.extract_messages(payload):
        msg["store_id"] = store_id          # carry routing target for the handler
        msg_id = (msg.get("msg_id") or "").strip()
        if not db.available():
            print(f"[telegram] ⛔ DB down — processing synchronously store={store_id!r}")
            asyncio.create_task(handle_telegram_message(msg))
            continue
        result = await db.inbox_insert(
            source     = "telegram",
            event_type = "telegram.message",
            dedup_key  = f"tg:{store_id}:{msg_id}" if msg_id else "",
            store_id   = store_id,
            payload    = msg,
            meta       = {},
        )
        if result["inserted"]:
            queued += 1
    return {"status": "ok", "queued": queued}


# Label + URL fragment hint per media kind. The frontend renderer reads the
# fragment (/file/<id>#audio) to pick <img> / <audio> / <video> / download.
_TG_MEDIA_RENDER = {
    "image": ("صورة",         ""),
    "audio": ("🎤 تسجيل صوتي", "#audio"),
    "video": ("🎬 فيديو",      "#video"),
    "file":  ("📎 ملف",        "#file"),
}


async def _telegram_store_media(token: str, media: dict, store_id: str,
                                session_id: str, caption: str) -> str:
    """Download ANY inbound Telegram attachment (image/audio/video/file), persist
    it via the upload store, and return the message text with an inline link
    (carrying a #kind hint) folded in so it renders correctly in the inbox. Falls
    back to a placeholder on any failure so the customer's message never vanishes."""
    import os as _os
    import uuid as _uuid
    import telegram as tg

    kind     = media.get("kind", "file")
    file_id  = media.get("file_id", "")
    filename = (media.get("filename") or "").strip()
    label, frag = _TG_MEDIA_RENDER.get(kind, _TG_MEDIA_RENDER["file"])
    if kind == "file" and filename:
        label = f"📎 {filename}"

    def _placeholder() -> str:
        noun = {"image": "صورة", "audio": "تسجيلاً صوتياً",
                "video": "فيديو"}.get(kind, "مرفقاً")
        ph = f"📎 (أرسل العميل {noun})"
        return f"{caption}\n{ph}".strip() if caption else ph

    fetched = await tg.fetch_media(token, file_id)
    if not fetched or not db.available():
        return _placeholder()
    raw, ctype = fetched
    ctype = media.get("mime") or ctype        # Telegram's declared mime is more reliable
    fid   = str(_uuid.uuid4())
    fname = filename or f"telegram_{fid}"
    try:
        await db.save_upload(file_id=fid, filename=fname, content_type=ctype,
                             data=raw, store_id=store_id, session_id=session_id)
    except Exception as exc:
        print(f"[telegram] save media failed: {exc}")
        return _placeholder()
    base_url = _os.getenv("BASE_URL", "").rstrip("/")
    url = f"{base_url}/file/{fid}{frag}" if base_url else f"/file/{fid}{frag}"
    md = f"[{label}]({url})"
    return f"{caption}\n{md}".strip() if caption else md


async def handle_telegram_message(msg: dict):
    """
    Route one inbound Telegram message → bot → reply. Channel-agnostic mirror of
    handle_messenger_message: the same agent answers, and the thread shows in the
    admin inbox tagged by channel. Never raises — the inbox drainer logs failures
    and applies backoff.

    Public (no leading underscore) because the drainer reaches it via
    main._process_inbox_row.
    """
    import telegram as tg
    try:
        store_id = str(msg.get("store_id", "") or "")
        chat_id  = str(msg.get("chat_id", "") or "")
        sender   = str(msg.get("from", "") or "")
        text     = msg.get("text", "")
        media    = msg.get("media") if isinstance(msg.get("media"), dict) else None

        # Log metadata only — never the message body (PII / message content, M-17).
        print(f"[telegram] 📨 incoming: store={store_id!r} chat={chat_id!r} "
              f"chars={len(text)} media={media.get('kind') if media else 'n'}")
        if not (store_id and chat_id):
            return

        cfg   = sm.get_ai_config(store_id) or {}
        token = (cfg.get("telegram_bot_token") or "").strip()
        if not (cfg.get("telegram_enabled") and token):
            print(f"[telegram] ⛔ disabled or no token for store {store_id!r}")
            return

        # Stable per-customer session keyed by store + chat id — persists and shows
        # in the admin inbox just like a widget / WhatsApp / Messenger chat.
        # store_id is REQUIRED: same Telegram chat_id could be linked to a
        # different store after the bot token is reassigned.
        session_id = f"tg:{store_id}:{sender}"

        # Any attachment becomes an inline link so it renders in the inbox; the bot
        # can't read media content, so it's handled (acknowledge + escalate) below.
        media_text = ""
        if media:
            media_text = await _telegram_store_media(token, media, store_id, session_id, text)
        if not (text or media_text):
            return

        await cs.restore_to_memory(session_id)
        cs.get_or_create(session_id, store_id)
        info = cs.get_customer_info(session_id) or {}
        # Telegram updates carry the sender's name on every message; backfill it
        # while missing so the admin inbox shows the customer, not "جلسة <id>"
        # (also fixes older sessions created before names were captured).
        if not (info.get("name") or "").strip():
            await cs.set_customer_info(session_id, {
                "name":    msg.get("name", ""),
                "channel": "telegram",
            })

        # Inbound attachment → the bot can't read media content. Record it so it
        # shows in the inbox, acknowledge gracefully, and ESCALATE to support
        # (handoff) so a human reviews it — surfaces in the "needs support" queue.
        # Never the rude "don't share files here" the text model would produce.
        if media:
            await cs.add_message(session_id, "user", media_text, store_id)
            if cs.is_bot_enabled(session_id):
                ack = (
                    "شكراً، استلمت المرفق 📎 لا أستطيع الاطّلاع على محتواه مباشرةً، "
                    "لكن أحد ممثلي خدمة العملاء سيراجعه ويساعدك. "
                    "أو اكتب لي اسم المنتج أو تفاصيل طلبك وأساعدك فوراً 🌷"
                )
                await cs.add_message(session_id, "assistant", ack, store_id)
                await cs.escalate_session(
                    session_id, reason="customer_attachment",
                    details=f"أرسل العميل مرفقاً ({media.get('kind', 'file')}) يحتاج مراجعة بشرية.",
                    customer_summary="📎 مرفق من العميل",
                )
                await tg.send_text(token, chat_id, ack)
                print(f"[telegram] 📎 {media.get('kind')} → escalated to support (store {store_id})")
            return

        # CSAT reply intercept — if the most-recent bot message was a CSAT survey
        # (sent by end-conversation), treat a numeric/label reply as the rating
        # rather than routing it through the agent. Mirrors handle_whatsapp_message.
        conv_now = cs.all_conversations().get(session_id) or {}
        csat_msg = None
        for prev in reversed(conv_now.get("messages", [])):
            role = prev.get("role")
            if role == "user":
                break
            if role == "assistant" and (prev.get("meta") or {}).get("kind") == "csat":
                csat_msg = prev
                break
        if csat_msg:
            rating = _parse_csat_reply("", text)
            if rating:
                await cs.add_message(session_id, "user", text, store_id)
                await cs.set_rating(session_id, rating, f"CSAT Telegram: {text}")
                csat_meta = csat_msg.get("meta") or {}
                conv_now["rating_employee_id"]   = csat_meta.get("target_agent_id")
                conv_now["rating_employee_name"] = csat_meta.get("target_agent_name", "")
                conv_now["rated_at"]             = _dt.datetime.utcnow().isoformat()
                cs.mark_dirty(session_id)
                await cs.flush(session_id)
                await tg.send_text(token, chat_id, "شكراً لتقييمك 🌷")
                print(f"[telegram] ⭐ CSAT recorded: {rating} for store {store_id}")
                return

        if not cs.is_bot_enabled(session_id):
            # Admin took this thread over — just record the message.
            await cs.add_message(session_id, "user", text, store_id)
            return

        agent = sm.get_agent(store_id)
        if agent is None:
            return
        reply = await agent.chat(message=text, session_id=session_id)
        await tg.send_text(token, chat_id, reply)
        print(f"[telegram] ↩ replied to {chat_id} (store {store_id})")
    except Exception as exc:
        print(f"[telegram] handle error: {exc}")
        _s = str(exc).lower()
        if "authentication_error" in _s or "invalid x-api-key" in _s or "401" in _s:
            print(f"[telegram] ⛔ auth error — not retrying (fix the API key for store {store_id})")
            return
        raise  # let the inbox drainer retry transient errors
