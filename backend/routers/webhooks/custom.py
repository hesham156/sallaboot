"""Custom-store webhook ingest — for merchants on a self-built store that pushes
catalog + events to 7ayak (حياك) over HTTP.

Two entry points:
  • POST /webhooks/custom/{store_id}/catalog  — full catalog replace (synchronous)
  • POST /webhooks/custom/{store_id}/events   — one event (insert-then-ack via inbox)

Auth: the store must have a live "custom" integration whose `signing_secret`
HMAC-signs the raw request body. Header `X-Hayyak-Signature: sha256=<hexdigest>`.
See docs/custom_store_integration.md for the merchant-facing spec.

Split out alongside the Salla / Zid / Shopify webhook modules."""
from __future__ import annotations
import hashlib
import hmac
import json as _json
from fastapi import HTTPException, Request

import database as db
import store_manager as sm
from routers.webhooks._base import (
    router,
    _log_event,
    _normalize_phone,
    _wa_send,
    record_abandoned_cart,
)


# ── Signature verification ────────────────────────────────────────────────────

async def _authed_secret(store_id: str) -> str:
    """Return the store's custom-integration signing secret, or raise 404 when
    the store has no active custom integration (mirrors the Zid guard)."""
    integrations = await db.get_integrations(store_id)
    custom = integrations.get("custom")
    if not custom:
        _log_event(store_id, "custom", "rejected", "no active custom integration")
        raise HTTPException(404, "No active custom integration for this store")
    return (custom.get("signing_secret") or "").strip()


def _verify_custom_signature(body: bytes, secret: str, headers) -> tuple:
    """
    Verify the HMAC-SHA256 signature over the raw body. Hard-fail when a secret
    is configured (the normal case). Returns (ok, detail).
    """
    if not secret:
        # No secret on file — should not happen (connect always sets one), but
        # fail closed rather than accept unsigned writes.
        return False, "no_signing_secret_configured"
    sig = (headers.get("X-Hayyak-Signature") or "").strip()
    if not sig:
        return False, "signature_required_but_absent"
    if sig.startswith("sha256="):
        sig = sig[len("sha256="):]
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False, f"signature_mismatch got={sig[:16]}"
    return True, "signature_ok"


# ── Event handlers ────────────────────────────────────────────────────────────

def _phone(data: dict) -> str:
    cust = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    raw = (
        data.get("customer_phone") or data.get("phone") or data.get("mobile")
        or cust.get("phone") or cust.get("mobile") or ""
    )
    return _normalize_phone(str(raw))


def _name(data: dict) -> str:
    cust = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    return (
        str(data.get("customer_name") or data.get("name") or cust.get("name") or "").strip()
        or "عزيزي العميل"
    )


async def _handle_product(event: str, store_id: str, data: dict) -> None:
    """product.created|updated|deleted — incremental cache patch + agent reset."""
    import custom_sync as _cs
    deleted = event.endswith(".deleted")
    _cs.patch_custom_product(store_id, data, deleted=deleted)
    sm.reset_agent(store_id)
    _log_event(store_id, f"custom:{event}", "ok", f"product_id={data.get('id','')}")


async def _handle_order(event: str, store_id: str, data: dict) -> None:
    """order.created → confirmation; order.status_updated → status notice."""
    order_ref  = str(data.get("reference_id") or data.get("code") or data.get("id", ""))
    cfg        = sm.get_ai_config(store_id) or {}
    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "متجرنا")
    phone      = _phone(data)
    name       = _name(data)

    if event == "order.created":
        total    = str(data.get("total") or "")
        currency = data.get("currency") or "SAR"
        _log_event(store_id, "custom:order.created", "ok",
                   f"order={order_ref} total={total} {currency}")
        if not phone:
            return
        msg = (
            f"أهلاً {name} 😊\n"
            f"تم استلام طلبك بنجاح في {store_name}!\n\n"
            f"📦 رقم الطلب: #{order_ref}\n"
        )
        if total:
            msg += f"💰 الإجمالي: {total} {currency}\n"
        msg += "\nسنُعلمك فور تجهيز طلبك وإرساله. شكراً لثقتك بنا! 🌟"
        await _wa_send(store_id, cfg, phone, msg)
        return

    # order.status_updated
    status_name = str(data.get("status") or "").strip()
    if isinstance(data.get("status"), dict):
        status_name = str(data["status"].get("name") or "").strip()
    _log_event(store_id, "custom:order.status_updated", "ok",
               f"order={order_ref} status={status_name}")
    if not phone or not status_name:
        return
    msg = (
        f"أهلاً {name} 📬\n"
        f"تحديث على طلبك #{order_ref} في {store_name}:\n\n"
        f"الحالة الجديدة: *{status_name}*\n\n"
        f"للاستفسار تواصل معنا في أي وقت. 😊"
    )
    await _wa_send(store_id, cfg, phone, msg)


async def _handle_cart(store_id: str, data: dict) -> None:
    """cart.abandoned — record + owner email + customer WhatsApp reminder."""
    import custom_sync as _cs
    notification, phone = _cs.custom_cart_to_notification(data)
    if notification["id"]:
        await record_abandoned_cart(store_id, notification, phone=phone)


async def process_custom_event(event: str, store_id: str, data: dict) -> None:
    """
    Single dispatch point for custom-store events — called by the inbox drainer
    (and the synchronous DB-down fallback). Mirrors process_zid_event semantics.
    """
    if not store_id:
        return
    if event.startswith("product."):
        await _handle_product(event, store_id, data)
        return
    if event.startswith("order."):
        await _handle_order(event, store_id, data)
        return
    if event.startswith("cart."):
        await _handle_cart(store_id, data)
        return
    _log_event(store_id, f"custom:{event}", "unhandled")


# ── HTTP endpoints ────────────────────────────────────────────────────────────

@router.post("/webhooks/custom/{store_id}/catalog")
async def custom_catalog(store_id: str, request: Request):
    """
    Full catalog replace. Synchronous: the merchant sent the whole payload, so
    we shape it and write cache_data inline, then return counts.
    """
    body   = await request.body()
    secret = await _authed_secret(store_id)
    ok, detail = _verify_custom_signature(body, secret, request.headers)
    if not ok:
        _log_event(store_id, "custom:catalog", "rejected", f"signature: {detail}")
        raise HTTPException(401, f"Webhook signature invalid: {detail}")

    try:
        payload = _json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Body must be a JSON object")

    import custom_sync as _cs
    result = _cs.apply_catalog(store_id, payload)
    _log_event(store_id, "custom:catalog", "ok",
               f"products={result['products']} categories={result['categories']}")
    return {"status": "ok", **result}


@router.post("/webhooks/custom/{store_id}/events")
async def custom_events(store_id: str, request: Request):
    """
    One incremental event. Insert-then-ack via the inbox (mirrors Salla/Zid);
    falls back to synchronous processing only when the DB is unavailable.

    Body: {"event": "<name>", "data": {...}}
    """
    body   = await request.body()
    secret = await _authed_secret(store_id)
    ok, detail = _verify_custom_signature(body, secret, request.headers)
    if not ok:
        _log_event(store_id, "custom:event", "rejected", f"signature: {detail}")
        raise HTTPException(401, f"Webhook signature invalid: {detail}")

    try:
        payload = _json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    event = str((payload or {}).get("event") or "").strip()
    data  = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not event:
        raise HTTPException(400, "Missing 'event' field")

    dedup_key = f"custom:{store_id}:{event}:{hashlib.sha256(body).hexdigest()[:16]}"
    print(f"[custom] webhook event={event!r} store={store_id!r}")

    result = await db.inbox_insert(
        source="custom", event_type=event, dedup_key=dedup_key,
        store_id=store_id, payload=data, meta={},
    )
    if not result["inserted"] and not db.available():
        print(f"[custom] ⛔ DB unavailable — handling {event!r} synchronously")
        try:
            await process_custom_event(event, store_id, data)
        except Exception as exc:
            print(f"[custom] ⛔ synchronous fallback failed: {exc}")
    return {"status": "ok", "event": event}
