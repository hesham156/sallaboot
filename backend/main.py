import os
import uuid
import aiofiles
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from agent import PrintingAgent
from salla_oauth import get_auth_url, exchange_code, save_tokens

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
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
@app.get("/health")
async def health():
    has_token = bool(os.getenv("SALLA_ACCESS_TOKEN"))
    return {"status": "ok", "service": "salla-printing-chatbot", "salla_connected": has_token}


# ── Salla Webhook (Easy Mode) ──────────────────────────────────────────────────
@app.post("/webhook/salla")
async def salla_webhook(payload: dict):
    """
    Receives Salla webhook events.
    On app.store.authorize: saves the access_token and refresh_token.
    """
    event = payload.get("event", "")

    if event == "app.store.authorize":
        data = payload.get("data", {})
        access_token = data.get("access_token", "")
        refresh_token = data.get("refresh_token", "")

        if access_token:
            save_tokens(access_token, refresh_token)
            # Update running agent's Salla client if initialized
            try:
                a = get_agent()
                if a.salla:
                    a.salla.headers["Authorization"] = f"Bearer {access_token}"
            except Exception:
                pass
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
    reply = await get_agent().chat(message=req.message, session_id=session_id)
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
