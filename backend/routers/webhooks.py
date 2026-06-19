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
import base64
import datetime as _dt
import hashlib
import hmac
import json as _json
import os
import secrets as _secrets

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import conversation_store as cs
import database as db
import notifications as _notif
import store_manager as sm
from store_sync import sync_store
import log as _logmod

log = _logmod.get_logger("backend.webhooks")


router = APIRouter()


# Store IDs that are reserved and must never be used as real Salla
# merchant IDs (kept in sync with main._RESERVED_IDS). The marketing
# demo store ("sallabot") is also reserved — see bootstrap.py.
_RESERVED_IDS = {"super", "admin", "stores", "auth", "default", "sallabot"}


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
    Verify a Salla webhook using whichever security strategy the request
    declares. Returns (ok: bool, detail: str).

    Salla supports two strategies (see X-Salla-Security-Strategy header):
      - Signature (default): X-Salla-Signature = HMAC-SHA256(body, secret).
      - Token: Authorization: Bearer <token>, where <token> equals the
        webhook secret. Salla App Market apps frequently ship with the
        Token strategy, in which case NO X-Salla-Signature is ever sent —
        the strict signature-only check then rejected every event with
        signature_required_but_absent.

    Behaviour:
      - No secret configured → accept (dev mode only, loud warning).
      - Secret configured + a matching credential present → verify strictly.
      - Secret configured + credential ABSENT → REJECT (unless dev override).

    Pre-hardening (before C5) accepted unsigned webhooks by default,
    which let attackers forge app.store.authorize and inject an
    attacker-controlled access_token into any merchant_id. Hard-fail
    is now the default; WEBHOOK_ALLOW_UNSIGNED=true is the dev override.
    """
    secret = os.getenv("SALLA_WEBHOOK_SECRET", "")
    if not secret:
        log.warning("webhook_no_secret_dev_mode")
        return True, "no_secret_configured"

    sig = headers.get("X-Salla-Signature", "")

    # ── Token strategy ──────────────────────────────────────────────────
    # When Salla uses the Token strategy it sends the secret in the
    # Authorization header instead of signing the body. Accept it when no
    # HMAC signature is present so the two strategies don't conflict.
    if not sig:
        auth = headers.get("Authorization", "")
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else auth.strip()
        if token:
            # A dedicated token can be set via SALLA_WEBHOOK_TOKEN; otherwise
            # the same SALLA_WEBHOOK_SECRET doubles as the Token value, which
            # is how Salla pre-fills it for App Market apps.
            expected_token = os.getenv("SALLA_WEBHOOK_TOKEN", "") or secret
            if hmac.compare_digest(expected_token, token):
                return True, "token_ok"
            log.warning("webhook_token_mismatch", extra={"got_prefix": token[:16]})
            return False, f"token_mismatch got={token[:16]}"

    if not sig:
        if os.getenv("WEBHOOK_ALLOW_UNSIGNED", "false").lower() == "true":
            log.warning("webhook_unsigned_dev_override")
            return True, "signature_absent_dev_override"
        log.warning("webhook_signature_missing")
        return False, "signature_required_but_absent"

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        # Truncate the received sig to a prefix — full sig might end up
        # in a downstream log shipper, no need to expose it.
        log.warning("webhook_signature_mismatch", extra={"got_prefix": sig[:16]})
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
    store_info    = data.get("store", {}) or {}

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

    # Owner email: Salla nests it under user.email in some payloads and
    # under store.email in others. Try both — empty fall-through is fine,
    # the store can be email-linked later by the unified login fallback or
    # by re-authorising.
    user_blob   = data.get("user") or {}
    owner_email = (
        (user_blob.get("email")  or "").strip().lower()
        or (store_info.get("email") or "").strip().lower()
    )

    # Account unification: if this merchant already signed up on 7ayak (a
    # platform-less placeholder keyed by their email) and is now installing
    # Salla, detach the email from that placeholder and carry its chosen
    # password onto this Salla store so they keep ONE login. Runs BEFORE
    # register_store so the email match resolves to the placeholder, not the
    # store we're about to create. Only applied on first install.
    is_new = not sm.is_registered(store_id)
    carried_pwd, placeholder_id = (
        await sm.reassign_owner_email(owner_email, store_id) if is_new else ("", "")
    )

    await sm.register_store(
        store_id=store_id,
        access_token=access_token,
        refresh_token=refresh_token,
        store_info=merged_info,
        owner_email=owner_email,
    )

    if carried_pwd:
        await sm.set_admin_password(store_id, carried_pwd)
        print(f"[webhook] 🔗 linked existing 7ayak account → Salla store {store_id!r}")

    # Merge the signup placeholder's data into this Salla store and delete the
    # duplicate row — same cleanup the app-settings link path does, so the
    # primary install path doesn't leave an orphaned account behind.
    if placeholder_id:
        if await db.merge_placeholder_into(placeholder_id, store_id):
            sm.unregister(placeholder_id)

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
    app.feedback.created.
    """
    store_id = merchant_id or "default"
    _log_event(store_id, event, "ok", "acknowledged")
    print(f"[webhook] {event!r} acknowledged for store {store_id!r}")


def extract_app_settings_fields(settings) -> tuple:
    """
    Pull (email, api_key) out of a Salla app-settings dict. Salla derives a
    field's programmatic key from its (often Arabic) label, so the slugs are
    unpredictable — e.g. "الايميل" → `alaemel`, "الـ API Key" → `al_api_key`.
    Match on shape/intent rather than an exact key name:
      • api_key  → key contains both "api" and "key", or a known key slug.
      • email    → value looks like an email (contains "@"), or key mentions mail.
    Shared by the app.settings.updated webhook and the App-Settings Validation URL.
    """
    settings = settings if isinstance(settings, dict) else {}
    email = ""
    api_key = ""
    _API_SLUGS = {"api_key", "apikey", "api-key", "apikey", "key", "token", "al_api_key"}
    for raw_k, raw_v in settings.items():
        if raw_v is None or isinstance(raw_v, (dict, list)):
            continue
        key = str(raw_k).strip().lower().replace("-", "_").replace(" ", "_")
        val = str(raw_v).strip()
        if not val:
            continue
        if not api_key and (("api" in key and "key" in key) or key in _API_SLUGS):
            api_key = val
        elif not email and ("@" in val or "email" in key or "mail" in key or "aemel" in key):
            email = val
    return email.strip().lower(), api_key


async def link_store_via_app_settings(store_id: str, email: str, api_key: str) -> tuple:
    """
    Bind a Salla store to an existing 7ayak account from the App-Settings
    fields. Returns (ok: bool, detail: str).

    Resolves the "home" 7ayak account by API key (primary — a secret proof of
    ownership) or by email (fallback), then moves its login identity — email +
    chosen password + the API key — onto this Salla store and detaches them
    from the home account, so the merchant signs in with their 7ayak
    credentials and sees this store's data.

    Non-destructive: the home account's data is left intact (reachable by
    store_id); a home account already running another platform is never
    touched. Shared by the app.settings.updated webhook and the validation URL.
    """
    home = await db.find_store_by_api_key(api_key) if api_key else None
    if not home and email:
        home = await db.find_store_by_owner_email(email)

    if not home:
        return False, "no 7ayak account matched the email/API key provided"
    if str(home) == str(store_id):
        return True, "already linked"

    # Guard: the Salla store must already exist (created by app.store.authorize)
    # before we move identity onto it. Without this, a link that arrives before
    # the authorize webhook clears the home account's email + api_key while the
    # SET on the not-yet-existent Salla store is a silent no-op (registry miss /
    # 0-row UPDATE) — gutting the merchant's account so they can no longer log in
    # by email, and leaving two orphaned rows. Bail out without touching anything.
    if not sm.is_registered(store_id):
        return False, "salla_store_not_ready"

    # Never hijack a live store that already runs on another platform.
    home_integrations = await db.get_integrations(home)
    if any(home_integrations.get(p) for p in ("shopify", "zid", "woocommerce")):
        return False, f"home account {home!r} already has another platform"

    # Move identity (email + password + API key) home → this Salla store.
    link_email = email or (sm.get_store_info(home) or {}).get("owner_email", "")
    pwd        = sm.get_admin_password_hash(home)
    if link_email:
        await db.set_store_owner_email(store_id, link_email)
        await db.set_store_owner_email(home, "")
    if pwd:
        await sm.set_admin_password(store_id, pwd)
    # Transfer the linking key (clear home first to satisfy the unique index)
    # so the dashboard + any future settings update resolve straight here.
    await db.set_api_key(home, None)
    if api_key:
        await db.set_api_key(store_id, api_key)
    sm.reset_agent(store_id)

    # De-duplicate: the home account was a pure signup placeholder (no platform
    # checked above, no access token) — migrate any bot config/training it has
    # onto the Salla store and delete the now-empty row so the merchant is left
    # with ONE account instead of a duplicate. Only when it's truly a placeholder
    # (an access token means it's a real store we must never delete).
    merged = ""
    if not sm.get_access_token(home):
        if await db.merge_placeholder_into(home, store_id):
            sm.unregister(home)
            merged = " (placeholder merged + removed)"

    return True, f"linked to 7ayak account (was {home!r}){merged}"


async def _handle_app_settings_updated(merchant_id: str, data: dict):
    """
    app.settings.updated — the merchant filled the app's settings form in their
    Salla dashboard (their 7ayak email + API key) to bind THIS Salla store to
    their existing 7ayak account. Salla delivers the form fields under
    data.settings as key/value pairs.
    """
    store_id = merchant_id or "default"
    email, api_key = extract_app_settings_fields(data.get("settings"))
    ok, detail = await link_store_via_app_settings(store_id, email, api_key)
    _log_event(store_id, "app.settings.updated", "ok" if ok else "skip", detail)
    if ok and detail.startswith("linked"):
        print(f"[webhook] 🔗 Salla store {store_id!r} linked to 7ayak account via App Settings (detail={detail})")


async def _handle_product_event(event: str, merchant_id: str, data: dict):
    """
    product.* — incremental cache patch instead of full re-sync. Resets
    the per-store agent so the updated catalogue is picked up next chat.
    product.review.added → sends a thank-you WhatsApp message to the reviewer.
    """
    if event == "product.review.added":
        await _handle_review_event(event, merchant_id, data)
        return

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


async def _send_invoice_email(store_id: str, order_id: str, order_ref: str) -> None:
    """Fire-and-forget: ask Salla to send the invoice PDF to the customer's email."""
    from salla_client import SallaClient
    try:
        token = sm.get_access_token(store_id)
        if not token:
            return
        client = SallaClient(token, store_id=store_id)
        await client.send_order_invoice(int(order_id))
        log.info("invoice_email_sent", extra={"store_id": store_id, "order_ref": order_ref})
    except Exception as exc:
        log.warning("invoice_email_failed", extra={"store_id": store_id,
                                                    "order_ref": order_ref, "error": str(exc)})


async def _handle_order_event(event: str, merchant_id: str, data: dict):
    """order.* — logs + sends WhatsApp notifications to the customer."""
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

    cfg = sm.get_ai_config(store_id) or {}

    if event == "order.created":
        await _wa_order_created(store_id, cfg, data, order_ref, total_amt, currency)
        # Classify customer as buyer
        try:
            from customer_followup import classify_customer
            customer = data.get("customer") or {}
            phone = _extract_phone(customer)
            name  = _extract_name(customer)
            cust_id = str(customer.get("id") or phone or "")
            if cust_id:
                await classify_customer(
                    store_id=store_id, customer_id=cust_id,
                    customer_name=name, phone=phone,
                    order_count=1, last_order_id=order_id,
                    last_order_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                )
        except Exception as _ce:
            log.warning("classify_buyer_error", extra={"error": str(_ce)})
        # Auto-send invoice email if customer has an email address on file
        customer_email = (data.get("customer") or {}).get("email", "")
        if customer_email and order_id:
            asyncio.create_task(_send_invoice_email(store_id, order_id, order_ref))
    elif event in ("order.status.updated", "order.updated"):
        await _wa_order_status(store_id, cfg, data, order_ref, status_name)
    elif event in ("order.invoice.created", "invoice.created"):
        await _wa_invoice_created(store_id, cfg, data, order_ref)


async def _wa_order_created(store_id: str, cfg: dict, data: dict,
                             order_ref: str, total: str, currency: str):
    """تأكيد الطلب الجديد للعميل عبر واتساب."""
    phone = _extract_phone(data.get("customer") or data)
    if not phone:
        return
    customer = data.get("customer") or {}
    name = customer.get("name", "") or _extract_name(customer) or "عزيزي العميل"
    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "متجرنا")
    msg = (
        f"أهلاً {name} 😊\n"
        f"تم استلام طلبك بنجاح في {store_name}!\n\n"
        f"📦 رقم الطلب: #{order_ref}\n"
        f"💰 الإجمالي: {total} {currency}\n\n"
        f"سنُعلمك فور تجهيز طلبك وإرساله. شكراً لثقتك بنا! 🌟"
    )
    await _wa_send(store_id, cfg, phone, msg)


async def _wa_order_status(store_id: str, cfg: dict, data: dict,
                            order_ref: str, status_name: str):
    """إشعار تحديث حالة الطلب للعميل."""
    phone = _extract_phone(data.get("customer") or data)
    if not phone or not status_name:
        return
    customer = data.get("customer") or {}
    name = customer.get("name", "") or _extract_name(customer) or "عزيزي العميل"
    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "متجرنا")
    msg = (
        f"أهلاً {name} 📬\n"
        f"تحديث على طلبك #{order_ref} في {store_name}:\n\n"
        f"الحالة الجديدة: *{status_name}*\n\n"
        f"للاستفسار تواصل معنا في أي وقت. 😊"
    )
    await _wa_send(store_id, cfg, phone, msg)


async def _wa_invoice_created(store_id: str, cfg: dict, data: dict, order_ref: str):
    """إشعار إنشاء الفاتورة للعميل."""
    phone = _extract_phone(data.get("customer") or data)
    if not phone:
        return
    customer = data.get("customer") or {}
    name = customer.get("name", "") or _extract_name(customer) or "عزيزي العميل"
    invoice_url = data.get("invoice_url") or data.get("url", "")
    store_info  = sm.get_store_info(store_id) or {}
    store_name  = store_info.get("store_name", "متجرنا")
    msg = (
        f"أهلاً {name} 🧾\n"
        f"تم إنشاء فاتورتك للطلب #{order_ref} في {store_name}.\n"
    )
    if invoice_url:
        msg += f"\nيمكنك تحميل الفاتورة من هنا:\n{invoice_url}"
    await _wa_send(store_id, cfg, phone, msg)


async def _handle_customer_event(event: str, merchant_id: str, data: dict):
    store_id    = merchant_id or "default"
    customer_id = str(data.get("id", ""))
    _log_event(store_id, event, "ok", f"customer_id={customer_id}")
    print(f"[webhook] {event!r} customer={customer_id} store={store_id}")

    if event == "customer.created":
        await _wa_customer_welcome(store_id, data)


async def _wa_customer_welcome(store_id: str, data: dict):
    """Send a welcome WhatsApp message to a newly registered customer."""
    phone = _extract_phone(data)
    if not phone:
        return
    first  = (data.get("first_name") or "").strip()
    last   = (data.get("last_name")  or "").strip()
    name   = (first + " " + last).strip() or data.get("name", "عزيزي العميل")
    cfg    = sm.get_ai_config(store_id) or {}
    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "متجرنا")
    msg = (
        f"مرحباً {name} 👋\n"
        f"أهلاً وسهلاً بك في {store_name}!\n"
        f"يسعدنا انضمامك إلينا. إذا احتجت أي مساعدة في طلباتك أو منتجاتنا، "
        f"فريقنا دائماً في خدمتك. 🌟"
    )
    await _wa_send(store_id, cfg, phone, msg)


async def _handle_shipment_event(event: str, merchant_id: str, data: dict):
    """shipment.created — يُعلم العميل برقم التتبع وشركة الشحن."""
    store_id = merchant_id or "default"
    shipment_id = str(data.get("id", ""))
    tracking    = data.get("tracking_number") or data.get("tracking", "")
    company     = (data.get("company") or {}).get("name", "") if isinstance(data.get("company"), dict) else str(data.get("company") or "")
    order_id    = str(data.get("order_id", "") or (data.get("order") or {}).get("id", ""))
    order_ref   = str((data.get("order") or {}).get("reference_id", order_id))

    _log_event(store_id, event, "ok",
               f"shipment={shipment_id}  tracking={tracking}  company={company}  order={order_ref}")
    print(f"[webhook] {event!r} — shipment={shipment_id} order={order_ref} store={store_id}")

    cfg      = sm.get_ai_config(store_id) or {}
    customer = data.get("customer") or (data.get("order") or {}).get("customer") or {}
    phone    = _extract_phone(customer)
    if not phone:
        return
    name       = customer.get("name", "") or _extract_name(customer) or "عزيزي العميل"
    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "متجرنا")

    msg = (
        f"أهلاً {name} 🚚\n"
        f"تم شحن طلبك #{order_ref} من {store_name}!\n\n"
    )
    if company:
        msg += f"شركة الشحن: {company}\n"
    if tracking:
        msg += f"رقم التتبع: *{tracking}*\n"
    msg += "\nيمكنك تتبع شحنتك للاطلاع على موعد التسليم. 📦"
    await _wa_send(store_id, cfg, phone, msg)


async def _handle_review_event(event: str, merchant_id: str, data: dict):
    """product.review.added — شكر العميل على تقييمه."""
    store_id   = merchant_id or "default"
    review_id  = str(data.get("id", ""))
    rating     = data.get("rating", "")
    product    = (data.get("product") or {}).get("name", "") if isinstance(data.get("product"), dict) else ""
    customer   = data.get("customer") or {}

    _log_event(store_id, event, "ok",
               f"review={review_id}  rating={rating}  product={product}")
    print(f"[webhook] {event!r} — review={review_id} rating={rating} store={store_id}")

    cfg   = sm.get_ai_config(store_id) or {}
    phone = _extract_phone(customer)
    if not phone:
        return
    name       = customer.get("name", "") or _extract_name(customer) or "عزيزي العميل"
    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "متجرنا")

    stars = "⭐" * int(rating) if str(rating).isdigit() else ""
    msg = (
        f"شكراً جزيلاً {name}! {stars}\n"
        f"نقدر كثيراً وقتك في تقييم تجربتك مع {store_name}.\n"
    )
    if product:
        msg += f"تقييمك لـ \"{product}\" يساعدنا على التحسين المستمر. 🙏"
    await _wa_send(store_id, cfg, phone, msg)


# ── WhatsApp shared helpers ───────────────────────────────────────────────────

def _extract_phone(data: dict) -> str:
    """
    Extract a dialable phone number from a Salla customer/order dict.
    Salla sends mobile_code (+966) + mobile (5xxxxxxxx) separately.
    Falls back to phone / mobile fields as-is.
    """
    if not data:
        return ""
    mobile_code = str(data.get("mobile_code") or "").strip().lstrip("+")
    mobile      = str(data.get("mobile")      or "").strip()
    if mobile_code and mobile:
        return f"+{mobile_code}{mobile}"
    phone = str(data.get("phone") or data.get("mobile") or "").strip()
    # Normalize Saudi numbers without country code
    if phone.startswith("05") and len(phone) == 10:
        phone = "+966" + phone[1:]
    return phone


def _extract_name(data: dict) -> str:
    first = (data.get("first_name") or "").strip()
    last  = (data.get("last_name")  or "").strip()
    return (first + " " + last).strip()


async def _wa_send(store_id: str, cfg: dict, phone: str, text: str) -> None:
    """Send a WhatsApp text if the store has WhatsApp configured."""
    if not phone:
        return
    token    = (cfg.get("whatsapp_token")    or "").strip()
    phone_id = (cfg.get("whatsapp_phone_id") or "").strip()
    enabled  = bool(cfg.get("whatsapp_enabled"))
    if not (token and phone_id and enabled):
        return
    import whatsapp as wa
    try:
        await wa.send_text(token, phone_id, phone, text)
        print(f"[webhook] WhatsApp sent to {phone} for store {store_id!r}")
    except Exception as exc:
        print(f"[webhook] WhatsApp send failed for {phone}: {exc}")


async def _recovery_coupon_line(store_id: str, cfg: dict) -> str:
    """
    Issue a one-use, 24h recovery coupon for an abandoned cart (only when the
    merchant opted into AI coupons) and return a WhatsApp-ready line. Best-effort:
    returns "" on any failure so the reminder still goes out without a coupon.

    Caps mirror agent._issue_coupon so the cart channel can't hand out a bigger
    discount than the in-chat one. Requires the coupons.read_write scope.
    """
    if not cfg.get("coupons_enabled"):
        return ""
    token = sm.get_access_token(store_id)
    if not token:
        return ""
    try:
        pct       = max(1, min(int(cfg.get("coupon_max_percent", 15) or 15), 90))
        cap       = float(cfg.get("coupon_max_discount_value", 200) or 200)
        min_order = float(cfg.get("coupon_min_order", 0) or 0)
    except (TypeError, ValueError):
        pct, cap, min_order = 15, 200.0, 0.0

    expiry_dt = (_dt.datetime.utcnow() + _dt.timedelta(days=1)).replace(
        hour=23, minute=59, second=59, microsecond=0)
    code = "CART" + _secrets.token_hex(3).upper()
    try:
        from salla_client import SallaClient
        client = SallaClient(token, store_id=store_id)
        await client.create_coupon(
            code=code, amount=pct, coupon_type="percentage",
            expiry_date=expiry_dt.strftime("%Y-%m-%d %H:%M:%S"),
            maximum_amount=cap, minimum_amount=(min_order or None),
            usage_limit=1, usage_limit_per_user=1,
        )
    except Exception as exc:
        print(f"[cart-coupon] failed store={store_id!r}: {exc}")
        return ""

    line = f"هدية خاصة لإتمام طلبك: استخدم كود *{code}* لخصم {pct}٪"
    if min_order:
        line += f" (للطلبات من {int(min_order)} ريال فأكثر)"
    line += " — صالح ٢٤ ساعة فقط ⏳"
    return line


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

    # WhatsApp reminder to the customer
    phone = _extract_phone(customer) or notification["customer_phone"]
    if phone and phone != "—":
        cfg        = sm.get_ai_config(store_id) or {}
        store_info = sm.get_store_info(store_id) or {}
        store_name = store_info.get("store_name", "متجرنا")
        name       = customer.get("name", "").strip() or "عزيزي العميل"
        total_str  = f"{notification['total']} {notification['currency']}"
        checkout   = notification["checkout_url"]

        msg = (
            f"مرحباً {name} 👋\n"
            f"لاحظنا أنك تركت سلة التسوق في {store_name} بدون إتمام الطلب.\n\n"
            f"إجمالي سلتك: *{total_str}*\n"
        )
        # Optional AI recovery coupon (opt-in per store) — created before the
        # checkout link so the customer sees the incentive right next to it.
        coupon_line = await _recovery_coupon_line(store_id, cfg)
        if coupon_line:
            msg += f"\n🎁 {coupon_line}\n"
        if checkout:
            msg += f"\nأكمل طلبك الآن: {checkout}"
        msg += "\n\nنحن هنا لمساعدتك إذا كان لديك أي استفسار 😊"

        asyncio.create_task(_wa_send(store_id, cfg, phone, msg))


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
    if event.startswith("shipment."):
        await _handle_shipment_event(event, merchant_id, data)
        return
    if event == "app.settings.updated":
        await _handle_app_settings_updated(merchant_id, data)
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
# Phone normalisation shared by Shopify + Zid handlers
# ─────────────────────────────────────────────────────────────────────────

def _normalize_phone(raw: str) -> str:
    """
    Best-effort E.164 normaliser for Shopify/Zid customer phones.
    Salla sends mobile_code+mobile separately (handled by _extract_phone);
    Shopify/Zid send a single string that's usually already E.164 but may
    be a bare Saudi number.
    """
    p = (raw or "").strip().replace(" ", "").replace("-", "")
    if not p:
        return ""
    if p.startswith("+"):
        return p
    if p.startswith("00"):
        return "+" + p[2:]
    if p.startswith("966"):
        return "+" + p
    if p.startswith("05") and len(p) == 10:
        return "+966" + p[1:]
    if p.startswith("5") and len(p) == 9:
        return "+966" + p
    return p


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
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}

    obj    = payload.get("object", "")
    queued = 0

    # ── Messenger / Instagram ────────────────────────────────────────────
    if obj in ("page", "instagram"):
        for msg in ms.extract_messages(payload):
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
            await cs.set_customer_info(session_id, {
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

        print(f"[{channel}] 📨 incoming: recipient={recipient_id!r} from={sender!r} text={text[:60]!r}")
        if not (recipient_id and sender and text):
            return

        store_id = sm.find_store_by_page_id(recipient_id)
        if not store_id:
            print(f"[{channel}] ❌ no store for recipient_id={recipient_id!r}")
            return

        cfg     = sm.get_ai_config(store_id) or {}
        token   = (cfg.get("page_token") or "").strip()
        page_id = (cfg.get("page_id") or recipient_id).strip()
        enabled = bool(cfg.get("instagram_enabled") if channel == "instagram"
                       else cfg.get("messenger_enabled"))
        if not (enabled and token):
            print(f"[{channel}] ⛔ disabled or no page_token for store {store_id!r}")
            return

        # Stable per-customer session keyed by PSID/IGSID — persists and shows
        # in the admin inbox just like a widget or WhatsApp chat.
        session_id = f"{'ig' if channel == 'instagram' else 'msgr'}:{sender}"
        await cs.restore_to_memory(session_id)
        cs.get_or_create(session_id, store_id)
        info = cs.get_customer_info(session_id) or {}
        if not info.get("channel"):
            await cs.set_customer_info(session_id, {
                "name":    msg.get("name", "") or info.get("name", ""),
                "channel": channel,
            })

        if not cs.is_bot_enabled(session_id):
            # Admin took this thread over — just record the message.
            await cs.add_message(session_id, "user", text, store_id)
            return

        agent = sm.get_agent(store_id)
        if agent is None:
            return
        reply = await agent.chat(message=text, session_id=session_id)
        await ms.send_text(token, page_id, sender, reply, channel=channel)
        print(f"[{channel}] ↩ replied to {sender} (store {store_id})")
    except Exception as exc:
        print(f"[messenger] handle error: {exc}")
