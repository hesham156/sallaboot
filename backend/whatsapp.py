"""
whatsapp.py
─────────────────────────────────────────────────────────────────────────────
WhatsApp Cloud API (Meta) transport for the bot.

The bot's brain (agent.chat) is channel-agnostic — WhatsApp is just another
pipe. Incoming WhatsApp messages are routed to the same agent and the reply is
sent back through the Cloud API, so the conversation also shows up in the admin
inbox (tagged as a WhatsApp session).

Per-store config lives in ai_config:
    whatsapp_enabled   : bool
    whatsapp_token     : str   (permanent access token / system-user token)
    whatsapp_phone_id  : str   (the Phone Number ID from Meta)

Webhook verification uses a single app-level verify token (env
WHATSAPP_VERIFY_TOKEN), since one webhook URL serves all stores and incoming
messages are routed to the right store by phone_number_id.
"""
from __future__ import annotations
import os
import httpx

GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v21.0")
VERIFY_TOKEN  = os.getenv("WHATSAPP_VERIFY_TOKEN", "sallabot-wa")
_WA_TEXT_LIMIT = 4096


def verify_challenge(mode: str, token: str, challenge: str) -> str | None:
    """
    Meta webhook handshake. Returns the challenge string to echo back when the
    verify token matches, otherwise None (caller returns 403).
    """
    if mode == "subscribe" and token and token == VERIFY_TOKEN:
        return challenge
    return None


def extract_messages(payload: dict) -> list[dict]:
    """
    Parse a Cloud API webhook payload into a flat list of inbound text messages:
        [{phone_id, from, text, msg_id, name}, ...]
    Non-text messages (images, etc.) are surfaced with a placeholder text so the
    bot still responds rather than going silent.
    """
    out: list[dict] = []
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {}) or {}
                meta  = value.get("metadata", {}) or {}
                phone_id = str(meta.get("phone_number_id", "") or "")

                # map wa_id → profile name
                names: dict[str, str] = {}
                for c in value.get("contacts", []) or []:
                    wa_id = str(c.get("wa_id", "") or "")
                    nm = ((c.get("profile") or {}).get("name") or "").strip()
                    if wa_id:
                        names[wa_id] = nm

                for m in value.get("messages", []) or []:
                    sender = str(m.get("from", "") or "")
                    mtype  = m.get("type", "")
                    interactive_id = ""
                    if mtype == "text":
                        text = ((m.get("text") or {}).get("body") or "").strip()
                    elif mtype in ("image", "document", "audio", "video"):
                        text = "📎 (أرسل العميل مرفقاً عبر واتساب)"
                    elif mtype == "interactive":
                        inter = m.get("interactive") or {}
                        reply = inter.get("button_reply") or inter.get("list_reply") or {}
                        text = (reply.get("title") or "").strip()
                        # When we sent a list/buttons, each row's id carries the
                        # rating value (e.g. "csat:5") — surfacing it lets the
                        # CSAT handler distinguish a rating reply from a normal
                        # text response.
                        interactive_id = (reply.get("id") or "").strip()
                    else:
                        text = ""
                    if not text and not interactive_id:
                        continue
                    out.append({
                        "phone_id":       phone_id,
                        "from":           sender,
                        "text":           text or interactive_id,
                        "msg_id":         str(m.get("id", "") or ""),
                        "name":           names.get(sender, ""),
                        "interactive_id": interactive_id,
                    })
    except Exception as exc:
        print(f"[whatsapp] extract_messages error: {exc}")
    return out


async def send_text(token: str, phone_id: str, to: str, text: str) -> bool:
    """
    Send a plain-text WhatsApp message via the Cloud API. Splits overly long
    replies into chunks (WhatsApp caps a text body at ~4096 chars).
    Returns True on success. Never raises.
    """
    if not (token and phone_id and to and text):
        return False
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    chunks = _split(text, _WA_TEXT_LIMIT)
    ok = True
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for chunk in chunks:
                body = {
                    "messaging_product": "whatsapp",
                    "recipient_type":    "individual",
                    "to":                to,
                    "type":              "text",
                    "text":              {"preview_url": True, "body": chunk},
                }
                r = await client.post(url, headers=headers, json=body)
                if r.status_code >= 400:
                    print(f"[whatsapp] send failed {r.status_code}: {r.text[:300]}")
                    ok = False
    except Exception as exc:
        print(f"[whatsapp] send_text error: {exc}")
        return False
    return ok


async def send_list(
    token: str,
    phone_id: str,
    to: str,
    body: str,
    button: str,
    rows: list[dict],
    header: str = "",
    footer: str = "",
) -> bool:
    """
    Send an interactive **list** message (one section, up to 10 rows).
    Used for the post-conversation CSAT survey where 5 buttons wouldn't
    fit WhatsApp's 3-button interactive cap.

    Each row must be {"id": "csat:5", "title": "راضٍ تماماً"} — title is
    capped at 24 chars by Meta. Returns True on success; never raises.
    """
    if not (token and phone_id and to and body and rows):
        return False
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    interactive: dict = {
        "type": "list",
        "body": {"text": body[:1024]},
        "action": {
            "button": (button or "اختر")[:20],
            "sections": [{
                "title": "التقييم"[:24],
                "rows": [
                    {
                        "id":    str(r.get("id", ""))[:200],
                        "title": str(r.get("title", ""))[:24],
                        "description": str(r.get("description", ""))[:72],
                    }
                    for r in rows[:10]
                    if r.get("id") and r.get("title")
                ],
            }],
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    if footer:
        interactive["footer"] = {"text": footer[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "interactive",
        "interactive":       interactive,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                print(f"[whatsapp] send_list failed {r.status_code}: {r.text[:300]}")
                return False
    except Exception as exc:
        print(f"[whatsapp] send_list error: {exc}")
        return False
    return True


def _split(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        # Hard-split any single line longer than the limit.
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
