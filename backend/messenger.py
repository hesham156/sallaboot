"""
messenger.py
─────────────────────────────────────────────────────────────────────────────
Facebook Messenger + Instagram Direct transport for the bot.

Like whatsapp.py, this is just another pipe into the channel-agnostic agent
(agent.chat). Meta delivers Messenger and Instagram events to the SAME webhook
URL as WhatsApp — they're told apart by the top-level `object` field:

    object = "whatsapp_business_account"  → handled by whatsapp.py
    object = "page"                       → Messenger        (this module)
    object = "instagram"                  → Instagram Direct (this module)

Both Messenger and Instagram use the Graph API "Send API": you POST to the
connected Facebook **Page**'s /messages edge with a Page access token; the
recipient id is the PSID (Messenger) or IGSID (Instagram). So a single send
path serves both — we just carry the channel label for logging + session keys.

Per-store config lives in ai_config:
    messenger_enabled  : bool
    instagram_enabled  : bool
    page_id            : str   (Facebook Page ID — webhook recipient + send target)
    page_token         : str   (long-lived Page access token)
    ig_id              : str   (Instagram Business Account ID — webhook recipient)

Incoming messages are routed to the owning store via page_id / ig_id (see
store_manager.find_store_by_page_id / find_store_by_ig_id).
"""
from __future__ import annotations

import os
import httpx

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", os.getenv("WHATSAPP_GRAPH_VERSION", "v21.0"))
_TEXT_LIMIT = 1000   # Messenger/IG cap a single text message at 2000 chars; we
                     # stay well under and split so long bot replies still land.


def extract_messages(payload: dict) -> list[dict]:
    """
    Parse a Messenger/Instagram webhook payload into a flat list of inbound
    messages. Returns dicts shaped:

        {
          "channel":      "messenger" | "instagram",
          "recipient_id": "<page_id or ig_id>",   # used to find the store
          "from":         "<PSID / IGSID>",        # the customer
          "text":         "<message text>",
          "msg_id":       "<message mid>",
          "name":         "",                      # filled later if resolvable
        }

    Echoes (our own outgoing messages), read receipts, and delivery events are
    skipped. Non-text messages get a placeholder so the bot still responds.
    """
    out: list[dict] = []
    obj = payload.get("object", "")
    channel = "instagram" if obj == "instagram" else "messenger"
    try:
        for entry in payload.get("entry", []) or []:
            # `entry.id` is the Page ID (Messenger) or IG account ID (Instagram);
            # individual events also carry recipient.id which we prefer.
            entry_id = str(entry.get("id", "") or "")
            for ev in entry.get("messaging", []) or []:
                msg = ev.get("message") or {}
                # Skip echoes of our own sends + non-message events.
                if msg.get("is_echo"):
                    continue
                if "message" not in ev and "postback" not in ev:
                    continue  # delivery / read / reaction → ignore

                sender    = str((ev.get("sender") or {}).get("id", "") or "")
                recipient = str((ev.get("recipient") or {}).get("id", "") or "") or entry_id
                if not sender or not recipient:
                    continue

                # Text, quick-reply, or postback payload → a usable string.
                text = ""
                if msg:
                    text = (msg.get("text") or "").strip()
                    if not text and msg.get("attachments"):
                        text = "📎 (أرسل العميل مرفقاً)"
                    qr = msg.get("quick_reply") or {}
                    if not text and qr.get("payload"):
                        text = str(qr.get("payload"))
                elif ev.get("postback"):
                    pb = ev["postback"]
                    text = (pb.get("title") or pb.get("payload") or "").strip()

                if not text:
                    continue

                out.append({
                    "channel":      channel,
                    "recipient_id": recipient,
                    "from":         sender,
                    "text":         text,
                    "msg_id":       str(msg.get("mid", "") or ""),
                    "name":         "",
                })
    except Exception as exc:
        print(f"[messenger] extract_messages error: {exc}")
    return out


async def send_text(token: str, page_id: str, to: str, text: str,
                    channel: str = "messenger") -> bool:
    """
    Send a text message via the Graph Send API. Works for both Messenger and
    Instagram (both route through the connected Page's /messages edge).

    `page_id` is the Facebook Page ID; `to` is the recipient PSID/IGSID.
    Splits long replies. Returns True on success, never raises.
    """
    if not (token and page_id and to and text):
        return False
    url     = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    ok = True
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for chunk in _split(text, _TEXT_LIMIT):
                body = {
                    "recipient":      {"id": to},
                    "messaging_type": "RESPONSE",
                    "message":        {"text": chunk},
                }
                r = await client.post(url, headers=headers, json=body)
                if r.status_code >= 400:
                    print(f"[{channel}] send failed {r.status_code}: {r.text[:300]}")
                    ok = False
    except Exception as exc:
        print(f"[{channel}] send_text error: {exc}")
        return False
    return ok


async def get_sender_name(token: str, psid: str) -> str:
    """
    Best-effort profile-name lookup for a Messenger PSID. Instagram does not
    expose this for IGSIDs in most cases, so callers should treat "" as normal.
    """
    if not (token and psid):
        return ""
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{psid}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"fields": "name", "access_token": token})
            if r.status_code == 200:
                return (r.json().get("name") or "").strip()
    except Exception:
        pass
    return ""


async def list_pages(user_token: str) -> list[dict]:
    """
    Fetch the Facebook Pages the user manages, each with its own long-lived
    Page access token and any linked Instagram Business account.
    GET /me/accounts?fields=id,name,access_token,instagram_business_account{...}

    Returns [{id, name, access_token, ig_id, ig_username}]. Never raises.
    """
    if not user_token:
        return []
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/me/accounts"
    params = {
        "fields":       "id,name,access_token,instagram_business_account{id,username}",
        "access_token": user_token,
        "limit":        100,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                print(f"[messenger] list_pages {r.status_code}: {r.text[:200]}")
                return []
            out = []
            for p in r.json().get("data", []) or []:
                ig = p.get("instagram_business_account") or {}
                out.append({
                    "id":           p.get("id", ""),
                    "name":         p.get("name", ""),
                    "access_token": p.get("access_token", ""),
                    "ig_id":        ig.get("id", ""),
                    "ig_username":  ig.get("username", ""),
                })
            return out
    except Exception as exc:
        print(f"[messenger] list_pages error: {exc}")
        return []


# Webhook fields covering both Messenger and Instagram message events delivered
# through the connected Page subscription.
_PAGE_SUBSCRIBE_FIELDS = "messages,messaging_postbacks,messaging_optins,message_reactions"


async def subscribe_page(page_token: str, page_id: str) -> bool:
    """
    Subscribe THIS app to a Page's messaging webhooks (covers Messenger and,
    when an IG business account is linked, Instagram Direct).
    POST /{page_id}/subscribed_apps. Idempotent. Returns True; never raises.
    """
    if not (page_token and page_id):
        return False
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/subscribed_apps"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, headers={"Authorization": f"Bearer {page_token}"},
                                  params={"subscribed_fields": _PAGE_SUBSCRIBE_FIELDS})
            if r.status_code >= 400:
                print(f"[messenger] subscribe_page {r.status_code}: {r.text[:200]}")
                return False
            return True
    except Exception as exc:
        print(f"[messenger] subscribe_page error: {exc}")
        return False


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
