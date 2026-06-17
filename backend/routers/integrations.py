"""
Integrations router — OAuth flows, status endpoints, and widget injection
for external platforms.

Currently supported:
  • Shopify — full OAuth 2.0 install + ScriptTag widget injection + disconnect
"""

import hashlib
import hmac as _hmac
import os
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
SHOPIFY_SCOPES        = "read_orders,read_products,read_customers,read_inventory,write_script_tags"
BASE_URL              = os.getenv("BASE_URL", "http://localhost:8000")

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


def _normalize_shop(shop: str) -> str:
    shop = shop.strip().lower().rstrip("/")
    for prefix in ("https://", "http://", "https//", "http//"):
        if shop.startswith(prefix):
            shop = shop[len(prefix):]
            break
    shop = shop.split("/")[0].split("?")[0]
    if not shop.endswith(".myshopify.com"):
        shop = shop + ".myshopify.com"
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

def _zid_start_page(error: str = "") -> str:
    err_block = (
        f'<div class="err" style="display:block">{error}</div>'
        if error else
        '<div class="err" id="err"></div>'
    )
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
  button{{width:100%;margin-top:20px;padding:13px;background:#111827;color:#fff;border:none;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer}}
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
    <span>سوق زد</span>
    <span class="arrow">←</span>
    <span>ربط المتجر</span>
  </div>
  <h2>أدخل بريدك الإلكتروني في 7ayak</h2>
  <p>لإتمام ربط متجر زد مع 7ayak، أدخل البريد الإلكتروني المرتبط بحساب 7ayak الخاص بك.</p>
  <form id="frm" method="POST" action="/integrations/zid/start">
    <label for="email">البريد الإلكتروني لحساب 7ayak</label>
    <input type="email" id="email" name="email" placeholder="example@email.com" required autocomplete="email">
    <div class="hint">البريد الذي تستخدمه لتسجيل الدخول في 7ayak</div>
    {err_block}
    <button type="submit" id="btn">متابعة</button>
  </form>
</div>
<script>
document.getElementById('frm').addEventListener('submit',function(){{
  var btn=document.getElementById('btn');
  btn.disabled=true;btn.textContent='جارٍ التحقق…';
}});
</script>
</body>
</html>"""


@router.get("/integrations/zid/start", include_in_schema=False)
async def zid_start_get(request: Request):
    """
    Application URL — Zid redirects merchants here from the App Market.
    Shows a form asking for their 7ayak email.
    """
    return Response(content=_zid_start_page(), media_type="text/html; charset=utf-8")


@router.post("/integrations/zid/start", include_in_schema=False)
async def zid_start_post(request: Request):
    """
    Handles form from zid_start_get.
    Looks up the store by email, generates OAuth state, redirects to Zid authorization.
    """
    if not ZID_CLIENT_ID:
        return Response(
            content=_zid_start_page("خدمة ربط زد غير مفعّلة حالياً، يرجى التواصل مع الدعم."),
            media_type="text/html; charset=utf-8",
        )

    form  = await request.form()
    email = str(form.get("email", "")).strip().lower()
    if not email:
        return Response(content=_zid_start_page("الرجاء إدخال البريد الإلكتروني."),
                        media_type="text/html; charset=utf-8")

    store_id = await db.find_store_by_owner_email(email)
    if not store_id:
        return Response(
            content=_zid_start_page("لم نجد حساباً بهذا البريد. تأكد من صحة البريد ثم أعد المحاولة."),
            media_type="text/html; charset=utf-8",
        )

    # Check exclusivity
    existing = await db.get_integrations(store_id)
    for platform, label in {"salla": "سلّة", "shopify": "شوبيفاي", "woocommerce": "ووكومرس"}.items():
        if existing.get(platform):
            return Response(
                content=_zid_start_page(f"الحساب مربوط بـ {label} بالفعل — لا يمكن ربط منصتَي تجارة في آنٍ واحد."),
                media_type="text/html; charset=utf-8",
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
    return RedirectResponse(f"{ZID_OAUTH_BASE}/oauth/authorize?{params}", status_code=302)


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
