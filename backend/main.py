import os
import uuid
import asyncio
import aiofiles
import collections
import datetime as _dt
from pathlib import Path
from urllib.parse import quote
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
import time as _time
import collections as _collections
import store_manager as sm
import auth as _auth
import database as db
from store_sync import sync_store
from salla_oauth import get_auth_url, exchange_code, save_tokens
import conversation_store as cs
import pricing_calculator as pc
import store_brain as brain
import smart_router

# ── Rate limiter for login endpoints (DB-backed, survives restarts) ──────────

async def _is_rate_limited(attempt_key: str, max_attempts: int = 5, window: int = 300) -> bool:
    """
    Return True if `attempt_key` has exceeded `max_attempts` login attempts in
    the last `window` seconds. Persists to PostgreSQL so a server restart
    doesn't reset an attacker's counter.

    Records the new attempt as a side effect — call once per login try.
    """
    if db.available():
        count = await db.count_recent_login_attempts(attempt_key, window)
        if count >= max_attempts:
            return True
        await db.record_login_attempt(attempt_key)
        return False

    # DB unavailable fallback — fail open (allow), since rejecting all logins
    # when the DB is down would brick the admin panel.
    return False

# Store IDs that are reserved and must never be used as real Salla merchant IDs
_RESERVED_IDS = {"super", "admin", "stores", "auth", "default"}

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
    # 1. Connect to PostgreSQL (no-op if DATABASE_URL not set)
    await db.init()

    # 2. Load stores: JSON files first (fallback), then DB overwrites
    sm.load_all_stores()
    await sm.load_from_db()

    # 3. Restore recent conversations from DB
    await cs.load_conversations_from_db()

    # 4. Restore global app-level settings (e.g. bot_globally_enabled)
    await cs.load_globals_from_db()

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

    # Start background proactive token refresh (checks every hour)
    asyncio.create_task(_token_refresh_loop())
    print("[startup] 🔄 Token auto-refresh loop started")

    # Start periodic flush loop (safety net: saves dirty sessions every 5 min)
    asyncio.create_task(_periodic_flush_loop())
    print("[startup] 💾 Periodic conversation flush loop started (every 5 min)")

    # Start periodic cleanup loop (prunes old webhook_seen / login_attempts / webhook_log)
    asyncio.create_task(_periodic_cleanup_loop())
    print("[startup] 🧹 Periodic DB cleanup loop started (every 6 hours)")

    # ── Critical warning if DB is not connected ────────────────────────────────
    db_st = db.get_status()
    if not db_st["connected"]:
        if not db_st["database_url"]:
            print("=" * 60)
            print("⛔  WARNING: DATABASE_URL is NOT set!")
            print("    Store data (tokens, AI config, passwords) will be")
            print("    DELETED on every Railway deploy / restart.")
            print("    Fix: Add a PostgreSQL service in Railway and link it.")
            print("=" * 60)
        else:
            print("=" * 60)
            print("⛔  WARNING: DATABASE_URL is set but connection FAILED!")
            print("    Store data will NOT be persisted between deploys.")
            print("=" * 60)
    else:
        print(f"[startup] 💾 DB connected — {len(sm.list_stores())} stores persisted")


@app.on_event("shutdown")
async def shutdown_event():
    """
    Flush ALL in-memory conversation state to PostgreSQL before the server stops.
    Railway sends SIGTERM and waits ~10 s for graceful shutdown — this makes
    sure no cart items, customer info, or messages are lost on every deploy.
    """
    if not db.available():
        return
    print("[shutdown] 💾 Flushing all conversations to DB …")
    saved = await cs.flush_all()
    print(f"[shutdown] ✅ Flushed {saved} conversation(s) to PostgreSQL")


async def _periodic_flush_loop():
    """
    Background safety-net: persist any sessions marked dirty every 5 minutes.
    This catches state that was mutated but not yet explicitly flushed —
    e.g. if a tool call crashed between the mutation and the explicit flush().
    """
    await asyncio.sleep(60)   # let startup finish first
    while True:
        try:
            saved = await cs.flush_dirty()
            if saved:
                print(f"[periodic_flush] 💾 Flushed {saved} dirty session(s)")
        except Exception as exc:
            print(f"[periodic_flush] ❌ Error: {exc}")
        await asyncio.sleep(300)  # every 5 minutes


async def _periodic_cleanup_loop():
    """
    Background DB hygiene — runs every 6 hours:
      • webhook_seen: drop dedup keys older than 24h (Salla retries cap at 15 min)
      • login_attempts: drop attempts older than 24h (rate-limit window is 5 min)
      • webhook_log: drop log rows older than 30 days
    Without this the small tables grow forever and slow down queries.
    """
    await asyncio.sleep(300)   # wait 5 min after startup
    while True:
        try:
            seen   = await db.prune_webhook_seen(keep_last_hours=24)
            logins = await db.prune_login_attempts(keep_last_hours=24)
            wlog   = await db.prune_webhook_log(keep_last_days=30)
            if seen or logins or wlog:
                print(
                    f"[periodic_cleanup] 🧹 Pruned: webhook_seen={seen}, "
                    f"login_attempts={logins}, webhook_log={wlog}"
                )
        except Exception as exc:
            print(f"[periodic_cleanup] ❌ Error: {exc}")
        await asyncio.sleep(6 * 3600)  # every 6 hours


async def _sync_task(store_id: str, token: str):
    try:
        await sync_store(token, store_id)
        print(f"✅ Store sync completed for {store_id!r}")
    except Exception as e:
        print(f"⚠️ Store sync failed for {store_id!r}: {e}")


# ── Proactive token refresh ────────────────────────────────────────────────────

async def _check_expiring_tokens():
    """
    Proactively refresh any store token that expires within 2 days.
    Called by _token_refresh_loop() every hour and can also be triggered manually.
    """
    from salla_oauth import refresh_access_token

    now       = _dt.datetime.utcnow()
    threshold = now + _dt.timedelta(days=2)
    refreshed = 0

    for store in sm.list_stores():
        sid            = store["store_id"]
        expires_at_str = sm.get_token_expires_at(sid)
        if not expires_at_str:
            continue  # no expiry data yet — rely on reactive 401 refresh
        try:
            expires_at = _dt.datetime.fromisoformat(expires_at_str)
        except Exception:
            continue
        if expires_at <= threshold:
            days_left = max(0, (expires_at - now).days)
            print(f"[token_refresh] 🔄 Store {sid!r} expires in {days_left}d — proactive refresh …")
            try:
                await refresh_access_token(sid)
                print(f"[token_refresh] ✅ Proactive refresh OK for {sid!r}")
                refreshed += 1
            except Exception as exc:
                print(f"[token_refresh] ❌ Proactive refresh FAILED for {sid!r}: {exc}")

    if refreshed:
        print(f"[token_refresh] {refreshed} store(s) refreshed proactively")


async def _token_refresh_loop():
    """
    Background task: check for expiring tokens every hour.
    Waits 2 minutes after startup to let the app fully initialise first.
    """
    await asyncio.sleep(120)          # let startup settle
    while True:
        try:
            await _check_expiring_tokens()
        except Exception as exc:
            print(f"[token_refresh] Unexpected loop error: {exc}")
        await asyncio.sleep(3_600)    # re-check every hour


# CORS middleware is registered LAST (below admin_auth_middleware) so it ends
# up as the OUTERMOST layer — this guarantees that even error responses (500,
# 502, auth rejections) include Access-Control-Allow-Origin so the browser
# doesn't show a misleading "blocked by CORS" instead of the real error.
# See the CORS block further down in this file.

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

_ADMIN_HTML     = Path(__file__).parent / "admin.html"
_ADMIN_DIST_DIR = Path(__file__).parent / "admin-dist"
_ADMIN_DIST_IDX = _ADMIN_DIST_DIR / "index.html"

# Mount React static assets (JS/CSS bundles) — only if the dist folder exists.
# The dist folder is produced by `npm run build` in the frontend/ directory.
if _ADMIN_DIST_DIR.exists():
    from fastapi.staticfiles import StaticFiles as _StaticFiles
    # Mount /assets separately so API routes under /admin/* still take priority.
    _assets_dir = _ADMIN_DIST_DIR / "assets"
    if _assets_dir.exists():
        app.mount("/assets", _StaticFiles(directory=str(_assets_dir)), name="admin-assets")


def _serve_react_or_legacy() -> HTMLResponse:
    """Serve the new React app if built; fall back to legacy admin.html."""
    if _ADMIN_DIST_IDX.exists():
        return HTMLResponse(_ADMIN_DIST_IDX.read_text(encoding="utf-8"))
    return HTMLResponse(_ADMIN_HTML.read_text(encoding="utf-8"))


# ── Auth middleware ────────────────────────────────────────────────────────────
# Protects all per-store admin API routes (not the HTML pages or auth endpoints).
_PROTECTED_RE = _re.compile(
    r"^/admin/(?!stores$|auth/)([^/]+)/(conversations|bot|sync|products|debug|settings|webhooks|abandoned-carts|analytics|orders|info)"
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

    response = await call_next(request)

    # ── Security hardening headers (defense-in-depth) ─────────────────────────
    # nosniff + a sane referrer policy are safe everywhere. Clickjacking
    # protection is applied only to the admin dashboard pages — never the
    # script-injected widget or the /chat API, so embedding still works.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if path == "/admin" or path.startswith("/admin/"):
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


# CORS registered AFTER admin_auth_middleware so it becomes the outermost
# layer of the middleware chain (Starlette wraps in reverse order). Putting
# CORS outermost means every response — including 401s from auth and 500s
# from route handlers — carries the right Access-Control-Allow-* headers,
# so the browser shows the actual status code instead of a misleading
# "blocked by CORS" message.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)


# ── Models ─────────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    store_id: Optional[str] = "default"
    # Salla storefront SDK passes the logged-in customer's ID here. When
    # present, the backend looks up the customer's profile from Salla
    # (name, phone, email, city, gender) and links any future conversation
    # to it — so the same customer's chat history follows them across
    # devices and re-opens.
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None   # widget hint when SDK has it


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
    email: Optional[str] = ""


class AIConfigRequest(BaseModel):
    groq_api_key:      Optional[str] = ""
    anthropic_api_key: Optional[str] = ""
    openai_api_key:    Optional[str] = ""  # sk-proj-...
    ai_model:          Optional[str] = ""  # e.g. "gpt-4o", "llama-3.3-70b-versatile", "claude-sonnet-4-6"
    bot_name:          Optional[str] = ""
    store_type:        Optional[str] = None  # "printing" | "general" — gates printing features


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password:     str


class RateRequest(BaseModel):
    session_id: str
    store_id:   str = "default"
    rating:     int          # 1 – 5
    comment:    str = ""


# ── Utility endpoints ──────────────────────────────────────────────────────────
@app.get("/env-check")
async def env_check(request: Request):
    """
    Health / diagnostics endpoint.
    Basic info is public (needed to debug widget issues).
    Security-sensitive flags (default password, ADMIN_SECRET stability) are
    ONLY returned to authenticated super-admins to avoid leaking the security
    posture to unauthenticated callers.
    """
    stores    = sm.list_stores()
    db_status = db.get_status()
    store_agents = []
    for s in stores:
        sid = s["store_id"]
        a   = sm.get_agent(sid)
        store_agents.append({
            "store_id":   sid,
            "store_name": s.get("store_name", ""),
            "agent_ok":   a is not None,
            "has_ai_cfg": s.get("has_ai_config", False),
        })

    if not db_status["connected"]:
        if not db_status["database_url"]:
            print("[startup] ⚠️  DATABASE_URL not set — store data will be LOST on every deploy!")
        else:
            print("[startup] ⚠️  DATABASE_URL is set but DB connection failed — check Railway logs")

    result: dict = {
        "GROQ_API_KEY":           bool(os.getenv("GROQ_API_KEY")),
        "ANTHROPIC_API_KEY":      bool(os.getenv("ANTHROPIC_API_KEY")),
        "SALLA_ACCESS_TOKEN":     bool(os.getenv("SALLA_ACCESS_TOKEN")),
        "SALLA_WEBHOOK_SECRET":   bool(os.getenv("SALLA_WEBHOOK_SECRET")),
        "DATABASE_URL":           db_status["database_url"],
        "DB_CONNECTED":           db_status["connected"],
        "BASE_URL":               os.getenv("BASE_URL", "not set"),
        "stores_registered":      len(stores),
        "stores":                 store_agents,
    }

    # Security-sensitive diagnostics — only visible to authenticated super-admins
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if claims and claims.get("su"):
        super_pass = os.getenv("SUPER_ADMIN_PASSWORD", "admin")
        result["ADMIN_SECRET_STABLE"]             = _auth.ADMIN_SECRET_STABLE
        result["SUPER_ADMIN_PASSWORD_IS_DEFAULT"] = (super_pass == "admin")

    return result


@app.post("/admin/force-db-sync")
async def force_db_sync(request: Request):
    """
    Super-admin: force-save every in-memory store to PostgreSQL.
    Use this to migrate data after connecting a new DB, or to recover
    from a situation where DB wasn't connected during registration.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(403, "مصرح للمدير العام فقط")

    if not db.available():
        raise HTTPException(503, "قاعدة البيانات غير متصلة. تأكد من إعداد DATABASE_URL في Railway.")

    # Build the list of all stores with their full token dicts
    stores_data = []
    for s in sm.list_stores():
        sid    = s["store_id"]
        tokens = sm.get_store_info(sid)
        if tokens:
            stores_data.append({"store_id": sid, "tokens": tokens})

    saved = await db.force_save_all_stores(stores_data)
    print(f"[admin] force-db-sync: saved {saved}/{len(stores_data)} stores to DB")
    return {
        "status":  "ok",
        "saved":   saved,
        "total":   len(stores_data),
        "message": f"تم حفظ {saved} متجر في قاعدة البيانات بنجاح ✅",
    }


@app.get("/widget.js")
async def serve_widget():
    widget_path = Path(__file__).parent / "widget.js"
    return FileResponse(widget_path, media_type="application/javascript")


@app.get("/snippet")
async def snippet_guide():
    """
    Public page — shows the exact Salla Snippets code the app developer needs
    to paste in the Partners Portal (App → Snippets → New Snippet).

    Uses {{ merchant.id }} so Salla resolves the correct store ID automatically
    for every merchant that installs the app.
    """
    base = os.getenv("BASE_URL", "http://localhost:8000")
    snippet_code = (
        f"<!-- Salla Chat Bot — paste this in Partners Portal → App → Snippets -->\n"
        f"<script>\n"
        f"window.SallaChatConfig = {{\n"
        f'  storeId:      "{{{{ merchant.id }}}}",\n'
        f'  storeName:    "{{{{ store.name }}}}",\n'
        f'  primaryColor: "#1a56db",\n'
        f'  position:     "left"\n'
        f"}};\n"
        f"</script>\n"
        f'<script src="{base}/widget.js" defer></script>'
    )
    html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Salla Snippets — كود التضمين التلقائي</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;800&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Tajawal',sans-serif;background:#f1f5f9;color:#1e293b;padding:32px;direction:rtl}}
  .card{{background:#fff;border-radius:16px;padding:28px 32px;max-width:820px;margin:0 auto;box-shadow:0 2px 16px rgba(0,0,0,.08)}}
  h1{{font-size:22px;font-weight:800;margin-bottom:6px}}
  .sub{{color:#64748b;font-size:14px;margin-bottom:24px}}
  .steps{{counter-reset:step;display:flex;flex-direction:column;gap:12px;margin-bottom:24px}}
  .step{{display:flex;gap:12px;align-items:flex-start;font-size:14px;line-height:1.6}}
  .step::before{{counter-increment:step;content:counter(step);min-width:26px;height:26px;border-radius:50%;background:#3b82f6;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;flex-shrink:0;margin-top:1px}}
  code{{background:#f1f5f9;padding:2px 7px;border-radius:4px;font-size:13px;font-family:monospace}}
  .code-box{{background:#0f172a;color:#e2e8f0;border-radius:10px;padding:20px;font-family:monospace;font-size:13px;line-height:1.7;white-space:pre;overflow-x:auto;position:relative;margin-bottom:16px}}
  .copy-btn{{background:#3b82f6;color:#fff;border:none;border-radius:8px;padding:9px 20px;font-family:'Tajawal',sans-serif;font-size:14px;font-weight:700;cursor:pointer;transition:.15s}}
  .copy-btn:hover{{background:#2563eb}}
  .alert{{background:#f0fdf4;border:1px solid #bbf7d0;color:#14532d;border-radius:8px;padding:12px 16px;font-size:13px;line-height:1.6}}
  a{{color:#3b82f6}}
</style>
</head>
<body>
<div class="card">
  <h1>🧩 Salla Snippets — تضمين تلقائي للبوت</h1>
  <p class="sub">هذا الكود يُضاف مرة واحدة في Partners Portal وسلة تحقنه تلقائياً في كل متجر يثبّت تطبيقك</p>

  <div class="steps">
    <div class="step">افتح <a href="https://salla.partners" target="_blank">salla.partners</a> ← تطبيقاتي ← تطبيقك ← Snippets</div>
    <div class="step">اضغط <strong>إنشاء Snippet جديد</strong></div>
    <div class="step">اختر الموضع: <code>Body End</code> (قبل نهاية &lt;body&gt;)</div>
    <div class="step">الصق الكود التالي كاملاً ثم احفظ</div>
    <div class="step">عند تثبيت أي متجر للتطبيق، البوت يظهر تلقائياً بدون أي إعداد إضافي ✅</div>
  </div>

  <div class="code-box" id="snippet-code">{snippet_code}</div>
  <button class="copy-btn" onclick="copySnippet()">📋 نسخ الكود</button>

  <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0">
  <div class="alert">
    💡 <strong>ملاحظة:</strong> <code>{{{{ merchant.id }}}}</code> و <code>{{{{ store.name }}}}</code>
    يُستبدلان تلقائياً بسلة بمعرّف وباسم المتجر الحقيقي — لا تغيّر هذه القيم يدوياً.
    <br>يمكنك تغيير <code>primaryColor</code> و <code>position</code> حسب تصميم تطبيقك.
  </div>
</div>

<script>
function copySnippet() {{
  var code = document.getElementById('snippet-code').textContent;
  navigator.clipboard.writeText(code).then(function() {{
    var btn = document.querySelector('.copy-btn');
    btn.textContent = '✅ تم النسخ!';
    setTimeout(function(){{ btn.textContent = '📋 نسخ الكود'; }}, 2000);
  }});
}}
</script>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/test-widget/{store_id}", response_class=HTMLResponse)
async def test_widget_page(store_id: str):
    """
    Quick test page — embeds the widget with the *real* store_id so developers
    can test the bot without going through Salla Snippets.
    Linked from the admin dashboard 'Test Bot' button.
    """
    base  = os.getenv("BASE_URL", "http://localhost:8000")
    info  = sm.get_store_info(store_id)
    name  = info.get("store_name", f"متجر {store_id}")
    return HTMLResponse(f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>اختبار بوت — {name}</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Tajawal',sans-serif;background:#f1f5f9;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:24px}}
  .card{{background:#fff;border-radius:16px;padding:28px 32px;max-width:480px;width:100%;box-shadow:0 4px 24px rgba(0,0,0,.10);text-align:center}}
  h1{{font-size:20px;font-weight:800;margin-bottom:8px;color:#1e293b}}
  .sub{{color:#64748b;font-size:14px;margin-bottom:24px}}
  .info{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px 16px;font-size:13px;color:#475569;text-align:right;margin-bottom:16px}}
  .info b{{color:#1e293b}}
  .hint{{font-size:12px;color:#94a3b8;margin-top:16px}}
</style>
</head>
<body>
<div class="card">
  <h1>🧪 وضع الاختبار</h1>
  <p class="sub">البوت يعمل بـ store_id الحقيقي — اضغط أيقونة الدردشة أسفل الشاشة</p>
  <div class="info">
    <div><b>المتجر:</b> {name}</div>
    <div><b>Store ID:</b> {store_id}</div>
  </div>
  <p class="hint">💡 هذه الصفحة للاختبار فقط — لا تشاركها مع العملاء</p>
</div>
<script>
window.SallaChatConfig = {{
  storeId:      "{store_id}",
  storeName:    "{name}",
  primaryColor: "#1a56db",
  position:     "left",
  apiUrl:       "{base}",
}};
</script>
<script src="{base}/widget.js" defer></script>
</body>
</html>""")


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


# ── Admin HTML (React app or legacy fallback) ──────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root_index():
    return _serve_react_or_legacy()

@app.get("/landing", response_class=HTMLResponse)
async def landing_page():
    return _serve_react_or_legacy()

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return _serve_react_or_legacy()

@app.get("/admin", response_class=HTMLResponse)
async def admin_index():
    return _serve_react_or_legacy()

@app.get("/store/{store_id}", response_class=HTMLResponse)
async def store_spa(store_id: str):
    return _serve_react_or_legacy()

@app.get("/store/{store_id}/{rest:path}", response_class=HTMLResponse)
async def store_spa_sub(store_id: str, rest: str):
    return _serve_react_or_legacy()


@app.get("/admin/stores")
async def admin_list_stores():
    """Return JSON list of all registered stores."""
    return {"stores": sm.list_stores()}


# NOTE: /admin/{store_id} must come AFTER /admin/stores so FastAPI matches
# the literal 'stores' path first.
@app.get("/admin/{store_id}", response_class=HTMLResponse)
async def admin_store_page(store_id: str):
    """Per-store admin dashboard — serves the React SPA (hash-router handles sub-routes)."""
    return _serve_react_or_legacy()


# ── Auth: Admin login (email + password) ────────────────────────────────────────
@app.post("/admin/auth/login")
async def super_login(req: LoginRequest, request: Request):
    ip          = request.client.host if request.client else "unknown"
    super_email = os.getenv("SUPER_ADMIN_EMAIL", "h456ad@gmail.com").strip().lower()
    super_pass  = os.getenv("SUPER_ADMIN_PASSWORD", "admin")

    # Warn once in logs if default password is still in use
    if super_pass == "admin":
        print("⚠️  [auth] SUPER_ADMIN_PASSWORD is still the default 'admin' — please change it!")

    if await _is_rate_limited(f"super:{ip}"):
        raise HTTPException(429, "محاولات تسجيل دخول كثيرة جداً. انتظر 5 دقائق وحاول مجدداً.")

    email_in = (req.email or "").strip().lower()
    # Constant-time comparison for both fields to avoid timing leaks.
    email_ok = hmac.compare_digest(email_in, super_email)
    pass_ok  = bool(req.password) and hmac.compare_digest(req.password, super_pass)
    if not (email_ok and pass_ok):
        print(f"[auth] ❌ Failed admin login attempt from {ip} (email={email_in!r})")
        raise HTTPException(401, "البريد الإلكتروني أو كلمة المرور غير صحيحة")

    print(f"[auth] ✅ Admin login ({email_in}) from {ip}")
    token = _auth.create_token("super", is_super=True)
    return {"token": token, "store_id": "super", "is_super": True}


# ── Auth: Per-store login ──────────────────────────────────────────────────────
@app.post("/admin/{store_id}/auth/login")
async def store_login(store_id: str, req: LoginRequest, request: Request):
    ip = request.client.host if request.client else "unknown"

    if await _is_rate_limited(f"{store_id}:{ip}"):
        raise HTTPException(429, "محاولات تسجيل دخول كثيرة جداً. انتظر 5 دقائق وحاول مجدداً.")

    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    stored_hash = sm.get_admin_password_hash(store_id)
    if not stored_hash or not _auth.check_password(req.password, stored_hash):
        print(f"[auth] ❌ Failed login for store {store_id!r} from {ip}")
        raise HTTPException(401, "كلمة المرور غير صحيحة")

    print(f"[auth] ✅ Store login: {store_id!r} from {ip}")
    token = _auth.create_token(store_id)
    info  = sm.get_store_info(store_id)
    return {
        "token":      token,
        "store_id":   store_id,
        "store_name": info.get("store_name", f"متجر {store_id}"),
    }


# ── Auth: Token verify (lightweight — for client-side checkAuth) ──────────────
@app.get("/admin/{store_id}/auth/verify")
async def verify_store_token(store_id: str, request: Request):
    """
    Lightweight endpoint the admin SPA calls on page load to check whether
    its stored token is still valid without triggering a heavy data load.
    Returns 200 {ok: true} or 401.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims:
        raise HTTPException(401, "توكن منتهي أو غير صحيح")
    if not claims.get("su") and claims.get("s") != store_id:
        raise HTTPException(403, "غير مصرح")
    return {"ok": True, "store_id": store_id, "is_super": claims.get("su", False)}


# ── Store info (for store owner — no super token needed) ─────────────────────
@app.get("/admin/{store_id}/info")
async def get_store_info_endpoint(store_id: str):
    """Basic store metadata accessible with a store-level token."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    stores = sm.list_stores()
    found = next((s for s in stores if s["store_id"] == store_id), None)
    if not found:
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    return found


# ── Settings: AI config ────────────────────────────────────────────────────────
@app.get("/admin/{store_id}/settings/ai")
async def get_ai_settings(store_id: str):
    cfg = sm.get_ai_config(store_id)
    # Mask the keys — return only whether they exist, not the actual values
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
    # Resolve store type: explicit setting, else heuristic (configured pricing
    # ⇒ printing). Mirrors agent._is_printing_store so UI matches bot behaviour.
    store_type = (cfg.get("store_type") or "").strip().lower()
    if not store_type:
        store_type = "printing" if cfg.get("pricing_config") else "general"

    return {
        "groq_api_key":      "••••" if groq_set      else "",
        "anthropic_api_key": "••••" if anthropic_set else "",
        "openai_api_key":    "••••" if openai_set    else "",
        "ai_model":          cfg.get("ai_model",  ""),
        "bot_name":          cfg.get("bot_name",  ""),
        "provider":          provider,
        "store_type":        store_type,
    }


@app.put("/admin/{store_id}/settings/ai")
async def update_ai_settings(store_id: str, req: AIConfigRequest):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    existing = sm.get_ai_config(store_id)

    # Clear other providers' keys when a specific provider is chosen
    # (frontend sends "" for providers that are not selected)
    groq_key      = (req.groq_api_key      or "").strip()
    anthropic_key = (req.anthropic_api_key or "").strip()
    openai_key    = (req.openai_api_key    or "").strip()

    # Start from a copy of the existing config so OTHER keys (pricing_config,
    # store_type, …) are preserved — they used to be silently wiped here.
    config = dict(existing)
    config.update({
        # Keep existing key when frontend sends empty string (masked value)
        "groq_api_key":      groq_key      or existing.get("groq_api_key",      ""),
        "anthropic_api_key": anthropic_key or existing.get("anthropic_api_key", ""),
        "openai_api_key":    openai_key    or existing.get("openai_api_key",    ""),
        "ai_model":          (req.ai_model  or "").strip() or existing.get("ai_model",  ""),
        "bot_name":          (req.bot_name  or "").strip() or existing.get("bot_name",  ""),
    })

    # Store type — only overwrite when the frontend sends a valid value.
    if req.store_type is not None:
        st = req.store_type.strip().lower()
        if st in ("printing", "general"):
            config["store_type"] = st

    # When a specific provider key is explicitly set, clear the other two
    # so only one provider is active at a time
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

    # Await DB writes directly (instead of fire-and-forget) to guarantee
    # settings survive server restarts. save_store saves ai_config inside the
    # tokens JSONB column; save_ai_config also persists it in the separate column.
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, config)

    return {"status": "ok", "message": "تم حفظ إعدادات الذكاء الاصطناعي ✅"}


# ── Settings: AI Brain (custom knowledge + memory preview) ───────────────────

class CustomKnowledgeRequest(BaseModel):
    custom_knowledge: str = ""


@app.get("/admin/{store_id}/settings/brain")
async def get_ai_brain(store_id: str):
    """
    Return what the AI 'knows' about this store: overview stats, the
    admin's custom knowledge text, and a preview of the full knowledge
    block injected into the system prompt.
    """
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    return brain.preview_knowledge(store_id)


@app.put("/admin/{store_id}/settings/brain")
async def update_ai_brain(store_id: str, req: CustomKnowledgeRequest):
    """
    Save the admin's custom-knowledge text. The next chat turn will see
    it in the system prompt (no agent restart needed since get_system_prompt
    is called fresh each turn).
    """
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    brain.set_custom_knowledge(store_id, req.custom_knowledge)
    # Persist to DB so it survives deploys
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, sm.get_ai_config(store_id))
    return {"status": "ok", "message": "تم حفظ ذاكرة المتجر ✅"}


@app.post("/admin/{store_id}/settings/brain/retrain")
async def retrain_ai_brain(store_id: str):
    """
    Force a fresh re-sync of the store's products from Salla so the AI
    'memory' reflects the latest catalog. Returns the resulting overview.
    """
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    token = sm.get_access_token(store_id)
    if not token:
        raise HTTPException(400, "لا يوجد access token — لا يمكن المزامنة")
    try:
        data = await sync_store(token, store_id)
        # Reset the agent so the new catalog is picked up next chat
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


# ── Bot training (admin teaches the AI: instructions, FAQs, files) ──────────

class TrainingTextRequest(BaseModel):
    kind:    str       # 'instruction' | 'faq'
    title:   str       # short label / question
    content: str       # body / answer
    enabled: bool = True


@app.get("/admin/{store_id}/settings/training")
async def list_bot_training(store_id: str):
    """List all training entries the admin has added for this store."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    items = await db.list_training(store_id)
    return {"count": len(items), "items": items}


@app.post("/admin/{store_id}/settings/training/text")
async def add_text_training(store_id: str, req: TrainingTextRequest):
    """Add a text training entry (instruction or FAQ)."""
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
    smart_router.invalidate_faq_cache(store_id)   # pick up new FAQ immediately
    return {"status": "ok", "id": new_id, "message": "تمت إضافة التدريب ✅"}


@app.post("/admin/{store_id}/settings/training/file")
async def upload_training_file(
    store_id: str,
    file:  UploadFile = File(...),
    title: str        = Form(default=""),
):
    """
    Upload a reference file (PDF / TXT / MD / CSV). The text is extracted
    and stored alongside the binary so the AI can read it without parsing
    PDF on every request.
    """
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    filename = file.filename or "training.bin"
    suffix   = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".txt", ".md", ".csv", ".log"):
        raise HTTPException(
            400,
            "نوع الملف غير مدعوم. الأنواع المتاحة: PDF, TXT, MD, CSV"
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"حجم الملف يتجاوز الحد ({MAX_FILE_MB} MB)")

    # Save raw file in the persistent uploads table so the admin can re-download
    file_id      = str(uuid.uuid4())
    content_type = _CONTENT_TYPES.get(suffix, "application/octet-stream")
    db_saved = False
    if db.available():
        db_saved = await db.save_upload(
            file_id=file_id, filename=filename, content_type=content_type,
            data=contents, store_id=store_id, session_id="",
        )

    # Extract text — non-fatal if it fails
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


@app.patch("/admin/{store_id}/settings/training/{training_id}")
async def toggle_training(store_id: str, training_id: int, payload: dict):
    """Enable/disable a single training entry without deleting it."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    ok = await db.update_training_enabled(training_id, bool(payload.get("enabled", True)))
    if not ok:
        raise HTTPException(500, "تعذّر التحديث")
    sm.reset_agent(store_id)
    smart_router.invalidate_faq_cache(store_id)
    return {"status": "ok"}


@app.delete("/admin/{store_id}/settings/training/{training_id}")
async def delete_training_entry(store_id: str, training_id: int):
    """Delete a training entry (and its underlying upload, if any)."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    ok, deleted_file_id = await db.delete_training(training_id)
    if not ok:
        raise HTTPException(500, "تعذّر الحذف")
    sm.reset_agent(store_id)
    smart_router.invalidate_faq_cache(store_id)
    return {"status": "ok", "deleted_file_id": deleted_file_id}


# ── Settings: Pricing config (for the printing calculator) ───────────────────

@app.get("/admin/{store_id}/settings/pricing")
async def get_pricing_settings(store_id: str):
    """
    Return the store's pricing config merged with defaults so the UI always
    sees every field. The frontend can rely on every key being present.
    """
    cfg = sm.get_ai_config(store_id) or {}
    pricing = cfg.get("pricing_config") or {}
    merged = {**pc.DEFAULT_PRICING_CONFIG, **{k: v for k, v in pricing.items() if v is not None}}
    return merged


@app.put("/admin/{store_id}/settings/pricing")
async def update_pricing_settings(store_id: str, pricing: dict):
    """
    Save the printing-calculator config for a store. Stored inside the
    existing ai_config blob so it travels alongside the AI provider/model
    settings and survives deploys via the same DB pipeline.
    """
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    existing = sm.get_ai_config(store_id) or {}
    existing["pricing_config"] = pricing or {}
    sm.set_ai_config(store_id, existing)

    # Await the DB write so the change survives a restart immediately
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, existing)

    return {"status": "ok", "message": "تم حفظ إعدادات حاسبة الأسعار ✅"}


@app.post("/admin/{store_id}/settings/pricing/test")
async def test_pricing_calculation(store_id: str, payload: dict):
    """
    Run the calculator against the store's saved config with the given
    inputs — used by the admin UI's "Test Calculator" preview so the
    admin can verify settings before exposing them to customers via the bot.
    """
    cfg = sm.get_ai_config(store_id) or {}
    pricing_cfg = cfg.get("pricing_config") or {}

    printing_type = payload.get("printing_type", "digital")
    width    = float(payload.get("width", 0))
    height   = float(payload.get("height", 0))
    quantity = int(payload.get("quantity", 0))

    result = pc.calculate_quote(
        printing_type = printing_type,
        config        = pricing_cfg,
        width         = width,
        height        = height,
        quantity      = quantity,
        roll_width    = payload.get("roll_width"),
        paper_type    = payload.get("paper_type"),
        sheet_size    = payload.get("sheet_size"),
        addons        = payload.get("addons") or [],
        foil_width    = float(payload.get("foil_width",  0) or 0),
        foil_height   = float(payload.get("foil_height", 0) or 0),
        spot_uv       = bool(payload.get("spot_uv", False)),
        cutting       = payload.get("cutting", "normal"),
        folding       = bool(payload.get("folding", False)),
        punching      = bool(payload.get("punching", False)),
    )
    return result


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
    # Persist immediately to DB so password survives server restarts
    await db.save_store(store_id, sm.get_store_info(store_id))
    return {"status": "ok", "message": "تم تغيير كلمة المرور بنجاح"}


# ── Settings: Token status & manual refresh ───────────────────────────────────

@app.get("/admin/{store_id}/settings/token-status")
async def token_status(store_id: str):
    """Return OAuth token health for the admin settings page."""
    from salla_oauth import get_token_status
    info   = sm.get_store_info(store_id)
    status = get_token_status(store_id)
    return {
        **status,
        "store_name":   info.get("store_name",  ""),
        "connected_at": info.get("connected_at", ""),
        "has_refresh":  bool(sm.get_refresh_token(store_id)),
    }


@app.post("/admin/{store_id}/settings/token-refresh")
async def manual_token_refresh(store_id: str):
    """Manually trigger an OAuth token refresh for a store."""
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
async def store_products(
    store_id: str,
    limit:  int = 500,
    offset: int = 0,
):
    """
    Return cached products for a store.
    ?limit=500&offset=0 for pagination.
    """
    cache    = sm.get_cache(store_id)
    products = cache.get("products", [])
    total    = len(products)
    page     = products[offset : offset + limit] if limit > 0 else products
    return {
        "products":        page,
        "total_products":  total,
        "categories":      cache.get("categories", []),
        "articles":        cache.get("articles", []),
        "products_count":  cache.get("products_count", 0),
        "last_sync":       cache.get("last_sync", "never"),
        "errors":          cache.get("last_sync_errors", []),
    }


# ── Per-store debug ────────────────────────────────────────────────────────────
@app.post("/admin/{store_id}/debug/test-order")
async def debug_test_order(store_id: str, request: Request):
    """
    Super-admin diagnostic: attempt to create a custom product + order
    exactly like the bot's create_quote_order does, and return the FULL
    Salla error if it fails. Use this to pinpoint why quote→order fails
    (almost always a missing products.read_write / orders.read_write scope).

    Cleans up the test product is NOT possible via API delete here, so it
    creates a clearly-labelled test product. Safe to run; just leaves one
    hidden test product behind.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    access = sm.get_access_token(store_id)
    if not access:
        return {"ok": False, "stage": "token", "error": "no access token for store"}

    from salla_client import SallaClient
    client = SallaClient(access, store_id=store_id)
    result: dict = {"ok": False, "store_id": store_id}

    # 1) Create product
    try:
        presp = await client.create_product(
            name="🔧 منتج اختبار (تشخيص) — احذفه",
            price=1.0, product_type="service", unlimited_quantity=True,
            description="منتج تشخيص من لوحة التحكم", status="sale",
        )
        pid = (presp.get("data") or {}).get("id")
        result["product_created"] = bool(pid)
        result["product_id"] = pid
    except Exception as e:
        result["stage"] = "create_product"
        result["error"] = str(e)
        return result

    if not pid:
        result["stage"] = "create_product"
        result["error"] = "no product id returned"
        return result

    # 1b) Attach an image so the product is sellable (not hidden)
    try:
        info = brain.get_store_info(store_id)
        img = (info.get("avatar") or "").strip() or \
              "https://cdn.assets.salla.network/prod/admin/cp/assets/images/placeholder.png"
        await client.attach_product_image_url(pid, img, alt="diagnostic")
        result["image_attached"] = True
    except Exception as e:
        result["image_attached"] = False
        result["image_error"] = str(e)

    # 1c) Create (or find) a test customer so the order uses customer.id —
    #     Salla requires name+mobile+email when ordering with raw fields.
    test_customer = {"name": "عميل اختبار", "phone": "0500000000"}
    try:
        cresp = await client.create_customer(
            first_name="عميل", last_name="اختبار",
            mobile="500000000", mobile_code_country="+966",
        )
        tcid = (cresp.get("data") or {}).get("id")
        if tcid:
            test_customer = {"salla_customer_id": tcid}
            result["test_customer_id"] = tcid
    except Exception as e:
        # Customer may already exist (unique mobile) — try to find them
        try:
            fr = await client.get_customer_by_phone("500000000")
            fl = fr.get("data", [])
            fc = fl[0] if isinstance(fl, list) and fl else {}
            if fc.get("id"):
                test_customer = {"salla_customer_id": fc["id"]}
                result["test_customer_id"] = fc["id"]
            else:
                result["customer_note"] = str(e)
        except Exception as e2:
            result["customer_note"] = f"{e} | {e2}"

    # 2) Create order with that product + customer
    try:
        oresp = await client.create_order(
            [{"product_id": pid, "quantity": 1}],
            test_customer,
            "طلب اختبار تشخيصي",
        )
        order = oresp.get("data") or {}
        result["order_created"] = bool(order.get("id"))
        result["order_id"]      = order.get("id")
        result["payment_url"]   = (order.get("urls") or {}).get("customer", "")
        result["ok"] = bool(order.get("id"))
    except Exception as e:
        result["stage"] = "create_order"
        result["error"] = str(e)
        return result

    result["message"] = "✅ كل الخطوات نجحت — ميزة عرض السعر → طلب تعمل بشكل صحيح"
    return result


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


# ── Analytics ──────────────────────────────────────────────────────────────────

@app.get("/admin/{store_id}/analytics")
async def store_analytics(store_id: str):
    """
    Return aggregated analytics for a store.
    Computed from in-memory conversation_store + store_manager cache.
    """
    import datetime as _dtt

    now_utc = _dtt.datetime.utcnow()

    # ── Conversations ──────────────────────────────────────────────────────────
    all_convs = await cs.get_all_conversations_for_store(store_id)

    total_convs   = len(all_convs)
    today_convs   = 0
    week_convs    = 0
    bot_handled   = 0
    admin_takeover = 0
    total_msgs    = 0
    user_msgs     = 0
    bot_msgs      = 0
    admin_msgs    = 0

    # Daily counts: last 14 days  {date_str: count}
    daily: dict = {}
    for i in range(14):
        d = (now_utc - _dtt.timedelta(days=i)).strftime("%Y-%m-%d")
        daily[d] = 0

    # Hourly distribution: 24-slot list  [count_at_hour_0, ..., count_at_hour_23]
    hourly = [0] * 24

    for conv in all_convs.values():
        created_str = conv.get("created_at", "")
        try:
            created = _dtt.datetime.fromisoformat(created_str)
            delta   = now_utc - created
            if delta.days == 0:
                today_convs += 1
            if delta.days < 7:
                week_convs += 1
            date_key = created.strftime("%Y-%m-%d")
            if date_key in daily:
                daily[date_key] += 1
            hourly[created.hour] += 1
        except Exception:
            pass

        if not conv.get("bot_enabled", True):
            admin_takeover += 1
        else:
            bot_handled += 1

        for m in conv.get("messages", []):
            total_msgs += 1
            role = m.get("role", "")
            if role == "user":
                user_msgs += 1
            elif role == "assistant":
                bot_msgs += 1
            elif role == "admin":
                admin_msgs += 1

    avg_msgs = round(total_msgs / total_convs, 1) if total_convs else 0

    daily_counts = [
        {"date": d, "count": daily[d]}
        for d in sorted(daily.keys())
    ]

    # ── Abandoned carts ────────────────────────────────────────────────────────
    carts_list = list(_abandoned_carts.get(store_id, []))
    if not carts_list and db.available():
        carts_list = await db.load_abandoned_carts(store_id)

    total_carts    = len(carts_list)
    recovered_carts = sum(1 for c in carts_list if c.get("recovered"))
    pending_carts  = total_carts - recovered_carts
    recovery_rate  = round(recovered_carts / total_carts * 100, 1) if total_carts else 0

    # ── Products / store cache ─────────────────────────────────────────────────
    cache = sm.get_cache(store_id)

    # ── Ratings ────────────────────────────────────────────────────────────────
    rated_vals   = [c.get("rating") for c in all_convs.values() if c.get("rating")]
    rated_count  = len(rated_vals)
    avg_rating   = round(sum(rated_vals) / rated_count, 1) if rated_count else 0
    distribution = [sum(1 for r in rated_vals if r == i) for i in range(1, 6)]

    return {
        "conversations": {
            "total":          total_convs,
            "today":          today_convs,
            "this_week":      week_convs,
            "bot_handled":    bot_handled,
            "admin_takeover": admin_takeover,
            "avg_messages":   avg_msgs,
            "daily_counts":   daily_counts,
            "hourly_distribution": hourly,
        },
        "messages": {
            "total":     total_msgs,
            "user":      user_msgs,
            "bot":       bot_msgs,
            "admin":     admin_msgs,
        },
        "abandoned_carts": {
            "total":         total_carts,
            "recovered":     recovered_carts,
            "pending":       pending_carts,
            "recovery_rate": recovery_rate,
        },
        "products": {
            "count":     cache.get("products_count", 0),
            "last_sync": cache.get("last_sync", "never"),
        },
        "ratings": {
            "count":        rated_count,
            "avg":          avg_rating,
            "distribution": distribution,   # [1★,2★,3★,4★,5★]
        },
    }



# ── Conversation insights (advanced analytics) ─────────────────────────────────
@app.get("/admin/{store_id}/analytics/insights")
async def store_insights(store_id: str):
    """
    Deep analysis of conversations for a store.
    Returns: top question topics, non-purchase reasons,
             at-risk customers, sentiment breakdown, conversion rate.
    """
    import conversation_analyzer as ca

    all_convs = await cs.get_all_conversations_for_store(store_id)

    return ca.analyze_insights(all_convs)


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
async def store_conversations(
    store_id: str,
    limit:  int = 100,
    offset: int = 0,
):
    """
    List conversation summaries for a store.
    ?limit=100&offset=0 — paginated, newest-first.
    Response: {total: int, conversations: [...]}
    """
    await cs.get_all_conversations_for_store(store_id)
    return cs.summary_list(store_id, limit=limit, offset=offset)


# ── Super-admin: ALL conversations across every store (debug / orphan hunt) ──
@app.get("/admin/conversations-all")
async def all_conversations_superadmin(
    request: Request,
    limit:   int = 200,
    offset:  int = 0,
):
    """
    Super-admin only: return ALL conversations regardless of store_id.
    Each entry includes its store_id so orphan conversations (tagged with
    'default' or an unregistered store) can be located and re-assigned.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    # summary_list(store_id=None) returns conversations from every store
    base = cs.summary_list(store_id=None, limit=limit, offset=offset)

    # Enrich each summary with the actual store_id stored in the conversation
    all_convs = cs.all_conversations()
    registered_ids = {s["store_id"] for s in sm.list_stores()}
    for s in base.get("conversations", []):
        conv = all_convs.get(s["session_id"], {})
        sid  = conv.get("store_id", "default")
        s["store_id"]   = sid
        s["is_orphan"]  = (sid == "default") or (sid not in registered_ids)
    return base


@app.get("/admin/{store_id}/conversations/{session_id}")
async def store_conversation_detail(store_id: str, session_id: str):
    await cs.restore_to_memory(session_id)
    cs.mark_admin_read(session_id)
    conv = cs.all_conversations().get(session_id)
    if not conv:
        raise HTTPException(404, "المحادثة غير موجودة")
    return conv


@app.post("/admin/{store_id}/conversations/{session_id}/reply")
async def store_admin_reply(store_id: str, session_id: str, req: AdminReplyRequest):
    if not req.message.strip():
        raise HTTPException(400, "الرسالة فارغة")
    await cs.restore_to_memory(session_id)
    text = req.message.strip()
    msg = await cs.add_message(session_id, "admin", text, store_id)
    cs.mark_admin_read(session_id)
    # Learn from this correction in the background: the admin's answer is the
    # right response, captured as a pending lesson for review. Fire-and-forget
    # so it never slows the reply.
    import bot_learning
    asyncio.create_task(bot_learning.capture_admin_correction(store_id, session_id, text))
    return {"status": "sent", "message": msg}


@app.post("/admin/{store_id}/conversations/{session_id}/takeover")
async def store_takeover(store_id: str, session_id: str):
    await cs.restore_to_memory(session_id)
    cs.set_session_bot(session_id, False)
    cs.mark_admin_read(session_id)
    # Persist the bot_enabled change so it survives restart
    await cs.flush(session_id)
    return {"status": "ok", "bot_enabled": False, "session_id": session_id}


@app.post("/admin/{store_id}/conversations/{session_id}/handback")
async def store_handback(store_id: str, session_id: str):
    await cs.restore_to_memory(session_id)
    cs.set_session_bot(session_id, True)
    await cs.add_message(session_id, "admin",
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
    await cs.set_bot_globally(req.enabled)
    return {"bot_globally_enabled": cs.get_bot_globally()}


@app.get("/admin/conversations")
async def admin_conversations_compat(limit: int = 100, offset: int = 0):
    return await store_conversations("default", limit=limit, offset=offset)


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


# ── Webhook infrastructure (all state persisted to PostgreSQL) ───────────────

# Abandoned carts: in-memory hot cache mirroring the abandoned_carts table.
# DB is the source of truth — this exists only to avoid a query per page load.
_abandoned_carts: dict = collections.defaultdict(lambda: collections.deque(maxlen=500))


def _log_event(store_id: str, event: str, status: str, detail: str = "",
                sig_status: str = "", body_head: str = "",
                content_type: str = "", user_agent: str = ""):
    """
    Fire-and-forget webhook log row. Writes to webhook_log table so the
    full audit trail survives every Railway redeploy. Errors are logged
    by the db.fire callback (no silent loss).
    """
    db.fire(db.log_webhook(
        store_id=store_id, event=event, status=status, detail=detail,
        sig_status=sig_status, body_head=body_head,
        content_type=content_type, user_agent=user_agent,
    ))


async def _already_seen(dedup_key: str) -> bool:
    """
    Atomic check-and-set on webhook_seen table. Returns True if this key
    has already been processed (Salla retried). Persisted across restarts
    so a redeploy mid-retry-window doesn't re-process old events.
    """
    return await db.is_webhook_seen(dedup_key)


def _verify_signature(body: bytes, headers) -> tuple:
    """
    Verify X-Salla-Signature using HMAC-SHA256.
    Returns (ok: bool, detail: str).

    Behaviour:
    - No secret configured → accept (dev mode).
    - Secret configured + signature present → verify strictly.
    - Secret configured + signature ABSENT:
        • Default (lenient): accept with warning — some Salla easy-mode events
          legitimately omit the header.
        • Strict mode (WEBHOOK_REQUIRE_SIGNATURE=true env var): reject — use
          this in production once you've confirmed all events carry a signature.
    """
    secret = os.getenv("SALLA_WEBHOOK_SECRET", "")
    if not secret:
        return True, "no_secret_configured"

    sig = headers.get("X-Salla-Signature", "")
    if not sig:
        if os.getenv("WEBHOOK_REQUIRE_SIGNATURE", "false").lower() == "true":
            print("[webhook] ⛔ Missing X-Salla-Signature — rejected (strict mode)")
            return False, "signature_required_but_absent"
        print("[webhook] ⚠️ Missing X-Salla-Signature — accepted with warning (set WEBHOOK_REQUIRE_SIGNATURE=true to harden)")
        return True, "signature_absent_accepted"

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        print(f"[webhook] ⛔ Signature mismatch — rejected (got {sig[:16]}…)")
        return False, f"signature_mismatch got={sig[:16]}"

    return True, "signature_ok"


# ── Per-event async handlers ───────────────────────────────────────────────────

async def _handle_store_authorize(merchant_id: str, data: dict):
    """app.store.authorize — store installs / reinstalls the app."""
    access_token  = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    expires       = data.get("expires", 0)       # unix timestamp (2-week expiry)
    expires_in    = data.get("expires_in", 0)    # seconds alternative
    store_info    = data.get("store", {})

    store_id = merchant_id or "default"
    if not access_token:
        print(f"[webhook] app.store.authorize for {store_id!r} — no token in payload")
        return
    if store_id.lower() in _RESERVED_IDS and store_id != "default":
        print(f"[webhook] ⚠️ Reserved store_id {store_id!r} — ignoring authorize event")
        return

    # Compute expires_at ISO string for proactive refresh scheduling
    expires_at = ""
    try:
        if expires_in:
            expires_at = (_dt.datetime.utcnow() + _dt.timedelta(seconds=int(expires_in))).isoformat()
        elif expires:
            expires_at = _dt.datetime.utcfromtimestamp(int(expires)).isoformat()
    except Exception:
        pass

    merged_info = {**store_info, "expires_at": expires_at} if expires_at else store_info

    sm.register_store(
        store_id=store_id,
        access_token=access_token,
        refresh_token=refresh_token,
        store_info=merged_info,
    )

    # Directly await the DB save for this critical event so data is never
    # lost even if the server restarts seconds after the webhook.
    if db.available():
        tokens = sm.get_store_info(store_id)
        await db.save_store(store_id, tokens)
        print(f"[webhook] 💾 Store {store_id!r} directly saved to DB")

    asyncio.create_task(_sync_task(store_id, access_token))
    _log_event(store_id, "app.store.authorize", "ok",
               f"token …{access_token[-6:]}  expires={expires}")
    print(f"[webhook] ✅ Store {store_id!r} authorized, sync triggered")


async def _handle_app_uninstalled(merchant_id: str, data: dict):
    """
    app.uninstalled — the merchant removed the app. Salla's app review
    REQUIRES that uninstalling deletes the merchant's data. We purge the
    store from the DB and drop it from memory/files so we never use the
    revoked token again.
    """
    store_id = merchant_id or "default"
    if store_id == "default":
        print("[webhook] app.uninstalled for 'default' — skipping purge (env store)")
        return
    try:
        if db.available():
            await db.purge_store(store_id)
        sm.unregister_store(store_id)
        _log_event(store_id, "app.uninstalled", "ok", "store data purged")
        print(f"[webhook] 🗑️ Store {store_id!r} uninstalled — data purged")
    except Exception as e:
        _log_event(store_id, "app.uninstalled", "error", str(e))
        print(f"[webhook] ❌ app.uninstalled purge failed for {store_id!r}: {e}")


async def _handle_app_lifecycle(event: str, merchant_id: str, data: dict):
    """
    Acknowledge the remaining app lifecycle events Salla sends and checks
    for during app review:
      app.installed, app.trial.started, app.trial.expired,
      app.subscription.started, app.subscription.renewed,
      app.subscription.expired, app.subscription.canceled,
      app.feedback.created, app.settings.updated
    We log them (and could gate features on subscription status later).
    """
    store_id = merchant_id or "default"
    _log_event(store_id, event, "ok", "acknowledged")
    print(f"[webhook] {event!r} acknowledged for store {store_id!r}")


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

    # Reset the cached agent so the updated catalogue is picked up on next chat
    if ok:
        sm.reset_agent(store_id)


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


async def _handle_abandoned_cart(merchant_id: str, data: dict):
    """
    abandoned.cart — a customer added items but didn't complete checkout.
    Stores a normalised notification in the per-store in-memory deque so the
    admin dashboard can show it without a live API call.
    """
    store_id = merchant_id or "default"
    cart_id  = str(data.get("id", ""))
    customer = data.get("customer") or {}
    total    = data.get("total")    or {}

    notification = {
        "id":             cart_id,
        "ts":             _dt.datetime.utcnow().isoformat() + "Z",
        "customer_name":  customer.get("name", "—"),
        "customer_phone": customer.get("mobile", customer.get("phone", "—")),
        "customer_email": customer.get("email", "—"),
        "total":          (total.get("amount", "—") if isinstance(total, dict) else str(total or "—")),
        "currency":       (total.get("currency", "SAR") if isinstance(total, dict) else "SAR"),
        "items_count":    len(data.get("items") or []),
        "age_minutes":    data.get("age_in_minutes", 0),
        "checkout_url":   data.get("checkout_url", ""),
        "status":         data.get("status", "active"),   # active | purchased
        "recovered":      False,
    }
    _abandoned_carts[store_id].appendleft(notification)

    # Persist to DB so carts survive restarts
    if cart_id:
        await db.save_abandoned_cart(store_id, cart_id, notification)

    _log_event(
        store_id, "abandoned.cart", "ok",
        f"cart_id={cart_id}  customer={notification['customer_name']}  "
        f"total={notification['total']} {notification['currency']}"
    )
    print(
        f"[webhook] 🛒 Abandoned cart {cart_id!r} — "
        f"{notification['customer_name']} — "
        f"{notification['total']} {notification['currency']} — "
        f"store={store_id!r}"
    )


# ── Salla Webhook endpoint ─────────────────────────────────────────────────────
@app.post("/webhook/salla")
async def salla_webhook(request: Request):
    """
    Central Salla webhook receiver.
    • Logs every raw attempt before any processing (for debugging)
    • Verifies HMAC-SHA256 signature; missing signature = warning only (easy-mode compat)
    • Deduplicates retries (Salla retries up to 3× every 5 min)
    • Routes to per-event async handlers and always returns 200 within the 30 s timeout
    """
    body = await request.body()
    body_head = body[:200].decode("utf-8", errors="replace")
    content_type = request.headers.get("Content-Type", "")
    user_agent   = request.headers.get("User-Agent", "")

    # ── 1. Signature verification ──────────────────────────────────────────────
    sig_ok, sig_detail = _verify_signature(body, request.headers)

    if not sig_ok:
        # Log the rejection too — useful for debugging mismatched secrets
        _log_event("", "", "rejected", f"signature: {sig_detail}",
                   sig_status=sig_detail, body_head=body_head,
                   content_type=content_type, user_agent=user_agent)
        raise HTTPException(401, f"Webhook signature invalid: {sig_detail}")

    # ── 2. Parse JSON ──────────────────────────────────────────────────────────
    import json as _json
    try:
        payload = _json.loads(body)
    except Exception as exc:
        _log_event("", "", "error", f"invalid JSON: {exc}",
                   sig_status=sig_detail, body_head=body_head,
                   content_type=content_type, user_agent=user_agent)
        raise HTTPException(400, f"Invalid JSON: {exc}")

    event       = payload.get("event", "")
    merchant_id = str(payload.get("merchant", ""))
    data        = payload.get("data", {})
    created_at  = payload.get("created_at", "")

    print(f"[webhook] {event!r}  merchant={merchant_id or '—'}  ts={created_at}")

    # ── 3. Idempotency — skip duplicate deliveries (DB-backed) ────────────────
    dedup_key = f"{event}:{merchant_id}:{created_at}"
    if await _already_seen(dedup_key):
        print(f"[webhook] Duplicate event skipped: {dedup_key}")
        _log_event(merchant_id or "", event, "duplicate", dedup_key,
                   sig_status=sig_detail, body_head=body_head,
                   content_type=content_type, user_agent=user_agent)
        return {"status": "ok", "duplicate": True}

    # Stash these on the request so the per-event handlers can include them
    # in their own log rows (we don't want to log the same event twice).
    _webhook_ctx = {
        "sig_status": sig_detail, "body_head": body_head,
        "content_type": content_type, "user_agent": user_agent,
    }

    # ── 4. Route to handler ────────────────────────────────────────────────────
    if event == "app.store.authorize":
        # Handle synchronously so the store is registered before we return
        await _handle_store_authorize(merchant_id, data)

    elif event == "app.updated":
        # Salla will immediately follow up with app.store.authorize containing
        # new tokens — nothing to do here except log it.
        _log_event(merchant_id or "default", event, "ok", "awaiting app.store.authorize",
                   **_webhook_ctx)
        print(f"[webhook] app.updated for merchant {merchant_id} — new tokens incoming")

    elif event.startswith("product."):
        asyncio.create_task(_handle_product_event(event, merchant_id, data))

    elif event.startswith("order."):
        asyncio.create_task(_handle_order_event(event, merchant_id, data))

    elif event.startswith("customer."):
        asyncio.create_task(_handle_customer_event(event, merchant_id, data))

    elif event == "abandoned.cart":
        asyncio.create_task(_handle_abandoned_cart(merchant_id, data))

    elif event == "app.uninstalled":
        # Handle synchronously — delete merchant data (Salla privacy rule)
        await _handle_app_uninstalled(merchant_id, data)

    elif event.startswith("app."):
        # app.installed / app.trial.* / app.subscription.* / app.feedback.* …
        asyncio.create_task(_handle_app_lifecycle(event, merchant_id, data))

    else:
        # Unknown / unhandled event — log and acknowledge
        _log_event(merchant_id or "default", event, "unhandled", **_webhook_ctx)
        print(f"[webhook] Unhandled event: {event!r}")

    return {"status": "ok", "event": event}


# ── Webhook events log (per-store) ─────────────────────────────────────────────
@app.get("/admin/{store_id}/webhooks/log")
async def store_webhook_log(store_id: str):
    """Return the newest 200 webhook events for this store from the DB."""
    events = await db.get_webhook_log(store_id=store_id, limit=200)
    return {"store_id": store_id, "count": len(events), "events": events}


# ── Abandoned carts ────────────────────────────────────────────────────────────

@app.get("/admin/{store_id}/abandoned-carts")
async def store_abandoned_carts(store_id: str, source: str = "cache"):
    """
    Return abandoned carts for a store.

    ?source=cache  (default) — in-memory webhook notifications received since last restart.
    ?source=api    — live fetch from Salla GET /carts/abandoned (requires carts.read scope).
    """
    if source == "api":
        token = sm.get_access_token(store_id)
        if not token:
            raise HTTPException(400, f"No access token for store '{store_id}'")
        from salla_client import SallaClient
        client = SallaClient(token, store_id=store_id)
        try:
            data  = await client.get_abandoned_carts(per_page=50)
            carts = data.get("data", [])
            return {"source": "api", "carts": carts, "count": len(carts)}
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {e}")

    # cache source — try in-memory first; fall back to DB on cold start
    carts = list(_abandoned_carts.get(store_id, []))
    if not carts and db.available():
        carts = await db.load_abandoned_carts(store_id)
        # Warm the in-memory cache from DB
        for cart in reversed(carts):
            _abandoned_carts[store_id].appendleft(cart)
        return {"source": "db", "carts": carts, "count": len(carts)}
    return {"source": "cache", "carts": carts, "count": len(carts)}


@app.post("/admin/{store_id}/abandoned-carts/{cart_id}/recover")
async def mark_cart_recovered(store_id: str, cart_id: str):
    """Mark an abandoned cart notification as handled / recovered."""
    carts = _abandoned_carts.get(store_id)
    found = False
    if carts:
        for cart in carts:
            if cart.get("id") == cart_id:
                cart["recovered"] = True
                found = True
                break
    # Persist recovery status to DB
    asyncio.create_task(db.mark_cart_recovered(store_id, cart_id))
    return {"status": "ok", "cart_id": cart_id, "recovered": True, "found_in_cache": found}


# ── Orders ────────────────────────────────────────────────────────────────────

@app.get("/admin/{store_id}/orders")
async def store_orders(
    store_id: str,
    page:      int = 1,
    per_page:  int = 20,
    keyword:   str = "",
    status:    str = "",
):
    """
    Proxy Salla GET /orders for a store — list with optional keyword / status filter.
    Requires carts.read or orders.read scope on the Salla app.
    """
    token = sm.get_access_token(store_id)
    if not token:
        raise HTTPException(400, f"No access token for store '{store_id}'")
    from salla_client import SallaClient
    client = SallaClient(token, store_id=store_id)
    try:
        data = await client.get_orders(
            per_page=per_page,
            page=page,
            keyword=keyword or None,
            status=status or None,
        )
        return data
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@app.get("/admin/{store_id}/orders/{order_id}")
async def store_order_detail(store_id: str, order_id: str):
    """Proxy Salla GET /orders/{id} for a store."""
    token = sm.get_access_token(store_id)
    if not token:
        raise HTTPException(400, f"No access token for store '{store_id}'")
    from salla_client import SallaClient
    client = SallaClient(token, store_id=store_id)
    try:
        return await client.get_order(order_id)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


# ── Webhook raw attempts debug (super-admin only) ─────────────────────────────
@app.get("/webhook/salla/debug")
async def webhook_debug(request: Request):
    """
    Diagnostics endpoint — shows last 50 raw webhook attempts.
    Requires super-admin authentication to avoid leaking merchant IDs to
    unauthenticated callers.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    attempts = await db.get_webhook_log(store_id=None, limit=50)
    return {
        "webhook_url":    f"{os.getenv('BASE_URL','http://localhost:8000')}/webhook/salla",
        "secret_set":     bool(os.getenv("SALLA_WEBHOOK_SECRET", "")),
        "total_attempts": len(attempts),
        "attempts":       attempts,
    }


# ── Manual store registration (super admin) ────────────────────────────────────
class ManualRegisterRequest(BaseModel):
    store_id:      str
    access_token:  str
    refresh_token: Optional[str] = ""
    store_name:    Optional[str] = ""


@app.post("/admin/stores/register")
async def manual_register_store(req: ManualRegisterRequest, request: Request):
    """
    Manually register / re-register a store when the webhook wasn't received
    (e.g. Railway filesystem wipe, Salla Partners URL misconfiguration, etc.)
    Requires super-admin token.

    The DB write is AWAITED (not fire-and-forget) so that if persistence
    fails the admin gets a clear error instead of the row silently
    disappearing on the next deploy.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(403, "مصرح للمدير العام فقط")

    store_id = req.store_id.strip()
    if not store_id or not req.access_token.strip():
        raise HTTPException(400, "store_id و access_token مطلوبان")

    sm.register_store(
        store_id=store_id,
        access_token=req.access_token.strip(),
        refresh_token=req.refresh_token.strip(),
        store_info={"name": req.store_name.strip() or f"متجر {store_id}"},
    )

    # CRITICAL: await the DB write so it survives the next deploy. Without
    # this, register_store only fires a background task that may never run
    # if the server restarts moments later (common cause of "stores
    # disappear on every deploy").
    persisted = False
    if db.available():
        try:
            tokens = sm.get_store_info(store_id)
            await db.save_store(store_id, tokens)
            persisted = True
            print(f"[admin] 💾 Store {store_id!r} persisted to DB synchronously")
        except Exception as exc:
            print(f"[admin] ❌ DB persist failed for {store_id!r}: {exc}")
            raise HTTPException(
                500,
                f"تم تسجيل المتجر في الذاكرة لكن فشل الحفظ في قاعدة البيانات: {exc}. "
                "المتجر سيُحذف عند أول إعادة تشغيل. راجع DATABASE_URL في Railway."
            )
    else:
        # No DB at all — warn the user loudly
        raise HTTPException(
            503,
            "قاعدة البيانات غير متصلة. المتاجر ستُحذف عند أول deploy. "
            "افتح Railway → أضف Postgres service → اربط DATABASE_URL."
        )

    # Kick off a background sync only after persistence is guaranteed
    asyncio.create_task(_sync_task(store_id, req.access_token.strip()))
    return {
        "status":    "ok",
        "store_id":  store_id,
        "persisted": persisted,
        "message":   f"تم تسجيل المتجر {store_id!r} وحفظه في قاعدة البيانات ✅",
    }


# ── DB diagnostic — registry vs DB comparison ────────────────────────────────
@app.get("/admin/registry-vs-db")
async def registry_vs_db(request: Request):
    """
    Super-admin diagnostic: compare what's in the in-memory registry vs
    what's actually persisted in PostgreSQL. Highlights any store that's
    in the DB but not in the registry (= would disappear on next restart
    even though it's "saved") and vice versa (= in memory only, will be
    lost on restart).
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    db_rows = await db.list_raw_stores() if db.available() else []
    memory  = sm.list_stores()

    db_ids     = {r["store_id"] for r in db_rows}
    memory_ids = {s["store_id"] for s in memory}

    return {
        "db_connected":      db.available(),
        "in_db":             len(db_rows),
        "in_memory":         len(memory),
        "only_in_db":        sorted(db_ids - memory_ids),       # persisted but not loaded
        "only_in_memory":    sorted(memory_ids - db_ids),       # at-risk: not saved
        "in_both":           sorted(db_ids & memory_ids),       # healthy
        "db_rows":           db_rows,
        "memory_rows":       memory,
    }


# ── DB diagnostic — force reload registry from DB ────────────────────────────
@app.post("/admin/reload-from-db")
async def reload_from_db(request: Request):
    """
    Super-admin: re-run load_from_db() to pull the latest store data from
    PostgreSQL into the in-memory registry. Useful when a store appears in
    /admin/registry-vs-db as "only_in_db" — usually because asyncpg's JSONB
    codec wasn't registered on a previous deploy and rows were silently
    skipped on startup.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    before = len(sm.list_stores())
    await sm.load_from_db()
    after = len(sm.list_stores())
    return {
        "status":  "ok",
        "before":  before,
        "after":   after,
        "loaded":  after - before,
        "message": f"تم إعادة التحميل من DB — {before} → {after} متجر",
    }


# ── DB diagnostic — round-trip test ───────────────────────────────────────────
@app.get("/admin/db-test")
async def db_diagnostic(request: Request):
    """
    Super-admin only: run a write→read→delete round-trip against the stores
    table to verify the DB is actually usable. Also returns the real row
    count (excluding the test row) so admin can see if persistence works
    but data is being wiped externally.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    result = await db.test_round_trip()
    result["env_database_url_set"] = bool(os.getenv("DATABASE_URL", "").strip())
    result["in_memory_stores"]     = len(sm.list_stores())
    return result


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


# ── Chat helpers ───────────────────────────────────────────────────────────────

async def _fetch_salla_customer(store_id: str, customer_id: str,
                                  fallback_name: str = "") -> dict:
    """
    Pull a customer's full profile from Salla's /customers/{id} and
    normalise it to the fields conversation_store.customer_info expects.
    Never raises — returns a minimal {name: fallback_name} on any error
    so chat flow keeps working even if Salla is down or the scope is missing.
    """
    name = (fallback_name or "").strip()
    base = {"name": name} if name else {}
    if not customer_id:
        return base

    token = sm.get_access_token(store_id)
    if not token:
        return base

    try:
        from salla_client import SallaClient
        client = SallaClient(token, store_id=store_id)
        # Request order stats too so the bot can tell a returning buyer from a
        # first-timer and personalise accordingly. Falls back gracefully if the
        # scope/fields aren't available.
        resp   = await client.get_customer(
            int(customer_id),
            fields=["orders_count", "orders_amount"],
        )
        c      = resp.get("data") or {}
    except Exception as exc:
        print(f"[chat] customer lookup failed for {customer_id}: {exc}")
        return base

    if not c:
        return base

    first = (c.get("first_name") or "").strip()
    last  = (c.get("last_name") or "").strip()
    full_name = (first + " " + last).strip() or name or f"عميل #{customer_id}"

    mobile_code = str(c.get("mobile_code", "") or "")
    mobile      = str(c.get("mobile", "") or "")
    phone       = (f"+{mobile_code}{mobile}" if mobile_code and mobile else mobile) or ""

    data = {
        "name":     full_name,
        "phone":    phone,
        "email":    c.get("email", "") or "",
        "city":     c.get("city", "") or "",
        "country":  c.get("country", "") or "",
        "avatar":   c.get("avatar", "") or "",
        "gender":   c.get("gender", "") or "",
        # IDs go in their own field — keep "name" clean for display
        "salla_customer_id": str(c.get("id") or customer_id),
    }
    # Order history (optional — only when the fields came back)
    oc = c.get("orders_count")
    if oc is not None:
        data["orders_count"] = oc
    oa = c.get("orders_amount")
    if isinstance(oa, dict) and oa.get("amount") is not None:
        data["orders_amount"] = f"{oa.get('amount')} {oa.get('currency', 'SAR')}"
    return data


# ── Chat ───────────────────────────────────────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(400, "الرسالة فارغة")

    store_id   = req.store_id or "default"

    # Sanitize store_id — if Salla's template wasn't resolved server-side
    # (e.g. widget tested outside Salla Snippets), "{{ merchant.id }}" is
    # passed literally.  Fall back to "default" to avoid polluting the registry.
    if "{{" in store_id or "}}" in store_id:
        store_id = "default"

    # ── Customer identity (when the widget runs on a Salla store and the
    # visitor is logged in, the SDK gives us a stable customer_id). We use
    # it to resume the customer's previous conversation and to look up their
    # name / phone / email from Salla so the admin sees a real person, not
    # an anonymous session id. ────────────────────────────────────────────
    raw_cid = (req.customer_id or "").strip()
    if raw_cid in ("0", "null", "undefined") or "{{" in raw_cid:
        raw_cid = ""

    # If the widget didn't send a session_id but we know the customer,
    # try to resume their newest conversation in this store.
    if raw_cid and not req.session_id:
        resumed = await cs.find_session_by_customer_db(store_id, raw_cid)
        if resumed:
            session_id = resumed
            print(f"[chat] 🔄 Resumed session {session_id} for customer {raw_cid}")
        else:
            session_id = str(uuid.uuid4())
    else:
        session_id = req.session_id or str(uuid.uuid4())

    await cs.restore_to_memory(session_id)

    # Link customer (cheap if already linked — overwrites only when empty)
    if raw_cid:
        conv_now = cs.all_conversations().get(session_id) or cs.get_or_create(session_id, store_id)
        if str(conv_now.get("salla_customer_id", "")) != raw_cid:
            # First time seeing this customer in this session — fetch their
            # full profile from Salla and persist
            customer_data = await _fetch_salla_customer(store_id, raw_cid, req.customer_name)
            cs.link_customer(session_id, raw_cid, customer_data)
            await cs.flush(session_id)

    bot_on     = cs.is_bot_enabled(session_id)

    if not bot_on:
        await cs.add_message(session_id, "user", req.message, store_id)
        return ChatResponse(
            reply="شكراً لرسالتك، سيتواصل معك أحد أعضاء فريق الدعم قريباً. 👨‍💼",
            session_id=session_id,
            bot_enabled=False,
        )

    agent = sm.get_agent(store_id)
    requested_store_id = store_id   # remember what the widget asked for
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

        # Loud warning so super-admin can see in Railway logs that a real
        # merchant's widget is hitting our backend but the store was never
        # registered — usually a missing/lost app.store.authorize webhook.
        if agent is not None and requested_store_id != store_id:
            print(
                f"[chat] ⚠️ ORPHAN STORE: widget requested {requested_store_id!r} "
                f"(not registered) — falling back to {store_id!r}. "
                f"Conversation will appear in {store_id!r}'s dashboard. "
                f"Fix: register {requested_store_id!r} via /admin/stores/register "
                f"or reinstall the app on that store."
            )

        # 3) Nothing works → friendly message (NOT bot_enabled=False — that triggers
        #    the widget's "admin takeover" UI which loops endlessly)
        if agent is None:
            err_reply = (
                "عذراً، المتجر غير مُعدّ بعد. "
                "يرجى ربط المتجر من لوحة التحكم أو التواصل مع الدعم."
            )
            await cs.add_message(session_id, "assistant", err_reply, store_id)
            return ChatResponse(
                reply=err_reply,
                session_id=session_id,
                bot_enabled=True,   # keep widget in normal state; bot is just misconfigured
            )

    try:
        reply = await agent.chat(message=req.message, session_id=session_id)
    except Exception as e:
        import traceback as _tb
        err_msg  = str(e)
        err_type = type(e).__name__
        print(
            f"[chat] ❌ agent.chat error store={store_id!r} session={session_id!r}\n"
            f"  {err_type}: {err_msg}\n"
            f"{_tb.format_exc()}"
        )

        # Pick a user-visible message based on error class / text.
        # Never return bot_enabled=False here — that triggers the widget's
        # admin-takeover loop and confuses the user.
        err_lower = err_msg.lower()
        # Check auth/key errors FIRST (before rate-limit) to avoid mis-classification.
        # OpenAI 401 contains "401" and "incorrect api key" or "invalid_api_key".
        # Groq 401 contains "401" and "invalid api key".
        if (
            "401" in err_lower
            or "authentication" in err_lower
            or ("invalid" in err_lower and "key" in err_lower)
            or "incorrect api key" in err_lower
            or "invalid_api_key" in err_lower
        ):
            friendly = "عذراً، هناك مشكلة في مفتاح API للذكاء الاصطناعي. يرجى مراجعة الإعدادات من لوحة التحكم. 🔑"
        elif "rate" in err_lower or "429" in err_lower or "quota" in err_lower:
            friendly = "عذراً، المساعد مشغول الآن بسبب الضغط الزائد. انتظر لحظة وحاول مجدداً. ⏳"
        elif "timeout" in err_lower or "connect" in err_lower or "connection" in err_lower:
            friendly = "عذراً، انتهت مهلة الاتصال. يرجى المحاولة مرة أخرى. 🌐"
        elif "key" in err_lower or "api" in err_lower:
            friendly = "عذراً، هناك مشكلة في إعدادات الذكاء الاصطناعي. يرجى التواصل مع الدعم. ⚙️"
        else:
            friendly = "عذراً، حدث خطأ مؤقت في معالجة طلبك. يرجى المحاولة مرة أخرى. 🙏"

        await cs.add_message(session_id, "assistant", friendly, store_id)
        return ChatResponse(
            reply=friendly,
            session_id=session_id,
            bot_enabled=True,   # error ≠ admin takeover; do NOT confuse the widget
        )

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


@app.post("/chat/rate")
async def chat_rate(req: RateRequest):
    """Customer rates a conversation 1-5 stars."""
    if not 1 <= req.rating <= 5:
        raise HTTPException(400, "التقييم يجب أن يكون بين 1 و 5")
    await cs.restore_to_memory(req.session_id)
    await cs.set_rating(req.session_id, req.rating, req.comment)
    return {"status": "ok", "message": "شكراً لتقييمك! 😊"}


@app.get("/chat/poll")
async def chat_poll(session_id: str):
    """Widget polls this endpoint to receive admin messages in real time."""
    await cs.restore_to_memory(session_id)
    pending = cs.pop_pending_for_widget(session_id)
    bot_on  = cs.is_bot_enabled(session_id)
    return {"messages": pending, "bot_enabled": bot_on}


@app.get("/chat/history")
async def chat_history(session_id: str):
    """
    Public endpoint the widget calls on load so a returning visitor sees
    their previous conversation after a refresh / leave-and-return.

    Access model: session_id is an unguessable random UUID stored in the
    visitor's own browser (localStorage), so possessing it acts as the
    access token for that single conversation — same model as /chat/poll.
    No admin auth required (this is the visitor's own thread).

    Returns messages mapped to the widget's two visual roles:
      'user'                  → 'user'  (right bubble)
      'assistant' | 'admin'   → 'bot'   (left bubble)
    """
    if not session_id or "{{" in session_id:
        return {"messages": [], "bot_enabled": True}
    await cs.restore_to_memory(session_id)
    conv = cs.all_conversations().get(session_id)
    if not conv:
        return {"messages": [], "bot_enabled": True}

    out = []
    for m in conv.get("messages", []):
        role = m.get("role")
        if role not in ("user", "assistant", "admin"):
            continue
        out.append({
            "role":    "user" if role == "user" else "bot",
            "content": m.get("content", ""),
            "ts":      m.get("ts", ""),
        })
    return {"messages": out, "bot_enabled": cs.is_bot_enabled(session_id)}


# ── File upload ────────────────────────────────────────────────────────────────
# MIME content-type lookup for the few extensions we care about
_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".tif": "image/tiff", ".tiff": "image/tiff",
    ".ai":  "application/postscript", ".eps": "application/postscript",
    ".psd": "image/vnd.adobe.photoshop",
    ".cdr": "application/vnd.corel-draw",
    ".zip": "application/zip",
}


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str  = Form(default=""),
    store_id: str    = Form(default="default"),
):
    """
    Customer file attachment from the widget.

    Storage strategy: persist to PostgreSQL as bytea so files survive
    Railway deploys (the local filesystem is wiped on every restart).
    A local-disk copy is kept as a best-effort cache for the static
    /uploads mount but is not relied on.

    The endpoint deliberately does NOT call the LLM — see commit f6022f7
    for the rationale (agent.chat failures used to bubble up as 500s
    without CORS headers, breaking the widget upload UX).
    """
    # Sanitize literal Salla template placeholders
    if "{{" in store_id or "}}" in store_id:
        store_id = "default"

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"نوع الملف غير مدعوم. الأنواع المسموحة: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"حجم الملف يتجاوز الحد المسموح ({MAX_FILE_MB} MB)")

    file_id      = str(uuid.uuid4())
    content_type = _CONTENT_TYPES.get(suffix, "application/octet-stream")
    filename     = file.filename or f"upload{suffix}"

    # Primary storage: PostgreSQL (persistent across deploys)
    db_saved = False
    if db.available():
        db_saved = await db.save_upload(
            file_id=file_id, filename=filename, content_type=content_type,
            data=contents, store_id=store_id, session_id=session_id,
        )
        if not db_saved:
            print(f"[upload] ⚠️ DB save failed for {file_id!r} — falling back to disk only")

    # Best-effort local cache (lost on Railway redeploys)
    try:
        save_path = UPLOAD_DIR / f"{file_id}{suffix}"
        async with aiofiles.open(save_path, "wb") as f:
            await f.write(contents)
    except Exception as exc:
        print(f"[upload] ⚠️ Disk cache save failed for {file_id!r}: {exc}")
        if not db_saved:
            raise HTTPException(500, f"تعذّر حفظ الملف: {exc}")

    # Build a public URL the admin dashboard / widget can render.
    # Routes through /file/{id} which falls back to DB if disk copy is gone.
    base_url = os.getenv("BASE_URL", "").rstrip("/")
    file_url = f"{base_url}/file/{file_id}" if base_url else f"/file/{file_id}"

    # Record the upload in the conversation transcript using a markdown link
    # so the admin UI can render it as a thumbnail / clickable link.
    if session_id:
        try:
            notification = f"📎 تم إرفاق ملف تصميم: [{filename}]({file_url})"
            await cs.add_message(session_id, "user", notification, store_id)
        except Exception as exc:
            print(f"[upload] ⚠️ Failed to log upload in conversation: {exc}")

    return {
        "message":  "تم رفع الملف بنجاح! سيتم مراجعته من فريق التصميم وسنتواصل معك قريباً.",
        "file_id":  file_id,
        "filename": filename,
        "url":      file_url,
    }


def _content_disposition(filename: str, disposition: str = "inline") -> str:
    """
    Build a latin-1-safe Content-Disposition header value.

    HTTP header values must be encodable as latin-1, but uploaded filenames
    are often Arabic/UTF-8. We emit an ASCII fallback for old clients plus a
    percent-encoded UTF-8 `filename*` (RFC 5987) for modern ones.
    """
    name = filename or "file"
    # ASCII fallback: drop non-latin-1 chars; if nothing's left, use a default.
    ascii_name = name.encode("ascii", "ignore").decode("ascii").strip() or "file"
    ascii_name = ascii_name.replace('"', "")
    utf8_name  = quote(name, safe="")
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


@app.get("/file/{file_id}")
async def get_uploaded_file(file_id: str):
    """
    Serve an uploaded file. Tries PostgreSQL first (persistent across
    deploys), then falls back to the local /uploads disk cache.

    On Railway the disk is ephemeral, so after a redeploy the UPLOAD_DIR may
    not exist and any DB-less file is simply gone. Both lookups are guarded so
    a missing file returns a clean 404 instead of a 500 (FileNotFoundError on
    iterdir of a non-existent directory).
    """
    # 1) Try DB (load_upload already swallows its own errors → None)
    if db.available():
        record = await db.load_upload(file_id)
        if record:
            from fastapi.responses import Response
            return Response(
                content=record["data"],
                media_type=record["content_type"],
                headers={
                    # RFC 5987/6266: HTTP headers are latin-1 only, so a non-ASCII
                    # filename (e.g. Arabic) must be percent-encoded via filename*.
                    # We send an ASCII fallback + the UTF-8 version.
                    "Content-Disposition": _content_disposition(record["filename"]),
                    "Cache-Control": "private, max-age=3600",
                },
            )

    # 2) Disk fallback — scan UPLOAD_DIR for any file whose stem == file_id.
    #    Guard against the directory being absent (fresh/ephemeral deploy).
    try:
        if UPLOAD_DIR.exists():
            for path in UPLOAD_DIR.iterdir():
                if path.stem == file_id:
                    return FileResponse(path)
    except Exception as e:
        print(f"[file] disk lookup failed for {file_id!r}: {e}")

    raise HTTPException(404, "الملف غير موجود أو تم حذفه")
