"""Salla webhook ingest + per-event business logic (store authorize/uninstall, app settings linking, product/order/customer/shipment notifications).

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
import database as db
import store_manager as sm
from store_sync import sync_store
from routers.webhooks._base import (
    router,
    log,
    _RESERVED_IDS,
    _log_event,
    _extract_phone,
    _extract_name,
    _wa_send,
    record_abandoned_cart,
)



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
    secret = os.getenv("SALLA_WEBHOOK_SECRET", "").strip()   # tolerate stray whitespace in the env value
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
            # Token strategy: Salla sends the webhook credential in the
            # Authorization header instead of signing the body. That credential
            # MUST be a DEDICATED value (SALLA_WEBHOOK_TOKEN), separate from the
            # HMAC signing secret. Reusing the signing secret as a bearer token
            # leaks it to anything that captures request headers (proxies, log
            # shippers, APM) — and the same secret then forges signatures (M3).
            #
            # Backward-compat: when SALLA_WEBHOOK_TOKEN is unset we still accept
            # the signing secret as the token so existing installs keep working,
            # but warn loudly so the operator provisions a separate token and
            # updates it in Salla's webhook settings. Set SALLA_WEBHOOK_TOKEN to
            # complete the separation.
            dedicated = os.getenv("SALLA_WEBHOOK_TOKEN", "").strip()
            if dedicated:
                expected_token = dedicated
            else:
                expected_token = secret
                log.warning("webhook_token_uses_signing_secret_deprecated")
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

    # Canonical model: store_id IS the Salla merchant_id everywhere (the widget,
    # webhooks, and the agent all key on it), so there's ONE store per merchant —
    # no parallel account, no merchant→account map, no duplicates. If this
    # merchant's owner already signed up on 7ayak (a placeholder keyed by their
    # email), fold that placeholder INTO this Salla store: carry its chosen
    # password + email, then delete it, so the merchant ends with ONE account
    # they log into by email. Only on first install.
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
        print(f"[webhook] 🔗 carried 7ayak password onto Salla store {store_id!r}")

    if placeholder_id and await db.merge_placeholder_into(placeholder_id, store_id):
        sm.unregister(placeholder_id)
        # Seamless: the merchant's open session (token bound to the deleted
        # placeholder) migrates to this store without a re-login.
        await db.record_account_forward(placeholder_id, store_id)

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
            await db.clear_salla_merchant_map(store_id)   # drop any legacy breadcrumb
        sm.unregister_store(store_id)
        _log_event(store_id, "app.uninstalled", "ok", "store data purged")
        print(f"[webhook] 🗑️ Store {store_id!r} uninstalled — data purged")
    except Exception as e:
        _log_event(store_id, "app.uninstalled", "error", str(e))
        print(f"[webhook] ❌ app.uninstalled handling failed for {store_id!r}: {e}")


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
    Bind a signup-first 7ayak account to its Salla store. Returns (ok, detail).

    Canonical model: `store_id` IS the Salla merchant_id, and that is the ONE
    store for this merchant (widget, webhooks, and agent all key on it). The
    7ayak account is resolved by the SECRET API key, then its login identity
    (email + chosen password) is moved onto the Salla store and the now-duplicate
    placeholder account is merged in + deleted. The merchant ends with ONE store,
    logged into by email — no parallel account, no merchant→account map, no
    duplicates. Shared by the app.settings.updated webhook and the validation URL.
    """
    # Resolve the account ONLY by the API key — the secret proof of ownership.
    # Email is non-secret and must never be the lookup credential (finding C-4).
    home = await db.find_store_by_api_key(api_key) if api_key else None
    if not home:
        return False, "no 7ayak account matched the API key provided"
    if str(home) == str(store_id):
        return True, "already linked"   # Salla-first: the account already IS this store

    # The Salla store must exist (created by app.store.authorize). Reconcile from
    # the shared DB in case it registered on another web replica / the worker.
    if not sm.is_registered(store_id):
        await sm.sync_one_from_db(store_id)
    if not sm.is_registered(store_id):
        return False, "salla_store_not_ready"

    # Never hijack a home account that is itself already a live store on any
    # e-commerce platform (incl. Salla) — a signup placeholder has none.
    home_integrations = await db.get_integrations(home)
    if any(home_integrations.get(p) for p in ("salla", "shopify", "zid", "woocommerce")):
        return False, f"home account {home!r} already has another platform"

    # Move the login identity (email + password + API key) from the placeholder
    # account onto the canonical Salla store.
    link_email = email or (sm.get_store_info(home) or {}).get("owner_email", "")
    pwd        = sm.get_admin_password_hash(home)
    if link_email:
        await db.set_store_owner_email(store_id, link_email)
        await db.set_store_owner_email(home, "")
    if pwd:
        await sm.set_admin_password(store_id, pwd)
    await db.set_api_key(home, None)        # clear first to satisfy the unique index
    if api_key:
        await db.set_api_key(store_id, api_key)
    sm.reset_agent(store_id)

    # Merge the placeholder's bot config/training into the Salla store and delete
    # it — but only when it's a pure signup placeholder (no Salla token of its
    # own). The merchant is then left with ONE account.
    merged = ""
    if not sm.get_access_token(home):
        if await db.merge_placeholder_into(home, store_id):
            sm.unregister(home)
            # Seamless: migrate the merchant's open session off the deleted
            # placeholder to this store (resolve-link / "تحديث الربط" button).
            await db.record_account_forward(home, store_id)
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


async def _handle_abandoned_cart(merchant_id: str, data: dict):
    """
    abandoned.cart (Salla) — customer added items but didn't complete checkout.
    Normalises the payload and hands off to the shared recorder.
    """
    store_id = merchant_id or "default"
    customer = data.get("customer") or {}
    total    = data.get("total")    or {}

    notification = {
        "id":             str(data.get("id", "")),
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
    phone = _extract_phone(customer) or notification["customer_phone"]
    await record_abandoned_cart(store_id, notification, phone=phone)


async def process_salla_event(event: str, merchant_id: str, data: dict) -> None:
    """
    Single dispatch point for Salla events — called by both the inbox
    drain loop and the synchronous DB-down fallback. Raises on
    unrecoverable errors so the drainer can mark the row failed/dead.
    Returns normally on success (including unhandled events, which are
    acknowledged silently).
    """
    # Canonical model: store_id IS the Salla merchant_id everywhere, so every
    # handler keys on merchant_id directly — no resolution needed.
    if event == "app.store.authorize":
        await _handle_store_authorize(merchant_id, data)
        return
    if event == "app.updated":
        _log_event(merchant_id or "default", event, "ok", "awaiting app.store.authorize")
        return
    if event == "app.uninstalled":
        await _handle_app_uninstalled(merchant_id, data)
        return
    if event == "app.settings.updated":
        await _handle_app_settings_updated(merchant_id, data)
        return
    if event.startswith("app."):
        await _handle_app_lifecycle(event, merchant_id, data)
        return

    store_id = merchant_id

    if event.startswith("product."):
        await _handle_product_event(event, store_id, data)
        return
    if event.startswith("order."):
        await _handle_order_event(event, store_id, data)
        return
    if event.startswith("customer."):
        await _handle_customer_event(event, store_id, data)
        return
    if event == "abandoned.cart":
        await _handle_abandoned_cart(store_id, data)
        return
    if event.startswith("shipment."):
        await _handle_shipment_event(event, store_id, data)
        return
    _log_event(store_id or "default", event, "unhandled")


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
