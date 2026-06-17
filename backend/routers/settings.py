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
        # Messenger + Instagram (Facebook Page) connection status — token masked.
        "messenger_enabled":   bool(cfg.get("messenger_enabled")),
        "instagram_enabled":   bool(cfg.get("instagram_enabled")),
        "page_id":             cfg.get("page_id", ""),
        "page_name":           cfg.get("page_name", ""),
        "page_token_set":      bool(cfg.get("page_token")),
        "ig_id":               cfg.get("ig_id", ""),
        "ig_username":         cfg.get("ig_username", ""),
        "coupons_enabled":           bool(cfg.get("coupons_enabled")),
        "coupon_max_percent":        int(cfg.get("coupon_max_percent", 15) or 15),
        "coupon_max_discount_value": float(cfg.get("coupon_max_discount_value", 200) or 200),
        "coupon_min_order":          float(cfg.get("coupon_min_order", 0) or 0),
        "coupon_ttl_hours":          int(cfg.get("coupon_ttl_hours", 24) or 24),
        # Data-access permissions (None in DB = True/enabled by default)
        "access_orders":            cfg.get("access_orders",            None),
        "access_invoices":          cfg.get("access_invoices",          None),
        "access_customers":         cfg.get("access_customers",         None),
        "access_reviews":           cfg.get("access_reviews",           None),
        "access_abandoned_carts":   cfg.get("access_abandoned_carts",   None),
        "access_shipments":         cfg.get("access_shipments",         None),
        "access_delivery_promises": cfg.get("access_delivery_promises", None),
        # Bot personality & response style
        "bot_tone":            cfg.get("bot_tone",            "friendly"),
        "bot_language":        cfg.get("bot_language",        "ar"),
        "response_length":     cfg.get("response_length",     "normal"),
        "use_emoji":           cfg.get("use_emoji",           None),
        "greeting_message":    cfg.get("greeting_message",    ""),
        "custom_instructions": cfg.get("custom_instructions", ""),
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
    if req.messenger_enabled is not None:
        config["messenger_enabled"] = bool(req.messenger_enabled)
    if req.instagram_enabled is not None:
        config["instagram_enabled"] = bool(req.instagram_enabled)

    # ── AI coupon settings (clamped server-side; agent re-clamps too) ─────────
    if req.coupons_enabled is not None:
        config["coupons_enabled"] = bool(req.coupons_enabled)
    if req.coupon_max_percent is not None:
        config["coupon_max_percent"] = max(1, min(int(req.coupon_max_percent), 90))
    if req.coupon_max_discount_value is not None:
        config["coupon_max_discount_value"] = max(0.0, float(req.coupon_max_discount_value))
    if req.coupon_min_order is not None:
        config["coupon_min_order"] = max(0.0, float(req.coupon_min_order))
    if req.coupon_ttl_hours is not None:
        config["coupon_ttl_hours"] = max(24, min(int(req.coupon_ttl_hours), 720))

    # ── Data-access permissions ───────────────────────────────────────────────
    _PERM_FLAGS = (
        "access_orders", "access_invoices", "access_customers",
        "access_reviews", "access_abandoned_carts",
        "access_shipments", "access_delivery_promises",
    )
    for flag in _PERM_FLAGS:
        val = getattr(req, flag, None)
        if val is not None:
            config[flag] = bool(val)

    # ── Bot personality & response style ─────────────────────────────────────
    _PERSONALITY_STR_FIELDS = (
        "bot_language", "bot_tone", "response_length",
        "greeting_message", "custom_instructions",
    )
    for field in _PERSONALITY_STR_FIELDS:
        val = getattr(req, field, None)
        if val is not None:
            config[field] = str(val).strip()
    if getattr(req, "use_emoji", None) is not None:
        config["use_emoji"] = bool(req.use_emoji)

    if groq_key:
        config["anthropic_api_key"] = ""
        config["openai_api_key"]    = ""
    elif anthropic_key:
        config["groq_api_key"]   = ""
        config["openai_api_key"] = ""
    elif openai_key:
        config["groq_api_key"]      = ""
        config["anthropic_api_key"] = ""

    await sm.set_ai_config(store_id, config)
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, config)
    # Rebuild the agent so permission / personality changes take effect immediately
    # without waiting for the next natural agent expiry or server restart.
    sm.reset_agent(store_id)

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


# ── WhatsApp Embedded Signup ───────────────────────────────────────────────────

@router.get("/admin/{store_id}/whatsapp/meta-app-id")
async def get_meta_app_id(store_id: str):
    """Return the public META_APP_ID so the frontend can init the FB SDK."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    app_id = os.getenv("META_APP_ID", "")
    if not app_id:
        raise HTTPException(503, "META_APP_ID غير مضبوط في بيئة الخادم — راجع Railway env vars")
    return {"app_id": app_id, "graph_version": "v21.0"}


@router.post("/admin/{store_id}/whatsapp/connect")
async def whatsapp_connect(store_id: str, request: Request):
    """
    Exchange the short-lived user token (from FB.login / Embedded Signup)
    for a long-lived token, discover the WABA and phone number, then
    save everything to ai_config.

    Body JSON:
        { "user_token": "...", "waba_id": "..." (optional), "phone_number_id": "..." (optional) }
    """
    import httpx as _httpx

    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    body = await request.json()
    user_token      = (body.get("user_token") or "").strip()
    chosen_waba_id  = (body.get("waba_id") or "").strip()
    chosen_phone_id = (body.get("phone_number_id") or "").strip()

    if not user_token:
        raise HTTPException(400, "user_token مطلوب")

    app_id     = os.getenv("META_APP_ID", "")
    app_secret = os.getenv("META_APP_SECRET", "")
    if not app_id or not app_secret:
        raise HTTPException(503, "META_APP_ID / META_APP_SECRET غير مضبوطين في بيئة الخادم")

    gv = "v21.0"
    base = f"https://graph.facebook.com/{gv}"

    async with _httpx.AsyncClient(timeout=30) as client:
        # 1. Exchange short-lived → long-lived token
        resp = await client.get(f"{base}/oauth/access_token", params={
            "grant_type":        "fb_exchange_token",
            "client_id":         app_id,
            "client_secret":     app_secret,
            "fb_exchange_token": user_token,
        })
        if resp.status_code != 200:
            raise HTTPException(400, f"فشل تبادل التوكن: {resp.text}")
        long_token = resp.json().get("access_token", "")
        if not long_token:
            raise HTTPException(400, "لم يُرجع Meta توكناً صالحاً")

        # 2. Get WABA accounts linked to this user
        if not chosen_waba_id:
            resp2 = await client.get(f"{base}/me/businesses", params={
                "fields":       "whatsapp_business_accounts{id,name}",
                "access_token": long_token,
            })
            data2 = resp2.json() if resp2.status_code == 200 else {}
            wabas: list[dict] = []
            for biz in (data2.get("data") or []):
                for w in ((biz.get("whatsapp_business_accounts") or {}).get("data") or []):
                    wabas.append({"id": w["id"], "name": w.get("name", w["id"])})

            if not wabas:
                raise HTTPException(400, "لم يُعثر على حسابات WhatsApp Business مرتبطة بهذا الحساب")
            if len(wabas) > 1:
                # Ask frontend to let the user pick
                return {"step": "choose_waba", "options": wabas, "user_token": long_token}
            chosen_waba_id = wabas[0]["id"]

        # 3. Get phone numbers for the WABA
        if not chosen_phone_id:
            resp3 = await client.get(f"{base}/{chosen_waba_id}/phone_numbers", params={
                "fields":       "id,display_phone_number,verified_name",
                "access_token": long_token,
            })
            data3 = resp3.json() if resp3.status_code == 200 else {}
            phones: list[dict] = [({"id": p["id"], "number": p.get("display_phone_number", p["id"]), "name": p.get("verified_name", "")})
                                  for p in (data3.get("data") or [])]
            if not phones:
                raise HTTPException(400, "لم يُعثر على أرقام واتساب في هذا WABA")
            if len(phones) > 1:
                return {"step": "choose_phone", "options": phones,
                        "user_token": long_token, "waba_id": chosen_waba_id}
            chosen_phone_id = phones[0]["id"]

    # 4. Subscribe our app to this WABA so Meta actually delivers message
    #    webhooks — previously the merchant had to wire this manually in Meta.
    import whatsapp as _wa
    subscribed = await _wa.subscribe_waba(long_token, chosen_waba_id)

    # 5. Save to ai_config
    existing = sm.get_ai_config(store_id)
    config = dict(existing)
    config.update({
        "whatsapp_token":    long_token,
        "whatsapp_phone_id": chosen_phone_id,
        "whatsapp_waba_id":  chosen_waba_id,
        "whatsapp_enabled":  True,
    })
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)

    await audit(request, "whatsapp_embedded_signup", target_store=store_id,
                details={"waba_id": chosen_waba_id, "phone_id": chosen_phone_id,
                         "subscribed": subscribed})

    return {
        "status":          "connected",
        "phone_number_id": chosen_phone_id,
        "waba_id":         chosen_waba_id,
        "webhook_subscribed": subscribed,
        "message":         "✅ تم ربط واتساب بنجاح" + ("" if subscribed else " (لكن تعذّر اشتراك الـ webhook تلقائياً)"),
    }


# ── Messenger + Instagram connect ──────────────────────────────────────────────

@router.post("/admin/{store_id}/meta/connect-pages")
async def meta_connect_pages(store_id: str, request: Request):
    """
    Connect Facebook Messenger + Instagram Direct via Facebook Login.

    Flow (mirrors the WhatsApp Embedded Signup):
      1. Exchange the short-lived user token for a long-lived one.
      2. List the user's Pages (each carries its own Page token + linked IG).
      3. If >1 page, ask the frontend to pick.
      4. Subscribe the chosen Page to our app's webhooks, persist the Page
         token + IG id, and enable the channels.

    Body JSON: { "user_token": "...", "page_id": "..." (optional) }
    """
    import httpx as _httpx
    import messenger as _ms

    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    body           = await request.json()
    user_token     = (body.get("user_token") or "").strip()
    chosen_page_id = (body.get("page_id") or "").strip()
    if not user_token:
        raise HTTPException(400, "user_token مطلوب")

    app_id     = os.getenv("META_APP_ID", "")
    app_secret = os.getenv("META_APP_SECRET", "")
    if not app_id or not app_secret:
        raise HTTPException(503, "META_APP_ID / META_APP_SECRET غير مضبوطين في بيئة الخادم")

    base = "https://graph.facebook.com/v21.0"
    async with _httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{base}/oauth/access_token", params={
            "grant_type":        "fb_exchange_token",
            "client_id":         app_id,
            "client_secret":     app_secret,
            "fb_exchange_token": user_token,
        })
        if resp.status_code != 200:
            raise HTTPException(400, f"فشل تبادل التوكن: {resp.text}")
        long_user_token = resp.json().get("access_token", "") or user_token

    pages = await _ms.list_pages(long_user_token)
    if not pages:
        raise HTTPException(400, "لم يُعثر على صفحات فيسبوك يديرها هذا الحساب. "
                                 "تأكد من منح صلاحيات إدارة الصفحات والرسائل.")
    if not chosen_page_id and len(pages) > 1:
        return {"step": "choose_page",
                "options": [{"id": p["id"], "name": p["name"],
                             "ig_username": p.get("ig_username", "")} for p in pages],
                "user_token": long_user_token}

    page = (next((p for p in pages if p["id"] == chosen_page_id), None)
            if chosen_page_id else pages[0]) or pages[0]
    page_token = page.get("access_token", "")
    page_id    = page.get("id", "")
    ig_id      = page.get("ig_id", "")
    if not (page_token and page_id):
        raise HTTPException(400, "تعذّر الحصول على توكن الصفحة — أعد المحاولة ومنح الصلاحيات كاملة.")

    subscribed = await _ms.subscribe_page(page_token, page_id)

    existing = sm.get_ai_config(store_id)
    config = dict(existing)
    config.update({
        "page_id":           page_id,
        "page_name":         page.get("name", ""),
        "page_token":        page_token,
        "messenger_enabled": True,
        "ig_id":             ig_id,
        "ig_username":       page.get("ig_username", ""),
        "instagram_enabled": bool(ig_id),
    })
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)

    await audit(request, "meta_pages_connect", target_store=store_id,
                details={"page_id": page_id, "ig_id": ig_id, "subscribed": subscribed})

    return {
        "status":            "connected",
        "page_id":           page_id,
        "page_name":         page.get("name", ""),
        "instagram_enabled": bool(ig_id),
        "ig_username":       page.get("ig_username", ""),
        "webhook_subscribed": subscribed,
        "message": ("✅ تم ربط ماسنجر" + ("وإنستقرام" if ig_id else "") + " بنجاح"
                    + ("" if subscribed else " (لكن تعذّر اشتراك الـ webhook تلقائياً)")),
    }


@router.delete("/admin/{store_id}/meta/connect-pages")
async def meta_disconnect_pages(store_id: str, request: Request):
    """Remove Messenger/Instagram credentials from ai_config."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    config = dict(sm.get_ai_config(store_id))
    for k in ("page_id", "page_name", "page_token", "ig_id", "ig_username"):
        config.pop(k, None)
    config["messenger_enabled"] = False
    config["instagram_enabled"] = False
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)
    await audit(request, "meta_pages_disconnect", target_store=store_id)
    return {"status": "disconnected", "message": "تم فصل ماسنجر وإنستقرام"}


@router.delete("/admin/{store_id}/whatsapp/connect")
async def whatsapp_disconnect(store_id: str, request: Request):
    """Remove WhatsApp credentials from ai_config."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    existing = sm.get_ai_config(store_id)
    config = dict(existing)
    config.update({
        "whatsapp_token":    "",
        "whatsapp_phone_id": "",
        "whatsapp_waba_id":  "",
        "whatsapp_enabled":  False,
    })
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)
    await audit(request, "whatsapp_disconnect", target_store=store_id)
    return {"status": "ok", "message": "تم إلغاء ربط واتساب"}


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
    await brain.set_custom_knowledge(store_id, req.custom_knowledge)
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, sm.get_ai_config(store_id))
    return {"status": "ok", "message": "تم حفظ ذاكرة المتجر ✅"}


@router.post("/admin/{store_id}/settings/brain/retrain")
async def retrain_ai_brain(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    # ── Shopify store ─────────────────────────────────────────────────────────
    integrations_data = await db.get_integrations(store_id)
    shopify_data = integrations_data.get("shopify", {})
    if shopify_data.get("shop") and shopify_data.get("access_token"):
        from shopify_sync import sync_shopify_store
        try:
            result = await sync_shopify_store(
                store_id,
                shopify_data["shop"],
                shopify_data["access_token"],
            )
            sm.reset_agent(store_id)
            return {
                "status":          "ok",
                "products_synced": result.get("products", 0),
                "categories":      0,
                "overview":        brain.get_overview(store_id),
                "message":         f"تم تحديث ذاكرة المتجر من Shopify — {result.get('products', 0)} منتج ✅",
            }
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {str(e)}")

    # ── Salla store ───────────────────────────────────────────────────────────
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
    """Return notification settings in BOTH the new (`notify_*` / `email`)
    and legacy (`on_*` / `email_address`) key shapes plus quiet-hours.

    The SPA still reads the legacy keys (Settings.tsx uses on_new_conversation,
    on_abandoned_cart, on_low_rating, email_address). If we only returned the
    new shape, the frontend would receive `undefined` for those fields and
    render every checkbox as unchecked on reload — which is the exact bug
    the merchant just hit.
    """
    cfg = sm.get_ai_config(store_id) or {}
    nested = cfg.get("notifications") or {}

    # ── Canonical values ────────────────────────────────────────────────
    email_addr   = cfg.get("notify_email", "") or nested.get("email_address", "")
    new_conv     = bool(cfg.get("notify_new_conv", nested.get("on_new_conversation", True)))
    low_rating   = bool(cfg.get("notify_low_rating", nested.get("on_low_rating", True)))
    abandoned    = bool(cfg.get("notify_abandoned_cart", nested.get("on_abandoned_cart", True)))
    llm_budget   = bool(cfg.get("notify_llm_budget", True))
    qh_enabled   = bool(nested.get("quiet_hours_enabled", False))
    qh_start     = int(nested.get("quiet_hours_start", 22))
    qh_end       = int(nested.get("quiet_hours_end",   8))

    return {
        # ── New shape (settings-page POST + future code) ──
        "email_enabled":         bool(cfg.get("notify_email_enabled")),
        "email":                 email_addr,
        "webhook_enabled":       bool(cfg.get("notify_webhook_enabled")),
        "webhook_url":           cfg.get("notify_webhook_url", ""),
        "notify_new_conv":       new_conv,
        "notify_low_rating":     low_rating,
        "notify_llm_budget":     llm_budget,
        "notify_abandoned_cart": abandoned,
        # ── Legacy aliases (what the SPA actually binds to) ──
        "email_address":         email_addr,
        "on_new_conversation":   new_conv,
        "on_abandoned_cart":     abandoned,
        "on_low_rating":         low_rating,
        # ── Quiet hours (always nested in notifications dict) ──
        "quiet_hours_enabled":   qh_enabled,
        "quiet_hours_start":     qh_start,
        "quiet_hours_end":       qh_end,
    }


@router.put("/admin/{store_id}/settings/notifications")
async def update_notification_settings(store_id: str, req: NotificationSettingsRequest):
    """Persist notification settings in BOTH key shapes so the email sender
    (notifications._send_email path, reads cfg["notifications"]) and the
    settings GET (reads flat notify_* keys) both see the same truth.

    Without the nested-dict write, even a perfectly-saved settings form
    produces zero emails: notify(store_id, ...) reads get_settings() which
    reads cfg["notifications"], which never gets written.
    """
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    cfg = dict(sm.get_ai_config(store_id) or {})
    email = (req.email or req.email_address or "").strip()

    # The SPA sends the legacy on_* keys; the model also accepts the new
    # notify_* keys. Either one being True wins (OR-logic) — but only when
    # the corresponding payload key was actually sent in the request body,
    # not the Pydantic default. `model_fields_set` tells us which keys the
    # caller explicitly included.
    sent = req.model_fields_set
    def resolved(new_key: str, legacy_key: str, default: bool = True) -> bool:
        if legacy_key in sent and new_key in sent:
            return bool(getattr(req, new_key) or getattr(req, legacy_key))
        if legacy_key in sent:
            return bool(getattr(req, legacy_key))
        if new_key in sent:
            return bool(getattr(req, new_key))
        return default

    new_conv   = resolved("notify_new_conv",       "on_new_conversation")
    low_rating = resolved("notify_low_rating",     "on_low_rating")
    abandoned  = resolved("notify_abandoned_cart", "on_abandoned_cart")
    llm_budget = bool(req.notify_llm_budget)

    cfg.update({
        # Flat keys — read by settings GET
        "notify_email_enabled":   bool(req.email_enabled),
        "notify_email":           email,
        "notify_webhook_enabled": bool(req.webhook_enabled),
        "notify_webhook_url":     (req.webhook_url or "").strip(),
        "notify_new_conv":        new_conv,
        "notify_low_rating":      low_rating,
        "notify_llm_budget":      llm_budget,
        "notify_abandoned_cart":  abandoned,
    })

    # Nested dict — read by the email sender (notifications.get_settings).
    # Mirror every flag so the two sides never drift.
    cfg["notifications"] = {
        "email_enabled":        bool(req.email_enabled),
        "email_address":        email,
        "webhook_url":          (req.webhook_url or "").strip(),
        "on_new_conversation":  new_conv,
        "on_abandoned_cart":    abandoned,
        "on_low_rating":        low_rating,
        "quiet_hours_enabled":  bool(req.quiet_hours_enabled),
        "quiet_hours_start":    int(req.quiet_hours_start or 22),
        "quiet_hours_end":      int(req.quiet_hours_end or 8),
    }

    await sm.set_ai_config(store_id, cfg)
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, cfg)
    return {"status": "ok", "message": "تم حفظ إعدادات الإشعارات ✅"}


@router.post("/admin/{store_id}/settings/notifications/test")
async def test_notification(store_id: str):
    """Send a real test email/webhook synchronously so the merchant gets
    immediate feedback. Bypasses notify() → outbox → drainer because:

    - notify() gates on event type ('new_conversation', 'abandoned_cart',
      'low_rating', 'llm_budget_warning'); 'test' isn't in the gate dict
      and silently early-returns.
    - deliver_outbox_row() has no 'test' branch either, so even if we did
      enqueue it would no-op.
    - We want the actual provider response surfaced to the UI ("domain
      not verified" / "invalid from") instead of a misleading "تم الإرسال"
      while the email never leaves.
    """
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    n = _notif.get_settings(store_id)
    if not n["email_enabled"] and not n["webhook_url"]:
        raise HTTPException(
            400,
            "فعّل البريد الإلكتروني أو الـ Webhook أولاً، ثم اضغط حفظ، ثم اضغط اختبار."
        )

    results: dict = {"email": None, "webhook": None}

    if n["email_enabled"]:
        if not n["email_address"]:
            raise HTTPException(400, "البريد الإلكتروني مفعّل لكن خانة عنوان الاستقبال فارغة.")
        info       = sm.get_store_info(store_id) or {}
        store_name = info.get("store_name") or f"متجر {store_id}"
        subject    = f"إشعار تجريبي من حياك — {store_name} ✅"
        html = f"""
        <div dir="rtl" style="font-family: Arial, Tahoma, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; background: #f9fafb;">
          <div style="background: white; padding: 32px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
            <h2 style="color: #0d9488; margin: 0 0 16px;">إشعار تجريبي ✅</h2>
            <p style="color: #374151; line-height: 1.7;">
              تم استلام هذا الإيميل بنجاح — إعدادات الإشعارات تعمل بشكل صحيح
              للمتجر <b>{store_name}</b>.
            </p>
            <p style="color: #6b7280; font-size: 14px; margin-top: 24px;">
              الإيميل المسجّل: <code style="background: #f3f4f6; padding: 2px 6px; border-radius: 4px;">{n["email_address"]}</code>
            </p>
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
            <p style="color: #9ca3af; font-size: 12px; text-align: center; margin: 0;">
              نظام حياك — مساعدك الذكي للمتاجر
            </p>
          </div>
        </div>
        """
        results["email"] = await _notif._send_email(n["email_address"], subject, html)

    if n["webhook_url"]:
        results["webhook"] = await _notif._send_webhook(n["webhook_url"], {
            "event":      "test",
            "store_id":   store_id,
            "store_name": (sm.get_store_info(store_id) or {}).get("store_name", ""),
            "message":    "إشعار تجريبي من لوحة التحكم",
        })

    failed = [ch for ch, ok in results.items() if ok is False]
    if failed:
        raise HTTPException(
            502,
            f"فشل الإرسال للقنوات: {', '.join(failed)} — راجع Railway logs لمعرفة السبب الدقيق "
            "(غالباً: domain غير مفعّل في Resend، أو API key غير صحيح)."
        )

    sent_to = []
    if results["email"]:   sent_to.append(f"إيميل ({n['email_address']})")
    if results["webhook"]: sent_to.append("webhook")
    return {
        "status":  "ok",
        "sent":    True,
        "channels": results,
        "message": f"✅ تم الإرسال إلى: {' + '.join(sent_to)}",
    }


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
    await sm.set_ai_config(store_id, cfg)
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
    await sm.set_ai_config(store_id, cfg)
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
    await sm.set_admin_password(store_id, _auth.hash_password(req.new_password))
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
    await sm.set_admin_password(store_id, _auth.hash_password(str(store_id)))
    return {"status": "ok", "message": f"تمت إعادة تعيين كلمة المرور إلى: {store_id}"}
