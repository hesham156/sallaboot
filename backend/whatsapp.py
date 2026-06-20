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
VERIFY_TOKEN  = os.getenv("WHATSAPP_VERIFY_TOKEN", "7ayak-wa")
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


async def send_template(
    token: str,
    phone_id: str,
    to: str,
    template_name: str,
    language: str = "ar",
    header_params: list[str] | None = None,
    body_params: list[str] | None = None,
    buttons: list[dict] | None = None,
) -> bool:
    """
    Send a Meta-approved WhatsApp template message.

    - header_params: list of strings for {{1}}, {{2}} … in the header component
    - body_params:   list of strings for {{1}}, {{2}} … in the body component
    - buttons:       list of {index, sub_type, parameters} for dynamic buttons

    Returns True on success. Never raises.
    """
    if not (token and phone_id and to and template_name):
        return False

    components: list[dict] = []

    if header_params:
        components.append({
            "type": "header",
            "parameters": [{"type": "text", "text": p} for p in header_params],
        })

    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in body_params],
        })

    if buttons:
        for btn in buttons:
            components.append({
                "type":       "button",
                "sub_type":   btn.get("sub_type", "quick_reply"),
                "index":      str(btn.get("index", 0)),
                "parameters": btn.get("parameters", []),
            })

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                to,
        "type":              "template",
        "template": {
            "name":     template_name,
            "language": {"code": language},
            **({"components": components} if components else {}),
        },
    }

    url     = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                print(f"[whatsapp] send_template failed {r.status_code}: {r.text[:300]}")
                return False
        print(f"[whatsapp] template '{template_name}' sent to {to}")
        return True
    except Exception as exc:
        print(f"[whatsapp] send_template error: {exc}")
        return False


async def list_meta_templates(token: str, waba_id: str) -> list[dict]:
    """
    Fetch the store's approved templates directly from Meta Graph API.
    Requires the WhatsApp Business Account ID (WABA ID), not the phone number ID.
    Returns a simplified list: [{name, language, status, category, body}]
    """
    if not (token and waba_id):
        return []
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/message_templates"
    params = {"fields": "name,language,status,category,components", "limit": 100}
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers=headers, params=params)
            if r.status_code != 200:
                print(f"[whatsapp] list_meta_templates {r.status_code}: {r.text[:200]}")
                return []
            data = r.json().get("data", [])
            out = []
            for t in data:
                body_text = ""
                for c in t.get("components", []):
                    if c.get("type") == "BODY":
                        body_text = c.get("text", "")
                out.append({
                    "name":     t.get("name", ""),
                    "language": t.get("language", "ar"),
                    "status":   t.get("status", ""),
                    "category": t.get("category", ""),
                    "body":     body_text,
                    "components": t.get("components", []),
                })
            return out
    except Exception as exc:
        print(f"[whatsapp] list_meta_templates error: {exc}")
        return []


async def create_meta_template(
    token: str,
    waba_id: str,
    *,
    name: str,
    body_text: str,
    language: str = "ar",
    category: str = "MARKETING",
    header_text: str = "",
    footer_text: str = "",
    buttons: list[dict] | None = None,
    body_examples: list[str] | None = None,
) -> dict:
    """
    Submit a new message template to Meta for approval.
    POST /{waba_id}/message_templates

    Meta requires an `example` value for every {{n}} placeholder in the body,
    so we auto-fill placeholders when the caller doesn't supply examples.
    Returns {"ok": bool, "id", "status", "category"} or {"ok": False, "error"}.
    Never raises. New templates come back as status "PENDING" until Meta reviews.
    """
    if not (token and waba_id and name and body_text):
        return {"ok": False, "error": "missing token / waba_id / name / body_text"}

    import re
    components: list[dict] = []
    if header_text:
        components.append({"type": "HEADER", "format": "TEXT", "text": header_text})

    body_comp: dict = {"type": "BODY", "text": body_text}
    nvars = len(re.findall(r"\{\{\s*\d+\s*\}\}", body_text))
    if nvars:
        ex = list(body_examples or [])[:nvars]
        ex += [f"مثال{i + 1}" for i in range(len(ex), nvars)]
        body_comp["example"] = {"body_text": [ex]}
    components.append(body_comp)

    if footer_text:
        components.append({"type": "FOOTER", "text": footer_text})
    if buttons:
        components.append({"type": "BUTTONS", "buttons": buttons})

    payload = {
        "name":       name,
        "language":   language,
        "category":   (category or "MARKETING").upper(),
        "components": components,
    }
    url     = f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/message_templates"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, headers=headers, json=payload)
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                err = (data.get("error") or {}).get("message") or r.text[:300]
                print(f"[whatsapp] create_meta_template {r.status_code}: {err}")
                return {"ok": False, "error": err, "status_code": r.status_code}
            return {
                "ok":       True,
                "id":       data.get("id", ""),
                "status":   data.get("status", "PENDING"),
                "category": data.get("category", category),
            }
    except Exception as exc:
        print(f"[whatsapp] create_meta_template error: {exc}")
        return {"ok": False, "error": str(exc)}


async def subscribe_waba(token: str, waba_id: str) -> bool:
    """
    Subscribe THIS app to the merchant's WhatsApp Business Account so Meta
    delivers message webhooks for it. POST /{waba_id}/subscribed_apps.
    Idempotent on Meta's side. Returns True on success; never raises.
    """
    if not (token and waba_id):
        return False
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/subscribed_apps"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, headers={"Authorization": f"Bearer {token}"})
            if r.status_code >= 400:
                print(f"[whatsapp] subscribe_waba {r.status_code}: {r.text[:200]}")
                return False
            return True
    except Exception as exc:
        print(f"[whatsapp] subscribe_waba error: {exc}")
        return False


async def unsubscribe_waba(token: str, waba_id: str) -> bool:
    """
    Inverse of subscribe_waba: detach THIS app from the merchant's WhatsApp
    Business Account so Meta stops delivering their message webhooks to us.
    DELETE /{waba_id}/subscribed_apps. Used on full disconnect so unlinking
    from the app is a real unlink at Meta, not just clearing local creds.
    Idempotent on Meta's side. Returns True on success; never raises.
    """
    if not (token and waba_id):
        return False
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/subscribed_apps"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.delete(url, headers={"Authorization": f"Bearer {token}"})
            if r.status_code >= 400:
                print(f"[whatsapp] unsubscribe_waba {r.status_code}: {r.text[:200]}")
                return False
            return True
    except Exception as exc:
        print(f"[whatsapp] unsubscribe_waba error: {exc}")
        return False


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
