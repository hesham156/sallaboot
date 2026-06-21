"""
Telegram Bot API pipe.

Like whatsapp.py and messenger.py, this is just another pipe into the
channel-agnostic agent (agent.chat). A merchant connects their bot by pasting
its Bot API token (from @BotFather); we register a webhook that points at
/telegram/webhook/{store_id}, and every inbound message is routed to the SAME
agent. The reply is sent back with sendMessage.

Per-store config lives in ai_config:
    telegram_enabled       : bool  (auto-reply on/off)
    telegram_bot_token     : str   (BotFather token — the send credential)
    telegram_bot_id        : str   (numeric id, parsed from the token)
    telegram_bot_username  : str   (@handle, for display)
    telegram_secret        : str   (webhook secret-token, verifies inbound calls)

Telegram routes inbound updates to an arbitrary per-bot webhook URL, so we key
the URL by store_id and don't need a reverse lookup. The secret token Telegram
echoes in the X-Telegram-Bot-Api-Secret-Token header is what proves a call
really came from Telegram for THIS store.
"""
from __future__ import annotations

import httpx

API_BASE = "https://api.telegram.org"

# Telegram caps a text message body at 4096 chars.
_TG_TEXT_LIMIT = 4096


def _api(token: str, method: str) -> str:
    return f"{API_BASE}/bot{token}/{method}"


def bot_id_from_token(token: str) -> str:
    """The numeric bot id is the part of the token before the first ':'."""
    return (token or "").split(":", 1)[0].strip()


async def get_me(token: str) -> dict | None:
    """Validate a bot token. Returns the bot's user object on success, else None.
    Never raises — a bad token simply resolves to None."""
    token = (token or "").strip()
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(_api(token, "getMe"))
        data = r.json()
        if r.status_code < 400 and data.get("ok"):
            return data.get("result") or {}
    except Exception as exc:
        print(f"[telegram] getMe error: {exc}")
    return None


async def set_webhook(token: str, url: str, secret: str) -> tuple[bool, str]:
    """Point this bot's updates at `url`, authenticated by `secret` (echoed back
    by Telegram in the X-Telegram-Bot-Api-Secret-Token header). Returns
    (ok, detail). Never raises."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(_api(token, "setWebhook"), json={
                "url":             url,
                "secret_token":    secret,
                "allowed_updates": ["message", "edited_message"],
                # Drop any backlog queued while the bot was unconfigured so the
                # merchant doesn't get a burst of stale auto-replies on connect.
                "drop_pending_updates": True,
            })
        data = r.json()
        if r.status_code < 400 and data.get("ok"):
            return True, "ok"
        return False, str(data.get("description") or f"http {r.status_code}")
    except Exception as exc:
        return False, str(exc)


async def delete_webhook(token: str) -> bool:
    """Remove the webhook so Telegram stops delivering updates. Never raises."""
    token = (token or "").strip()
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(_api(token, "deleteWebhook"),
                                  json={"drop_pending_updates": False})
        return r.status_code < 400 and (r.json().get("ok") is True)
    except Exception as exc:
        print(f"[telegram] deleteWebhook error: {exc}")
        return False


def _sender_name(frm: dict) -> str:
    first = str(frm.get("first_name") or "").strip()
    last  = str(frm.get("last_name") or "").strip()
    name  = (first + " " + last).strip()
    return name or str(frm.get("username") or "").strip()


def extract_messages(payload: dict) -> list[dict]:
    """
    Normalise one Telegram update into our channel-agnostic message shape.
    Telegram POSTs ONE update per webhook call, but we return a list to mirror
    whatsapp.extract_messages / messenger.extract_messages.

    Emitted dict keys:
      msg_id        : str  — "<update_id>" (unique per bot → dedup key)
      chat_id       : str  — Telegram chat id (the send target)
      from          : str  — same chat id (sender identity for the session)
      text          : str  — message body (caption for media)
      name          : str  — sender display name
      photo_file_id : str  — set when the message carries a photo; the handler
                             resolves it to a stored image (else "").

    A photo is surfaced with its largest file_id so the handler can download +
    store it. Other media (documents, voice, video, stickers …) get a placeholder
    text so the message still appears and the bot responds rather than going
    silent — mirrors whatsapp.extract_messages.
    """
    if not isinstance(payload, dict):
        return []
    msg = payload.get("message") or payload.get("edited_message")
    if not isinstance(msg, dict):
        return []
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id:
        return []

    update_id = payload.get("update_id")
    base = {
        "msg_id":  str(update_id if update_id is not None else msg.get("message_id", "")),
        "chat_id": chat_id,
        "from":    chat_id,
        "name":    _sender_name(msg.get("from") or {}),
        "photo_file_id": "",
    }
    caption = str(msg.get("caption") or "").strip()

    photo = msg.get("photo")
    if isinstance(photo, list) and photo:
        # PhotoSize array is ordered small→large; take the largest.
        file_id = str((photo[-1] or {}).get("file_id") or "")
        if file_id:
            return [{**base, "text": caption, "photo_file_id": file_id}]

    if any(k in msg for k in ("document", "video", "voice", "audio", "sticker", "animation")):
        return [{**base, "text": caption or "📎 (أرسل العميل مرفقاً عبر تيليجرام)"}]

    body = str(msg.get("text") or "").strip() or caption
    if not body:
        return []
    return [{**base, "text": body}]


async def fetch_media(token: str, file_id: str) -> tuple[bytes, str] | None:
    """
    Resolve a Telegram file_id → (raw_bytes, content_type). Two calls: getFile
    (file_id → file_path) then a download from the file endpoint. Returns None on
    any failure so the caller falls back to a placeholder. Never raises.
    """
    if not (token and file_id):
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(_api(token, "getFile"), params={"file_id": file_id})
            data = r.json()
            if not (r.status_code < 400 and data.get("ok")):
                return None
            file_path = ((data.get("result") or {}).get("file_path") or "").strip()
            if not file_path:
                return None
            fr = await client.get(f"{API_BASE}/file/bot{token}/{file_path}")
            if fr.status_code >= 400 or not fr.content:
                return None
            ctype = (fr.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
            return fr.content, ctype
    except Exception as exc:
        print(f"[telegram] fetch_media error: {exc}")
        return None


def _split(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur); cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            if cur:
                parts.append(cur)
            cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        parts.append(cur)
    return parts


async def send_text(token: str, chat_id: str, text: str) -> bool:
    """
    Send a plain-text Telegram message. Splits overly long replies into chunks
    (Telegram caps a text body at 4096 chars). Returns True on success; never
    raises.
    """
    if not (token and chat_id and text):
        return False
    url = _api(token, "sendMessage")
    ok = True
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for chunk in _split(text, _TG_TEXT_LIMIT):
                r = await client.post(url, json={
                    "chat_id": chat_id,
                    "text":    chunk,
                    "disable_web_page_preview": False,
                })
                if r.status_code >= 400:
                    print(f"[telegram] send failed {r.status_code}: {r.text[:300]}")
                    ok = False
    except Exception as exc:
        print(f"[telegram] send_text error: {exc}")
        return False
    return ok
