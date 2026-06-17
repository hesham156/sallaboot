"""
Integrations router — OAuth flows, status endpoints, and widget injection
for external platforms.

Currently supported:
  • Shopify — full OAuth 2.0 install + ScriptTag widget injection + disconnect
"""

import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

import database as db
from routers.deps import require_store_owner

router = APIRouter()

SHOPIFY_CLIENT_ID     = os.getenv("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_SCOPES        = "read_orders,read_products,read_customers,read_inventory,write_script_tags"
BASE_URL              = os.getenv("BASE_URL", "http://localhost:8000")

# In-memory CSRF state store (ephemeral)
_oauth_states: dict[str, dict] = {}


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

    shop = _normalize_shop(shop)
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"store_id": store_id, "shop": shop}

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

    # 3. Save to DB
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

    # 4. Inject chat widget into Shopify storefront via ScriptTag
    widget_src = f"{BASE_URL}/widget-shopify/{store_id}.js"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Remove any existing script tags we created first (idempotent)
            r = await client.get(
                f"{_shopify_api(shop)}/script_tags.json?src={widget_src}",
                headers={"X-Shopify-Access-Token": access_token},
            )
            existing = r.json().get("script_tags", []) if r.is_success else []
            for tag in existing:
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
            if not r.is_success:
                print(f"[integrations] ScriptTag POST failed {r.status_code}: {r.text[:400]}")
            r.raise_for_status()
            print(f"[integrations] ✅ ScriptTag injected for {shop}")
    except Exception as e:
        print(f"[integrations] ScriptTag injection failed (non-fatal): {e}")

    return RedirectResponse(
        f"{BASE_URL}/store/{store_id}/integrations?shopify=connected",
        status_code=302,
    )


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
