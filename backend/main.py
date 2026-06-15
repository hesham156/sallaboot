"""
Salla Printing Chatbot — Multi-tenant backend.

This file is intentionally kept short: it wires together the FastAPI app,
lifecycle hooks, middleware, and routers. Feature logic lives in the
routers/ package.
"""
import os
import sys
from pathlib import Path

# Force UTF-8 on stdout/stderr before importing anything that prints emoji
# startup banners (crypto.py / auth.py warn with ⚠️). On a Windows console the
# default cp1252 codec raises UnicodeEncodeError at import time, which would
# otherwise crash `uvicorn main:app` locally. No-op on Linux (already UTF-8).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

from dotenv import load_dotenv

load_dotenv()

import log as _logmod
_logmod.setup_logging()
log = _logmod.get_logger("backend.main")

from fastapi import FastAPI, Request as _Req
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import HTTPException as _FHTTPException
from starlette.exceptions import HTTPException as _SHTTPException

import socket as _socket

# ── Process identity (referenced by lifecycle + worker) ──────────────────────
_WORKER_ID = f"{os.getenv('WORKER_ROLE', 'web')}:{_socket.gethostname()}:{os.getpid()}"

# ── Upload dir (must exist before routers import deps) ───────────────────────
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Salla Printing Chatbot — Multi-tenant", version="2.0.0")

# ── Lifecycle (startup / shutdown / background loops) ────────────────────────
import lifecycle as _lc
_lc.register(app)

# Backward-compat aliases — worker.py and tests still reach into main.*
_enable_drainers       = _lc.enable_drainers
_enable_periodic       = _lc.enable_periodic
_sync_task             = _lc.sync_task
_check_expiring_tokens = _lc.check_expiring_tokens
_token_refresh_loop    = _lc.token_refresh_loop
_periodic_flush_loop   = _lc.periodic_flush_loop
_periodic_cleanup_loop = _lc.periodic_cleanup_loop
_inbox_drain_loop      = _lc.inbox_drain_loop
_outbox_drain_loop     = _lc.outbox_drain_loop

# ── Inbox / outbox dispatchers ────────────────────────────────────────────────
# Called by lifecycle loops. Kept here because they reference webhook handlers
# that live in routers/webhooks.py.

from routers import webhooks as _webhooks_router

async def _process_inbox_row(row: dict) -> None:
    source  = row["source"]
    payload = row["payload"] or {}
    if source == "salla":
        event       = row.get("event_type") or payload.get("event", "")
        merchant_id = row.get("store_id") or str(payload.get("merchant", ""))
        data        = payload.get("data") or {}
        await _webhooks_router.process_salla_event(event, merchant_id, data)
        return
    if source == "whatsapp":
        await _webhooks_router.handle_whatsapp_message(payload)
        return
    raise ValueError(f"unknown inbox source: {source!r}")


async def _deliver_outbox_row(row: dict) -> None:
    kind     = row["kind"]
    payload  = row["payload"] or {}
    store_id = row.get("store_id") or ""

    if kind == "notify_event":
        import notifications as _notif_mod
        await _notif_mod.deliver_outbox_row(store_id, payload)
        return

    if kind == "whatsapp_send":
        import whatsapp as wa
        import store_manager as sm
        cfg      = sm.get_ai_config(store_id) or {}
        token    = (cfg.get("whatsapp_token") or "").strip()
        phone_id = payload.get("phone_id") or (cfg.get("whatsapp_phone_id") or "")
        to       = payload.get("to", "")
        text     = payload.get("text", "")
        if not (token and phone_id and to and text):
            print(f"[outbox] whatsapp_send skipped (store={store_id}): missing config")
            return
        ok = await wa.send_text(token, phone_id, to, text)
        if not ok:
            raise RuntimeError("whatsapp send failed (see whatsapp.py log)")
        return

    raise ValueError(f"unknown outbox kind: {kind!r}")


# lifecycle.py does `import main as _main` and calls _main._process_inbox_row /
# _main._deliver_outbox_row — the functions above satisfy that contract.

# ── Static assets ─────────────────────────────────────────────────────────────
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

_ADMIN_HTML     = Path(__file__).parent / "admin.html"
_ADMIN_DIST_DIR = Path(__file__).parent / "admin-dist"
_ADMIN_DIST_IDX = _ADMIN_DIST_DIR / "index.html"

if _ADMIN_DIST_DIR.exists():
    _assets_dir = _ADMIN_DIST_DIR / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="admin-assets")

# Serve logo from admin-dist (committed to git, survives Railway deploys).
# Falls back to uploads/ if admin-dist copy is missing.
from fastapi.responses import FileResponse as _FR
@app.get("/logo.png", include_in_schema=False)
async def serve_logo():
    dist_logo = _ADMIN_DIST_DIR / "logo.png"
    if dist_logo.exists():
        return _FR(str(dist_logo), media_type="image/png",
                   headers={"Cache-Control": "public, max-age=86400"})
    upload_logo = UPLOAD_DIR / "logo.png"
    if upload_logo.exists():
        return _FR(str(upload_logo), media_type="image/png",
                   headers={"Cache-Control": "public, max-age=86400"})
    from fastapi import HTTPException as _HE
    raise _HE(404, "logo not found")


# ── Middleware ────────────────────────────────────────────────────────────────
import middleware as _mw
_mw.register(app)

# ── Routers ───────────────────────────────────────────────────────────────────
from routers import public    as _public_router
from routers import auth      as _auth_router
from routers import settings  as _settings_router
from routers import analytics as _analytics_router
from routers import platform  as _platform_router
from routers import conversations as _conv_router
from routers import employees as _employees_router
from routers import orders    as _orders_router
from routers import stores    as _stores_router
from routers import chat      as _chat_router
from routers import stream    as _stream_router
from routers import files        as _files_router
from routers import wa_templates as _wa_templates_router
from routers import segments     as _segments_router
from routers import blog         as _blog_router

# Wire lifecycle.sync_task into routers that need it.
_stores_router.set_sync_task(_lc.sync_task)
_chat_router.set_sync_task(_lc.sync_task)

app.include_router(_public_router.router)
app.include_router(_auth_router.router)
app.include_router(_webhooks_router.router)
app.include_router(_settings_router.router)
app.include_router(_analytics_router.router)
app.include_router(_platform_router.router)
app.include_router(_conv_router.router)
app.include_router(_employees_router.router)
app.include_router(_orders_router.router)
app.include_router(_stores_router.router)
app.include_router(_chat_router.router)
app.include_router(_stream_router.router)
app.include_router(_files_router.router)
app.include_router(_wa_templates_router.router)
app.include_router(_segments_router.router)
app.include_router(_blog_router.router)

# Backward-compat aliases for tests that import from main
_process_salla_event     = _webhooks_router.process_salla_event
_handle_whatsapp_message = _webhooks_router.handle_whatsapp_message
_verify_signature        = _webhooks_router._verify_signature
_log_event               = _webhooks_router._log_event

# Stream-ticket + daily-budget helpers were moved into routers during the
# Phase-2 split; tests (and any old import sites) still reach them via main.*.
# `_stream_time` is the shared `time` module the ticket helpers call — tests
# monkeypatch `main._stream_time.time` to simulate clock skew / expiry, which
# works because routers/stream.py imports the same singleton module object.
import time as _stream_time
_issue_stream_ticket   = _stream_router._issue_stream_ticket
_consume_stream_ticket = _stream_router._consume_stream_ticket
_TICKET_TTL_SECONDS    = _stream_router._TICKET_TTL_SECONDS
from routers.deps import daily_token_budget as _daily_token_budget


# ── SPA deep-link fallback for /admin/{store_id} (MUST stay registered last) ──
# Browser hard-navigation/refresh to a per-store admin deep link needs the SPA
# shell back so React Router can take over client-side. This catch-all is
# declared AFTER every API router on purpose: a `/admin/{store_id}` path-param
# route shadows any literal `/admin/<name>` JSON endpoint registered before it
# (audit-log, db-test, registry-vs-db, conversations, products, debug). Keeping
# it last means those literal endpoints win for XHR while genuine deep links
# still fall through to here.
@app.get("/admin/{store_id}", response_class=HTMLResponse, include_in_schema=False)
async def _admin_store_spa(store_id: str):
    return _public_router._serve_react_or_legacy()

# ── Browser-friendly error pages ──────────────────────────────────────────────
_API_ONLY_PREFIXES = (
    "/chat", "/webhook/", "/whatsapp/", "/widget.js", "/file/",
    "/upload", "/uploads/", "/assets/", "/health", "/env-check",
    "/snippet", "/api/",
)

_SPA_SHELL_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma":        "no-cache",
}


def _wants_html(request: _Req) -> bool:
    accept = (request.headers.get("Accept") or "").lower()
    if "text/html" not in accept:
        return False
    path = request.url.path
    return not any(path.startswith(p) for p in _API_ONLY_PREFIXES)


@app.exception_handler(_SHTTPException)
async def _http_exception_to_spa(request: _Req, exc: _SHTTPException):
    if _wants_html(request) and exc.status_code in (404, 410):
        if _ADMIN_DIST_IDX.exists():
            html = _ADMIN_DIST_IDX.read_text(encoding="utf-8")
        else:
            html = _ADMIN_HTML.read_text(encoding="utf-8") if _ADMIN_HTML.exists() else "<h1>404</h1>"
        return HTMLResponse(html, status_code=200, headers=_SPA_SHELL_NO_CACHE_HEADERS)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: _Req, exc: Exception):
    import traceback as _tb
    print(f"[unhandled] {type(exc).__name__}: {exc}\n{_tb.format_exc()}")

    if _wants_html(request):
        if _ADMIN_DIST_IDX.exists():
            html = _ADMIN_DIST_IDX.read_text(encoding="utf-8")
            redirect_snippet = (
                "<script>"
                "history.replaceState(null,'','/error/500');"
                "</script>"
            )
            html = html.replace("</head>", redirect_snippet + "</head>", 1)
            return HTMLResponse(html, status_code=500, headers=_SPA_SHELL_NO_CACHE_HEADERS)
        return HTMLResponse("<h1>500</h1>", status_code=500)

    return JSONResponse({"detail": "Internal Server Error"}, status_code=500)
