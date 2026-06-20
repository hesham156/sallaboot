"""
Integrations router — OAuth flows, status endpoints, and widget injection
for external platforms.

Currently supported:
  • Shopify — full OAuth 2.0 install + ScriptTag widget injection + disconnect
"""

import hashlib
import hmac as _hmac
import json as _json
import os
import re
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

import database as db
import store_manager as sm
from routers.deps import require_store_owner

router = APIRouter()

SHOPIFY_CLIENT_ID     = os.getenv("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_SCOPES        = (
    "read_orders,read_products,read_customers,read_inventory,write_script_tags,"
    # Catalogue-context + abandoned-cart parity with Salla. read_checkouts is
    # required for the abandoned-checkout poll; the rest feed the bot's knowledge
    # (locations/branches, shipping zones, discounts). Adding scopes means
    # already-connected stores must reconnect to grant them.
    "read_checkouts,read_locations,read_shipping,read_price_rules"
)
# Trailing slash matters: redirect_uri must EXACTLY match the URL registered
# in the Salla/Shopify/Zid dashboards. A BASE_URL like "https://7ayak.app/"
# would make redirect_uri "https://7ayak.app//integrations/zid/callback"
# (double slash) → provider rejects it and bounces back with no code.
BASE_URL              = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

ZID_CLIENT_ID     = os.getenv("ZID_CLIENT_ID", "")
ZID_CLIENT_SECRET = os.getenv("ZID_CLIENT_SECRET", "")
ZID_OAUTH_BASE    = "https://oauth.zid.sa"

# In-memory CSRF state store — single-process only.
# In multi-worker deployments (gunicorn/uvicorn --workers N) use Redis instead.
_oauth_states: dict[str, dict] = {}
_OAUTH_STATE_TTL = 600  # seconds


def _prune_oauth_states() -> None:
    """Remove states older than TTL to prevent memory growth."""
    cutoff = time.time() - _OAUTH_STATE_TTL
    expired = [k for k, v in _oauth_states.items() if v.get("ts", 0) < cutoff]
    for k in expired:
        _oauth_states.pop(k, None)


def _verify_shopify_hmac(query_params: dict, secret: str) -> bool:
    """Verify Shopify's HMAC-SHA256 signature on OAuth callbacks."""
    received = query_params.get("hmac", "")
    if not received or not secret:
        return False
    message = "&".join(
        f"{k}={v}" for k, v in sorted(query_params.items()) if k != "hmac"
    )
    expected = _hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return _hmac.compare_digest(expected, received)


def _shopify_api(shop: str) -> str:
    return f"https://{shop}/admin/api/2024-01"


# A Shopify shop domain is a single lowercase alphanumeric/hyphen label under
# .myshopify.com — nothing else. Anchored so an embedded delimiter can't smuggle
# a second host past the check.
_SHOPIFY_SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")


def _normalize_shop(shop: str) -> str:
    """Normalise + STRICTLY validate a Shopify shop domain.

    Returns the canonical "<store>.myshopify.com". Raises HTTPException(400)
    for anything that isn't a bare myshopify.com subdomain.

    The previous check only did ``endswith(".myshopify.com")``, so a value like
    "attacker.com#x.myshopify.com" (or ".../path", "user@evil", "host:port")
    passed — yet, placed into ``https://{shop}/...``, the fragment/userinfo made
    the real host attacker.com (SSRF / open-redirect, finding M-13). We now strip
    every delimiter that could introduce a second host and validate the result
    against a strict anchored pattern.
    """
    shop = (shop or "").strip().lower().rstrip("/")
    for prefix in ("https://", "http://", "https//", "http//"):
        if shop.startswith(prefix):
            shop = shop[len(prefix):]
            break
    # Cut anything after a path/query/fragment, and drop any userinfo prefix.
    shop = shop.split("/")[0].split("?")[0].split("#")[0].split("@")[-1]
    # Lenient convenience: a bare handle ("mystore") → "mystore.myshopify.com".
    if "." not in shop:
        shop = shop + ".myshopify.com"
    if not _SHOPIFY_SHOP_RE.match(shop):
        raise HTTPException(400, "نطاق متجر Shopify غير صالح")
    return shop


# ── Shopify widget loader script (public) ─────────────────────────────────────

@router.get("/widget-shopify/{store_id}.js", include_in_schema=False)
async def shopify_widget_script(store_id: str):
    """
    Returns a JS snippet that pre-configures SallaChatConfig with the correct
    store_id, then dynamically loads /widget.js.
    Shopify ScriptTag points here so the widget auto-appears on the storefront.
    """
    widget_url = f"{BASE_URL}/widget.js"
    script = f"""(function(){{
  window.SallaChatConfig = window.SallaChatConfig || {{}};
  window.SallaChatConfig.storeId  = "{store_id}";
  window.SallaChatConfig.apiUrl   = "{BASE_URL}";
  window.SallaChatConfig.platform = "shopify";
  var s = document.createElement('script');
  s.src = '{widget_url}';
  s.async = true;
  document.head.appendChild(s);
}})();"""
    return Response(content=script, media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=300"})


# ── List integrations ─────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/integrations")
async def list_integrations(store_id: str, request: Request):
    require_store_owner(request, store_id)
    data = await db.get_integrations(store_id)
    return {"integrations": data}


# ── Linking API key (for the Salla App Settings flow) ─────────────────────────
# The merchant copies this key + their email into the Salla app's settings form;
# Salla then fires app.settings.updated and we bind that Salla store to this
# 7ayak account (see routers.webhooks._handle_app_settings_updated).

@router.get("/admin/{store_id}/api-key")
async def get_api_key(store_id: str, request: Request):
    require_store_owner(request, store_id)
    key = await db.get_or_create_api_key(store_id)
    return {"api_key": key}


@router.post("/admin/{store_id}/api-key/regenerate")
async def regenerate_api_key(store_id: str, request: Request):
    require_store_owner(request, store_id)
    key = await db.regenerate_api_key(store_id)
    if not key:
        raise HTTPException(500, "تعذّر توليد مفتاح جديد")
    return {"api_key": key}


# ── Salla App-Settings Validation URL ─────────────────────────────────────────
# Registered in the Salla Partner Portal as the app's "رابط التحقق من الإعدادات".
# When the merchant saves the app's settings form (their 7ayak email + API key),
# Salla POSTs the values here BEFORE persisting them. We resolve + bind the store
# synchronously and return success so the save completes with immediate feedback,
# rather than waiting on the app.settings.updated webhook. The app.settings.updated
# webhook still runs as a backstop (idempotent — re-linking the same store is a
# no-op), so linking works whether or not the validation URL fires.

@router.post("/integrations/salla/app-settings-validation")
async def salla_app_settings_validation(request: Request):
    from fastapi.responses import JSONResponse
    from routers import webhooks as _wh

    body = await request.body()

    # Auth: only hard-reject a *wrong* credential. Salla may send the app's
    # security strategy here (Token/Signature) — verify it when present — but an
    # absent credential is allowed because the API key inside the body is itself
    # the secret proof of ownership (a bad key simply resolves to no account).
    _ok, sig_detail = _wh._verify_signature(body, request.headers)
    if "mismatch" in sig_detail:
        return JSONResponse(status_code=401,
                            content={"success": False, "message": "توقيع غير صالح"})

    try:
        payload = _json.loads(body or b"{}")
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}

    # Salla's exact validation payload shape isn't documented, so be liberal:
    # merge every dict the fields could live in (data.settings, top-level
    # settings, data itself, the envelope), earlier candidates winning, then
    # extract email + api_key from the merged view.
    merged: dict = {}
    for cand in (
        data.get("settings") if isinstance(data.get("settings"), dict) else None,
        payload.get("settings") if isinstance(payload.get("settings"), dict) else None,
        data or None,
        payload,
    ):
        if isinstance(cand, dict):
            for k, v in cand.items():
                if k not in merged and not isinstance(v, (dict, list)):
                    merged[k] = v
    email, api_key = _wh.extract_app_settings_fields(merged)

    merchant_id = str(
        payload.get("merchant")
        or payload.get("merchant_id")
        or data.get("merchant")
        or data.get("merchant_id")
        or data.get("id")
        or merged.get("merchant")
        or ""
    ).strip()

    # Temporary diagnostics — logged server-side (Railway) and echoed in the
    # error body. Names/lengths only, never the secret key value.
    debug = {
        "top_keys":      sorted(str(k) for k in payload.keys()),
        "data_keys":     sorted(str(k) for k in data.keys()) if data else [],
        "field_keys":    sorted(str(k) for k in merged.keys()),
        "merchant_seen": bool(merchant_id),
        "email_found":   bool(email),
        "api_key_len":   len(api_key),
    }
    print(f"[salla-validation] payload diagnostics: {debug}")

    if not merchant_id:
        # No store to bind in this request — let the webhook do the linking.
        # Don't block the merchant's save.
        return {"success": True}

    ok, detail = await _wh.link_store_via_app_settings(merchant_id, email, api_key)
    if ok:
        return {"success": True}

    # Surface a clear, actionable error so the merchant fixes their input.
    msg = "تعذّر الربط — تأكد من بريدك الإلكتروني في حياك ومن نسخ مفتاح الربط بالكامل"
    if "another platform" in detail:
        msg = "حساب حياك مرتبط بمنصة تجارة إلكترونية أخرى بالفعل"
    elif detail == "salla_store_not_ready":
        msg = "لم يكتمل تثبيت التطبيق بعد — انتظر لحظات ثم احفظ مرة أخرى"
    return JSONResponse(status_code=422, content={
        "success": False,
        "message": msg,
        "error": {"fields": ["api_key"], "values": [msg]},
    })


# ── Shopify: initiate install ─────────────────────────────────────────────────

@router.get("/admin/{store_id}/integrations/shopify/install")
async def shopify_install(store_id: str, shop: str, request: Request):
    require_store_owner(request, store_id)

    if not SHOPIFY_CLIENT_ID:
        raise HTTPException(503, "لم يتم تهيئة تكامل Shopify على هذا الخادم")

    # Enforce ecommerce exclusivity: one platform per store
    existing = await db.get_integrations(store_id)
    _ECOMMERCE_NAMES = {"salla": "سلّة", "zid": "زد", "woocommerce": "ووكومرس"}
    for platform, label in _ECOMMERCE_NAMES.items():
        if existing.get(platform):
            raise HTTPException(
                409,
                f"الحساب مربوط بـ {label} بالفعل — لا يمكن ربط منصتَي تجارة إلكترونية في آنٍ واحد",
            )

    shop = _normalize_shop(shop)
    state = secrets.token_urlsafe(32)
    _prune_oauth_states()
    _oauth_states[state] = {"store_id": store_id, "shop": shop, "ts": time.time()}

    redirect_uri = f"{BASE_URL}/integrations/shopify/callback"
    params = {
        "client_id":    SHOPIFY_CLIENT_ID,
        "scope":        SHOPIFY_SCOPES,
        "redirect_uri": redirect_uri,
        "state":        state,
    }
    install_url = f"https://{shop}/admin/oauth/authorize?" + urlencode(params)
    return {"install_url": install_url, "shop": shop}


# ── Shopify: OAuth callback ───────────────────────────────────────────────────

@router.get("/integrations/shopify/callback")
async def shopify_callback(
    request: Request,
    code: str = "",
    shop: str = "",
    state: str = "",
    error: str = "",
):
    # Verify Shopify's HMAC signature first — before touching any state.
    if not error and not _verify_shopify_hmac(dict(request.query_params), SHOPIFY_CLIENT_SECRET):
        raise HTTPException(400, "Invalid Shopify HMAC — request may have been tampered with")

    if error:
        store_id = (_oauth_states.pop(state, None) or {}).get("store_id", "unknown")
        return RedirectResponse(
            f"{BASE_URL}/store/{store_id}/integrations?shopify=error&reason={error}",
            status_code=302,
        )

    state_data = _oauth_states.pop(state, None)
    if not state_data or state_data.get("shop") != shop:
        raise HTTPException(400, "Invalid or expired OAuth state — please retry the connection")

    store_id = state_data["store_id"]

    # 1. Exchange code → access token
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://{shop}/admin/oauth/access_token",
                json={
                    "client_id":     SHOPIFY_CLIENT_ID,
                    "client_secret": SHOPIFY_CLIENT_SECRET,
                    "code":          code,
                },
            )
            r.raise_for_status()
            token_data = r.json()
    except Exception as exc:
        raise HTTPException(502, f"فشل استبدال الكود مع Shopify: {exc}") from exc

    access_token = token_data.get("access_token", "")
    if not access_token:
        raise HTTPException(400, "لم يُرجع Shopify access_token")

    # 2. Fetch basic shop info
    shop_info: dict = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{_shopify_api(shop)}/shop.json",
                headers={"X-Shopify-Access-Token": access_token},
            )
            r.raise_for_status()
            shop_info = r.json().get("shop", {})
    except Exception as e:
        print(f"[integrations] shopify shop info fetch failed (non-fatal): {e}")

    # 3a. Enforce one-store-per-shop rule
    existing_store = await db.find_store_by_shopify_shop(shop)
    if existing_store and existing_store != store_id:
        return RedirectResponse(
            f"{BASE_URL}/store/{store_id}/integrations?shopify=error&reason=shop_already_connected",
            status_code=302,
        )

    # 3b. Save to DB
    try:
        await db.save_integration(store_id, "shopify", {
            "shop":         shop,
            "access_token": access_token,
            "shop_name":    shop_info.get("name", shop),
            "shop_email":   shop_info.get("email", ""),
            "plan_name":    shop_info.get("plan_name", ""),
            "currency":     shop_info.get("currency", ""),
        })
        print(f"[integrations] ✅ Shopify connected: store={store_id} shop={shop}")
    except Exception as e:
        print(f"[integrations] ❌ save_integration failed: {e}")
        return RedirectResponse(
            f"{BASE_URL}/store/{store_id}/integrations?shopify=error&reason=db_save_failed",
            status_code=302,
        )

    # 4. Fire background sync (products + store info → cache for bot)
    import shopify_sync as _ss
    import database as _db_fire
    _db_fire.fire(_ss.sync_shopify_store(store_id, shop, access_token))

    # 5. Register Shopify webhooks (fire-and-forget)
    _db_fire.fire(_ss.register_shopify_webhooks(shop, access_token, store_id, BASE_URL))

    # 6. Inject chat widget into Shopify storefront via ScriptTag
    widget_src = f"{BASE_URL}/widget-shopify/{store_id}.js"
    _scripttag_ok = False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Remove any existing script tags we created first (idempotent)
            r = await client.get(
                f"{_shopify_api(shop)}/script_tags.json?src={widget_src}",
                headers={"X-Shopify-Access-Token": access_token},
            )
            existing_tags = r.json().get("script_tags", []) if r.is_success else []
            for tag in existing_tags:
                await client.delete(
                    f"{_shopify_api(shop)}/script_tags/{tag['id']}.json",
                    headers={"X-Shopify-Access-Token": access_token},
                )
            # Create fresh ScriptTag
            r = await client.post(
                f"{_shopify_api(shop)}/script_tags.json",
                headers={"X-Shopify-Access-Token": access_token},
                json={"script_tag": {"event": "onload", "src": widget_src}},
            )
            r.raise_for_status()
            _scripttag_ok = True
            print(f"[integrations] ✅ ScriptTag injected for {shop}")
    except Exception as e:
        print(f"[integrations] ⚠️ ScriptTag injection failed: {e}")

    redirect_qs = "shopify=connected" if _scripttag_ok else "shopify=connected&widget_warning=1"
    return RedirectResponse(
        f"{BASE_URL}/store/{store_id}/integrations?{redirect_qs}",
        status_code=302,
    )


# ── Shopify: manual re-sync ───────────────────────────────────────────────────

@router.post("/admin/{store_id}/integrations/shopify/sync")
async def shopify_sync_now(store_id: str, request: Request):
    require_store_owner(request, store_id)
    integrations_data = await db.get_integrations(store_id)
    shopify_data      = integrations_data.get("shopify", {})
    shop              = shopify_data.get("shop", "")
    access_token      = shopify_data.get("access_token", "")
    if not shop or not access_token:
        raise HTTPException(400, "لا يوجد ربط نشط مع Shopify")
    import shopify_sync as _ss
    result = await _ss.sync_shopify_store(store_id, shop, access_token)
    return {"message": "تمت المزامنة", **result}


# ── Salla: disconnect ────────────────────────────────────────────────────────

@router.delete("/admin/{store_id}/integrations/salla")
async def salla_disconnect(store_id: str, request: Request):
    require_store_owner(request, store_id)
    await db.clear_salla_tokens(store_id)
    sm.clear_salla_token(store_id)   # also evict from in-memory registry
    return {"message": "تم قطع الاتصال مع سلّة"}


# ── Shopify: disconnect ───────────────────────────────────────────────────────

@router.delete("/admin/{store_id}/integrations/shopify")
async def shopify_disconnect(store_id: str, request: Request):
    require_store_owner(request, store_id)

    # Remove ScriptTag from Shopify store
    data = await db.get_integrations(store_id)
    shopify_data = data.get("shopify", {})
    shop         = shopify_data.get("shop", "")
    access_token = shopify_data.get("access_token", "")

    if shop and access_token:
        widget_src = f"{BASE_URL}/widget-shopify/{store_id}.js"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{_shopify_api(shop)}/script_tags.json?src={widget_src}",
                    headers={"X-Shopify-Access-Token": access_token},
                )
                for tag in r.json().get("script_tags", []):
                    await client.delete(
                        f"{_shopify_api(shop)}/script_tags/{tag['id']}.json",
                        headers={"X-Shopify-Access-Token": access_token},
                    )
                print(f"[integrations] ScriptTag removed from {shop}")
        except Exception as e:
            print(f"[integrations] ScriptTag removal failed (non-fatal): {e}")

    await db.remove_integration(store_id, "shopify")
    return {"message": "تم قطع الاتصال مع Shopify وإزالة الويدجت من المتجر"}


# ── Zid: initiate install ─────────────────────────────────────────────────────

@router.get("/admin/{store_id}/integrations/zid/install")
async def zid_install(store_id: str, request: Request):
    require_store_owner(request, store_id)

    if not ZID_CLIENT_ID:
        raise HTTPException(503, "لم يتم تهيئة تكامل Zid على هذا الخادم")

    existing = await db.get_integrations(store_id)
    _ECOMMERCE_NAMES = {"salla": "سلّة", "shopify": "شوبيفاي", "woocommerce": "ووكومرس"}
    for platform, label in _ECOMMERCE_NAMES.items():
        if existing.get(platform):
            raise HTTPException(
                409,
                f"الحساب مربوط بـ {label} بالفعل — لا يمكن ربط منصتَي تجارة إلكترونية في آنٍ واحد",
            )

    state = secrets.token_urlsafe(32)
    _prune_oauth_states()
    _oauth_states[state] = {"store_id": store_id, "platform": "zid", "ts": time.time()}

    redirect_uri = f"{BASE_URL}/integrations/zid/callback"
    params = urlencode({
        "client_id":     ZID_CLIENT_ID,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "state":         state,
    })
    return {"install_url": f"{ZID_OAUTH_BASE}/oauth/authorize?{params}"}


# ── Zid: marketplace start page (Application URL in Zid partner dashboard) ───
# Set "Application URL" in Zid partner dashboard to:
#   {BASE_URL}/integrations/zid/start
# Zid redirects merchants here on install. We ask for their 7ayak email,
# look up their store, then redirect to Zid OAuth — which comes back with
# a proper code+state to the Redirection URL (callback).

def _zid_start_page(
    login_error: str = "",
    register_error: str = "",
    active_tab: str = "login",
    prefill_name: str = "",
    prefill_email_reg: str = "",
) -> str:
    import html as _h
    def _err(msg: str) -> str:
        return f'<div class="err" style="display:block">{_h.escape(msg)}</div>' if msg else '<div class="err"></div>'

    login_tab_cls    = "tab active" if active_tab == "login"    else "tab"
    register_tab_cls = "tab active" if active_tab == "register" else "tab"
    login_panel_cls    = "panel active" if active_tab == "login"    else "panel"
    register_panel_cls = "panel active" if active_tab == "register" else "panel"

    safe_name  = _h.escape(prefill_name,      quote=True)
    safe_email = _h.escape(prefill_email_reg, quote=True)

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>7ayak — ربط متجر زد</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',system-ui,sans-serif;background:#f8fafc;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:16px}}
  .card{{background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);padding:36px 32px;max-width:460px;width:100%}}
  .logo{{text-align:center;font-size:26px;font-weight:800;color:#111827;margin-bottom:4px;letter-spacing:-.5px}}
  .sub{{text-align:center;font-size:13px;color:#6b7280;margin-bottom:24px}}
  .badge{{display:flex;align-items:center;gap:8px;justify-content:center;margin-bottom:20px;font-size:13px;color:#6b7280}}
  .badge .arr{{color:#d1d5db}}
  .tabs{{display:flex;background:#f1f5f9;border-radius:10px;padding:4px;margin-bottom:24px;gap:4px}}
  .tab{{flex:1;padding:9px;text-align:center;border:none;background:transparent;border-radius:8px;font-size:14px;font-weight:600;color:#6b7280;cursor:pointer;transition:.15s}}
  .tab.active{{background:#fff;color:#111827;box-shadow:0 1px 4px rgba(0,0,0,.1)}}
  .panel{{display:none}}.panel.active{{display:block}}
  label{{display:block;font-size:13px;font-weight:600;color:#374151;margin-bottom:5px;margin-top:14px}}
  label:first-of-type{{margin-top:0}}
  input{{width:100%;padding:11px 14px;border:1.5px solid #e5e7eb;border-radius:10px;font-size:14px;outline:none;transition:.15s}}
  input:focus{{border-color:#111827}}
  .hint{{font-size:11px;color:#9ca3af;margin-top:4px}}
  .btn{{width:100%;margin-top:18px;padding:13px;background:#111827;color:#fff;border:none;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;transition:.15s}}
  .btn:hover{{background:#1f2937}}
  .btn:disabled{{opacity:.55;cursor:not-allowed}}
  .err{{margin-top:10px;padding:9px 13px;background:#fef2f2;border-radius:8px;color:#b91c1c;font-size:13px;display:none}}
</style>
</head>
<body>
<div class="card">
  <div class="logo">7ayak</div>
  <div class="sub">مساعد التجارة الذكي</div>
  <div class="badge"><span>سوق زد</span><span class="arr">←</span><span>ربط المتجر</span></div>

  <div class="tabs">
    <button class="{login_tab_cls}"    onclick="switchTab('login')"   type="button">لدي حساب</button>
    <button class="{register_tab_cls}" onclick="switchTab('register')" type="button">حساب جديد</button>
  </div>

  <!-- Tab: Login -->
  <div id="panel-login" class="{login_panel_cls}">
    <form method="POST" action="/integrations/zid/start" onsubmit="lock(this)">
      <input type="hidden" name="action" value="login">
      <label for="l-email">البريد الإلكتروني لحساب 7ayak</label>
      <input type="email" id="l-email" name="email" placeholder="example@email.com" required autocomplete="email">
      {_err(login_error)}
      <button class="btn" type="submit">متابعة</button>
    </form>
  </div>

  <!-- Tab: Register -->
  <div id="panel-register" class="{register_panel_cls}">
    <form method="POST" action="/integrations/zid/start" onsubmit="lock(this)">
      <input type="hidden" name="action" value="register">
      <label for="r-name">الاسم الكامل</label>
      <input type="text" id="r-name" name="name" placeholder="محمد عبدالله" required value="{safe_name}">
      <label for="r-email">البريد الإلكتروني</label>
      <input type="email" id="r-email" name="email" placeholder="example@email.com" required autocomplete="email" value="{safe_email}">
      <label for="r-pass">كلمة المرور</label>
      <input type="password" id="r-pass" name="password" placeholder="8 أحرف على الأقل" required minlength="8" autocomplete="new-password">
      <label for="r-pass2">تأكيد كلمة المرور</label>
      <input type="password" id="r-pass2" name="password2" placeholder="أعد إدخال كلمة المرور" required minlength="8">
      {_err(register_error)}
      <button class="btn" type="submit">إنشاء حساب والمتابعة</button>
    </form>
  </div>
</div>
<script>
function switchTab(t){{
  ['login','register'].forEach(function(id){{
    document.getElementById('panel-'+id).className='panel'+(t===id?' active':'');
    document.querySelectorAll('.tab').forEach(function(b,i){{
      b.className='tab'+((['login','register'][i])===t?' active':'');
    }});
  }});
}}
function lock(form){{
  form.querySelector('.btn').disabled=true;
  form.querySelector('.btn').textContent='جارٍ المعالجة…';
}}
</script>
</body>
</html>"""


@router.get("/integrations/zid/start", include_in_schema=False)
async def zid_start_get(request: Request):
    """Application URL — Zid App Market redirects merchants here on install."""
    return Response(content=_zid_start_page(), media_type="text/html; charset=utf-8")


def _zid_oauth_redirect(store_id: str) -> RedirectResponse:
    """Generate Zid OAuth URL and redirect with a fresh state nonce."""
    state = secrets.token_urlsafe(32)
    _prune_oauth_states()
    _oauth_states[state] = {"store_id": store_id, "platform": "zid", "ts": time.time()}
    params = urlencode({
        "client_id":     ZID_CLIENT_ID,
        "redirect_uri":  f"{BASE_URL}/integrations/zid/callback",
        "response_type": "code",
        "state":         state,
    })
    return RedirectResponse(f"{ZID_OAUTH_BASE}/oauth/authorize?{params}", status_code=302)


@router.post("/integrations/zid/start", include_in_schema=False)
async def zid_start_post(request: Request):
    """
    Handles both tabs from the start page:
      action=login    → look up existing 7ayak account by email → OAuth
      action=register → create new 7ayak account → OAuth
    """
    import re
    import auth as _auth_lib
    import store_manager as sm

    if not ZID_CLIENT_ID:
        return Response(
            content=_zid_start_page(login_error="خدمة ربط زد غير مفعّلة، يرجى التواصل مع الدعم."),
            media_type="text/html; charset=utf-8",
        )

    form   = await request.form()
    action = str(form.get("action", "login"))
    email  = str(form.get("email", "")).strip().lower()

    # ── Login tab ────────────────────────────────────────────────────────
    if action == "login":
        if not email:
            return Response(content=_zid_start_page(login_error="الرجاء إدخال البريد الإلكتروني."),
                            media_type="text/html; charset=utf-8")
        store_id = await db.find_store_by_owner_email(email)
        if not store_id:
            return Response(
                content=_zid_start_page(login_error="لم نجد حساباً بهذا البريد. تأكد من صحة البريد أو أنشئ حساباً جديداً."),
                media_type="text/html; charset=utf-8",
            )
        existing = await db.get_integrations(store_id)
        for platform, label in {"salla": "سلّة", "shopify": "شوبيفاي", "woocommerce": "ووكومرس"}.items():
            if existing.get(platform):
                return Response(
                    content=_zid_start_page(login_error=f"الحساب مربوط بـ {label} — لا يمكن ربط منصتَي تجارة في آنٍ واحد."),
                    media_type="text/html; charset=utf-8",
                )
        return _zid_oauth_redirect(store_id)

    # ── Register tab ─────────────────────────────────────────────────────
    name      = str(form.get("name", "")).strip()
    password  = str(form.get("password", ""))
    password2 = str(form.get("password2", ""))

    def _reg_err(msg: str):
        return Response(
            content=_zid_start_page(register_error=msg, active_tab="register",
                                    prefill_name=name, prefill_email_reg=email),
            media_type="text/html; charset=utf-8",
        )

    if not name:
        return _reg_err("الاسم الكامل مطلوب.")
    if not email:
        return _reg_err("البريد الإلكتروني مطلوب.")
    if len(password) < 8:
        return _reg_err("كلمة المرور يجب أن تكون 8 أحرف على الأقل.")
    if password != password2:
        return _reg_err("كلمتا المرور غير متطابقتين.")

    # Check if email already taken
    existing_id = await db.find_store_by_owner_email(email)
    if existing_id:
        return _reg_err("البريد الإلكتروني مستخدم بالفعل. اضغط على «لدي حساب» لتسجيل الدخول.")

    # Generate unique store_id from email username
    slug = re.sub(r"[^a-z0-9]", "_", email.split("@")[0].lower())[:20]
    store_id = slug
    suffix = 2
    while sm.is_registered(store_id) or await db.find_store_by_owner_email(store_id):
        store_id = f"{slug}_{suffix}"
        suffix += 1

    # Create the store
    try:
        await sm.register_store(
            store_id=store_id,
            access_token="",
            store_info={"name": name},
            owner_email=email,
        )
        tokens = sm.get_store_info(store_id)
        await db.save_store(store_id, tokens)
        await db.set_store_owner_email(store_id, email)
        await sm.set_admin_password(store_id, _auth_lib.hash_password(password))
        print(f"[zid_start] ✅ New store created via marketplace: store_id={store_id!r} email={email!r}")
    except Exception as exc:
        print(f"[zid_start] ❌ Account creation failed: {exc}")
        return _reg_err("فشل إنشاء الحساب، يرجى المحاولة مرة أخرى.")

    return _zid_oauth_redirect(store_id)


# ── Zid: marketplace landing-page helpers ────────────────────────────────────

def _zid_no_code_page() -> str:
    """HTML shown when the callback receives neither code nor valid state."""
    return """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>7ayak — خطأ في الربط</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Segoe UI',system-ui,sans-serif;background:#f8fafc;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:16px}
  .card{background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);padding:40px 36px;max-width:440px;width:100%;text-align:center}
  .icon{font-size:48px;margin-bottom:20px}
  h1{font-size:20px;font-weight:700;color:#111827;margin-bottom:10px}
  p{font-size:14px;color:#6b7280;line-height:1.7;margin-bottom:24px}
  .btn{display:inline-block;padding:12px 28px;background:#111827;color:#fff;border-radius:10px;text-decoration:none;font-size:14px;font-weight:600}
</style>
</head>
<body>
<div class="card">
  <div class="icon">⚠️</div>
  <h1>رابط الربط غير صالح</h1>
  <p>لم يتم إرسال رمز التفويض من زد. الرجاء إعادة المحاولة من لوحة تحكم 7ayak ضمن قسم التكاملات.</p>
  <a class="btn" href="javascript:window.close()">إغلاق</a>
</div>
</body>
</html>"""


def _zid_landing_page(code: str) -> str:
    """
    HTML landing page for marketplace-initiated installs (Zid sends code but no state).
    The merchant enters their 7ayak store email so we can identify which store to connect.
    """
    import html as _html
    safe_code = _html.escape(code, quote=True)
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>7ayak — ربط متجر زد</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',system-ui,sans-serif;background:#f8fafc;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:16px}}
  .card{{background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);padding:40px 36px;max-width:460px;width:100%}}
  .logo{{text-align:center;font-size:26px;font-weight:800;color:#111827;margin-bottom:6px;letter-spacing:-.5px}}
  .sub{{text-align:center;font-size:13px;color:#6b7280;margin-bottom:28px}}
  h2{{font-size:17px;font-weight:700;color:#111827;margin-bottom:8px}}
  p{{font-size:13px;color:#6b7280;line-height:1.6;margin-bottom:24px}}
  label{{display:block;font-size:13px;font-weight:600;color:#374151;margin-bottom:6px}}
  input{{width:100%;padding:12px 14px;border:1.5px solid #e5e7eb;border-radius:10px;font-size:14px;outline:none;transition:.15s}}
  input:focus{{border-color:#111827}}
  .hint{{font-size:12px;color:#9ca3af;margin-top:5px}}
  button{{width:100%;margin-top:20px;padding:13px;background:#111827;color:#fff;border:none;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;transition:.15s}}
  button:hover{{background:#1f2937}}
  button:disabled{{opacity:.55;cursor:not-allowed}}
  .err{{margin-top:12px;padding:10px 14px;background:#fef2f2;border-radius:8px;color:#b91c1c;font-size:13px;display:none}}
  .zid-badge{{display:flex;align-items:center;gap:8px;justify-content:center;margin-bottom:22px}}
  .zid-badge span{{font-size:13px;color:#6b7280}}
  .arrow{{color:#d1d5db}}
</style>
</head>
<body>
<div class="card">
  <div class="logo">7ayak</div>
  <div class="sub">مساعد التجارة الذكي</div>
  <div class="zid-badge">
    <span>ربط متجر زد</span>
    <span class="arrow">←</span>
    <span>اكتمال التثبيت</span>
  </div>
  <h2>أدخل بريدك الإلكتروني في 7ayak</h2>
  <p>تم اكتشاف تثبيتك من سوق زد. لاكتمال الربط، أدخل البريد الإلكتروني المرتبط بحساب 7ayak الخاص بك.</p>
  <form id="frm" method="POST" action="/integrations/zid/complete">
    <input type="hidden" name="code" value="{safe_code}">
    <label for="email">البريد الإلكتروني لحساب 7ayak</label>
    <input type="email" id="email" name="email" placeholder="example@email.com" required autocomplete="email">
    <div class="hint">البريد الذي تستخدمه لتسجيل الدخول في 7ayak</div>
    <div class="err" id="err"></div>
    <button type="submit" id="btn">ربط المتجر</button>
  </form>
</div>
<script>
document.getElementById('frm').addEventListener('submit',function(e){{
  var btn=document.getElementById('btn');
  btn.disabled=true;
  btn.textContent='جارٍ الربط…';
}});
</script>
</body>
</html>"""


# ── Zid: complete marketplace install (form POST from _zid_landing_page) ──────

@router.post("/integrations/zid/complete", include_in_schema=False)
async def zid_complete(request: Request):
    """
    Handles form submission from the marketplace landing page.
    Looks up the store by the email entered, then completes the Zid OAuth flow.
    """
    form = await request.form()
    code  = str(form.get("code", "")).strip()
    email = str(form.get("email", "")).strip().lower()

    if not code or not email:
        return Response(content=_zid_no_code_page(), media_type="text/html; charset=utf-8")

    # Find the store by owner email
    store_id = await db.find_store_by_owner_email(email)
    if not store_id:
        err_html = _zid_landing_page(code).replace(
            'class="err" id="err"',
            'class="err" id="err" style="display:block"',
        ).replace(
            '</div>\n  <form',
            'لم نجد حساباً بهذا البريد الإلكتروني. تأكد من صحة البريد ثم أعد المحاولة.</div>\n  <form',
        )
        return Response(content=err_html, media_type="text/html; charset=utf-8")

    # Exchange code → tokens
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{ZID_OAUTH_BASE}/oauth/token",
                data={
                    "grant_type":    "authorization_code",
                    "client_id":     ZID_CLIENT_ID,
                    "client_secret": ZID_CLIENT_SECRET,
                    "redirect_uri":  f"{BASE_URL}/integrations/zid/callback",
                    "code":          code,
                },
            )
            r.raise_for_status()
            token_data = r.json()
    except Exception as exc:
        print(f"[zid_complete] token exchange failed: {exc}")
        return RedirectResponse(
            f"{BASE_URL}/store/{store_id}/integrations?zid=error&reason=token_exchange_failed",
            status_code=302,
        )

    access_token  = token_data.get("access_token", "")
    auth_jwt      = token_data.get("Authorization", "")
    refresh_token = token_data.get("refresh_token", "")
    if not access_token or not auth_jwt:
        return RedirectResponse(
            f"{BASE_URL}/store/{store_id}/integrations?zid=error&reason=missing_tokens",
            status_code=302,
        )

    # Fetch Zid store info
    store_info:   dict = {}
    zid_store_id: str  = ""
    try:
        from zid_client import ZidClient
        zid = ZidClient(access_token, auth_jwt, store_id=store_id)
        raw = await zid.get_store()
        zid_store_id = str(raw.get("id", ""))
        store_info = raw
    except Exception as e:
        print(f"[zid_complete] store info fetch failed (non-fatal): {e}")

    # Save integration
    try:
        await db.save_integration(store_id, "zid", {
            "access_token":      access_token,
            "authorization_jwt": auth_jwt,
            "refresh_token":     refresh_token,
            "zid_store_id":      zid_store_id,
            "store_name":        store_info.get("title", ""),
            "store_email":       store_info.get("email", ""),
            "store_url":         store_info.get("url", ""),
        })
        print(f"[zid_complete] ✅ Zid connected via marketplace: store={store_id}")
    except Exception as e:
        print(f"[zid_complete] ❌ save_integration failed: {e}")
        return RedirectResponse(
            f"{BASE_URL}/store/{store_id}/integrations?zid=error&reason=db_save_failed",
            status_code=302,
        )

    # Background sync + webhooks
    import zid_sync as _zs
    import database as _db_fire
    _db_fire.fire(_zs.sync_zid_store(store_id, access_token, auth_jwt, zid_store_id))
    _db_fire.fire(_zs.register_zid_webhooks(access_token, auth_jwt, zid_store_id, store_id, BASE_URL))

    return RedirectResponse(
        f"{BASE_URL}/store/{store_id}/integrations?zid=connected",
        status_code=302,
    )


# ── Zid: OAuth callback ───────────────────────────────────────────────────────

@router.get("/integrations/zid/callback")
async def zid_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
):
    # Diagnostic: log exactly what Zid sent so a "no code" landing is explainable
    # (direct visit? error? param-name mismatch?). Mask the code value.
    _qp = {k: (v[:6] + "…" if k == "code" and v else v) for k, v in request.query_params.items()}
    print(f"[zid_callback] query={_qp}")

    if error:
        store_id = (_oauth_states.pop(state, None) or {}).get("store_id", "unknown")
        return RedirectResponse(
            f"{BASE_URL}/store/{store_id}/integrations?zid=error&reason={error}",
            status_code=302,
        )

    state_data = _oauth_states.pop(state, None)

    # Marketplace-initiated install: Zid redirects without a state nonce
    # (merchant clicked "Install" from Zid App Market directly).
    # Show a landing page so the merchant can identify their 7ayak store.
    if not state_data or state_data.get("platform") != "zid":
        if not code:
            print(f"[zid_callback] ⚠️ no code + no valid state — showing no-code page. "
                  f"query_keys={list(request.query_params.keys())}")
            return Response(
                content=_zid_no_code_page(),
                media_type="text/html; charset=utf-8",
            )
        return Response(
            content=_zid_landing_page(code),
            media_type="text/html; charset=utf-8",
        )

    store_id = state_data["store_id"]

    # 1. Exchange code → tokens
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{ZID_OAUTH_BASE}/oauth/token",
                data={
                    "grant_type":    "authorization_code",
                    "client_id":     ZID_CLIENT_ID,
                    "client_secret": ZID_CLIENT_SECRET,
                    "redirect_uri":  f"{BASE_URL}/integrations/zid/callback",
                    "code":          code,
                },
            )
            r.raise_for_status()
            token_data = r.json()
    except Exception as exc:
        raise HTTPException(502, f"فشل استبدال الكود مع Zid: {exc}") from exc

    access_token  = token_data.get("access_token", "")
    auth_jwt      = token_data.get("Authorization", "")   # Zid returns key named "Authorization"
    refresh_token = token_data.get("refresh_token", "")
    if not access_token or not auth_jwt:
        raise HTTPException(400, "لم يُرجع Zid tokens صحيحة")

    # 2. Fetch store info
    store_info:   dict = {}
    zid_store_id: str  = ""
    try:
        from zid_client import ZidClient
        zid = ZidClient(access_token, auth_jwt, store_id=store_id)
        raw = await zid.get_store()
        zid_store_id = str(raw.get("id", ""))
        store_info = raw
    except Exception as e:
        print(f"[integrations] Zid store info failed (non-fatal): {e}")

    # 3. Save to DB
    try:
        await db.save_integration(store_id, "zid", {
            "access_token":      access_token,
            "authorization_jwt": auth_jwt,
            "refresh_token":     refresh_token,
            "zid_store_id":      zid_store_id,
            "store_name":        store_info.get("title", ""),
            "store_email":       store_info.get("email", ""),
            "store_url":         store_info.get("url", ""),
        })
        print(f"[integrations] ✅ Zid connected: store={store_id} zid_store_id={zid_store_id}")
    except Exception as e:
        print(f"[integrations] ❌ save_integration (zid) failed: {e}")
        return RedirectResponse(
            f"{BASE_URL}/store/{store_id}/integrations?zid=error&reason=db_save_failed",
            status_code=302,
        )

    # 4. Background sync
    import zid_sync as _zs
    import database as _db_fire
    _db_fire.fire(_zs.sync_zid_store(store_id, access_token, auth_jwt, zid_store_id))

    # 5. Register webhooks (fire-and-forget)
    _db_fire.fire(_zs.register_zid_webhooks(access_token, auth_jwt, zid_store_id, store_id, BASE_URL))

    return RedirectResponse(
        f"{BASE_URL}/store/{store_id}/integrations?zid=connected",
        status_code=302,
    )


# ── Zid: manual re-sync ───────────────────────────────────────────────────────

@router.post("/admin/{store_id}/integrations/zid/sync")
async def zid_sync_now(store_id: str, request: Request):
    require_store_owner(request, store_id)
    data         = await db.get_integrations(store_id)
    zid_data     = data.get("zid", {})
    access_token = zid_data.get("access_token", "")
    auth_jwt     = zid_data.get("authorization_jwt", "")
    zid_store_id = zid_data.get("zid_store_id", "")
    if not access_token or not auth_jwt:
        raise HTTPException(400, "لا يوجد ربط نشط مع Zid")
    import zid_sync as _zs
    result = await _zs.sync_zid_store(store_id, access_token, auth_jwt, zid_store_id)
    return {"message": "تمت المزامنة", **result}


# ── Zid: disconnect ───────────────────────────────────────────────────────────

@router.delete("/admin/{store_id}/integrations/zid")
async def zid_disconnect(store_id: str, request: Request):
    require_store_owner(request, store_id)
    await db.remove_integration(store_id, "zid")
    return {"message": "تم قطع الاتصال مع Zid"}


# ── Zid App Market webhooks (partner-level) ───────────────────────────────────
# Zid sends these when merchants install/uninstall the app or their
# subscription status changes. Target URL in the Zid partner dashboard:
#   {BASE_URL}/webhooks/zid/market

@router.post("/webhooks/zid/market", include_in_schema=False)
async def zid_market_webhook(request: Request):
    """
    Receives App Market lifecycle events from Zid:
      app.market.application.install     → merchant installed the app
      app.market.application.uninstall   → merchant uninstalled → remove integration
      app.market.application.authorized  → OAuth authorized (token already saved via callback)
      app.market.subscription.*          → subscription lifecycle changes
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    event    = payload.get("event", "")
    store_id = str(payload.get("store_id") or payload.get("merchant_id") or "")
    data     = payload.get("data") or {}

    print(f"[zid_market] event={event!r} store_id={store_id!r}")

    if event == "app.market.application.uninstall":
        if store_id:
            try:
                await db.remove_integration(store_id, "zid")
                print(f"[zid_market] ✅ Zid uninstalled: removed integration for store={store_id}")
            except Exception as e:
                print(f"[zid_market] ❌ remove_integration failed for store={store_id}: {e}")

    elif event == "app.market.subscription.suspended":
        print(f"[zid_market] ⚠️ Subscription suspended for store={store_id}")

    elif event == "app.market.subscription.expired":
        print(f"[zid_market] ⚠️ Subscription expired for store={store_id}")
        # Optionally disable the integration without full disconnect

    elif event == "app.market.subscription.active":
        print(f"[zid_market] ✅ Subscription active for store={store_id}")

    elif event == "app.market.application.install":
        print(f"[zid_market] 🎉 New Zid install for store={store_id}")

    # Always return 200 so Zid doesn't retry
    return {"received": True, "event": event}
