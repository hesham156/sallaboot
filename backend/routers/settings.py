"""
Store settings routes: store info, AI config, brain, training,
notifications, pricing, password, token status/refresh, super reset.
"""
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form

import auth as _auth
import database as db
import store_manager as sm
import store_brain as brain
import smart_router
from store_sync import sync_store
import notifications as _notif
from models import (
    AIConfigRequest, CustomKnowledgeRequest, TrainingTextRequest,
    NotificationSettingsRequest, PasswordChangeRequest,
)
from routers.deps import audit, CONTENT_TYPES, MAX_FILE_MB, UPLOAD_DIR

router = APIRouter()


# ── Store info ────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/info")
async def get_store_info_endpoint(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    stores = sm.list_stores()
    found = next((s for s in stores if s["store_id"] == store_id), None)
    if not found:
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    return found


# ── AI config ─────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/settings/ai")
async def get_ai_settings(store_id: str):
    cfg = sm.get_ai_config(store_id)
    groq_set      = bool(cfg.get("groq_api_key"))
    anthropic_set = bool(cfg.get("anthropic_api_key"))
    openai_set    = bool(cfg.get("openai_api_key"))
    if groq_set:
        provider = "groq"
    elif anthropic_set:
        provider = "anthropic"
    elif openai_set:
        provider = "openai"
    else:
        provider = "env"
    store_type = (cfg.get("store_type") or "").strip().lower()
    if not store_type:
        store_type = "printing" if cfg.get("pricing_config") else "general"
    import whatsapp as _wa
    base = os.getenv("BASE_URL", "").rstrip("/")
    return {
        "groq_api_key":      "••••" if groq_set      else "",
        "anthropic_api_key": "••••" if anthropic_set else "",
        "openai_api_key":    "••••" if openai_set    else "",
        "ai_model":          cfg.get("ai_model",  ""),
        "bot_name":          cfg.get("bot_name",  ""),
        "provider":          provider,
        "store_type":        store_type,
        "whatsapp_enabled":    bool(cfg.get("whatsapp_enabled")),
        "whatsapp_phone_id":   cfg.get("whatsapp_phone_id", ""),
        "whatsapp_token":      "••••" if cfg.get("whatsapp_token") else "",
        "whatsapp_waba_id":    cfg.get("whatsapp_waba_id", ""),
        "whatsapp_webhook":    (base + "/whatsapp/webhook") if base else "/whatsapp/webhook",
        "whatsapp_verify_token": _wa.VERIFY_TOKEN,
    }


@router.put("/admin/{store_id}/settings/ai")
async def update_ai_settings(store_id: str, req: AIConfigRequest, request: Request):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    existing = sm.get_ai_config(store_id)

    groq_key      = (req.groq_api_key      or "").strip()
    anthropic_key = (req.anthropic_api_key or "").strip()
    openai_key    = (req.openai_api_key    or "").strip()

    config = dict(existing)
    config.update({
        "groq_api_key":      groq_key      or existing.get("groq_api_key",      ""),
        "anthropic_api_key": anthropic_key or existing.get("anthropic_api_key", ""),
        "openai_api_key":    openai_key    or existing.get("openai_api_key",    ""),
        "ai_model":          (req.ai_model  or "").strip() or existing.get("ai_model",  ""),
        "bot_name":          (req.bot_name  or "").strip() or existing.get("bot_name",  ""),
    })

    if req.store_type is not None:
        st = req.store_type.strip().lower()
        if st in ("printing", "general"):
            config["store_type"] = st

    if req.whatsapp_phone_id is not None:
        config["whatsapp_phone_id"] = req.whatsapp_phone_id.strip()
    if req.whatsapp_enabled is not None:
        config["whatsapp_enabled"] = bool(req.whatsapp_enabled)
    if req.whatsapp_token is not None and req.whatsapp_token.strip():
        config["whatsapp_token"] = req.whatsapp_token.strip()
    if req.whatsapp_waba_id is not None:
        config["whatsapp_waba_id"] = req.whatsapp_waba_id.strip()

    if groq_key:
        config["anthropic_api_key"] = ""
        config["openai_api_key"]    = ""
    elif anthropic_key:
        config["groq_api_key"]   = ""
        config["openai_api_key"] = ""
    elif openai_key:
        config["groq_api_key"]      = ""
        config["anthropic_api_key"] = ""

    sm.set_ai_config(store_id, config)
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, config)

    _changed: list[str] = []
    for field in ("groq_api_key", "anthropic_api_key", "openai_api_key", "whatsapp_token"):
        if (existing.get(field) or "") != (config.get(field) or ""):
            _changed.append(field)
    other_changes = {}
    for field in ("ai_model", "bot_name", "store_type", "whatsapp_enabled", "whatsapp_phone_id"):
        if (existing.get(field) or None) != (config.get(field) or None):
            other_changes[field] = config.get(field)
    if _changed or other_changes:
        await audit(request, "update_ai_settings", target_store=store_id, details={
            "secret_fields_changed": _changed,
            "other_changes":         other_changes,
        })

    return {"status": "ok", "message": "تم حفظ إعدادات الذكاء الاصطناعي ✅"}


# ── AI Brain ──────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/settings/brain")
async def get_ai_brain(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    return brain.preview_knowledge(store_id)


@router.put("/admin/{store_id}/settings/brain")
async def update_ai_brain(store_id: str, req: CustomKnowledgeRequest):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    brain.set_custom_knowledge(store_id, req.custom_knowledge)
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, sm.get_ai_config(store_id))
    return {"status": "ok", "message": "تم حفظ ذاكرة المتجر ✅"}


@router.post("/admin/{store_id}/settings/brain/retrain")
async def retrain_ai_brain(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    token = sm.get_access_token(store_id)
    if not token:
        raise HTTPException(400, "لا يوجد access token — لا يمكن المزامنة")
    try:
        data = await sync_store(token, store_id)
        sm.reset_agent(store_id)
        return {
            "status":          "ok",
            "products_synced": data.get("products_count", 0),
            "categories":      len(data.get("categories", [])),
            "overview":        brain.get_overview(store_id),
            "message":         "تم تحديث ذاكرة المتجر بأحدث المنتجات ✅",
        }
    except Exception as e:
        raise HTTPException(500, f"فشل التحديث: {type(e).__name__}: {e}")


# ── Training ──────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/settings/training")
async def list_bot_training(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    items = await db.list_training(store_id)
    return {"count": len(items), "items": items}


@router.post("/admin/{store_id}/settings/training/text")
async def add_text_training(store_id: str, req: TrainingTextRequest):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    if req.kind not in ("instruction", "faq"):
        raise HTTPException(400, "kind must be 'instruction' or 'faq'")
    title   = (req.title or "").strip()
    content = (req.content or "").strip()
    if not (title or content):
        raise HTTPException(400, "العنوان أو المحتوى مطلوب")
    new_id = await db.add_training(store_id, req.kind, title, content)
    if new_id is None:
        raise HTTPException(503, "تعذّر الحفظ — قاعدة البيانات غير متاحة")
    sm.reset_agent(store_id)
    smart_router.invalidate_faq_cache(store_id)
    return {"status": "ok", "id": new_id, "message": "تمت إضافة التدريب ✅"}


@router.post("/admin/{store_id}/settings/training/file")
async def upload_training_file(
    store_id: str,
    file:  UploadFile = File(...),
    title: str        = Form(default=""),
):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    filename = file.filename or "training.bin"
    suffix   = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".txt", ".md", ".csv", ".log"):
        raise HTTPException(400, "نوع الملف غير مدعوم. الأنواع المتاحة: PDF, TXT, MD, CSV")

    contents = await file.read()
    if len(contents) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"حجم الملف يتجاوز الحد ({MAX_FILE_MB} MB)")

    file_id      = str(uuid.uuid4())
    content_type = CONTENT_TYPES.get(suffix, "application/octet-stream")
    db_saved = False
    if db.available():
        db_saved = await db.save_upload(
            file_id=file_id, filename=filename, content_type=content_type,
            data=contents, store_id=store_id, session_id="",
        )

    import bot_training as bt
    text, parse_err = bt.extract_text(filename, contents)
    if parse_err:
        print(f"[training] file {filename!r} parsed with warning: {parse_err}")

    if not text and not db_saved:
        raise HTTPException(500, "تعذّر حفظ الملف ولم يمكن استخراج النص")

    display_title = (title or filename).strip() or filename
    new_id = await db.add_training(
        store_id, "file", display_title, text,
        file_id=file_id if db_saved else "",
        file_name=filename,
    )
    if new_id is None:
        raise HTTPException(503, "تعذّر حفظ سجل التدريب — قاعدة البيانات غير متاحة")

    sm.reset_agent(store_id)
    return {
        "status":     "ok",
        "id":         new_id,
        "file_id":    file_id if db_saved else "",
        "filename":   filename,
        "size_chars": len(text),
        "warning":    parse_err,
        "message":    "تم رفع الملف وقراءته بنجاح ✅" if text else "تم رفع الملف (لم يُستخرج نص)",
    }


@router.patch("/admin/{store_id}/settings/training/{training_id}")
async def toggle_training(store_id: str, training_id: int, payload: dict):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    ok = await db.update_training_enabled(training_id, bool(payload.get("enabled", True)))
    if not ok:
        raise HTTPException(500, "تعذّر التحديث")
    sm.reset_agent(store_id)
    smart_router.invalidate_faq_cache(store_id)
    return {"status": "ok"}


@router.delete("/admin/{store_id}/settings/training/{training_id}")
async def delete_training_entry(store_id: str, training_id: int):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    ok, deleted_file_id = await db.delete_training(training_id)
    if not ok:
        raise HTTPException(500, "تعذّر الحذف")
    sm.reset_agent(store_id)
    smart_router.invalidate_faq_cache(store_id)
    return {"status": "ok", "deleted_file_id": deleted_file_id}


# ── Notifications ─────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/settings/notifications")
async def get_notification_settings(store_id: str):
    cfg = sm.get_ai_config(store_id) or {}
    return {
        "email_enabled":         bool(cfg.get("notify_email_enabled")),
        "email":                 cfg.get("notify_email", ""),
        "webhook_enabled":       bool(cfg.get("notify_webhook_enabled")),
        "webhook_url":           cfg.get("notify_webhook_url", ""),
        "notify_new_conv":       bool(cfg.get("notify_new_conv", True)),
        "notify_low_rating":     bool(cfg.get("notify_low_rating", True)),
        "notify_llm_budget":     bool(cfg.get("notify_llm_budget", True)),
        "notify_abandoned_cart": bool(cfg.get("notify_abandoned_cart", True)),
    }


@router.put("/admin/{store_id}/settings/notifications")
async def update_notification_settings(store_id: str, req: NotificationSettingsRequest):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    cfg = dict(sm.get_ai_config(store_id) or {})
    email = (req.email or req.email_address or "").strip()
    cfg.update({
        "notify_email_enabled":   bool(req.email_enabled),
        "notify_email":           email,
        "notify_webhook_enabled": bool(req.webhook_enabled),
        "notify_webhook_url":     (req.webhook_url or "").strip(),
        "notify_new_conv":        bool(req.notify_new_conv or req.on_new_conversation),
        "notify_low_rating":      bool(req.notify_low_rating or req.on_low_rating),
        "notify_llm_budget":      bool(req.notify_llm_budget),
        "notify_abandoned_cart":  bool(req.notify_abandoned_cart or req.on_abandoned_cart),
    })
    sm.set_ai_config(store_id, cfg)
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, cfg)
    return {"status": "ok", "message": "تم حفظ إعدادات الإشعارات ✅"}


@router.post("/admin/{store_id}/settings/notifications/test")
async def test_notification(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    try:
        ok = await _notif.notify(store_id, "test", {
            "message": "هذا إشعار تجريبي من لوحة التحكم ✅",
        })
        return {"status": "ok" if ok else "failed", "sent": ok}
    except Exception as e:
        raise HTTPException(500, f"فشل الإرسال: {e}")


# ── WhatsApp Events ───────────────────────────────────────────────────────────

_WA_EVENTS = [
    "customer_welcome",
    "new_order",
    "order_status",
    "invoice_created",
    "shipment_created",
    "review_added",
    "abandoned_cart",
    "verification_code",
]

@router.get("/admin/{store_id}/settings/whatsapp-events")
async def get_whatsapp_events(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    cfg = sm.get_ai_config(store_id) or {}
    events = {}
    for key in _WA_EVENTS:
        events[key] = {
            "enabled": bool(cfg.get(f"wa_event_{key}_enabled",
                            key not in ("invoice_created", "shipment_created",
                                        "review_added", "verification_code"))),
            "template": cfg.get(f"wa_event_{key}_template", ""),
        }
    return {"events": events}


@router.put("/admin/{store_id}/settings/whatsapp-events/{event_key}")
async def update_whatsapp_event(store_id: str, event_key: str, body: dict):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    if event_key not in _WA_EVENTS:
        raise HTTPException(400, f"حدث غير معروف: {event_key!r}")
    cfg = dict(sm.get_ai_config(store_id) or {})
    if "enabled" in body:
        cfg[f"wa_event_{event_key}_enabled"] = bool(body["enabled"])
    if "template" in body:
        cfg[f"wa_event_{event_key}_template"] = str(body["template"])
    sm.set_ai_config(store_id, cfg)
    await db.save_ai_config(store_id, cfg)
    return {"status": "ok"}


@router.post("/admin/{store_id}/settings/whatsapp-events/{event_key}/test")
async def test_whatsapp_event(store_id: str, event_key: str, request: Request):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    if event_key not in _WA_EVENTS:
        raise HTTPException(400, f"حدث غير معروف: {event_key!r}")

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    # Parse test_phone → mobile_code + mobile
    raw_phone = str(body.get("test_phone", "")).strip().replace(" ", "").replace("-", "")
    if raw_phone.startswith("+"):
        raw_phone = raw_phone[1:]
    # Detect country code: 2-3 digits before the local number
    if raw_phone.startswith("966"):
        mobile_code, mobile = "966", raw_phone[3:]
    elif raw_phone.startswith("20"):
        mobile_code, mobile = "20",  raw_phone[2:]
    elif raw_phone.startswith("971"):
        mobile_code, mobile = "971", raw_phone[3:]
    elif raw_phone.startswith("974"):
        mobile_code, mobile = "974", raw_phone[3:]
    elif raw_phone.startswith("965"):
        mobile_code, mobile = "965", raw_phone[3:]
    elif raw_phone.startswith("973"):
        mobile_code, mobile = "973", raw_phone[3:]
    elif raw_phone.startswith("968"):
        mobile_code, mobile = "968", raw_phone[3:]
    else:
        mobile_code, mobile = "966", raw_phone  # fallback

    def _customer():
        return {"name": "اختبار تجريبي", "mobile_code": mobile_code, "mobile": mobile}

    from routers.webhooks import process_salla_event
    salla_event_map = {
        "customer_welcome":  ("customer.created",      {"id": 0, "first_name": "اختبار", "last_name": "تجريبي", "mobile_code": mobile_code, "mobile": mobile}),
        "new_order":         ("order.created",         {"id": 0, "reference_id": "TEST-001", "total": {"amount": "100", "currency": "SAR"}, "customer": _customer()}),
        "order_status":      ("order.status.updated",  {"id": 0, "reference_id": "TEST-001", "status": {"name": "قيد التوصيل"}, "customer": _customer()}),
        "invoice_created":   ("order.invoice.created", {"id": 0, "order": {"reference_id": "TEST-001"}, "customer": _customer()}),
        "shipment_created":  ("shipment.created",      {"id": 0, "tracking_number": "123456789", "company": {"name": "أرامكس"}, "order": {"reference_id": "TEST-001"}, "customer": _customer()}),
        "review_added":      ("product.review.added",  {"id": 0, "rating": 5, "product": {"name": "منتج اختبار"}, "customer": _customer()}),
        "abandoned_cart":    ("abandoned.cart",        {"id": "cart-test", "customer": {**_customer(), "name": "اختبار"}, "total": {"amount": "250", "currency": "SAR"}, "checkout_url": ""}),
        "verification_code": (None, None),
    }
    salla_event, payload = salla_event_map.get(event_key, (None, None))
    if not salla_event:
        return {"status": "skipped", "message": "هذا الحدث يُدار بواسطة Salla مباشرة"}

    # Pre-flight: verify WhatsApp is configured before running the event
    cfg      = sm.get_ai_config(store_id) or {}
    token    = (cfg.get("whatsapp_token")    or "").strip()
    phone_id = (cfg.get("whatsapp_phone_id") or "").strip()
    enabled  = bool(cfg.get("whatsapp_enabled"))

    if not enabled:
        raise HTTPException(400, "WhatsApp غير مفعّل لهذا المتجر — فعّله من إعدادات WhatsApp أولاً")
    if not token:
        raise HTTPException(400, "whatsapp_token غير محدد — أضفه من إعدادات WhatsApp")
    if not phone_id:
        raise HTTPException(400, "whatsapp_phone_id غير محدد — أضفه من إعدادات WhatsApp")
    if not (mobile or raw_phone):
        raise HTTPException(400, "أدخل رقم الاختبار أولاً")

    try:
        await process_salla_event(salla_event, store_id, payload)
        return {"status": "ok", "message": f"✅ تم إرسال رسالة الاختبار إلى +{mobile_code}{mobile}"}
    except Exception as e:
        raise HTTPException(500, f"فشل الاختبار: {e}")


# ── Pricing ───────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/settings/pricing")
async def get_pricing_settings(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    cfg = sm.get_ai_config(store_id) or {}
    return {
        "pricing_config": cfg.get("pricing_config", {}),
        "currency":       cfg.get("currency", "SAR"),
    }


@router.put("/admin/{store_id}/settings/pricing")
async def update_pricing_settings(store_id: str, pricing: dict):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    cfg = dict(sm.get_ai_config(store_id) or {})
    cfg["pricing_config"] = pricing.get("pricing_config", cfg.get("pricing_config", {}))
    if "currency" in pricing:
        cfg["currency"] = pricing["currency"]
    sm.set_ai_config(store_id, cfg)
    sm.reset_agent(store_id)
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, cfg)
    return {"status": "ok", "message": "تم حفظ إعدادات التسعير ✅"}


@router.post("/admin/{store_id}/settings/pricing/test")
async def test_pricing_calculation(store_id: str, payload: dict):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    import pricing_calculator as pc
    cfg = sm.get_ai_config(store_id) or {}
    pricing_cfg = cfg.get("pricing_config", {})
    if not pricing_cfg:
        raise HTTPException(400, "لا توجد إعدادات تسعير محفوظة")
    try:
        result = pc.calculate(pricing_cfg, payload)
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(400, f"خطأ في الحساب: {e}")


# ── Password ──────────────────────────────────────────────────────────────────

@router.put("/admin/{store_id}/settings/password")
async def change_store_password(store_id: str, req: PasswordChangeRequest, request: Request):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    current_hash = sm.get_admin_password_hash(store_id)
    if not _auth.verify_password(req.current_password, current_hash):
        raise HTTPException(401, "كلمة المرور الحالية غير صحيحة")
    if len(req.new_password) < 6:
        raise HTTPException(400, "كلمة المرور الجديدة قصيرة جداً (6 أحرف على الأقل)")
    sm.set_admin_password(store_id, _auth.hash_password(req.new_password))
    await db.save_store(store_id, sm.get_store_info(store_id))
    await audit(request, "change_store_password", target_store=store_id)
    return {"status": "ok", "message": "تم تغيير كلمة المرور بنجاح"}


# ── Token status / refresh ────────────────────────────────────────────────────

@router.get("/admin/{store_id}/settings/token-status")
async def token_status(store_id: str):
    from salla_oauth import get_token_status
    info   = sm.get_store_info(store_id)
    status = get_token_status(store_id)
    return {
        **status,
        "store_name":   info.get("store_name",  ""),
        "connected_at": info.get("connected_at", ""),
        "has_refresh":  bool(sm.get_refresh_token(store_id)),
    }


@router.post("/admin/{store_id}/settings/token-refresh")
async def manual_token_refresh(store_id: str):
    from salla_oauth import refresh_access_token, get_token_status
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    if not sm.get_refresh_token(store_id):
        raise HTTPException(400, "لا يوجد Refresh Token — يجب إعادة تثبيت التطبيق من سلة")
    try:
        await refresh_access_token(store_id)
        status = get_token_status(store_id)
        return {"status": "ok", "message": "تم تجديد الـ Token بنجاح ✅", **status}
    except Exception as exc:
        raise HTTPException(500, f"فشل تجديد الـ Token: {exc}")


# ── Super admin reset password ────────────────────────────────────────────────

@router.put("/admin/stores/{store_id}/reset-password")
async def super_reset_password(store_id: str, request: Request):
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(403, "مصرح للمدير العام فقط")
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    sm.set_admin_password(store_id, _auth.hash_password(str(store_id)))
    return {"status": "ok", "message": f"تمت إعادة تعيين كلمة المرور إلى: {store_id}"}
