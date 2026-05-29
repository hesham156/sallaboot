import os
import uuid
import asyncio
import aiofiles
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import hmac
import hashlib

from agent import PrintingAgent
from salla_oauth import get_auth_url, exchange_code, save_tokens
from store_sync import sync_store, load_cache, get_store_data

# ── Setup ──────────────────────────────────────────────────────────────────────
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

ALLOWED_EXTENSIONS = {
    ".pdf", ".ai", ".eps", ".psd", ".png", ".jpg", ".jpeg",
    ".svg", ".tiff", ".tif", ".cdr", ".zip",
}

app = FastAPI(title="Salla Printing Chatbot", version="1.0.0")


@app.on_event("startup")
async def startup_event():
    """Load cached store data and attempt a live sync on startup."""
    load_cache()  # Always load cache first (instant)
    token = os.getenv("SALLA_ACCESS_TOKEN", "")
    if token:
        try:
            await sync_store(token)
            print("✅ Store sync completed on startup")
        except Exception as e:
            print(f"⚠️ Store sync failed on startup: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Lazy-init: don't crash on startup if env vars are missing
_agent = None

def get_agent() -> PrintingAgent:
    global _agent
    if _agent is None:
        _agent = PrintingAgent()
    return _agent


# ── Models ─────────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/env-check")
async def env_check():
    """Debug: show which API keys are configured (values hidden)."""
    return {
        "GROQ_API_KEY": bool(os.getenv("GROQ_API_KEY")),
        "ANTHROPIC_API_KEY": bool(os.getenv("ANTHROPIC_API_KEY")),
        "SALLA_ACCESS_TOKEN": bool(os.getenv("SALLA_ACCESS_TOKEN")),
        "BASE_URL": os.getenv("BASE_URL", "not set"),
    }


@app.get("/widget.js")
async def serve_widget():
    """Serve the chat widget JS file."""
    widget_path = Path(__file__).parent / "widget.js"
    return FileResponse(widget_path, media_type="application/javascript")


@app.get("/health")
async def health():
    has_token = bool(os.getenv("SALLA_ACCESS_TOKEN"))
    store = get_store_data()
    return {
        "status": "ok",
        "service": "salla-printing-chatbot",
        "salla_connected": has_token,
        "products_synced": store.get("products_count", 0),
        "last_sync": store.get("last_sync", "never"),
    }


@app.post("/admin/sync")
async def admin_sync():
    """Manually trigger a full store sync. Call this after updating products."""
    token = os.getenv("SALLA_ACCESS_TOKEN", "")
    if not token:
        raise HTTPException(status_code=400, detail="SALLA_ACCESS_TOKEN is missing.")
    try:
        data = await sync_store(token)
        return {
            "status": "ok",
            "products_count": data.get("products_count", 0),
            "categories_count": len(data.get("categories", [])),
            "articles_count": len(data.get("articles", [])),
            "last_sync": data.get("last_sync"),
            "errors": data.get("last_sync_errors", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel():
    """Serve the admin dashboard."""
    html_path = Path(__file__).parent / "admin.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/admin/products")
async def admin_products():
    """Return all cached products, categories and articles."""
    store = get_store_data()
    return {
        "products":   store.get("products", []),
        "categories": store.get("categories", []),
        "articles":   store.get("articles", []),
        "products_count": store.get("products_count", 0),
        "last_sync":  store.get("last_sync", "never"),
        "errors":     store.get("last_sync_errors", []),
    }


@app.get("/admin/debug")
async def admin_debug():
    """
    Diagnose Salla connection and store sync status.
    Tests the API directly and returns raw status — use this when products are not loading.
    """
    import httpx as _httpx

    token = os.getenv("SALLA_ACCESS_TOKEN", "")
    refresh = os.getenv("SALLA_REFRESH_TOKEN", "")
    store = get_store_data()

    result = {
        "token_present": bool(token),
        "token_preview": (token[:12] + "…") if token else None,
        "refresh_token_present": bool(refresh),
        "cached_products": store.get("products_count", 0),
        "cached_categories": len(store.get("categories", [])),
        "last_sync": store.get("last_sync", "never"),
        "last_sync_errors": store.get("last_sync_errors", []),
        "salla_api_test": None,
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


# ── Salla Webhook (Easy Mode) ──────────────────────────────────────────────────
@app.post("/webhook/salla")
async def salla_webhook(request: Request):
    """
    Receives Salla webhook events.
    Verifies HMAC signature when SALLA_WEBHOOK_SECRET is set.
    On app.store.authorize: saves the access_token and refresh_token.
    """
    body = await request.body()

    # Verify Salla signature if secret is configured
    webhook_secret = os.getenv("SALLA_WEBHOOK_SECRET", "")
    if webhook_secret:
        sig_header = request.headers.get("X-Salla-Signature", "")
        expected = hmac.new(
            webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        if sig_header and not hmac.compare_digest(expected, sig_header):
            print(f"[webhook] Invalid signature — rejected")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    import json as _json
    try:
        payload = _json.loads(body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    event = payload.get("event", "")
    print(f"[webhook] Received event: {event}")

    if event == "app.store.authorize":
        data = payload.get("data", {})
        access_token = data.get("access_token", "")
        refresh_token = data.get("refresh_token", "")

        if access_token:
            save_tokens(access_token, refresh_token)
            print(f"[webhook] ✅ Access token received and saved! (preview: {access_token[:12]}…)")
            # Update running agent's Salla client if initialized
            try:
                a = get_agent()
                if a.salla:
                    a.salla.headers["Authorization"] = f"Bearer {access_token}"
                else:
                    from salla_client import SallaClient
                    a.salla = SallaClient(access_token)
            except Exception:
                pass
            # Trigger background store sync with new token
            asyncio.create_task(sync_store(access_token))
            print(f"[webhook] ✅ Store sync triggered in background")
            return {"status": "ok", "message": "Token saved successfully"}

    # Log other events silently
    return {"status": "ok", "event": event}


# ── Salla OAuth ────────────────────────────────────────────────────────────────
@app.get("/auth/salla")
async def salla_auth(request_url: str = ""):
    """Redirect to Salla authorization page."""
    base = os.getenv("BASE_URL", "http://localhost:8000")
    redirect_uri = f"{base}/auth/callback"
    url = get_auth_url(redirect_uri)
    return RedirectResponse(url)


@app.get("/auth/callback")
async def salla_callback(code: str = "", error: str = ""):
    """Salla OAuth callback — exchanges code for access token."""
    if error or not code:
        return HTMLResponse(
            "<h2 style='color:red;font-family:Arial'>فشل التفويض. أعد المحاولة.</h2>",
            status_code=400,
        )
    base = os.getenv("BASE_URL", "http://localhost:8000")
    redirect_uri = f"{base}/auth/callback"
    try:
        tokens = await exchange_code(code, redirect_uri)
        save_tokens(tokens["access_token"], tokens.get("refresh_token", ""))
        # Reinitialize agent with new token
        a = get_agent()
        if a.salla:
            a.salla.headers["Authorization"] = f"Bearer {tokens['access_token']}"
        return HTMLResponse("""
        <html><body style='font-family:Arial;text-align:center;padding:60px;direction:rtl'>
          <h2 style='color:#16a34a'>✅ تم ربط المتجر بنجاح!</h2>
          <p>يمكنك إغلاق هذه الصفحة والعودة لاستخدام الشات بوت.</p>
        </body></html>
        """)
    except Exception as e:
        return HTMLResponse(
            f"<h2 style='color:red;font-family:Arial'>خطأ: {str(e)}</h2>",
            status_code=500,
        )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="الرسالة فارغة")

    session_id = req.session_id or str(uuid.uuid4())
    try:
        reply = await get_agent().chat(message=req.message, session_id=session_id)
    except Exception as e:
        # Return full error detail for debugging
        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {str(e)}"
        )
    return ChatResponse(reply=reply, session_id=session_id)


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(default=""),
):
    # Validate extension
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"نوع الملف غير مدعوم. الأنواع المسموحة: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Validate size
    contents = await file.read()
    if len(contents) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"حجم الملف يتجاوز الحد المسموح ({MAX_FILE_MB} MB)",
        )

    # Save file with unique name
    file_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{file_id}{suffix}"
    async with aiofiles.open(save_path, "wb") as f:
        await f.write(contents)

    # Notify agent about the file
    if session_id:
        notification = (
            f"[العميل أرسل ملف تصميم: {file.filename} — "
            f"تم حفظه بنجاح، سيتم مراجعته من فريق التصميم]"
        )
        await get_agent().chat(message=notification, session_id=session_id)

    return {
        "message": "تم رفع الملف بنجاح! سيتم مراجعته من فريق التصميم وسنتواصل معك قريباً.",
        "file_id": file_id,
        "filename": file.filename,
    }
