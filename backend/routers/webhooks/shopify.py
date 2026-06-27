"""Shopify webhook ingest + per-topic handlers (uninstall, product, order, customer, fulfillment).

Split out of the original single-file routers/webhooks.py."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json as _json
import os
from fastapi import HTTPException, Request
import database as db
import store_manager as sm
from routers.webhooks._base import (
    router,
    log,
    _log_event,
    _extract_name,
    _normalize_phone,
    _wa_send,
)



# ─────────────────────────────────────────────────────────────────────────
# Shopify per-store webhooks
# ─────────────────────────────────────────────────────────────────────────
# register_shopify_webhooks() points every topic at
#   {BASE_URL}/webhooks/shopify/{store_id}/{topic_with_slash_as_underscore}
# e.g. products/create → /webhooks/shopify/<id>/products_create
# ─────────────────────────────────────────────────────────────────────────

def _verify_shopify_webhook(body: bytes, headers) -> tuple[bool, str]:
    """
    Verify Shopify's webhook HMAC (base64 SHA-256 over the raw body, signed
    with the app's client secret). Mirrors _verify_signature semantics:
      - no secret configured → accept (dev mode, loud warning)
      - secret set + header present → strict verify
      - secret set + header absent → reject
    NB: this is base64, unlike the OAuth callback HMAC which is hex.
    """
    secret = os.getenv("SHOPIFY_CLIENT_SECRET", "")
    if not secret:
        log.warning("shopify_webhook_no_secret_dev_mode")
        return True, "no_secret_configured"
    received = headers.get("X-Shopify-Hmac-Sha256", "")
    if not received:
        log.warning("shopify_webhook_signature_missing")
        return False, "signature_absent"
    digest   = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    if not hmac.compare_digest(expected, received):
        log.warning("shopify_webhook_signature_mismatch")
        return False, "signature_mismatch"
    return True, "signature_ok"


async def _handle_shopify_uninstall(store_id: str, data: dict):
    """
    app/uninstalled — merchant removed the app from their Shopify store.
    Shopify's app review REQUIRES that uninstall stops all access. The
    access_token is already revoked by Shopify, so we just drop our stored
    integration (and the product cache the bot was using). We do NOT purge
    the whole 7ayak account: unlike Salla, the store_id here is the merchant's
    7ayak account — they may re-connect or keep using other channels.
    """
    try:
        await db.remove_integration(store_id, "shopify")
        sm.set_cache(store_id, {})   # bot no longer answers with stale catalogue
        sm.reset_agent(store_id)
        _log_event(store_id, "shopify:app/uninstalled", "ok", "integration removed")
        print(f"[shopify] 🗑️ store={store_id!r} uninstalled — integration removed")
    except Exception as e:
        _log_event(store_id, "shopify:app/uninstalled", "error", str(e))
        print(f"[shopify] ❌ uninstall cleanup failed for {store_id!r}: {e}")
        raise


async def _handle_shopify_product(store_id: str, data: dict, deleted: bool):
    """products/create|update|delete — incremental cache patch + agent reset."""
    import shopify_sync as _ss
    await _ss.patch_shopify_product(store_id, data, deleted=deleted)
    sm.reset_agent(store_id)
    _log_event(store_id, f"shopify:product:{'delete' if deleted else 'upsert'}",
               "ok", f"product_id={data.get('id','')}")


async def _handle_shopify_order_created(store_id: str, data: dict):
    """orders/create — WhatsApp order confirmation to the customer."""
    order_ref = data.get("name") or f"#{data.get('order_number', data.get('id', ''))}"
    total     = str(data.get("total_price") or data.get("current_total_price") or "")
    currency  = data.get("currency", "SAR")
    customer  = data.get("customer") or {}
    name      = _extract_name(customer) or "عزيزي العميل"
    phone     = _normalize_phone(
        customer.get("phone")
        or data.get("phone")
        or (data.get("shipping_address") or {}).get("phone")
        or (data.get("billing_address")  or {}).get("phone")
        or ""
    )
    _log_event(store_id, "shopify:orders/create", "ok",
               f"order={order_ref} total={total} {currency}")
    if not phone:
        return
    cfg        = sm.get_ai_config(store_id) or {}
    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "متجرنا")
    msg = (
        f"أهلاً {name} 😊\n"
        f"تم استلام طلبك بنجاح في {store_name}!\n\n"
        f"📦 رقم الطلب: {order_ref}\n"
    )
    if total:
        msg += f"💰 الإجمالي: {total} {currency}\n"
    msg += "\nسنُعلمك فور تجهيز طلبك وإرساله. شكراً لثقتك بنا! 🌟"
    await _wa_send(store_id, cfg, phone, msg)


async def _handle_shopify_customer_created(store_id: str, data: dict):
    """customers/create — welcome WhatsApp message."""
    name  = _extract_name(data) or "عزيزي العميل"
    phone = _normalize_phone(
        data.get("phone") or (data.get("default_address") or {}).get("phone") or ""
    )
    _log_event(store_id, "shopify:customers/create", "ok", f"customer={data.get('id','')}")
    if not phone:
        return
    cfg        = sm.get_ai_config(store_id) or {}
    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "متجرنا")
    msg = (
        f"مرحباً {name} 👋\n"
        f"أهلاً وسهلاً بك في {store_name}!\n"
        f"يسعدنا انضمامك إلينا. إذا احتجت أي مساعدة في طلباتك أو منتجاتنا، "
        f"فريقنا دائماً في خدمتك. 🌟"
    )
    await _wa_send(store_id, cfg, phone, msg)


async def _handle_shopify_fulfillment(store_id: str, data: dict):
    """fulfillments/create — order shipped → WhatsApp tracking to the customer
    (parity with Salla's shipment.created)."""
    order_ref = data.get("name") or f"#{data.get('order_id', '')}"
    company   = data.get("tracking_company") or ""
    tracking  = data.get("tracking_number") or (data.get("tracking_numbers") or [""])[0] or ""
    track_url = data.get("tracking_url") or (data.get("tracking_urls") or [""])[0] or ""
    dest      = data.get("destination") or {}
    phone     = _normalize_phone(dest.get("phone") or data.get("phone") or "")
    name      = dest.get("name") or _extract_name(dest) or "عزيزي العميل"

    _log_event(store_id, "shopify:fulfillments/create", "ok",
               f"order={order_ref} tracking={tracking} company={company}")
    if not phone:
        return
    cfg        = sm.get_ai_config(store_id) or {}
    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "متجرنا")
    msg = (
        f"أهلاً {name} 🚚\n"
        f"تم شحن طلبك {order_ref} من {store_name}!\n\n"
    )
    if company:
        msg += f"شركة الشحن: {company}\n"
    if tracking:
        msg += f"رقم التتبع: *{tracking}*\n"
    if track_url:
        msg += f"رابط التتبع: {track_url}\n"
    msg += "\nيمكنك تتبع شحنتك للاطلاع على موعد التسليم. 📦"
    await _wa_send(store_id, cfg, phone, msg)


async def process_shopify_event(topic: str, store_id: str, data: dict) -> None:
    """
    Single dispatch point for Shopify webhook topics — called by the inbox
    drainer (and the synchronous DB-down fallback). Raises on unrecoverable
    errors so the drainer can retry; returns normally otherwise (including
    unhandled topics, acknowledged silently).
    """
    if not store_id:
        return
    if topic == "app/uninstalled":
        await _handle_shopify_uninstall(store_id, data)
        return
    if topic == "fulfillments/create":
        await _handle_shopify_fulfillment(store_id, data)
        return
    if topic in ("products/create", "products/update"):
        await _handle_shopify_product(store_id, data, deleted=False)
        return
    if topic == "products/delete":
        await _handle_shopify_product(store_id, data, deleted=True)
        return
    if topic == "orders/create":
        await _handle_shopify_order_created(store_id, data)
        return
    if topic == "orders/updated":
        # Orders are read live from Shopify in the dashboard, so there's no
        # local order cache to patch. Avoid WhatsApp here — orders/updated
        # fires on every edit and we have no prior state to diff against,
        # which would spam the customer. Log only.
        _log_event(store_id, "shopify:orders/updated", "ok", f"order={data.get('name','')}")
        return
    if topic == "customers/create":
        await _handle_shopify_customer_created(store_id, data)
        return
    _log_event(store_id, f"shopify:{topic}", "unhandled")


@router.post("/webhooks/shopify/{store_id}/{topic}")
async def shopify_webhook(store_id: str, topic: str, request: Request):
    """
    Shopify per-store webhook receiver — insert-then-ack (mirrors Salla).
    HMAC-verified, deduped on X-Shopify-Webhook-Id, processed out-of-band.
    """
    body = await request.body()
    ok, detail = _verify_shopify_webhook(body, request.headers)
    if not ok:
        _log_event(store_id, f"shopify:{topic}", "rejected", f"hmac: {detail}",
                   sig_status=detail)
        raise HTTPException(401, f"Invalid Shopify webhook HMAC: {detail}")

    try:
        payload = _json.loads(body)
    except Exception:
        payload = {}

    # X-Shopify-Topic is authoritative (e.g. "products/create"); fall back to
    # the path param where slashes were encoded as underscores.
    topic_norm = request.headers.get("X-Shopify-Topic", "") or topic.replace("_", "/")
    webhook_id = request.headers.get("X-Shopify-Webhook-Id", "")
    dedup_key  = (
        f"shopify:{webhook_id}" if webhook_id
        else f"shopify:{store_id}:{topic_norm}:{hashlib.sha256(body).hexdigest()[:16]}"
    )

    print(f"[shopify] webhook topic={topic_norm!r} store={store_id!r}")

    result = await db.inbox_insert(
        source="shopify", event_type=topic_norm, dedup_key=dedup_key,
        store_id=store_id, payload=payload, meta={"sig_status": detail},
    )
    if not result["inserted"] and not db.available():
        # DB down — best-effort synchronous fallback so we don't lose uninstall.
        print(f"[shopify] ⛔ DB unavailable — handling {topic_norm!r} synchronously")
        try:
            # Shopify posts the resource object as the body directly (no envelope).
            await process_shopify_event(topic_norm, store_id, payload)
        except Exception as exc:
            print(f"[shopify] ⛔ synchronous fallback failed: {exc}")
    return {"status": "ok", "topic": topic_norm}
