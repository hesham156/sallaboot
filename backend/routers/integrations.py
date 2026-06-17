"""
Integrations router — OAuth flows and status endpoints for external platforms.

Currently supported:
  • Shopify — full OAuth 2.0 install + disconnect + status
"""

import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

import database as db
from routers.deps import require_store_owner

router = APIRouter()

SHOPIFY_CLIENT_ID     = os.getenv("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_SCOPES        = "read_orders,read_products,read_customers,read_inventory"
BASE_URL              = os.getenv("BASE_URL", "http://localhost:8000")

# In-memory CSRF state store (ephemeral — survives for the duration of the OAuth round-trip)
_oauth_states: dict[str, dict] = {}


def _shopify_api(shop: str) -> str:
    return f"https://{shop}/admin/api/2024-01"


def _normalize_shop(shop: str) -> str:
    shop = shop.strip().lower().rstrip("/")
    # Strip any protocol prefix the user may have pasted
    for prefix in ("https://", "http://", "https//", "http//"):
        if shop.startswith(prefix):
            shop = shop[len(prefix):]
            break
    # Strip trailing path/query if user pasted a full URL
    shop = shop.split("/")[0].split("?")[0]
    if not shop.endswith(".myshopify.com"):
        shop = shop + ".myshopify.com"
    return shop


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


# ── Shopify: OAuth callback (public — Shopify redirects here) ─────────────────

@router.get("/integrations/shopify/callback")
async def shopify_callback(
    request: Request,
    code: str = "",
    shop: str = "",
    state: str = "",
    error: str = "",
):
    if error:
        return RedirectResponse(f"{BASE_URL}/store/unknown/integrations?shopify=error&reason={error}")

    state_data = _oauth_states.pop(state, None)
    if not state_data or state_data.get("shop") != shop:
        raise HTTPException(400, "Invalid or expired OAuth state — please retry")

    store_id = state_data["store_id"]

    # Exchange code for permanent access token
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

    # Fetch basic shop info to display in the UI
    shop_info: dict = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{_shopify_api(shop)}/shop.json",
                headers={"X-Shopify-Access-Token": access_token},
            )
            r.raise_for_status()
            shop_info = r.json().get("shop", {})
    except Exception:
        pass  # non-fatal — we still save the token

    await db.save_integration(store_id, "shopify", {
        "shop":         shop,
        "access_token": access_token,
        "shop_name":    shop_info.get("name", shop),
        "shop_email":   shop_info.get("email", ""),
        "plan_name":    shop_info.get("plan_name", ""),
        "currency":     shop_info.get("currency", ""),
    })

    # Redirect the merchant back to the integrations page with a success flag
    frontend_url = f"{BASE_URL}/store/{store_id}/integrations?shopify=connected"
    return RedirectResponse(frontend_url, status_code=302)


# ── Shopify: disconnect ───────────────────────────────────────────────────────

@router.delete("/admin/{store_id}/integrations/shopify")
async def shopify_disconnect(store_id: str, request: Request):
    require_store_owner(request, store_id)
    await db.remove_integration(store_id, "shopify")
    return {"message": "تم قطع الاتصال مع Shopify بنجاح"}
