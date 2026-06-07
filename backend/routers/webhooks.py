"""
Webhook routes — Salla + WhatsApp ingest.

Both endpoints follow the Phase 1 insert-then-ack pattern:
  1. Verify the payload (signature for Salla, parse for both)
  2. INSERT into webhook_inbox
  3. Return 200 OK in < 100ms
  4. Drainer processes the row out-of-band

The per-event business logic (registering stores, syncing catalogues,
recording orders, etc) lives in this module too — exported via
process_salla_event() and handle_whatsapp_message() so the inbox
drainer can call them. main.py's _process_inbox_row dispatcher routes
based on the source field.

WhatsApp CSAT parsing (interactive list reply → 1-5) is here because
it's tightly coupled to the WhatsApp message handler.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import hmac
import json as _json
import os

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import conversation_store as cs
import database as db
import notifications as _notif
import store_manager as sm
from store_sync import sync_store


router = APIRouter()


# Store IDs that are reserved and must never be used as real Salla
# merchant IDs (kept in sync with main._RESERVED_IDS).
_RESERVED_IDS = {"super", "admin", "stores", "auth", "default"}


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


def _verify_signature(body: bytes, headers) -> tuple:
    """
    Verify X-Salla-Signature using HMAC-SHA256.
    Returns (ok: bool, detail: str).

    Behaviour:
      - No secret configured → accept (dev mode only, loud warning).
      - Secret configured + signature present → verify strictly.
      - Secret configured + signature ABSENT → REJECT.

    Pre-hardening (before C5) accepted unsigned webhooks by default,
    which let attackers forge app.store.authorize and inject an
    attacker-controlled access_token into any merchant_id. Hard-fail
    is now the default; WEBHOOK_ALLOW_UNSIGNED=true is the dev override.
    """
    secret = os.getenv("SALLA_WEBHOOK_SECRET", "")
    if not secret:
        print("[webhook] ⚠️ SALLA_WEBHOOK_SECRET not set — accepting unsigned webhooks (DEV ONLY)")
        return True, "no_secret_configured"

    sig = headers.get("X-Salla-Signature", "")
    if not sig:
        if os.getenv("WEBHOOK_ALLOW_UNSIGNED", "false").lower() == "true":
            print("[webhook] ⚠️ Missing X-Salla-Signature — accepted (WEBHOOK_ALLOW_UNSIGNED=true)")
            return True, "signature_absent_dev_override"
        print("[webhook] ⛔ Missing X-Salla-Signature — rejected (secret is configured)")
        return False, "signature_required_but_absent"

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        print(f"[webhook] ⛔ Signature mismatch — rejected (got {sig[:16]}…)")
        return False, f"signature_mismatch got={sig[:16]}"

    return True, "signature_ok"


# ─────────────────────────────────────────────────────────────────────────
# Salla per-event handlers
# ─────────────────────────────────────────────────────────────────────────

async def _sync_task(store_id: str, token: str) -> None:
    """Background catalogue sync — lifted from main, used by app.store.authorize."""
    try:
        await sync_store(token, store_id)
        print(f"✅ Store sync completed for {store_id!r}")
    except Exception as e:
        print(f"⚠️ Store sync failed for {store_id!r}: {e}")


async def _handle_store_authorize(merchant_id: str, data: dict):
    """app.store.authorize — store installs / reinstalls the app."""
    access_token  = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    expires       = data.get("expires", 0)
    expires_in    = data.get("expires_in", 0)
    store_info    = data.get("store", {})

    store_id = merchant_id or "default"
    if not access_token:
        print(f"[webhook] app.store.authorize for {store_id!r} — no token in payload")
        return
    if store_id.lower() in _RESERVED_IDS and store_id != "default":
        print(f"[webhook] ⚠️ Reserved store_id {store_id!r} — ignoring authorize event")
        return

    expires_at = ""
    try:
        if expires_in:
            expires_at = (_dt.datetime.utcnow() + _dt.timedelta(seconds=int(expires_in))).isoformat()
        elif expires:
            expires_at = _dt.datetime.utcfromtimestamp(int(expires)).isoformat()
    except Exception:
        pass

    merged_info = {**store_info, "expires_at": expires_at} if expires_at else store_info

    sm.register_store(
        store_id=store_id,
        access_token=access_token,
        refresh_token=refresh_token,
        store_info=merged_info,
    )

    # Directly await the DB save for this critical event so data is never
    # lost even if the server restarts seconds after the webhook.
    if db.available():
        tokens = sm.get_store_info(store_id)
        await db.save_store(store_id, tokens)
        print(f"[webhook] 💾 Store {store_id!r} directly saved to DB")

    asyncio.create_task(_sync_task(store_id, access_token))
    _log_event(store_id, "app.store.authorize", "ok",
               f"token …{access_token[-6:]}  expires={expires}")
    print(f"[webhook] ✅ Store {store_id!r} authorized, sync triggered")


async def _handle_app_uninstalled(merchant_id: str, data: dict):
    """
    app.uninstalled — merchant removed the app. Salla's app review
    REQUIRES that uninstalling deletes the merchant's data. Purge the
    store row + dependent data so we never use the revoked token again.
    """
    store_id = merchant_id or "default"
    if store_id == "default":
        print("[webhook] app.uninstalled for 'default' — skipping purge (env store)")
        return
    try:
        if db.available():
            await db.purge_store(store_id)
        sm.unregister_store(store_id)
        _log_event(store_id, "app.uninstalled", "ok", "store data purged")
        print(f"[webhook] 🗑️ Store {store_id!r} uninstalled — data purged")
    except Exception as e:
        _log_event(store_id, "app.uninstalled", "error", str(e))
        print(f"[webhook] ❌ app.uninstalled purge failed for {store_id!r}: {e}")


async def _handle_app_lifecycle(event: str, merchant_id: str, data: dict):
    """
    Acknowledge remaining app lifecycle events Salla sends + checks for
    during app review: app.installed, app.trial.*, app.subscription.*,
    app.feedback.created, app.settings.updated.
    """
    store_id = merchant_id or "default"
    _log_event(store_id, event, "ok", "acknowledged")
    print(f"[webhook] {event!r} acknowledged for store {store_id!r}")


async def _handle_product_event(event: str, merchant_id: str, data: dict):
    """
    product.* — incremental cache patch instead of full re-sync. Resets
    the per-store agent so the updated catalogue is picked up next chat.
    """
    from store_sync import patch_product_in_cache

    store_id   = merchant_id or "default"
    product_id = data.get("id") or data.get("product_id", "")
    if not product_id:
        return

    is_delete = event == "product.deleted"
    ok = await patch_product_in_cache(store_id, product_id, delete=is_delete)
    status = "ok" if ok else "skip"
    _log_event(store_id, event, status, f"product_id={product_id}")

    if ok:
        sm.reset_agent(store_id)


async def _handle_order_event(event: str, merchant_id: str, data: dict):
    """
    order.* — logs the event with key fields. Could be extended to send
    admin notifications or update the ROI ledger.
    """
    store_id    = merchant_id or "default"
    order_id    = str(data.get("id", ""))
    order_ref   = str(data.get("reference_id", ""))
    status_info = (data.get("status") or {})
    status_name = status_info.get("name", "") if isinstance(status_info, dict) else str(status_info)
    total_info  = (data.get("total") or {})
    total_amt   = total_info.get("amount", "") if isinstance(total_info, dict) else str(total_info)
    currency    = total_info.get("currency", "SAR") if isinstance(total_info, dict) else "SAR"

    detail = f"order_id={order_id}  ref={order_ref}  status={status_name}  total={total_amt} {currency}"
    _log_event(store_id, event, "ok", detail)
    print(f"[webhook] {event!r} — {detail}")


async def _handle_customer_event(event: str, merchant_id: str, data: dict):
    store_id    = merchant_id or "default"
    customer_id = str(data.get("id", ""))
    _log_event(store_id, event, "ok", f"customer_id={customer_id}")
    print(f"[webhook] {event!r} customer={customer_id} store={store_id}")


async def _handle_abandoned_cart(merchant_id: str, data: dict):
    """
    abandoned.cart — customer added items but didn't complete checkout.
    Persists to abandoned_carts (admin dashboard reads it) and fires a
    notify_event so the store owner gets an email if they're subscribed.
    """
    store_id = merchant_id or "default"
    cart_id  = str(data.get("id", ""))
    customer = data.get("customer") or {}
    total    = data.get("total")    or {}

    notification = {
        "id":             cart_id,
        "ts":             _dt.datetime.utcnow().isoformat() + "Z",
        "customer_name":  customer.get("name", "—"),
        "customer_phone": customer.get("mobile", customer.get("phone", "—")),
        "customer_email": customer.get("email", "—"),
        "total":          (total.get("amount", "—") if isinstance(total, dict) else str(total or "—")),
        "currency":       (total.get("currency", "SAR") if isinstance(total, dict) else "SAR"),
        "items_count":    len(data.get("items") or []),
        "age_minutes":    data.get("age_in_minutes", 0),
        "checkout_url":   data.get("checkout_url", ""),
        "status":         data.get("status", "active"),
        "recovered":      False,
    }

    if cart_id:
        await db.save_abandoned_cart(store_id, cart_id, notification)

    _log_event(
        store_id, "abandoned.cart", "ok",
        f"cart_id={cart_id}  customer={notification['customer_name']}  "
        f"total={notification['total']} {notification['currency']}"
    )
    print(
        f"[webhook] 🛒 Abandoned cart {cart_id!r} — "
        f"{notification['customer_name']} — "
        f"{notification['total']} {notification['currency']} — "
        f"store={store_id!r}"
    )

    asyncio.create_task(_notif.notify(store_id, "abandoned_cart", {
        "customer_name": notification["customer_name"],
        "cart_total":    f"{notification['total']} {notification['currency']}",
    }))


async def process_salla_event(event: str, merchant_id: str, data: dict) -> None:
    """
    Single dispatch point for Salla events — called by both the inbox
    drain loop and the synchronous DB-down fallback. Raises on
    unrecoverable errors so the drainer can mark the row failed/dead.
    Returns normally on success (including unhandled events, which are
    acknowledged silently).
    """
    if event == "app.store.authorize":
        await _handle_store_authorize(merchant_id, data)
        return
    if event == "app.updated":
        _log_event(merchant_id or "default", event, "ok", "awaiting app.store.authorize")
        return
    if event == "app.uninstalled":
        await _handle_app_uninstalled(merchant_id, data)
        return
    if event.startswith("product."):
        await _handle_product_event(event, merchant_id, data)
        return
    if event.startswith("order."):
        await _handle_order_event(event, merchant_id, data)
        return
    if event.startswith("customer."):
        await _handle_customer_event(event, merchant_id, data)
        return
    if event == "abandoned.cart":
        await _handle_abandoned_cart(merchant_id, data)
        return
    if event.startswith("app."):
        await _handle_app_lifecycle(event, merchant_id, data)
        return
    _log_event(merchant_id or "default", event, "unhandled")


# ─────────────────────────────────────────────────────────────────────────
# Salla webhook endpoint (insert-then-ack)
# ─────────────────────────────────────────────────────────────────────────

@router.post("/webhook/salla")
async def salla_webhook(request: Request):
    """
    Salla webhook receiver — insert-then-ack.

    Steps:
      1. Verify HMAC-SHA256 signature (hard-fail when secret is set).
      2. Parse JSON envelope.
      3. INSERT into webhook_inbox with (source='salla', dedup_key) UNIQUE.
      4. Return 200 OK in < 100 ms.

    All business logic runs in the inbox drain loop out-of-band. A
    process restart between received-and-processed doesn't lose the
    event: the row stays `pending` and the next worker picks it up.
    """
    body = await request.body()
    body_head = body[:200].decode("utf-8", errors="replace")
    content_type = request.headers.get("Content-Type", "")
    user_agent   = request.headers.get("User-Agent", "")

    sig_ok, sig_detail = _verify_signature(body, request.headers)
    if not sig_ok:
        _log_event("", "", "rejected", f"signature: {sig_detail}",
                   sig_status=sig_detail, body_head=body_head,
                   content_type=content_type, user_agent=user_agent)
        raise HTTPException(401, f"Webhook signature invalid: {sig_detail}")

    try:
        payload = _json.loads(body)
    except Exception as exc:
        _log_event("", "", "error", f"invalid JSON: {exc}",
                   sig_status=sig_detail, body_head=body_head,
                   content_type=content_type, user_agent=user_agent)
        raise HTTPException(400, f"Invalid JSON: {exc}")

    event       = payload.get("event", "")
    merchant_id = str(payload.get("merchant", ""))
    created_at  = payload.get("created_at", "")
    dedup_key   = f"{event}:{merchant_id}:{created_at}"

    print(f"[webhook] {event!r}  merchant={merchant_id or '—'}  ts={created_at}")

    result = await db.inbox_insert(
        source     = "salla",
        event_type = event,
        dedup_key  = dedup_key,
        store_id   = merchant_id,
        payload    = payload,
        meta       = {
            "sig_status":   sig_detail,
            "body_head":    body_head,
            "content_type": content_type,
            "user_agent":   user_agent,
        },
    )

    if not result["inserted"]:
        # Duplicate (Salla retried) OR DB down. Either way: ack 200.
        if db.available():
            print(f"[webhook] duplicate dedup_key={dedup_key} — already in inbox")
            _log_event(merchant_id or "default", event, "duplicate", dedup_key,
                       sig_status=sig_detail, body_head=body_head,
                       content_type=content_type, user_agent=user_agent)
            return {"status": "ok", "duplicate": True, "event": event}
        # DB down: best-effort synchronous fallback.
        print(f"[webhook] ⛔ DB unavailable — falling back to synchronous handler for {event!r}")
        try:
            await process_salla_event(event, merchant_id, payload.get("data") or {})
        except Exception as exc:
            print(f"[webhook] ⛔ synchronous fallback failed: {exc}")
        return {"status": "ok", "event": event, "fallback": "synchronous_db_down"}

    return {"status": "ok", "event": event, "queued": True, "inbox_id": result["id"]}


# ─────────────────────────────────────────────────────────────────────────
# Salla webhook diagnostics
# ─────────────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/webhooks/log")
async def store_webhook_log(store_id: str):
    """Return the newest 200 webhook events for this store from the DB."""
    events = await db.get_webhook_log(store_id=store_id, limit=200)
    return {"store_id": store_id, "count": len(events), "events": events}


@router.get("/webhook/salla/debug")
async def webhook_debug(request: Request):
    """
    Super-admin diagnostic: shows last 50 raw webhook attempts.
    Auth checked inline — sits outside the admin middleware regex.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    attempts = await db.get_webhook_log(store_id=None, limit=50)
    return {
        "webhook_url":    f"{os.getenv('BASE_URL','http://localhost:8000')}/webhook/salla",
        "secret_set":     bool(os.getenv("SALLA_WEBHOOK_SECRET", "")),
        "total_attempts": len(attempts),
        "attempts":       attempts,
    }


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


@router.post("/whatsapp/webhook")
async def whatsapp_incoming(request: Request):
    """
    Persist each incoming WhatsApp message to webhook_inbox, ack 200.

    Meta retries on 5xx for ~24h, so we must respond fast and never lose
    a message. Each individual message becomes its own inbox row (partial
    failure on one doesn't block the rest). The dedup_key is the
    WhatsApp message id, atomic via the unique index.
    """
    import whatsapp as wa
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}

    queued = 0
    for msg in wa.extract_messages(payload):
        msg_id = str(msg.get("id") or msg.get("message_id") or "").strip()
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
            "wa_verify_token": os.getenv("WHATSAPP_VERIFY_TOKEN", "sallabot-wa"),
            "webhook_url":    f"{os.getenv('BASE_URL','')}/whatsapp/webhook",
        })
    return {"stores": result}


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

        print(f"[whatsapp] 📨 incoming: phone_id={phone_id!r} from={sender!r} text={text[:60]!r}")

        if not (phone_id and sender and text):
            print(f"[whatsapp] ⚠️ missing required fields — dropped")
            return

        store_id = sm.find_store_by_whatsapp_phone_id(phone_id)
        if not store_id:
            registered = [
                (sid, (sm.get_ai_config(sid) or {}).get("whatsapp_phone_id", "—"))
                for sid in [s["store_id"] for s in sm.list_stores()]
            ]
            print(f"[whatsapp] ❌ no store for phone_id={phone_id!r}")
            print(f"[whatsapp]    registered phone IDs: {registered}")
            return

        cfg   = sm.get_ai_config(store_id) or {}
        token = (cfg.get("whatsapp_token") or "").strip()
        print(f"[whatsapp] ✅ store={store_id!r} enabled={cfg.get('whatsapp_enabled')} token={'✓' if token else '✗'}")
        if not cfg.get("whatsapp_enabled") or not token:
            print(f"[whatsapp] ⛔ disabled or no token — skipping")
            return

        # Stable per-customer session keyed by phone — thread persists
        # and shows in the admin inbox just like a widget chat.
        session_id = f"wa:{sender}"
        await cs.restore_to_memory(session_id)
        cs.get_or_create(session_id, store_id)
        info = cs.get_customer_info(session_id) or {}
        if not info.get("phone"):
            cs.set_customer_info(session_id, {
                "name":  msg.get("name", "") or info.get("name", ""),
                "phone": sender,
                "channel": "whatsapp",
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
