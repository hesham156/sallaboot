"""Meta (WhatsApp Cloud API + Messenger + Instagram Direct) webhook verify + message handlers.

Split out of the original single-file routers/webhooks.py."""
from __future__ import annotations
import asyncio
import datetime as _dt
import hashlib
import hmac
import json as _json
import os
from fastapi import HTTPException, Request
import auth as _auth
import conversation_store as cs
import database as db
import store_manager as sm
from routers.webhooks._base import (
    router,
    log,
    _log_event,
    _parse_csat_reply,
)



# ─────────────────────────────────────────────────────────────────────────
# WhatsApp Cloud API webhook
# ─────────────────────────────────────────────────────────────────────────

@router.get("/whatsapp/webhook")
async def whatsapp_verify(request: Request):
    """Meta verification handshake (GET with hub.* query params)."""
    import whatsapp as wa
    qp        = request.query_params
    challenge = wa.verify_challenge(
        qp.get("hub.mode", ""), qp.get("hub.verify_token", ""), qp.get("hub.challenge", ""))
    if challenge is not None:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(challenge)
    raise HTTPException(403, "verify token mismatch")


def _verify_meta_signature(body: bytes, headers) -> tuple[bool, str]:
    """
    Verify Meta's X-Hub-Signature-256 over the RAW request body using the app
    secret (HMAC-SHA256). Mirrors _verify_signature / _verify_shopify_webhook:
      - secret unset             → accept (dev mode only, loud warning)
      - secret set + sig present  → strict verify
      - secret set + sig absent   → REJECT

    Meta signs EVERY webhook delivery, so a missing/invalid signature on a
    configured app means the request did NOT come from Meta — i.e. a forged
    inbound WhatsApp / Messenger / Instagram event (finding C-3).
    """
    # The unified webhook may receive events from up to THREE different Meta
    # apps — each signs with its own App Secret:
    #   META_APP_SECRET       → main app  (Messenger + Facebook comments)
    #   INSTAGRAM_APP_SECRET  → Instagram sub-app (IG Direct + IG comments)
    #   WHATSAPP_APP_SECRET   → WhatsApp Business / BSP app
    # A signature matching ANY configured secret is accepted. Omit the vars
    # that share the same app as META_APP_SECRET (no need to duplicate).
    # .strip() each secret: a stray trailing newline/space in the Railway env
    # value is a common copy-paste mistake that makes every signature fail.
    secrets = [s for s in (
        os.getenv("META_APP_SECRET", "").strip(),
        os.getenv("INSTAGRAM_APP_SECRET", "").strip(),
        os.getenv("WHATSAPP_APP_SECRET", "").strip(),
    ) if s]
    if not secrets:
        log.warning("meta_webhook_no_secret_dev_mode")
        return True, "no_secret_configured"
    sig = (headers.get("X-Hub-Signature-256", "") or "").strip()
    if not sig:
        log.warning("meta_webhook_signature_missing")
        return False, "signature_required_but_absent"
    expected_prefix = ""
    for secret in secrets:
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        expected_prefix = expected_prefix or expected[:20]
        if hmac.compare_digest(expected, sig):
            return True, "signature_ok"
    # Diagnostic (never leaks the secret): the got/expected prefixes + key length
    # make a config mismatch obvious. #1 cause: META_APP_SECRET doesn't match the
    # Meta app's App Secret (Meta › App › Settings › Basic). If WhatsApp is on a
    # SEPARATE Meta/BSP app, set WHATSAPP_APP_SECRET to that app's secret too.
    log.warning("meta_webhook_signature_mismatch", extra={
        "got_prefix":      sig[:20],
        "expected_prefix": expected_prefix,
        "secret_lens":     [len(s) for s in secrets],
    })
    return False, "signature_mismatch"


@router.post("/whatsapp/webhook")
async def meta_webhook(request: Request):
    """
    Unified Meta webhook — WhatsApp, Messenger AND Instagram all POST here.
    Meta tells them apart by the top-level `object` field:
        whatsapp_business_account → WhatsApp (whatsapp.py)
        page                      → Messenger (messenger.py)
        instagram                 → Instagram Direct (messenger.py)

    Each message becomes its own webhook_inbox row (dedup by message id) and is
    acked fast (< 100 ms); the drainer processes it out-of-band. Falls back to
    synchronous handling when the DB is down so a message is never lost. Meta
    retries on 5xx for ~24h, so we must always respond 200.
    """
    import whatsapp as wa
    import messenger as ms
    import comments as cm

    body = await request.body()
    # DEBUG — log every POST so we can see if Meta is sending anything at all.
    try:
        _preview = _json.loads(body)
        _obj_dbg = _preview.get("object", "?")
        _eid_dbg = ((_preview.get("entry") or [{}])[0]).get("id", "?")
    except Exception:
        _obj_dbg, _eid_dbg = "?", "?"
    print(f"[meta_webhook] ← POST object={_obj_dbg!r} entry_id={_eid_dbg!r} "
          f"len={len(body)} sig={'present' if request.headers.get('X-Hub-Signature-256') else 'MISSING'}")
    sig_ok, sig_detail = _verify_meta_signature(body, request.headers)
    if not sig_ok:
        # Diagnostic (no secrets): which object/sender is being rejected, so a
        # signature mismatch can be traced to the right Meta app/channel.
        try:
            _p   = _json.loads(body)
            _obj = _p.get("object", "?")
            _eid = ((_p.get("entry") or [{}])[0]).get("id", "?")
            _fld = [c.get("field") for e in (_p.get("entry") or [])
                    for c in (e.get("changes") or [])]
            print(f"[meta_webhook] ⛔ 403 sig_mismatch object={_obj!r} entry_id={_eid!r} "
                  f"changes={_fld} body_len={len(body)}")
        except Exception:
            print(f"[meta_webhook] ⛔ 403 sig_mismatch (unparseable body, len={len(body)})")
        _log_event("", "meta.webhook", "rejected", f"signature: {sig_detail}",
                   sig_status=sig_detail)
        raise HTTPException(403, f"invalid signature: {sig_detail}")
    try:
        payload = _json.loads(body)
    except Exception:
        return {"status": "ignored"}

    obj    = payload.get("object", "")
    queued = 0

    # ── Messenger / Instagram ────────────────────────────────────────────
    if obj in ("page", "instagram"):
        _extracted = ms.extract_messages(payload)
        _comments  = cm.extract_comments(payload)
        # DEBUG — when an instagram event yields neither a DM nor a comment,
        # dump the raw payload so we can see its exact shape.
        if obj == "instagram" and not _extracted and not _comments:
            print(f"[instagram] ⚠️ webhook yielded 0 messages + 0 comments. RAW={body[:800]!r}")
        for msg in _extracted:
            msg_id  = (msg.get("msg_id") or "").strip()
            channel = msg.get("channel", "messenger")
            if not db.available():
                print(f"[{channel}] ⛔ DB down — processing synchronously")
                asyncio.create_task(handle_messenger_message(msg))
                continue
            result = await db.inbox_insert(
                source     = channel,
                event_type = f"{channel}.message",
                dedup_key  = f"{channel}:{msg_id}" if msg_id else "",
                store_id   = "",
                payload    = msg,
                meta       = {},
            )
            if result["inserted"]:
                queued += 1

        # Public comments arrive on the SAME page/instagram object but under
        # `changes[]` (feed/comments) rather than `messaging[]`. Queue them on a
        # distinct source so the drainer routes them to handle_comment_event.
        for c in _comments:
            cid      = (c.get("comment_id") or "").strip()
            platform = c.get("platform", "facebook")
            source   = "ig_comment" if platform == "instagram" else "fb_comment"
            if not db.available():
                print(f"[{source}] ⛔ DB down — processing synchronously")
                asyncio.create_task(handle_comment_event(c))
                continue
            result = await db.inbox_insert(
                source     = source,
                event_type = f"{source}.add",
                dedup_key  = f"{platform}:{cid}" if cid else "",
                store_id   = "",
                payload    = c,
                meta       = {},
            )
            if result["inserted"]:
                queued += 1
        return {"status": "ok", "queued": queued}

    # ── WhatsApp (default) ───────────────────────────────────────────────
    for msg in wa.extract_messages(payload):
        # extract_messages keys the id as "msg_id" — the previous code read
        # "id"/"message_id" (always empty), so dedup never engaged and Meta
        # retries could double-process. Fixed here.
        msg_id = (msg.get("msg_id") or "").strip()
        if not db.available():
            print(f"[whatsapp] ⛔ DB down — processing synchronously msg_id={msg_id!r}")
            asyncio.create_task(handle_whatsapp_message(msg))
            continue

        result = await db.inbox_insert(
            source     = "whatsapp",
            event_type = "whatsapp.message",
            dedup_key  = f"wa:{msg_id}" if msg_id else "",
            store_id   = "",
            payload    = msg,
            meta       = {},
        )
        if result["inserted"]:
            queued += 1
    return {"status": "ok", "queued": queued}


@router.get("/whatsapp/debug")
async def whatsapp_debug(request: Request):
    """
    Super-admin diagnostic: shows WhatsApp config for all stores. Masks
    the token — only shows if it's set or not.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    result = []
    for s in sm.list_stores():
        sid = s["store_id"]
        cfg = sm.get_ai_config(sid) or {}
        result.append({
            "store_id":       sid,
            "store_name":     s.get("store_name", ""),
            "wa_enabled":     bool(cfg.get("whatsapp_enabled")),
            "wa_phone_id":    cfg.get("whatsapp_phone_id", ""),
            "wa_token_set":   bool(cfg.get("whatsapp_token", "").strip()),
            "wa_verify_token": os.getenv("WHATSAPP_VERIFY_TOKEN", "7ayak-wa"),
            "webhook_url":    f"{os.getenv('BASE_URL','')}/whatsapp/webhook",
        })
    return {"stores": result}


async def handle_whatsapp_message(msg: dict):
    """
    Route one inbound WhatsApp message → bot → send reply. Never raises
    — the inbox drainer logs failures and applies backoff.

    Public (no leading underscore) because the drainer in lifecycle.py
    imports it via main as a redirect.
    """
    import whatsapp as wa
    try:
        phone_id = msg.get("phone_id", "")
        sender   = msg.get("from", "")
        text     = msg.get("text", "")

        # Log metadata only — never the message body (PII / message content, M-17).
        print(f"[whatsapp] 📨 incoming: phone_id={phone_id!r} from={sender!r} chars={len(text)}")

        if not (phone_id and sender and text):
            print(f"[whatsapp] ⚠️ missing required fields — dropped")
            return

        # Resolve which store + which of its WhatsApp numbers received this — a
        # store can connect several, and we MUST reply from the same number.
        store_id, number = sm.find_whatsapp_number(phone_id)
        if not store_id:
            registered = [
                (sid, [n.get("phone_id") for n in sm.get_whatsapp_numbers(sid)])
                for sid in [s["store_id"] for s in sm.list_stores()]
            ]
            print(f"[whatsapp] ❌ no store for phone_id={phone_id!r}")
            print(f"[whatsapp]    registered phone IDs: {registered}")
            return

        token = (number.get("token") or "").strip()
        number_enabled = number.get("enabled", True)
        print(f"[whatsapp] ✅ store={store_id!r} enabled={number_enabled} token={'✓' if token else '✗'}")
        if not number_enabled or not token:
            print(f"[whatsapp] ⛔ disabled or no token — skipping")
            return

        # Stable per-customer session keyed by store + phone — thread persists
        # and shows in the admin inbox just like a widget chat.
        # store_id is REQUIRED in the key: without it, the same phone number
        # would reuse an old session if a merchant reassigns the WhatsApp
        # number to a different Hayyak store.
        session_id = f"wa:{store_id}:{sender}"
        await cs.restore_to_memory(session_id)
        cs.get_or_create(session_id, store_id)
        info = cs.get_customer_info(session_id) or {}
        if not info.get("phone") or info.get("wa_phone_id") != phone_id:
            await cs.set_customer_info(session_id, {
                "name":  msg.get("name", "") or info.get("name", ""),
                "phone": sender,
                "channel": "whatsapp",
                # Remember WHICH of our numbers received this, so an admin reply
                # (and the bot) goes back out from the SAME number (multi-number).
                "wa_phone_id": phone_id,
            })

        # CSAT response intercept — if the most-recent bot msg was a CSAT
        # survey, treat any reply as a rating rather than routing through
        # the agent (bot would reply with something unrelated).
        conv_now   = cs.all_conversations().get(session_id) or {}
        msgs_now   = conv_now.get("messages", [])
        csat_msg   = None
        for prev in reversed(msgs_now):
            role = prev.get("role")
            if role == "user":
                break
            if role == "assistant" and (prev.get("meta") or {}).get("kind") == "csat":
                csat_msg = prev
                break
        if csat_msg:
            interactive_id = msg.get("interactive_id", "") or ""
            rating = _parse_csat_reply(interactive_id, text)
            if rating:
                await cs.add_message(session_id, "user", text or interactive_id, store_id)
                await cs.set_rating(session_id, rating, f"CSAT WhatsApp: {text or interactive_id}")
                csat_meta = csat_msg.get("meta") or {}
                conv_now["rating_employee_id"]   = csat_meta.get("target_agent_id")
                conv_now["rating_employee_name"] = csat_meta.get("target_agent_name", "")
                conv_now["rated_at"]             = _dt.datetime.utcnow().isoformat()
                cs.mark_dirty(session_id)
                await cs.flush(session_id)
                await wa.send_text(token, phone_id, sender, "شكراً لتقييمك 🌷")
                print(f"[whatsapp] ⭐ CSAT recorded: {rating} for store {store_id}")
                return

        if not cs.is_bot_enabled(session_id):
            # Admin took this thread over — just record the message.
            await cs.add_message(session_id, "user", text, store_id)
            return

        agent = sm.get_agent(store_id)
        if agent is None:
            return
        reply = await agent.chat(message=text, session_id=session_id)
        await wa.send_text(token, phone_id, sender, reply)
        print(f"[whatsapp] ↩ replied to {sender} (store {store_id})")
    except Exception as exc:
        print(f"[whatsapp] handle error: {exc}")
        # Auth errors (bad API key) will never succeed on retry — drop them.
        _s = str(exc).lower()
        if "authentication_error" in _s or "invalid x-api-key" in _s or "401" in _s:
            print(f"[whatsapp] ⛔ auth error — not retrying (fix the API key for store {store_id})")
            return
        raise  # let the inbox drainer retry transient errors


async def handle_messenger_message(msg: dict):
    """
    Route one inbound Facebook Messenger / Instagram Direct message → bot →
    reply. Channel-agnostic mirror of handle_whatsapp_message: the same agent
    answers, and the thread shows in the admin inbox tagged by channel. Never
    raises — the inbox drainer logs failures and applies backoff.

    Public (no leading underscore) because the drainer reaches it via
    main._process_inbox_row.
    """
    import messenger as ms
    try:
        channel      = msg.get("channel", "messenger")
        recipient_id = str(msg.get("recipient_id", "") or "")   # page_id / ig_id
        sender       = str(msg.get("from", "") or "")           # PSID / IGSID
        text         = msg.get("text", "")

        # Log metadata only — never the message body (PII / message content, M-17).
        print(f"[{channel}] 📨 incoming: recipient={recipient_id!r} from={sender!r} chars={len(text)}")
        if not (recipient_id and sender and text):
            return

        store_id = sm.find_store_by_page_id(recipient_id)
        if not store_id:
            print(f"[{channel}] ❌ no store for recipient_id={recipient_id!r}")
            return

        cfg     = sm.get_ai_config(store_id) or {}
        enabled = bool(cfg.get("instagram_enabled") if channel == "instagram"
                       else cfg.get("messenger_enabled"))
        # Instagram: prefer the dedicated ig_access_token (Instagram API with
        # Instagram Login → sends via graph.instagram.com); fall back to the
        # linked Facebook Page token (sends via graph.facebook.com/{page_id}).
        ig_login = False
        if channel == "instagram":
            ig_token = (cfg.get("ig_access_token") or "").strip()
            if ig_token:
                token, page_id, ig_login = ig_token, (cfg.get("ig_id") or recipient_id).strip(), True
            else:
                token   = (cfg.get("page_token") or "").strip()
                page_id = (cfg.get("page_id") or recipient_id).strip()
        else:
            token   = (cfg.get("page_token") or "").strip()
            page_id = (cfg.get("page_id") or recipient_id).strip()
        if not (enabled and token):
            print(f"[{channel}] ⛔ disabled or no token for store {store_id!r} "
                  f"(enabled={enabled} token_set={bool(token)})")
            return

        # Handover Protocol: a `standby[]` message means another app is the
        # primary receiver. Claim the thread so our reply can go through. Only
        # applies to the Page transport — the IG-login API (graph.instagram.com)
        # owns the conversation directly and has no handover endpoints.
        if msg.get("standby") and not ig_login:
            took = await ms.claim_thread_control(token, sender)
            print(f"[{channel}] 🤝 standby message — claim_thread_control={'✅' if took else '⚠️ failed'}")

        # Stable per-customer session keyed by store + PSID/IGSID — persists and
        # shows in the admin inbox just like a widget or WhatsApp chat.
        # store_id is REQUIRED: same PSID could be linked to different stores.
        session_id = f"{'ig' if channel == 'instagram' else 'msgr'}:{store_id}:{sender}"
        await cs.restore_to_memory(session_id)
        cs.get_or_create(session_id, store_id)
        info = cs.get_customer_info(session_id) or {}
        # The webhook payload carries only the PSID/IGSID — never a name. Resolve a
        # display name from the Graph API (best-effort) so the admin inbox shows the
        # customer instead of "جلسة <id>". Retried each message until one resolves;
        # set_customer_info ignores an empty name, so a failed lookup is harmless.
        if not (info.get("name") or "").strip():
            name = (msg.get("name", "") or "").strip() or await ms.get_user_profile(
                token, sender, channel=channel, instagram_login=ig_login)
            await cs.set_customer_info(session_id, {"name": name, "channel": channel})

        # CSAT response intercept — if the most-recent bot msg was a CSAT survey,
        # treat the reply as a rating (mirrors WhatsApp/Telegram) instead of
        # routing it through the agent.
        conv_now = cs.all_conversations().get(session_id) or {}
        csat_msg = None
        for prev in reversed(conv_now.get("messages", [])):
            if prev.get("role") == "user":
                break
            if prev.get("role") == "assistant" and (prev.get("meta") or {}).get("kind") == "csat":
                csat_msg = prev
                break
        if csat_msg:
            rating = _parse_csat_reply("", text)
            if rating:
                await cs.add_message(session_id, "user", text, store_id)
                await cs.set_rating(session_id, rating, f"CSAT {channel}: {text}")
                csat_meta = csat_msg.get("meta") or {}
                conv_now["rating_employee_id"]   = csat_meta.get("target_agent_id")
                conv_now["rating_employee_name"] = csat_meta.get("target_agent_name", "")
                conv_now["rated_at"]             = _dt.datetime.utcnow().isoformat()
                cs.mark_dirty(session_id)
                await cs.flush(session_id)
                await ms.send_text(token, page_id, sender, "شكراً لتقييمك 🌷",
                                   channel=channel, instagram_login=ig_login)
                print(f"[{channel}] ⭐ CSAT recorded: {rating} for store {store_id}")
                return

        if not cs.is_bot_enabled(session_id):
            # Admin took this thread over — just record the message.
            await cs.add_message(session_id, "user", text, store_id)
            return

        agent = sm.get_agent(store_id)
        if agent is None:
            return
        reply = await agent.chat(message=text, session_id=session_id)
        sent  = await ms.send_text(token, page_id, sender, reply,
                                   channel=channel, instagram_login=ig_login)
        print(f"[{channel}] {'↩ replied to' if sent else '⚠️ send FAILED to'} "
              f"{sender} (store {store_id})")
    except Exception as exc:
        print(f"[messenger] handle error: {exc}")
