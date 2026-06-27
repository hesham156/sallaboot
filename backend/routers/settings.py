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
    NotificationSettingsRequest, PasswordChangeRequest, AccountEmailRequest,
    AccountEmailVerifyRequest,
)
from routers.deps import (
    audit, CONTENT_TYPES, MAX_FILE_MB, UPLOAD_DIR, read_upload_bounded,
    require_store_owner,
)

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


# ── WhatsApp display-number helpers ─────────────────────────────────────────

async def _enrich_whatsapp_display(store_id: str) -> list:
    """Return the store's WhatsApp numbers, fetching + persisting any missing
    human-readable display number (+966…) from Meta. One-time per number."""
    import whatsapp as _wa
    nums = sm.get_whatsapp_numbers(store_id)
    for n in nums:
        token = str(n.get("token", "")).strip()
        if token and not str(n.get("display_number", "")).strip():
            info = await _wa.get_phone_number_info(token, n.get("phone_id", ""))
            disp = info.get("display_number", "")
            if disp:
                await sm.upsert_whatsapp_number(store_id, {
                    "phone_id":       n.get("phone_id", ""),
                    "display_number": disp,
                    "label":          n.get("label") or info.get("verified_name", ""),
                })
    return sm.get_whatsapp_numbers(store_id)


def _wa_primary_display(numbers: list) -> str:
    """Display number of the primary (first enabled-with-token) number, else ''."""
    primary = next(
        (n for n in numbers if n.get("enabled") and str(n.get("token", "")).strip()),
        numbers[0] if numbers else None,
    )
    return str((primary or {}).get("display_number", "")).strip()


# ── AI config ─────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/settings/ai")
async def get_ai_settings(store_id: str):
    cfg = sm.get_ai_config(store_id)
    groq_set      = bool(cfg.get("groq_api_key"))
    anthropic_set = bool(cfg.get("anthropic_api_key"))
    openai_set    = bool(cfg.get("openai_api_key"))
    naraya_set    = bool(cfg.get("naraya_api_key"))
    if groq_set:
        provider = "groq"
    elif anthropic_set:
        provider = "anthropic"
    elif openai_set:
        provider = "openai"
    elif naraya_set:
        provider = "naraya"
    else:
        provider = "env"
    store_type = (cfg.get("store_type") or "").strip().lower()
    if not store_type:
        store_type = "printing" if cfg.get("pricing_config") else "general"
    # Categories the merchant can pick from to hide from the bot, plus the
    # current selection. Names come from the synced catalogue.
    _cache_cats = (sm.get_cache(store_id) or {}).get("categories", []) or []
    available_categories = sorted(
        {c.get("name", "").strip() for c in _cache_cats if c.get("name", "").strip()}
    )
    excluded_categories = [str(c) for c in (cfg.get("excluded_categories") or [])]
    import whatsapp as _wa
    base = os.getenv("BASE_URL", "").rstrip("/")
    # Backfill display numbers (+966…) for any connected number missing one, so
    # the UI shows the real number instead of the Meta Phone-ID. One-time per
    # number (persisted), then this is a no-op.
    _wa_numbers = await _enrich_whatsapp_display(store_id)
    return {
        "groq_api_key":      "••••" if groq_set      else "",
        "anthropic_api_key": "••••" if anthropic_set else "",
        "openai_api_key":    "••••" if openai_set    else "",
        "naraya_api_key":    "••••" if naraya_set    else "",
        "ai_model":          cfg.get("ai_model",  ""),
        "bot_name":          cfg.get("bot_name",  ""),
        "provider":          provider,
        "store_type":        store_type,
        "excluded_categories":  excluded_categories,
        "available_categories": available_categories,
        "whatsapp_enabled":    bool(cfg.get("whatsapp_enabled")),
        "whatsapp_phone_id":   cfg.get("whatsapp_phone_id", ""),
        "whatsapp_token":      "••••" if cfg.get("whatsapp_token") else "",
        "whatsapp_waba_id":    cfg.get("whatsapp_waba_id", ""),
        # The human-readable primary number (+966…) for the inbox channel label.
        "whatsapp_display_number": _wa_primary_display(_wa_numbers),
        # All connected WhatsApp numbers (a store can link several). Tokens masked.
        "whatsapp_numbers":    [
            {"phone_id": n.get("phone_id", ""), "waba_id": n.get("waba_id", ""),
             "display_number": n.get("display_number", ""),
             "label": n.get("label", ""), "enabled": bool(n.get("enabled", True)),
             "has_token": bool(str(n.get("token", "")).strip())}
            for n in _wa_numbers
        ],
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
        "ig_token_set":        bool(cfg.get("ig_access_token")),
        # Telegram channel connection status — token never echoed.
        "telegram_enabled":      bool(cfg.get("telegram_enabled")),
        "telegram_bot_username": cfg.get("telegram_bot_username", ""),
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
    naraya_key    = (req.naraya_api_key    or "").strip()

    config = dict(existing)
    config.update({
        "groq_api_key":      groq_key      or existing.get("groq_api_key",      ""),
        "anthropic_api_key": anthropic_key or existing.get("anthropic_api_key", ""),
        "openai_api_key":    openai_key    or existing.get("openai_api_key",    ""),
        "naraya_api_key":    naraya_key    or existing.get("naraya_api_key",    ""),
        "ai_model":          (req.ai_model  or "").strip() or existing.get("ai_model",  ""),
        "bot_name":          (req.bot_name  or "").strip() or existing.get("bot_name",  ""),
    })

    if req.store_type is not None:
        st = req.store_type.strip().lower()
        if st in ("printing", "general"):
            config["store_type"] = st

    if req.excluded_categories is not None:
        # De-dupe while preserving order; drop blanks.
        seen: set[str] = set()
        cleaned: list[str] = []
        for c in req.excluded_categories:
            name = str(c).strip()
            key = name.lower()
            if name and key not in seen:
                seen.add(key)
                cleaned.append(name)
        config["excluded_categories"] = cleaned

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
        config["naraya_api_key"]    = ""
    elif anthropic_key:
        config["groq_api_key"]   = ""
        config["openai_api_key"] = ""
        config["naraya_api_key"] = ""
    elif openai_key:
        config["groq_api_key"]      = ""
        config["anthropic_api_key"] = ""
        config["naraya_api_key"]    = ""
    elif naraya_key:
        config["groq_api_key"]      = ""
        config["anthropic_api_key"] = ""
        config["openai_api_key"]    = ""

    await sm.set_ai_config(store_id, config)
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, config)
    # If a WhatsApp phone_id was (re)assigned to this store, detach it from any
    # OTHER store that still claims it so inbound messages route only here.
    _new_phone = (config.get("whatsapp_phone_id") or "").strip()
    if _new_phone:
        await sm.claim_whatsapp_phone_id(_new_phone, store_id)
    # Rebuild the agent so permission / personality changes take effect immediately
    # without waiting for the next natural agent expiry or server restart.
    sm.reset_agent(store_id)

    _changed: list[str] = []
    for field in ("groq_api_key", "anthropic_api_key", "openai_api_key", "naraya_api_key", "whatsapp_token"):
        if (existing.get(field) or "") != (config.get(field) or ""):
            _changed.append(field)
    other_changes = {}
    for field in ("ai_model", "bot_name", "store_type", "excluded_categories", "whatsapp_enabled", "whatsapp_phone_id"):
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

    # 5. Save: ADD this number to the store's WhatsApp numbers — a store can
    #    connect SEVERAL (sales + support + …). upsert keeps the legacy flat
    #    fields synced to the primary and persists to the DB. Fetch the
    #    human-readable display number so the UI shows +966… not the Phone ID.
    _info = await _wa.get_phone_number_info(long_token, chosen_phone_id)
    await sm.upsert_whatsapp_number(store_id, {
        "phone_id":       chosen_phone_id,
        "token":          long_token,
        "waba_id":        chosen_waba_id,
        "display_number": _info.get("display_number", ""),
        "label":          _info.get("verified_name", ""),
        "enabled":        True,
    })

    # Enforce phone-number uniqueness: detach this number from any OTHER store
    # that still claims it, so inbound messages route only to THIS store.
    released = await sm.claim_whatsapp_phone_id(chosen_phone_id, store_id)

    await audit(request, "whatsapp_embedded_signup", target_store=store_id,
                details={"waba_id": chosen_waba_id, "phone_id": chosen_phone_id,
                         "subscribed": subscribed, "released_from": released})

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

    # Authz: the `/admin/{store}/meta/*` prefix is gated by middleware
    # (_PROTECTED_RE) — it requires a valid token, binds it to this store_id
    # (no cross-store IDOR), and restricts to owner/manager (_MANAGER_ONLY_RE).
    # So no explicit require_store_owner() call is needed here.
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
            # Log the raw Graph error server-side; don't echo it to the client
            # (it can carry app/token internals). Generic message for the UI.
            print(f"[meta] token exchange failed {resp.status_code}: {resp.text[:300]}")
            raise HTTPException(400, "فشل تبادل التوكن مع Meta — أعد المحاولة ومنح الصلاحيات كاملة.")
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

    import comments as _cm
    subscribed     = await _ms.subscribe_page(page_token, page_id)
    # Also subscribe the comment webhook fields (feed/comments/mentions) so public
    # comments flow into the Smart Inbox. Comment AUTOMATION stays off until the
    # merchant enables it in the panel + the feature is entitled — see Phase C.
    subscribed_cm  = await _cm.subscribe_page_comments(page_token, page_id)

    existing = sm.get_ai_config(store_id)
    config = dict(existing)
    config.update({
        "page_id":           page_id,
        "page_name":         page.get("name", ""),
        "page_token":        page_token,
        "messenger_enabled": True,
        # Comment automation defaults — opt-in via the Automation panel.
        "comments_fb_enabled": config.get("comments_fb_enabled", False),
    })
    # If this Page has a linked Instagram account, save ig_id so that Instagram
    # DMs (delivered via the Page subscription + instagram_manage_messages field)
    # can be routed to this store. Does NOT overwrite a manually-set ig_id.
    if ig_id and not config.get("ig_id"):
        config["ig_id"]             = ig_id
        config["ig_username"]       = page.get("ig_username", "")
        config["instagram_enabled"] = True
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)

    await audit(request, "meta_pages_connect", target_store=store_id,
                details={"page_id": page_id, "ig_id": ig_id, "subscribed": subscribed})

    ig_note = f" وإنستقرام (@{page.get('ig_username', ig_id)})" if ig_id and not existing.get("ig_id") else ""
    return {
        "status":            "connected",
        "page_id":           page_id,
        "page_name":         page.get("name", ""),
        "ig_id":             ig_id,
        "webhook_subscribed": subscribed,
        "message": (f"✅ تم ربط ماسنجر{ig_note} بنجاح"
                    + ("" if subscribed else " (لكن تعذّر اشتراك الـ webhook تلقائياً)")),
    }


@router.delete("/admin/{store_id}/meta/connect-pages")
async def meta_disconnect_pages(store_id: str, request: Request):
    """Remove Messenger credentials from ai_config (keeps Instagram ig_id intact)."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    config = dict(sm.get_ai_config(store_id))
    for k in ("page_id", "page_name", "page_token"):
        config.pop(k, None)
    config["messenger_enabled"]   = False
    config["comments_fb_enabled"] = False
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)
    await audit(request, "meta_pages_disconnect", target_store=store_id)
    return {"status": "disconnected", "message": "تم فصل ماسنجر"}


async def _ig_long_lived_token(short_token: str) -> str:
    """
    Exchange a short-lived Instagram-login token (~1h) for a long-lived one
    (~60d) using the Instagram app secret. Returns the long-lived token, or ""
    when the exchange isn't possible (no secret, or the token is already
    long-lived). Best-effort; never raises.

    GET graph.instagram.com/access_token?grant_type=ig_exchange_token
    """
    import httpx as _httpx
    secret = os.getenv("INSTAGRAM_APP_SECRET", "").strip()
    if not secret:
        return ""
    try:
        async with _httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://graph.instagram.com/access_token",
                params={"grant_type": "ig_exchange_token",
                        "client_secret": secret, "access_token": short_token},
            )
            if r.status_code < 400:
                return (r.json().get("access_token") or "").strip()
            print(f"[instagram] long-lived exchange {r.status_code}: {r.text[:160]}")
    except Exception as exc:
        print(f"[instagram] long-lived exchange error: {exc}")
    return ""


async def _ig_validate_token(ig_access_token: str) -> tuple[bool, str]:
    """
    Validate an Instagram-login access token by calling graph.instagram.com/me.
    Returns (ok, detail) where detail is the IG username on success, or a short
    human-readable error on failure. The IG-login messaging API ONLY accepts
    `IGAA…` tokens against graph.instagram.com — Facebook `EAA…` tokens and
    expired/truncated tokens fail here with "Cannot parse access token".
    """
    import httpx as _httpx
    graph = os.getenv("META_GRAPH_VERSION", "v21.0")
    try:
        async with _httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://graph.instagram.com/{graph}/me",
                params={"fields": "user_id,username", "access_token": ig_access_token},
            )
            if r.status_code < 400:
                return True, (r.json().get("username") or "").strip()
            err = (r.json().get("error", {}) or {}).get("message", r.text[:120])
            print(f"[instagram] token validation {r.status_code}: {err}")
            return False, err
    except Exception as exc:
        print(f"[instagram] token validation error: {exc}")
        return False, str(exc)[:120]


@router.put("/admin/{store_id}/meta/instagram")
async def meta_set_instagram_manual(store_id: str, request: Request):
    """Manually save an Instagram Business Account ID for webhook routing."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    body = await request.json()
    ig_id           = (body.get("ig_id")           or "").strip()
    ig_access_token = (body.get("ig_access_token") or "").strip()
    if not ig_id:
        raise HTTPException(400, "ig_id مطلوب")
    if not ig_id.isdigit():
        raise HTTPException(400, "ig_id يجب أن يكون رقماً — ابحث عنه في Meta Business Suite أو إعدادات تطبيق فيسبوك")

    config = dict(sm.get_ai_config(store_id))

    # Validate a newly-supplied token BEFORE saving so a bad token (expired,
    # truncated, or a Facebook EAA token) is rejected with a clear message
    # instead of silently failing on every reply.
    token_valid = None  # None = not checked this request
    ig_username = ""
    if ig_access_token:
        token_valid, detail = await _ig_validate_token(ig_access_token)
        if not token_valid:
            raise HTTPException(400,
                f"رمز الوصول غير صالح: {detail} — تأكد أنه رمز إنستقرام (يبدأ بـ IGAA) "
                f"وغير منتهي. أعد إنشاءه من تطبيق إنستقرام في Meta Developers.")
        ig_username = detail
        # Upgrade the short-lived (~1h) token to a long-lived (~60d) one so the
        # connection doesn't die within the hour. Falls back to the original
        # token when the exchange isn't available.
        long_token = await _ig_long_lived_token(ig_access_token)
        config["ig_access_token"] = long_token or ig_access_token
        if long_token:
            print(f"[instagram] token upgraded to long-lived for ig_id={ig_id}")

    config["ig_id"]             = ig_id
    config["instagram_enabled"] = True
    if ig_username:
        config["ig_username"] = ig_username

    token_to_use = (config.get("ig_access_token") or "").strip()
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)
    await audit(request, "meta_instagram_manual_connect", target_store=store_id,
                details={"ig_id": ig_id, "token_set": bool(token_to_use),
                         "token_valid": token_valid})
    msg = f"✅ تم ربط إنستقرام (معرّف: {ig_id})"
    if token_valid:
        msg += f" — رمز الوصول صالح ✓{(' (@' + ig_username + ')') if ig_username else ''}"
    return {"status": "connected", "ig_id": ig_id,
            "ig_token_set": bool(token_to_use),
            "ig_username": ig_username,
            "message": msg}


@router.delete("/admin/{store_id}/meta/instagram")
async def meta_disconnect_instagram(store_id: str, request: Request):
    """Remove Instagram credentials only (keeps Messenger page_token connected)."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    config = dict(sm.get_ai_config(store_id))
    config.pop("ig_id",           None)
    config.pop("ig_username",     None)
    config.pop("ig_access_token", None)
    config["instagram_enabled"]   = False
    config["comments_ig_enabled"] = False
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)
    await audit(request, "meta_instagram_disconnect", target_store=store_id)
    return {"status": "disconnected", "message": "تم فصل إنستقرام"}


@router.delete("/admin/{store_id}/whatsapp/connect")
async def whatsapp_disconnect(store_id: str, request: Request):
    """Remove WhatsApp credentials from ai_config."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    existing = sm.get_ai_config(store_id)

    # Real unlink at Meta: detach our app from the merchant's WABA so Meta
    # stops delivering their messages to us. Best-effort — done BEFORE we wipe
    # the token/waba (we need them to call Meta). Never blocks the disconnect.
    unsubscribed = False
    token   = (existing.get("whatsapp_token")   or "").strip()
    waba_id = (existing.get("whatsapp_waba_id") or "").strip()
    phone_id = (existing.get("whatsapp_phone_id") or "").strip()
    if token and waba_id:
        import whatsapp as _wa
        try:
            unsubscribed = await _wa.unsubscribe_waba(token, waba_id)
        except Exception as exc:
            print(f"[whatsapp] disconnect unsubscribe skipped: {exc}")

    config = dict(existing)
    config.update({
        "whatsapp_token":    "",
        "whatsapp_phone_id": "",
        "whatsapp_waba_id":  "",
        "whatsapp_enabled":  False,
        "whatsapp_numbers":  [],   # disconnect ALL numbers
    })
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)

    # Unlinking a NUMBER must delete the number everywhere — not just this store.
    # The operator may be unable to reach the other store that still holds the
    # same phone_id (a different 7ayak account), yet that stale store is what
    # keeps receiving the messages. Purge the number from every store holding it.
    purged: list[str] = []
    if phone_id:
        purged = await sm.purge_whatsapp_phone_id(phone_id)
        purged = [s for s in purged if s != str(store_id)]

    await audit(request, "whatsapp_disconnect", target_store=store_id,
                details={"meta_unsubscribed": unsubscribed,
                         "phone_id": phone_id, "also_purged_from": purged})
    extra = (f" — وأُزيل الرقم أيضاً من {len(purged)} حساب آخر" if purged else "")
    return {
        "status":  "ok",
        "message": "تم إلغاء ربط واتساب" + extra
                   + ("" if unsubscribed or not waba_id
                      else " (لكن تعذّر إلغاء الاشتراك من Meta تلقائياً)"),
        "meta_unsubscribed": unsubscribed,
        "also_purged_from":  purged,
    }


# ── WhatsApp: multiple numbers ────────────────────────────────────────────────

@router.get("/admin/{store_id}/whatsapp/numbers")
async def list_whatsapp_numbers(store_id: str, request: Request):
    """All WhatsApp numbers connected to this store (tokens never returned)."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    return {"numbers": [
        {"phone_id": n.get("phone_id", ""), "waba_id": n.get("waba_id", ""),
         "display_number": n.get("display_number", ""),
         "label": n.get("label", ""), "enabled": bool(n.get("enabled", True)),
         "has_token": bool(str(n.get("token", "")).strip())}
        for n in await _enrich_whatsapp_display(store_id)
    ]}


@router.post("/admin/{store_id}/whatsapp/numbers")
async def add_whatsapp_number(store_id: str, request: Request):
    """Manually add (or update by phone_id) a WhatsApp number — Phone Number ID +
    Access Token (+ optional WABA id / label) from Meta › WhatsApp › API Setup.
    Body: {phone_id, token, waba_id?, label?}."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    body     = await request.json()
    phone_id = str(body.get("phone_id", "")).strip()
    token    = str(body.get("token", "")).strip()
    waba_id  = str(body.get("waba_id", "")).strip()
    label    = str(body.get("label", "")).strip()
    if not phone_id or not token:
        raise HTTPException(400, "Phone Number ID والـ Access Token مطلوبان")
    import whatsapp as _wa
    _info = await _wa.get_phone_number_info(token, phone_id)
    await sm.upsert_whatsapp_number(store_id, {
        "phone_id": phone_id, "token": token, "waba_id": waba_id,
        "display_number": _info.get("display_number", ""),
        "label": label or _info.get("verified_name", ""), "enabled": True,
    })
    # Global uniqueness — detach this number from any OTHER store that holds it.
    released = [s for s in await sm.claim_whatsapp_phone_id(phone_id, store_id) if s != str(store_id)]
    await audit(request, "whatsapp_add_number_manual", target_store=store_id,
                details={"phone_id": phone_id, "released_from": released})
    return {"status": "ok", "message": "تم إضافة الرقم", "phone_id": phone_id,
            "also_removed_from": released}


@router.delete("/admin/{store_id}/whatsapp/numbers/{phone_id}")
async def remove_whatsapp_number(store_id: str, phone_id: str, request: Request):
    """Unlink ONE WhatsApp number (leaves the others connected). Best-effort Meta
    unsubscribe + purge of that number from every store that still holds it."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    pid = (phone_id or "").strip()
    target = next((n for n in sm.get_whatsapp_numbers(store_id)
                   if str(n.get("phone_id", "")).strip() == pid), None)
    if not target:
        raise HTTPException(404, "هذا الرقم غير مربوط بالمتجر")

    unsubscribed = False
    token   = (target.get("token") or "").strip()
    waba_id = (target.get("waba_id") or "").strip()
    if token and waba_id:
        import whatsapp as _wa
        try:
            unsubscribed = await _wa.unsubscribe_waba(token, waba_id)
        except Exception as exc:
            print(f"[whatsapp] remove-number unsubscribe skipped: {exc}")

    await sm.remove_whatsapp_number(store_id, pid)
    # Purge from any OTHER store that still holds the same number.
    purged = [s for s in await sm.purge_whatsapp_phone_id(pid) if s != str(store_id)]

    await audit(request, "whatsapp_remove_number", target_store=store_id,
                details={"phone_id": pid, "meta_unsubscribed": unsubscribed,
                         "also_purged_from": purged})
    return {"status": "ok", "message": "تم إلغاء ربط الرقم",
            "meta_unsubscribed": unsubscribed, "also_purged_from": purged}


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

    # M-4: bounded streaming read instead of buffering the whole body into RAM.
    contents = await read_upload_bounded(file, MAX_FILE_MB * 1024 * 1024)

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
    # M-1: scope by store_id so a tenant can't toggle another store's row by id.
    ok = await db.update_training_enabled(training_id, bool(payload.get("enabled", True)), store_id)
    if not ok:
        raise HTTPException(404, "عنصر التدريب غير موجود")
    sm.reset_agent(store_id)
    smart_router.invalidate_faq_cache(store_id)
    return {"status": "ok"}


@router.delete("/admin/{store_id}/settings/training/{training_id}")
async def delete_training_entry(store_id: str, training_id: int):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    # M-1: scope by store_id so a tenant can't delete another store's row by id.
    ok, deleted_file_id = await db.delete_training(training_id, store_id)
    if not ok:
        raise HTTPException(404, "عنصر التدريب غير موجود")
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
    account_email = sm.get_owner_email(store_id)

    # ── Canonical values ────────────────────────────────────────────────
    # Default the notification email to the account email when unset.
    email_addr   = cfg.get("notify_email", "") or nested.get("email_address", "") or account_email
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
        # ── Account email (signup email) — source/default for notifications,
        # editable from the Security tab. ──
        "account_email":         account_email,
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
    if not _auth.check_password(req.current_password, current_hash):
        raise HTTPException(401, "كلمة المرور الحالية غير صحيحة")
    if len(req.new_password) < 6:
        raise HTTPException(400, "كلمة المرور الجديدة قصيرة جداً (6 أحرف على الأقل)")
    await sm.set_admin_password(store_id, _auth.hash_password(req.new_password))
    await db.save_store(store_id, sm.get_store_info(store_id))
    # Revoke every owner token issued before now (H-2 session revocation).
    await sm.mark_password_changed(store_id)
    await audit(request, "change_store_password", target_store=store_id)
    return {"status": "ok", "message": "تم تغيير كلمة المرور بنجاح"}


import re as _re
_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CHANGE_EMAIL_PURPOSE = "change_email"


async def _validate_new_account_email(store_id: str, raw_email: str) -> str:
    """Normalise + validate a candidate account email. Raises HTTPException
    on bad format / collision. Returns the clean lowercase email."""
    email = (raw_email or "").strip().lower()
    if not _EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(400, "صيغة البريد الإلكتروني غير صحيحة")
    # Uniqueness: an email must resolve to exactly one account.
    other = await db.find_store_by_owner_email(email)
    if other and other != store_id:
        raise HTTPException(409, "هذا البريد مستخدم في حساب آخر")
    return email


@router.post("/admin/{store_id}/settings/account-email/request-otp")
async def request_account_email_otp(store_id: str, req: AccountEmailRequest, request: Request):
    """Step 1 of changing the account email: send a 6-digit code to the NEW
    address to prove the owner controls it. Owner-only. Returns a signed
    challenge the client echoes back at verify-otp (stateless — no DB row)."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    require_store_owner(request, store_id)

    email = await _validate_new_account_email(store_id, req.email)
    if email == sm.get_owner_email(store_id):
        raise HTTPException(400, "هذا هو بريدك الحالي بالفعل")

    code      = _auth.generate_otp_code()
    challenge = _auth.make_otp_challenge(email, _CHANGE_EMAIL_PURPOSE, code)
    if not await _notif.send_otp_email(email, code, _CHANGE_EMAIL_PURPOSE):
        raise HTTPException(502, "تعذّر إرسال رمز التحقق إلى البريد الجديد. حاول لاحقاً.")
    return {"otp_required": True, "challenge": challenge, "email": email}


@router.post("/admin/{store_id}/settings/account-email/verify-otp")
async def verify_account_email_otp(store_id: str, req: AccountEmailVerifyRequest, request: Request):
    """Step 2: verify the code against the challenge, then apply the change.
    Changing the email routes login + default notifications to the new one."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    require_store_owner(request, store_id)

    email = await _validate_new_account_email(store_id, req.email)
    if not _auth.verify_otp_challenge(req.challenge or "", email, _CHANGE_EMAIL_PURPOSE, req.code or ""):
        raise HTTPException(400, "رمز التحقق غير صحيح أو منتهي الصلاحية")

    ok = await sm.set_owner_email(store_id, email)
    if not ok:
        raise HTTPException(503, "تعذّر حفظ البريد — تحقق من اتصال قاعدة البيانات")

    await audit(request, "change_account_email", target_store=store_id, details={
        "email": email, "verified": True,
    })
    return {"status": "ok", "email": email, "message": "تم تحديث بريد الحساب ✅"}


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
    # Reset to a RANDOM temp password, not the store_id. Resetting to the
    # store_id (the semi-public merchant id) left the account open to anyone via
    # the store_id+password login path. Hand the super a one-time secret to relay.
    import secrets as _secrets
    new_pwd = _secrets.token_urlsafe(9)
    await sm.set_admin_password(store_id, _auth.hash_password(new_pwd))
    await audit(request, "super_reset_password", target_store=store_id)
    return {"status": "ok", "password": new_pwd,
            "message": f"كلمة المرور المؤقتة الجديدة: {new_pwd} — سلّمها للتاجر ليغيّرها."}
