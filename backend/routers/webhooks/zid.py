"""Zid webhook ingest + per-event handlers (product, order, customer).

Split out of the original single-file routers/webhooks.py."""
from __future__ import annotations
import hashlib
import json as _json
from fastapi import HTTPException, Request
import database as db
import store_manager as sm
from routers.webhooks._base import (
    router,
    _log_event,
    _extract_name,
    _normalize_phone,
    _wa_send,
)



# ─────────────────────────────────────────────────────────────────────────
# Zid per-store webhooks
# ─────────────────────────────────────────────────────────────────────────
# register_zid_webhooks() points every event at
#   {BASE_URL}/webhooks/zid/{store_id}/{event_with_dot_as_underscore}
# e.g. order.create → /webhooks/zid/<id>/order_create
# Zid does not provide a per-webhook HMAC, so we validate that the target
# store actually has a live Zid integration before queueing the event.
# ─────────────────────────────────────────────────────────────────────────

def _zid_unwrap(payload: dict) -> dict:
    """Zid wraps the resource under varying keys depending on the event."""
    if not isinstance(payload, dict):
        return {}
    for key in ("data", "order", "product", "customer", "resource"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            return inner
    return payload


def _zid_phone(data: dict) -> str:
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    raw = (
        data.get("mobile") or data.get("phone")
        or customer.get("mobile") or customer.get("phone") or ""
    )
    return _normalize_phone(str(raw))


def _zid_name(data: dict) -> str:
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    return (
        str(data.get("name") or customer.get("name") or "").strip()
        or _extract_name(customer)
        or "عزيزي العميل"
    )


async def _handle_zid_product(event: str, store_id: str, data: dict):
    """product.create|update|delete — incremental cache patch + agent reset."""
    import zid_sync as _zs
    deleted = event.endswith(".delete")
    await _zs.patch_zid_product(store_id, data, deleted=deleted)
    sm.reset_agent(store_id)
    _log_event(store_id, f"zid:{event}", "ok", f"product_id={data.get('id','')}")


async def _handle_zid_order(event: str, store_id: str, data: dict):
    """order.create → confirmation; order.status.update → status notice."""
    order_ref = str(data.get("code") or data.get("reference_id") or data.get("id", ""))
    cfg        = sm.get_ai_config(store_id) or {}
    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "متجرنا")
    phone      = _zid_phone(data)
    name       = _zid_name(data)

    if event == "order.create":
        total_blob = data.get("order_total") or data.get("total") or {}
        total = (total_blob.get("value") if isinstance(total_blob, dict)
                 else str(total_blob or ""))
        currency = (total_blob.get("currency", "SAR") if isinstance(total_blob, dict) else "SAR")
        _log_event(store_id, "zid:order.create", "ok",
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

    # order.status.update
    status_blob = data.get("order_status") or data.get("status") or {}
    status_name = (status_blob.get("name") if isinstance(status_blob, dict)
                   else str(status_blob or "")).strip()
    _log_event(store_id, "zid:order.status.update", "ok",
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


async def _handle_zid_customer(store_id: str, data: dict):
    """customer.create — welcome WhatsApp message."""
    _log_event(store_id, "zid:customer.create", "ok", f"customer={data.get('id','')}")
    phone = _zid_phone(data)
    if not phone:
        return
    cfg        = sm.get_ai_config(store_id) or {}
    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "متجرنا")
    name       = _zid_name(data)
    msg = (
        f"مرحباً {name} 👋\n"
        f"أهلاً وسهلاً بك في {store_name}!\n"
        f"يسعدنا انضمامك إلينا. إذا احتجت أي مساعدة في طلباتك أو منتجاتنا، "
        f"فريقنا دائماً في خدمتك. 🌟"
    )
    await _wa_send(store_id, cfg, phone, msg)


async def process_zid_event(event: str, store_id: str, data: dict) -> None:
    """
    Single dispatch point for Zid webhook events — called by the inbox
    drainer (and the synchronous DB-down fallback). Mirrors
    process_shopify_event / process_salla_event semantics.
    """
    if not store_id:
        return
    if event.startswith("product."):
        await _handle_zid_product(event, store_id, data)
        return
    if event.startswith("order."):
        await _handle_zid_order(event, store_id, data)
        return
    if event.startswith("customer."):
        await _handle_zid_customer(store_id, data)
        return
    _log_event(store_id, f"zid:{event}", "unhandled")


@router.post("/webhooks/zid/{store_id}/{event}")
async def zid_webhook(store_id: str, event: str, request: Request):
    """
    Zid per-store webhook receiver — insert-then-ack (mirrors Salla).
    Validates the store has a live Zid integration (Zid has no per-webhook
    HMAC), dedupes on a body hash, processes out-of-band.
    """
    body = await request.body()
    try:
        payload = _json.loads(body)
    except Exception:
        payload = {}

    # event path encodes dots as underscores: order_status_update → order.status.update
    event_norm = event.replace("_", ".")

    # Lightweight auth: only accept events for stores we actually connected to Zid.
    integrations = await db.get_integrations(store_id)
    if not integrations.get("zid"):
        _log_event(store_id, f"zid:{event_norm}", "rejected", "no active zid integration")
        raise HTTPException(404, "No active Zid integration for this store")

    data      = _zid_unwrap(payload)
    dedup_key = f"zid:{store_id}:{event_norm}:{hashlib.sha256(body).hexdigest()[:16]}"

    print(f"[zid] webhook event={event_norm!r} store={store_id!r}")

    result = await db.inbox_insert(
        source="zid", event_type=event_norm, dedup_key=dedup_key,
        store_id=store_id, payload=data, meta={},
    )
    if not result["inserted"] and not db.available():
        print(f"[zid] ⛔ DB unavailable — handling {event_norm!r} synchronously")
        try:
            await process_zid_event(event_norm, store_id, data)
        except Exception as exc:
            print(f"[zid] ⛔ synchronous fallback failed: {exc}")
    return {"status": "ok", "event": event_norm}
