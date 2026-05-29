import os
import uuid
import asyncio
import aiofiles
import collections
import datetime as _dt
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import hmac
import hashlib

import re as _re
import store_manager as sm
import auth as _auth
from store_sync import sync_store
from salla_oauth import get_auth_url, exchange_code, save_tokens
import conversation_store as cs

# ── Setup ──────────────────────────────────────────────────────────────────────
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_MB        = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
ALLOWED_EXTENSIONS = {
    ".pdf", ".ai", ".eps", ".psd", ".png", ".jpg", ".jpeg",
    ".svg", ".tiff", ".tif", ".cdr", ".zip",
}

app = FastAPI(title="Salla Printing Chatbot — Multi-tenant", version="2.0.0")


@app.on_event("startup")
async def startup_event():
    """Load all registered stores and trigger background sync for each."""
    sm.load_all_stores()

    # Always register env-var token as "default" store — survives Railway restarts
    env_token = os.getenv("SALLA_ACCESS_TOKEN", "")
    if env_token and not sm.is_registered("default"):
        sm.register_store(
            "default", env_token,
            os.getenv("SALLA_REFRESH_TOKEN", ""),
            {"name": "المتجر الافتراضي"},
        )
        print("[startup] Registered 'default' store from SALLA_ACCESS_TOKEN env var")

    for store in sm.list_stores():
        token = sm.get_access_token(store["store_id"])
        if token:
            asyncio.create_task(_sync_task(store["store_id"], token))


async def _sync_task(store_id: str, token: str):
    try:
        await sync_store(token, store_id)
        print(f"✅ Store sync completed for {store_id!r}")
    except Exception as e:
        print(f"⚠️ Store sync failed for {store_id!r}: {e}")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

_ADMIN_HTML = Path(__file__).parent / "admin.html"


# ── Auth middleware ────────────────────────────────────────────────────────────
# Protects all per-store admin API routes (not the HTML pages or auth endpoints).
_PROTECTED_RE = _re.compile(
    r"^/admin/(?!stores$|auth/)([^/]+)/(conversations|bot|sync|products|debug|settings|webhooks)"
)
_SUPER_PROTECTED_RE = _re.compile(r"^/admin/stores$")


@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    path = request.url.path

    # Per-store API routes
    m = _PROTECTED_RE.match(path)
    if m:
        store_id = m.group(1)
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        claims = _auth.verify_token(token)
        if not claims:
            return JSONResponse({"detail": "يرجى تسجيل الدخول"}, status_code=401)
        if not claims.get("su") and claims.get("s") != store_id:
            return JSONResponse({"detail": "غير مصرح لك بالوصول"}, status_code=403)

    # Super admin: protect store list
    elif _SUPER_PROTECTED_RE.match(path):
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        claims = _auth.verify_token(token)
        if not claims or not claims.get("su"):
            return JSONResponse({"detail": "يرجى تسجيل الدخول كمدير عام"}, status_code=401)

    return await call_next(request)


# ── Models ─────────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    store_id: Optional[str] = "default"


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    bot_enabled: bool = True
    components: Optional[list] = None   # rich UI components (product cards, cart, checkout…)
    cart_count: int = 0                 # current cart item count for badge


class AdminReplyRequest(BaseModel):
    message: str


class BotToggleRequest(BaseModel):
    enabled: bool


class LoginRequest(BaseModel):
    password: str


class AIConfigRequest(BaseModel):
    groq_api_key:      Optional[str] = ""
    anthropic_api_key: Optional[str] = ""
    ai_model:          Optional[str] = ""  # e.g. "llama-3.3-70b-versatile" or "claude-sonnet-4-6"
    bot_name:          Optional[str] = ""


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password:     str


# ── Utility endpoints ──────────────────────────────────────────────────────────
@app.get("/env-check")
async def env_check():
    return {
        "GROQ_API_KEY":       bool(os.getenv("GROQ_API_KEY")),
        "ANTHROPIC_API_KEY":  bool(os.getenv("ANTHROPIC_API_KEY")),
        "SALLA_ACCESS_TOKEN": bool(os.getenv("SALLA_ACCESS_TOKEN")),
        "BASE_URL":           os.getenv("BASE_URL", "not set"),
        "stores_registered":  len(sm.list_stores()),
    }


@app.get("/widget.js")
async def serve_widget():
    widget_path = Path(__file__).parent / "widget.js"
    return FileResponse(widget_path, media_type="application/javascript")


@app.get("/health")
async def health():
    stores = sm.list_stores()
    total_products = sum(s.get("products_count", 0) for s in stores)
    return {
        "status":           "ok",
        "service":          "salla-printing-chatbot",
        "version":          "2.0.0",
        "stores_count":     len(stores),
        "total_products":   total_products,
    }


# ── Admin HTML ─────────────────────────────────────────────────────────────────
@app.get("/admin", response_class=HTMLResponse)
async def admin_index():
    """Super-admin dashboard (lists all connected stores)."""
    return HTMLResponse(_ADMIN_HTML.read_text(encoding="utf-8"))


@app.get("/admin/stores")
async def admin_list_stores():
    """Return JSON list of all registered stores."""
    return {"stores": sm.list_stores()}


# NOTE: /admin/{store_id} must come AFTER /admin/stores so FastAPI matches
# the literal 'stores' path first.
@app.get("/admin/{store_id}", response_class=HTMLResponse)
async def admin_store_page(store_id: str):
    """Per-store admin dashboard. Same HTML; JS reads the store_id from the URL."""
    return HTMLResponse(_ADMIN_HTML.read_text(encoding="utf-8"))


# ── Auth: Super admin login ────────────────────────────────────────────────────
@app.post("/admin/auth/login")
async def super_login(req: LoginRequest):
    super_pass = os.getenv("SUPER_ADMIN_PASSWORD", "admin")
    if not req.password or req.password != super_pass:
        raise HTTPException(401, "كلمة المرور غير صحيحة")
    token = _auth.create_token("super", is_super=True)
    return {"token": token, "store_id": "super", "is_super": True}


# ── Auth: Per-store login ──────────────────────────────────────────────────────
@app.post("/admin/{store_id}/auth/login")
async def store_login(store_id: str, req: LoginRequest):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    stored_hash = sm.get_admin_password_hash(store_id)
    if not stored_hash or not _auth.check_password(req.password, stored_hash):
        raise HTTPException(401, "كلمة المرور غير صحيحة")
    token = _auth.create_token(store_id)
    info  = sm.get_store_info(store_id)
    return {
        "token":      token,
        "store_id":   store_id,
        "store_name": info.get("store_name", f"متجر {store_id}"),
    }


# ── Settings: AI config ────────────────────────────────────────────────────────
@app.get("/admin/{store_id}/settings/ai")
async def get_ai_settings(store_id: str):
    cfg = sm.get_ai_config(store_id)
    # Mask the keys — return only whether they exist, not the actual value
    return {
        "groq_api_key":      "••••" if cfg.get("groq_api_key")      else "",
        "anthropic_api_key": "••••" if cfg.get("anthropic_api_key") else "",
        "ai_model":          cfg.get("ai_model",  ""),
        "bot_name":          cfg.get("bot_name",  ""),
        "provider":          "groq" if cfg.get("groq_api_key") else
                             ("anthropic" if cfg.get("anthropic_api_key") else "env"),
    }


@app.put("/admin/{store_id}/settings/ai")
async def update_ai_settings(store_id: str, req: AIConfigRequest):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    existing = sm.get_ai_config(store_id)
    config = {
        # Only update a key if a non-empty value was sent; keep existing otherwise
        "groq_api_key":      req.groq_api_key.strip()      or existing.get("groq_api_key",      ""),
        "anthropic_api_key": req.anthropic_api_key.strip() or existing.get("anthropic_api_key", ""),
        "ai_model":          req.ai_model.strip()          or existing.get("ai_model",          ""),
        "bot_name":          req.bot_name.strip()          or existing.get("bot_name",          ""),
    }
    sm.set_ai_config(store_id, config)
    return {"status": "ok", "message": "تم حفظ إعدادات الذكاء الاصطناعي"}


# ── Settings: Change password ──────────────────────────────────────────────────
@app.put("/admin/{store_id}/settings/password")
async def change_store_password(store_id: str, req: PasswordChangeRequest):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    stored_hash = sm.get_admin_password_hash(store_id)
    if not _auth.check_password(req.current_password, stored_hash):
        raise HTTPException(401, "كلمة المرور الحالية غير صحيحة")
    if len(req.new_password) < 6:
        raise HTTPException(400, "كلمة المرور الجديدة يجب أن تكون 6 أحرف على الأقل")
    sm.set_admin_password(store_id, _auth.hash_password(req.new_password))
    return {"status": "ok", "message": "تم تغيير كلمة المرور بنجاح"}


# ── Settings: Super admin reset password for a store ──────────────────────────
@app.put("/admin/stores/{store_id}/reset-password")
async def super_reset_password(store_id: str, request: Request):
    # Must be super admin
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(403, "مصرح للمدير العام فقط")
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    # Reset to store_id as default
    sm.set_admin_password(store_id, _auth.hash_password(str(store_id)))
    return {"status": "ok", "message": f"تمت إعادة تعيين كلمة المرور إلى: {store_id}"}


# ── Per-store sync ─────────────────────────────────────────────────────────────
@app.post("/admin/{store_id}/sync")
async def store_sync_endpoint(store_id: str):
    token = sm.get_access_token(store_id)
    if not token:
        raise HTTPException(400, f"No access token for store '{store_id}'.")
    try:
        data = await sync_store(token, store_id)
        return {
            "status":           "ok",
            "products_count":   data.get("products_count", 0),
            "categories_count": len(data.get("categories", [])),
            "articles_count":   len(data.get("articles", [])),
            "last_sync":        data.get("last_sync"),
            "errors":           data.get("last_sync_errors", []),
        }
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)}")


# ── Per-store products ─────────────────────────────────────────────────────────
@app.get("/admin/{store_id}/products")
async def store_products(store_id: str):
    cache = sm.get_cache(store_id)
    return {
        "products":        cache.get("products", []),
        "categories":      cache.get("categories", []),
        "articles":        cache.get("articles", []),
        "products_count":  cache.get("products_count", 0),
        "last_sync":       cache.get("last_sync", "never"),
        "errors":          cache.get("last_sync_errors", []),
    }


# ── Per-store debug ────────────────────────────────────────────────────────────
@app.get("/admin/{store_id}/debug")
async def store_debug(store_id: str):
    import httpx as _httpx

    token   = sm.get_access_token(store_id)
    refresh = sm.get_refresh_token(store_id)
    info    = sm.get_store_info(store_id)
    cache   = sm.get_cache(store_id)

    result = {
        "store_id":              store_id,
        "store_name":            info.get("store_name", "—"),
        "token_present":         bool(token),
        "token_preview":         (token[:12] + "…") if token else None,
        "refresh_token_present": bool(refresh),
        "cached_products":       cache.get("products_count", 0),
        "cached_categories":     len(cache.get("categories", [])),
        "last_sync":             cache.get("last_sync", "never"),
        "last_sync_errors":      cache.get("last_sync_errors", []),
        "salla_api_test":        None,
    }

    if token:
        try:
            async with _httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://api.salla.dev/admin/v2/products",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    params={"per_page": 3, "page": 1},
                )
                result["salla_api_test"] = {
                    "status_code": r.status_code,
                    "body_preview": r.text[:500],
                }
        except Exception as e:
            result["salla_api_test"] = {"error": f"{type(e).__name__}: {e}"}

    return result


# ── Per-store bot toggle ───────────────────────────────────────────────────────
@app.get("/admin/{store_id}/bot/status")
async def store_bot_status(store_id: str):
    return {"bot_globally_enabled": cs.get_store_bot(store_id)}


@app.post("/admin/{store_id}/bot/toggle")
async def store_bot_toggle(store_id: str, req: BotToggleRequest):
    cs.set_store_bot(store_id, req.enabled)
    return {"bot_globally_enabled": cs.get_store_bot(store_id)}


# ── Per-store conversations ────────────────────────────────────────────────────
@app.get("/admin/{store_id}/conversations")
async def store_conversations(store_id: str):
    return {"conversations": cs.summary_list(store_id)}


@app.get("/admin/{store_id}/conversations/{session_id}")
async def store_conversation_detail(store_id: str, session_id: str):
    cs.mark_admin_read(session_id)
    conv = cs.all_conversations().get(session_id)
    if not conv:
        raise HTTPException(404, "المحادثة غير موجودة")
    return conv


@app.post("/admin/{store_id}/conversations/{session_id}/reply")
async def store_admin_reply(store_id: str, session_id: str, req: AdminReplyRequest):
    if not req.message.strip():
        raise HTTPException(400, "الرسالة فارغة")
    msg = cs.add_message(session_id, "admin", req.message.strip(), store_id)
    cs.mark_admin_read(session_id)
    return {"status": "sent", "message": msg}


@app.post("/admin/{store_id}/conversations/{session_id}/takeover")
async def store_takeover(store_id: str, session_id: str):
    cs.set_session_bot(session_id, False)
    cs.mark_admin_read(session_id)
    return {"status": "ok", "bot_enabled": False, "session_id": session_id}


@app.post("/admin/{store_id}/conversations/{session_id}/handback")
async def store_handback(store_id: str, session_id: str):
    cs.set_session_bot(session_id, True)
    cs.add_message(session_id, "admin",
                   "✅ تم إعادة توصيلك بالمساعد الذكي. كيف يمكنني مساعدتك؟",
                   store_id)
    return {"status": "ok", "bot_enabled": True, "session_id": session_id}


# ── Backward-compat admin aliases (for single-store setups) ───────────────────
@app.post("/admin/sync")
async def admin_sync_compat():
    return await store_sync_endpoint("default")


@app.get("/admin/products")
async def admin_products_compat():
    return await store_products("default")


@app.get("/admin/debug")
async def admin_debug_compat():
    return await store_debug("default")


@app.get("/admin/bot/status")
async def admin_bot_status_compat():
    return {"bot_globally_enabled": cs.get_bot_globally()}


@app.post("/admin/bot/toggle")
async def admin_bot_toggle_compat(req: BotToggleRequest):
    cs.set_bot_globally(req.enabled)
    return {"bot_globally_enabled": cs.get_bot_globally()}


@app.get("/admin/conversations")
async def admin_conversations_compat():
    return await store_conversations("default")


@app.get("/admin/conversations/{session_id}")
async def admin_conversation_detail_compat(session_id: str):
    return await store_conversation_detail("default", session_id)


@app.post("/admin/conversations/{session_id}/reply")
async def admin_reply_compat(session_id: str, req: AdminReplyRequest):
    return await store_admin_reply("default", session_id, req)


@app.post("/admin/conversations/{session_id}/takeover")
async def admin_takeover_compat(session_id: str):
    return await store_takeover("default", session_id)


@app.post("/admin/conversations/{session_id}/handback")
async def admin_handback_compat(session_id: str):
    return await store_handback("default", session_id)


# ── Webhook infrastructure ─────────────────────────────────────────────────────

# In-memory log of the last 200 webhook events (per-process; lost on restart).
# Key: store_id → deque of event dicts.
_webhook_log: dict = collections.defaultdict(lambda: collections.deque(maxlen=200))

# Idempotency: remember (event, merchant_id, event_id) tuples we already handled.
# Salla retries up to 3× every 5 min — we must not double-process.
_seen_events: collections.deque = collections.deque(maxlen=1000)


def _log_event(store_id: str, event: str, status: str, detail: str = ""):
    _webhook_log[store_id].appendleft({
        "event":   event,
        "status":  status,
        "detail":  detail,
        "ts":      _dt.datetime.utcnow().isoformat() + "Z",
    })


def _already_seen(dedup_key: str) -> bool:
    if dedup_key in _seen_events:
        return True
    _seen_events.append(dedup_key)
    return False


def _verify_signature(body: bytes, headers) -> bool:
    """
    Verify X-Salla-Signature using HMAC-SHA256.
    Returns False (reject) if the secret is set but signature is missing or wrong.
    Returns True (accept) if secret is not configured (dev mode).
    """
    secret = os.getenv("SALLA_WEBHOOK_SECRET", "")
    if not secret:
        return True          # No secret configured — accept all (dev/test mode)

    sig = headers.get("X-Salla-Signature", "")
    if not sig:
        print("[webhook] ⛔ Missing X-Salla-Signature — rejected")
        return False

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        print(f"[webhook] ⛔ Signature mismatch — rejected (got {sig[:16]}…)")
        return False

    return True


# ── Per-event async handlers ───────────────────────────────────────────────────

async def _handle_store_authorize(merchant_id: str, data: dict):
    """app.store.authorize — store installs / reinstalls the app."""
    access_token  = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    expires       = data.get("expires", 0)       # unix timestamp (2-week expiry)
    store_info    = data.get("store", {})

    store_id = merchant_id or "default"
    if not access_token:
        print(f"[webhook] app.store.authorize for {store_id!r} — no token in payload")
        return

    sm.register_store(
        store_id=store_id,
        access_token=access_token,
        refresh_token=refresh_token,
        store_info=store_info,
    )
    asyncio.create_task(_sync_task(store_id, access_token))
    _log_event(store_id, "app.store.authorize", "ok",
               f"token …{access_token[-6:]}  expires={expires}")
    print(f"[webhook] ✅ Store {store_id!r} authorized, sync triggered")


async def _handle_product_event(event: str, merchant_id: str, data: dict):
    """
    product.created / product.updated / product.deleted /
    product.status.updated / product.price.updated / product.image.updated /
    product.category.updated / product.brand.updated / product.tags.updated /
    product.available / product.quantity.low
    → Incremental cache patch instead of full re-sync.
    """
    from store_sync import patch_product_in_cache

    store_id   = merchant_id or "default"
    product_id = data.get("id") or data.get("product_id", "")
    if not product_id:
        return

    is_delete = event == "product.deleted"
    ok = await patch_product_in_cache(store_id, product_id, delete=is_delete)
    status = "ok" if ok else "skip"
    _log_event(store_id, event, status, f"product_id={product_id}")

    # Also reset the agent so the updated catalogue is reflected in the next chat
    if ok:
        sm._registry.get(store_id, {}).update({"agent": None})


async def _handle_order_event(event: str, merchant_id: str, data: dict):
    """
    order.created / order.updated / order.status.updated / order.cancelled …
    Logs the event; could be extended to send admin notifications.
    """
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


async def _handle_customer_event(event: str, merchant_id: str, data: dict):
    store_id    = merchant_id or "default"
    customer_id = str(data.get("id", ""))
    _log_event(store_id, event, "ok", f"customer_id={customer_id}")
    print(f"[webhook] {event!r} customer={customer_id} store={store_id}")


# ── Salla Webhook endpoint ─────────────────────────────────────────────────────
@app.post("/webhook/salla")
async def salla_webhook(request: Request):
    """
    Central Salla webhook receiver.
    • Verifies HMAC-SHA256 signature (strict — rejects missing signatures when secret is set)
    • Deduplicates retries (Salla retries up to 3× every 5 min)
    • Routes to per-event async handlers and always returns 200 within the 30 s timeout
    """
    body = await request.body()

    # ── 1. Signature verification ──────────────────────────────────────────────
    if not _verify_signature(body, request.headers):
        raise HTTPException(401, "Invalid or missing webhook signature")

    # ── 2. Parse JSON ──────────────────────────────────────────────────────────
    import json as _json
    try:
        payload = _json.loads(body)
    except Exception as exc:
        raise HTTPException(400, f"Invalid JSON: {exc}")

    event       = payload.get("event", "")
    merchant_id = str(payload.get("merchant", ""))
    data        = payload.get("data", {})
    created_at  = payload.get("created_at", "")

    print(f"[webhook] {event!r}  merchant={merchant_id or '—'}  ts={created_at}")

    # ── 3. Idempotency — skip duplicate deliveries ─────────────────────────────
    dedup_key = f"{event}:{merchant_id}:{created_at}"
    if _already_seen(dedup_key):
        print(f"[webhook] Duplicate event skipped: {dedup_key}")
        return {"status": "ok", "duplicate": True}

    # ── 4. Route to handler ────────────────────────────────────────────────────
    if event == "app.store.authorize":
        # Handle synchronously so the store is registered before we return
        await _handle_store_authorize(merchant_id, data)

    elif event == "app.updated":
        # Salla will immediately follow up with app.store.authorize containing
        # new tokens — nothing to do here except log it.
        _log_event(merchant_id or "default", event, "ok", "awaiting app.store.authorize")
        print(f"[webhook] app.updated for merchant {merchant_id} — new tokens incoming")

    elif event.startswith("product."):
        asyncio.create_task(_handle_product_event(event, merchant_id, data))

    elif event.startswith("order."):
        asyncio.create_task(_handle_order_event(event, merchant_id, data))

    elif event.startswith("customer."):
        asyncio.create_task(_handle_customer_event(event, merchant_id, data))

    else:
        # Unknown / unhandled event — log and acknowledge
        _log_event(merchant_id or "default", event, "unhandled")
        print(f"[webhook] Unhandled event: {event!r}")

    return {"status": "ok", "event": event}


# ── Webhook events log (per-store) ─────────────────────────────────────────────
@app.get("/admin/{store_id}/webhooks/log")
async def store_webhook_log(store_id: str):
    """Return the last 200 webhook events received for this store."""
    events = list(_webhook_log.get(store_id, []))
    return {"store_id": store_id, "count": len(events), "events": events}


# ── Salla OAuth ────────────────────────────────────────────────────────────────
@app.get("/auth/salla")
async def salla_auth():
    base         = os.getenv("BASE_URL", "http://localhost:8000")
    redirect_uri = f"{base}/auth/callback"
    return RedirectResponse(get_auth_url(redirect_uri))


@app.get("/auth/callback")
async def salla_callback(code: str = "", error: str = ""):
    if error or not code:
        return HTMLResponse(
            "<h2 style='color:red;font-family:Arial'>فشل التفويض. أعد المحاولة.</h2>",
            status_code=400,
        )
    base         = os.getenv("BASE_URL", "http://localhost:8000")
    redirect_uri = f"{base}/auth/callback"
    try:
        tokens        = await exchange_code(code, redirect_uri)
        access_token  = tokens["access_token"]
        refresh_token = tokens.get("refresh_token", "")
        save_tokens(access_token, refresh_token)
        sm.register_store("default", access_token, refresh_token)
        asyncio.create_task(_sync_task("default", access_token))
        return HTMLResponse("""
        <html><body style='font-family:Arial;text-align:center;padding:60px;direction:rtl'>
          <h2 style='color:#16a34a'>✅ تم ربط المتجر بنجاح!</h2>
          <p>يمكنك إغلاق هذه الصفحة والعودة لاستخدام الشات بوت.</p>
          <a href='/admin' style='color:#3b82f6'>← فتح لوحة التحكم</a>
        </body></html>
        """)
    except Exception as e:
        return HTMLResponse(
            f"<h2 style='color:red;font-family:Arial'>خطأ: {str(e)}</h2>",
            status_code=500,
        )


# ── Chat ───────────────────────────────────────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(400, "الرسالة فارغة")

    store_id   = req.store_id or "default"
    session_id = req.session_id or str(uuid.uuid4())
    bot_on     = cs.is_bot_enabled(session_id)

    if not bot_on:
        cs.add_message(session_id, "user", req.message, store_id)
        return ChatResponse(
            reply="شكراً لرسالتك، سيتواصل معك أحد أعضاء فريق الدعم قريباً. 👨‍💼",
            session_id=session_id,
            bot_enabled=False,
        )

    agent = sm.get_agent(store_id)
    if agent is None:
        env_token = os.getenv("SALLA_ACCESS_TOKEN", "")

        # 1) Exact store not found — register env-var token as "default" ONCE
        #    (avoid calling register_store on every request — it resets the agent)
        if env_token:
            if not sm.is_registered("default"):
                sm.register_store(
                    "default", env_token,
                    os.getenv("SALLA_REFRESH_TOKEN", ""),
                    {"name": "المتجر الافتراضي"},
                )
            agent    = sm.get_agent("default")
            store_id = "default"

        # 2) No env var — fall back to first available registered store
        if agent is None:
            stores = sm.list_stores()
            if stores:
                fallback_id = stores[0]["store_id"]
                agent    = sm.get_agent(fallback_id)
                store_id = fallback_id

        # 3) Nothing works → friendly message (not HTTP 500)
        if agent is None:
            return ChatResponse(
                reply=(
                    "عذراً، المتجر غير مُعدّ بعد. "
                    "يرجى ربط المتجر من لوحة التحكم أو التواصل مع الدعم."
                ),
                session_id = session_id,
                bot_enabled= False,
            )

    try:
        reply = await agent.chat(message=req.message, session_id=session_id)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)}")

    # Pick up any rich UI component set by the agent tools this turn
    component  = cs.pop_last_component(session_id)
    cart_count = len(cs.get_cart(session_id))

    return ChatResponse(
        reply      = reply,
        session_id = session_id,
        bot_enabled= True,
        components = [component] if component else None,
        cart_count = cart_count,
    )


@app.get("/chat/poll")
async def chat_poll(session_id: str):
    """Widget polls this endpoint to receive admin messages in real time."""
    pending = cs.pop_pending_for_widget(session_id)
    bot_on  = cs.is_bot_enabled(session_id)
    return {"messages": pending, "bot_enabled": bot_on}


# ── File upload ────────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str  = Form(default=""),
    store_id: str    = Form(default="default"),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"نوع الملف غير مدعوم. الأنواع المسموحة: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"حجم الملف يتجاوز الحد المسموح ({MAX_FILE_MB} MB)")

    file_id   = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{file_id}{suffix}"
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(contents)

    if session_id:
        notification = (
            f"[العميل أرسل ملف تصميم: {file.filename} — "
            f"تم حفظه بنجاح، سيتم مراجعته من فريق التصميم]"
        )
        agent = sm.get_agent(store_id)
        if agent:
            await agent.chat(message=notification, session_id=session_id)

    return {
        "message":  "تم رفع الملف بنجاح! سيتم مراجعته من فريق التصميم وسنتواصل معك قريباً.",
        "file_id":  file_id,
        "filename": file.filename,
    }
