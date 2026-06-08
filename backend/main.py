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
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import hmac
import hashlib

# All request/response schemas live in models.py — re-export the names
# main.py historically defined so any external code that imported them
# from `main` keeps working during the Phase 2 migration.
from models import (
    ChatRequest, ChatResponse, RateRequest,
    AdminReplyRequest, BotToggleRequest, EndConversationRequest,
    LoginRequest, EmployeeLoginRequest, PasswordChangeRequest,
    AIConfigRequest, CustomKnowledgeRequest, TrainingTextRequest,
    NotificationSettingsRequest,
    EmployeeCreateRequest, EmployeeUpdateRequest,
    ManualRegisterRequest,
)

import re as _re
import time as _time
import socket as _socket
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
import realtime

# ── Process identity ─────────────────────────────────────────────────────────
# Stable identifier for this process. Used as:
#   • the `claimed_by` value when draining webhook_inbox / outbox rows
#   • the `holder` value when acquiring leader_locks (so we see which
#     instance is currently running periodic jobs from SELECT * FROM
#     leader_locks)
# Format: <role>:<hostname>:<pid> — role distinguishes web from worker
# when both run in the same Railway project. Worker process overrides
# the role via the WORKER_ROLE env var.
_WORKER_ID = f"{os.getenv('WORKER_ROLE', 'web')}:{_socket.gethostname()}:{os.getpid()}"

# ── Rate limiter (DB-backed, survives restarts) ─────────────────────────────
# Used by login endpoints AND by /chat. The login_attempts table is a
# generic (attempt_key, created_at) log — we reuse it as a sliding-window
# counter for any rate-limit purpose by namespacing the key prefix.

async def _is_rate_limited(attempt_key: str, max_attempts: int = 5, window: int = 300) -> bool:
    """
    Return True if `attempt_key` has exceeded `max_attempts` events in the
    last `window` seconds. Persists to PostgreSQL so a server restart doesn't
    reset an attacker's counter. Records the new attempt as a side effect —
    call once per event.
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


# Public /chat rate-limit budgets — tuned for an attentive human, not a bot.
# These are intentionally loose: the goal is to prevent LLM-cost abuse from a
# scripted hammer, NOT to throttle real shoppers. If a real user trips this,
# the limits are too low.
CHAT_RL_PER_SESSION = (40, 60)    # 40 msgs / 60s per session (typing fast is fine)
CHAT_RL_PER_IP      = (200, 60)   # 200 msgs / 60s per IP (multi-tab / shared NAT)
CHAT_RL_PER_STORE   = (2000, 60)  # 2000 msgs / 60s per store (high — protects spend)


async def _chat_rate_limited(store_id: str, session_id: str, ip: str) -> str | None:
    """
    Multi-axis rate limit for the public /chat endpoint. Returns a string
    naming the axis that tripped (for logs / response detail), or None if
    the request may proceed.

    Skipped when the DB isn't connected — fail-open like the login limiter.
    """
    if not db.available():
        return None

    sess_max, sess_win = CHAT_RL_PER_SESSION
    ip_max,   ip_win   = CHAT_RL_PER_IP
    str_max,  str_win  = CHAT_RL_PER_STORE

    if await _is_rate_limited(f"chat:s:{session_id}", sess_max, sess_win):
        return "session"
    if await _is_rate_limited(f"chat:i:{ip}",         ip_max,   ip_win):
        return "ip"
    if await _is_rate_limited(f"chat:t:{store_id}",   str_max,  str_win):
        return "store"
    return None


# ── Daily token-budget circuit breaker ────────────────────────────────────
# Defends against LLM-cost abuse from a single compromised store. Rate
# limits above bound requests-per-minute; this one bounds tokens-per-day,
# so a slow drip that hides under the rate limits still gets caught.
#
# Resolution order for the daily budget:
#   1. Per-store override in ai_config['daily_token_budget'] (admin can
#      raise/lower from the dashboard).
#   2. LLM_DAILY_TOKEN_BUDGET env var (operator's global default).
#   3. _DEFAULT_DAILY_TOKEN_BUDGET below.
#
# Set the per-store override to 0 to disable the breaker for that store
# (for a paying customer who agreed to unlimited usage).
_DEFAULT_DAILY_TOKEN_BUDGET = 500_000


def _daily_token_budget(store_id: str) -> int:
    """Return the active daily token budget for `store_id`. 0 means disabled."""
    cfg = sm.get_ai_config(store_id) or {}
    override = cfg.get("daily_token_budget")
    if override is not None:
        try:
            n = int(override)
            return max(0, n)
        except (TypeError, ValueError):
            pass  # malformed override — fall through to env default
    try:
        return max(0, int(os.getenv("LLM_DAILY_TOKEN_BUDGET", _DEFAULT_DAILY_TOKEN_BUDGET)))
    except ValueError:
        return _DEFAULT_DAILY_TOKEN_BUDGET


async def _budget_exhausted(store_id: str) -> tuple[bool, int, int]:
    """
    Check whether today's usage has hit the daily token budget.

    Returns (exhausted, used_today, budget). exhausted is False when the
    breaker is disabled (budget=0) or DB is unavailable (fail-open — we
    don't want a Postgres hiccup to brick every store's chat).
    """
    budget = _daily_token_budget(store_id)
    if budget <= 0 or not db.available():
        return False, 0, budget
    snapshot = await db.llm_usage_today(store_id)
    used = int(snapshot.get("tokens_total", 0))
    return used >= budget, used, budget

# Store IDs that are reserved and must never be used as real Salla merchant IDs
_RESERVED_IDS = {"super", "admin", "stores", "auth", "default"}


def _enable_drainers() -> bool:
    """True unless the deploy explicitly turned inbox/outbox drainers off."""
    return os.getenv("ENABLE_DRAINERS", "true").lower() != "false"


def _enable_periodic() -> bool:
    """True unless the deploy explicitly turned periodic loops off."""
    return os.getenv("ENABLE_PERIODIC", "true").lower() != "false"

# ── Setup ──────────────────────────────────────────────────────────────────────
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_MB        = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
ALLOWED_EXTENSIONS = {
    ".pdf", ".ai", ".eps", ".psd", ".png", ".jpg", ".jpeg",
    ".svg", ".tiff", ".tif", ".cdr", ".zip",
}

app = FastAPI(title="Salla Printing Chatbot — Multi-tenant", version="2.0.0")


# ── Lifecycle (startup / shutdown / background loops) ────────────────────
# All of it lives in lifecycle.py now. register() wires the FastAPI
# startup + shutdown hooks. The drainer loops + periodic loops live there
# too — worker.py imports them directly so the worker process runs the
# same code without the FastAPI app.
import lifecycle as _lc
_lc.register(app)
# Backward-compat aliases — worker.py and tests still reach into
# main._WORKER_ID / main._token_refresh_loop / etc.
_WORKER_ID                 = _lc.WORKER_ID
_enable_drainers           = _lc.enable_drainers
_enable_periodic           = _lc.enable_periodic
_sync_task                 = _lc.sync_task
_check_expiring_tokens     = _lc.check_expiring_tokens
_token_refresh_loop        = _lc.token_refresh_loop
_periodic_flush_loop       = _lc.periodic_flush_loop
_periodic_cleanup_loop     = _lc.periodic_cleanup_loop
_inbox_drain_loop          = _lc.inbox_drain_loop
_outbox_drain_loop         = _lc.outbox_drain_loop


# ── Inbox / outbox dispatchers ───────────────────────────────────────────
# Called by lifecycle.inbox_drain_loop / outbox_drain_loop via late
# import. Kept in main.py for now because they reference webhook handlers
# (_process_salla_event, _handle_whatsapp_message) that move to
# routers/webhooks.py in P2-6.

async def _process_inbox_row(row: dict) -> None:
    """
    Dispatch one inbox row to its source-specific handler. Raises on failure
    so the drainer can mark the row failed/dead with the right backoff.
    """
    source = row["source"]
    payload = row["payload"] or {}
    if source == "salla":
        event = row.get("event_type") or payload.get("event", "")
        merchant_id = row.get("store_id") or str(payload.get("merchant", ""))
        data = payload.get("data") or {}
        await _process_salla_event(event, merchant_id, data)
        return
    if source == "whatsapp":
        await _handle_whatsapp_message(payload)
        return
    raise ValueError(f"unknown inbox source: {source!r}")


async def _deliver_outbox_row(row: dict) -> None:
    """
    Dispatch one outbox row to its kind-specific sender. Raises on failure
    so the drainer applies the configured backoff (or DLQ after MAX_ATTEMPTS).
    """
    kind = row["kind"]
    payload = row["payload"] or {}
    store_id = row.get("store_id") or ""

    if kind == "notify_event":
        import notifications as _notif_mod
        await _notif_mod.deliver_outbox_row(store_id, payload)
        return

    if kind == "whatsapp_send":
        import whatsapp as wa
        cfg = sm.get_ai_config(store_id) or {}
        token = (cfg.get("whatsapp_token") or "").strip()
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


# ── Proactive token refresh ────────────────────────────────────────────────────

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
    """
    Legacy helper kept for any in-file callers (none after Phase 2.4
    — but importable). The canonical version lives in
    routers/public.py and is what the SPA endpoints actually use.
    """
    if _ADMIN_DIST_IDX.exists():
        return HTMLResponse(_ADMIN_DIST_IDX.read_text(encoding="utf-8"))
    return HTMLResponse(_ADMIN_HTML.read_text(encoding="utf-8"))


# Public router — landing pages, /health, /env-check, /widget.js,
# /snippet, /test-widget, /admin/stores list, super-admin force-sync.
from routers import public as _public_router
app.include_router(_public_router.router)

# Auth router — super/store/employee login + token verify.
from routers import auth as _auth_router
app.include_router(_auth_router.router)

# Webhook router — Salla + WhatsApp ingest + per-store webhook log +
# super-admin diagnostics. Also exposes process_salla_event() and
# handle_whatsapp_message() so the inbox drainer can dispatch into them.
from routers import webhooks as _webhooks_router
app.include_router(_webhooks_router.router)
# Backward-compat aliases — the drainer dispatchers + tests reference
# these names. Phase 2 keeps the legacy underscored names alive.
_process_salla_event      = _webhooks_router.process_salla_event
_handle_whatsapp_message  = _webhooks_router.handle_whatsapp_message
_verify_signature         = _webhooks_router._verify_signature
_log_event                = _webhooks_router._log_event


# ── Middleware moved to middleware.py ────────────────────────────────────
# Both auth + CORS middlewares live in middleware.py now. register()
# attaches them in the correct order so CORS wraps auth.
import middleware as _mw
_mw.register(app)


# ── Models moved to models.py (re-exported via the import above) ─────────


# ── Utility endpoints ──────────────────────────────────────────────────────────
# env-check, force-db-sync, widget.js, snippet, test-widget, health,
# SPA shells, and /admin/stores live in routers/public.py now.

# ── Auth endpoints moved to routers/auth.py ──────────────────────────────


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

    # WhatsApp channel status + the values the merchant pastes into Meta.
    import whatsapp as _wa
    base = os.getenv("BASE_URL", "").rstrip("/")
    return {
        "groq_api_key":      "••••" if groq_set      else "",
        "anthropic_api_key": "••••" if anthropic_set else "",
        "openai_api_key":    "••••" if openai_set    else "",
        "ai_model":          cfg.get("ai_model",  ""),
        "bot_name":          cfg.get("bot_name",  ""),
        "provider":          provider,
        "store_type":        store_type,
        "whatsapp_enabled":   bool(cfg.get("whatsapp_enabled")),
        "whatsapp_phone_id":  cfg.get("whatsapp_phone_id", ""),
        "whatsapp_token":     "••••" if cfg.get("whatsapp_token") else "",
        "whatsapp_webhook":   (base + "/whatsapp/webhook") if base else "/whatsapp/webhook",
        "whatsapp_verify_token": _wa.VERIFY_TOKEN,
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

    # WhatsApp channel — only overwrite fields the frontend explicitly sends.
    # Empty token string keeps the existing one (masked value round-trip).
    if req.whatsapp_phone_id is not None:
        config["whatsapp_phone_id"] = req.whatsapp_phone_id.strip()
    if req.whatsapp_enabled is not None:
        config["whatsapp_enabled"] = bool(req.whatsapp_enabled)
    if req.whatsapp_token is not None and req.whatsapp_token.strip():
        config["whatsapp_token"] = req.whatsapp_token.strip()

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


# ── Settings: Notifications (email + webhook) ─────────────────────────────────
import notifications as _notif


@app.get("/admin/{store_id}/settings/notifications")
async def get_notification_settings(store_id: str):
    """Return current notification settings for the store."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    return _notif.get_settings(store_id)


@app.put("/admin/{store_id}/settings/notifications")
async def update_notification_settings(store_id: str, req: NotificationSettingsRequest):
    """Save notification settings for the store."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    settings = {
        "email_enabled":       req.email_enabled,
        "email_address":       (req.email_address or "").strip(),
        "webhook_url":         (req.webhook_url   or "").strip(),
        "on_new_conversation": req.on_new_conversation,
        "on_abandoned_cart":   req.on_abandoned_cart,
        "on_low_rating":       req.on_low_rating,
        "quiet_hours_enabled": req.quiet_hours_enabled,
        "quiet_hours_start":   max(0, min(23, req.quiet_hours_start)),
        "quiet_hours_end":     max(0, min(23, req.quiet_hours_end)),
    }
    _notif.save_settings(store_id, settings)
    # Persist to DB
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, sm.get_ai_config(store_id))
    return {"status": "ok", "message": "تم حفظ إعدادات الإشعارات ✅"}


@app.post("/admin/{store_id}/settings/notifications/test")
async def test_notification(store_id: str):
    """Send a test email/webhook to verify the configuration works."""
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    n = _notif.get_settings(store_id)
    if not n["email_enabled"] and not n["webhook_url"]:
        raise HTTPException(400, "فعّل البريد الإلكتروني أو الـ Webhook أولاً")
    await _notif.notify(store_id, "new_conversation", {
        "customer_name": "عميل تجريبي",
        "session_id":    "test-session",
        "first_message": "هذه رسالة تجريبية للتأكد من أن الإشعارات تعمل ✅",
    })
    return {"status": "ok", "message": "تم إرسال إشعار تجريبي ✅"}


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

def _conv_channel(session_id: str, conv: dict) -> str:
    """Classify a conversation by its inbound channel.

    `wa:` prefix on the session_id is the canonical WhatsApp marker (set
    when /whatsapp/webhook creates the session). Fall back to the
    customer_info.channel field for safety.
    """
    if session_id.startswith("wa:"):
        return "whatsapp"
    ch = ((conv.get("customer_info") or {}).get("channel") or "").lower()
    if ch == "whatsapp":
        return "whatsapp"
    return "widget"


def _empty_channel_stats(now_utc) -> dict:
    import datetime as _dtt
    daily: dict = {}
    for i in range(14):
        d = (now_utc - _dtt.timedelta(days=i)).strftime("%Y-%m-%d")
        daily[d] = 0
    return {
        "_daily": daily,
        "conversations": {
            "total": 0, "today": 0, "this_week": 0,
            "bot_handled": 0, "admin_takeover": 0,
            "avg_messages": 0,
            "daily_counts": [],
            "hourly_distribution": [0] * 24,
        },
        "messages": {"total": 0, "user": 0, "bot": 0, "admin": 0},
        "ratings": {"count": 0, "avg": 0, "distribution": [0, 0, 0, 0, 0], "_sum": 0},
    }


def _accumulate_conv(stats: dict, conv: dict, now_utc) -> None:
    """Fold one conversation into a channel-stats bucket (mutates `stats`)."""
    import datetime as _dtt

    c = stats["conversations"]
    c["total"] += 1

    created_str = conv.get("created_at", "")
    try:
        created = _dtt.datetime.fromisoformat(created_str)
        delta   = now_utc - created
        if delta.days == 0:
            c["today"] += 1
        if delta.days < 7:
            c["this_week"] += 1
        date_key = created.strftime("%Y-%m-%d")
        if date_key in stats["_daily"]:
            stats["_daily"][date_key] += 1
        c["hourly_distribution"][created.hour] += 1
    except Exception:
        pass

    if not conv.get("bot_enabled", True):
        c["admin_takeover"] += 1
    else:
        c["bot_handled"] += 1

    m = stats["messages"]
    for msg in conv.get("messages", []):
        m["total"] += 1
        role = msg.get("role", "")
        if role == "user":
            m["user"] += 1
        elif role == "assistant":
            m["bot"] += 1
        elif role == "admin":
            m["admin"] += 1

    # Rating
    try:
        r = int(conv.get("rating") or 0)
    except (TypeError, ValueError):
        r = 0
    if 1 <= r <= 5:
        stats["ratings"]["count"]               += 1
        stats["ratings"]["_sum"]                += r
        stats["ratings"]["distribution"][r - 1] += 1


def _finalise_channel_stats(stats: dict) -> dict:
    """Compute derived fields (avg, daily list) and drop helper keys."""
    c = stats["conversations"]
    m = stats["messages"]
    r = stats["ratings"]

    c["avg_messages"] = round(m["total"] / c["total"], 1) if c["total"] else 0
    c["daily_counts"] = [
        {"date": d, "count": stats["_daily"][d]}
        for d in sorted(stats["_daily"].keys())
    ]
    r["avg"] = round(r["_sum"] / r["count"], 1) if r["count"] else 0

    # Remove internal-only keys
    stats.pop("_daily", None)
    r.pop("_sum", None)
    return stats


@app.get("/admin/{store_id}/analytics")
async def store_analytics(store_id: str):
    """
    Return aggregated analytics for a store, split by channel.

    Top-level fields (conversations / messages / ratings) reflect the
    grand total so existing callers keep working unchanged. A new
    `by_channel` dict carries the same shape, computed separately for
    widget chats and WhatsApp threads, so the dashboard can show each
    channel on its own.
    """
    import datetime as _dtt
    now_utc = _dtt.datetime.utcnow()

    all_convs = await cs.get_all_conversations_for_store(store_id)

    # Three accumulators: widget / whatsapp / total
    buckets = {
        "widget":   _empty_channel_stats(now_utc),
        "whatsapp": _empty_channel_stats(now_utc),
        "total":    _empty_channel_stats(now_utc),
    }

    for sid, conv in all_convs.items():
        channel = _conv_channel(sid, conv)
        _accumulate_conv(buckets[channel], conv, now_utc)
        _accumulate_conv(buckets["total"], conv, now_utc)

    for k in buckets:
        _finalise_channel_stats(buckets[k])

    # ── Abandoned carts ────────────────────────────────────────────────────────
    # Carts come from Salla webhooks and aren't tagged by channel, so they
    # only live at the top level. Read straight from the DB (the source of
    # truth — we no longer keep a process-local cache).
    carts_list = await db.load_abandoned_carts(store_id) if db.available() else []

    total_carts    = len(carts_list)
    recovered_carts = sum(1 for c in carts_list if c.get("recovered"))
    pending_carts  = total_carts - recovered_carts
    recovery_rate  = round(recovered_carts / total_carts * 100, 1) if total_carts else 0

    cache = sm.get_cache(store_id)

    total = buckets["total"]
    return {
        # Legacy top-level fields — equal to `by_channel.total` so existing
        # frontend code keeps reading from `.conversations`, `.messages`, etc.
        "conversations":   total["conversations"],
        "messages":        total["messages"],
        "ratings":         total["ratings"],
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
        # New per-channel breakdown
        "by_channel": {
            "widget":   {
                "conversations": buckets["widget"]["conversations"],
                "messages":      buckets["widget"]["messages"],
                "ratings":       buckets["widget"]["ratings"],
            },
            "whatsapp": {
                "conversations": buckets["whatsapp"]["conversations"],
                "messages":      buckets["whatsapp"]["messages"],
                "ratings":       buckets["whatsapp"]["ratings"],
            },
            "total":    {
                "conversations": total["conversations"],
                "messages":      total["messages"],
                "ratings":       total["ratings"],
            },
        },
    }



# ── LLM token usage + budget (circuit breaker for AI spend) ─────────────────
@app.get("/admin/{store_id}/llm-usage")
async def store_llm_usage(store_id: str, days: int = 7):
    """
    Today's tokens + recent daily history + active budget for this store.
    Used by the admin dashboard to show:
      • Current consumption against the daily limit
      • Trend over the last `days` (default 7) for chart rendering
      • The active budget value (with its source: per-store override vs env default)
    """
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    today    = await db.llm_usage_today(store_id)
    history  = await db.llm_usage_report(store_id, days=days)
    budget   = _daily_token_budget(store_id)
    override = (sm.get_ai_config(store_id) or {}).get("daily_token_budget")

    used_today = int(today.get("tokens_total", 0))
    return {
        "store_id": store_id,
        "today": {
            **today,
            "budget":           budget,
            "remaining":        max(0, budget - used_today) if budget > 0 else None,
            "percent_used":     round(used_today / budget * 100, 1) if budget > 0 else None,
            "exhausted":        budget > 0 and used_today >= budget,
        },
        "budget": {
            "value":         budget,
            "source":        "store_override" if override is not None else "env_default",
            "breaker_active": budget > 0,
        },
        "history": history,
    }


@app.put("/admin/{store_id}/llm-budget")
async def update_llm_budget(store_id: str, request: Request):
    """
    Set the per-store daily token budget. Pass 0 to disable the breaker for
    this store (paying customer with unlimited usage agreement). Pass null /
    omit the field to fall back to the env-var default.

    Body: {"daily_token_budget": int | null}
    """
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    # Owner-only — middleware already blocks agents; managers can change
    # most settings but the budget is a financial-risk knob, so we gate
    # it to the store owner / super admin the same way password reset is.
    _require_store_owner(request, store_id)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    raw = body.get("daily_token_budget", None) if isinstance(body, dict) else None
    cfg = dict(sm.get_ai_config(store_id) or {})

    if raw is None:
        cfg.pop("daily_token_budget", None)
        applied = None
    else:
        try:
            n = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(400, "daily_token_budget must be an integer or null")
        if n < 0:
            raise HTTPException(400, "daily_token_budget must be ≥ 0 (0 disables the breaker)")
        cfg["daily_token_budget"] = n
        applied = n

    sm.set_ai_config(store_id, cfg)
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, cfg)

    return {
        "status": "ok",
        "daily_token_budget": applied,
        "effective_budget":   _daily_token_budget(store_id),
    }


# ── ROI dashboard: "how much did the bot make you" ─────────────────────────────
@app.get("/admin/{store_id}/analytics/roi")
async def store_roi(store_id: str, days: int = 30):
    """
    Bottom-line value the bot delivered: revenue from orders it created,
    conversations handled (≈ staff time saved), and carts recovered.
    `days` selects the window (default 30).
    """
    import datetime as _dtt
    days = max(1, min(int(days or 30), 365))
    now_utc = _dtt.datetime.utcnow()
    window_start = now_utc - _dtt.timedelta(days=days)

    # 1) Bot-generated revenue (from the bot_orders ledger)
    roi = await db.get_bot_roi(store_id, days)

    # 2) Conversations handled in the window (≈ messages the bot answered)
    convs = await cs.get_all_conversations_for_store(store_id)
    convs_window = 0
    msgs_handled = 0
    for conv in convs.values():
        try:
            created = _dtt.datetime.fromisoformat(conv.get("created_at", ""))
            in_window = created >= window_start
        except Exception:
            in_window = True   # undated → count it
        if in_window:
            convs_window += 1
            msgs_handled += sum(
                1 for m in conv.get("messages", [])
                if m.get("role") in ("assistant", "admin")
            )

    # 3) Recovered abandoned carts (from DB — multi-instance safe)
    carts = await db.load_abandoned_carts(store_id) if db.available() else []
    carts_recovered = sum(1 for c in carts if c.get("recovered"))

    # 4) Time saved: assume each handled conversation would take a human ~5 min
    minutes_saved = convs_window * 5
    hours_saved   = round(minutes_saved / 60, 1)

    return {
        "days":            days,
        "currency":        roi["currency"],
        "revenue":         roi["revenue"],        # bot revenue in window
        "orders":          roi["orders"],         # bot orders in window
        "avg_order":       roi["avg_order"],
        "revenue_all":     roi["revenue_all"],    # all-time bot revenue
        "orders_all":      roi["orders_all"],
        "conversations":   convs_window,
        "messages_handled": msgs_handled,
        "hours_saved":     hours_saved,
        "carts_recovered": carts_recovered,
    }


# ── Weekly performance report (week-over-week) ─────────────────────────────────
@app.get("/admin/{store_id}/analytics/weekly")
async def store_weekly(store_id: str):
    """
    A pushable weekly summary: this week vs last week for revenue, orders,
    conversations, plus satisfaction and the top customer topic. Powers the
    in-dashboard report card + the "copy to share" text.
    """
    import datetime as _dtt

    def _pct(now_v: float, prev_v: float) -> int:
        if prev_v <= 0:
            return 100 if now_v > 0 else 0
        return round((now_v - prev_v) / prev_v * 100)

    now_utc   = _dtt.datetime.utcnow()
    week_ago  = now_utc - _dtt.timedelta(days=7)
    two_weeks = now_utc - _dtt.timedelta(days=14)

    wroi = await db.get_weekly_roi(store_id)

    # Conversations this week vs last week + ratings this week
    convs = await cs.get_all_conversations_for_store(store_id)
    conv_this = conv_prev = 0
    ratings: list[int] = []
    for conv in convs.values():
        try:
            created = _dtt.datetime.fromisoformat(conv.get("created_at", ""))
        except Exception:
            created = now_utc
        if created >= week_ago:
            conv_this += 1
            r = conv.get("rating")
            if isinstance(r, (int, float)) and r:
                ratings.append(int(r))
        elif two_weeks <= created < week_ago:
            conv_prev += 1

    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0.0

    # Top customer topic this week (reuse the keyword analyzer)
    top_topic = ""
    try:
        import conversation_analyzer as ca
        recent = {sid: c for sid, c in convs.items()
                  if (lambda d: d >= week_ago)(_safe_dt(c.get("created_at", ""), now_utc))}
        insights = ca.analyze_insights(list(recent.values()))
        tq = insights.get("top_questions") or []
        if tq:
            top_topic = tq[0].get("label", "")
    except Exception as exc:
        print(f"[weekly] topic analysis skipped: {exc}")

    return {
        "currency":       wroi["currency"],
        "revenue":        wroi["rev_this"],
        "revenue_delta":  _pct(wroi["rev_this"], wroi["rev_prev"]),
        "orders":         wroi["ord_this"],
        "orders_delta":   _pct(wroi["ord_this"], wroi["ord_prev"]),
        "conversations":  conv_this,
        "conv_delta":     _pct(conv_this, conv_prev),
        "avg_rating":     avg_rating,
        "top_topic":      top_topic,
    }


def _safe_dt(s: str, fallback):
    import datetime as _dtt
    try:
        return _dtt.datetime.fromisoformat(s)
    except Exception:
        return fallback


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
async def store_admin_reply(
    store_id: str,
    session_id: str,
    req: AdminReplyRequest,
    request: Request,
):
    if not req.message.strip():
        raise HTTPException(400, "الرسالة فارغة")
    await cs.restore_to_memory(session_id)
    text = req.message.strip()
    msg = await cs.add_message(session_id, "admin", text, store_id)

    # Stamp the employee identity onto the message so the customer-facing
    # widget and admin inbox can show "Shurog" instead of a generic "إدارة".
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    emp = _auth.token_employee(token)
    if emp and emp.get("name"):
        conv = cs.all_conversations().get(session_id)
        if conv and conv.get("messages"):
            conv["messages"][-1]["employee_name"] = emp["name"]
            conv["messages"][-1]["employee_id"]   = emp["id"]
            msg["employee_name"] = emp["name"]
            msg["employee_id"]   = emp["id"]
            cs.mark_dirty(session_id)
            await cs.flush(session_id)

    cs.mark_admin_read(session_id)
    # Learn from this correction in the background: the admin's answer is the
    # right response, captured as a pending lesson for review. Fire-and-forget
    # so it never slows the reply.
    import bot_learning
    asyncio.create_task(bot_learning.capture_admin_correction(store_id, session_id, text))

    # If this is a WhatsApp thread, also deliver the admin's reply to WhatsApp.
    # Routed through the durable outbox so a restart between admin-clicked-send
    # and Meta-API-accepted doesn't drop the customer-facing message.
    if session_id.startswith("wa:"):
        cfg = sm.get_ai_config(store_id) or {}
        token, phone_id = (cfg.get("whatsapp_token") or "").strip(), (cfg.get("whatsapp_phone_id") or "").strip()
        if token and phone_id:
            await db.outbox_enqueue(
                kind     = "whatsapp_send",
                store_id = store_id,
                payload  = {
                    "phone_id": phone_id,
                    "to":       session_id[3:],
                    "text":     text,
                },
            )

    return {"status": "sent", "message": msg}


@app.post("/admin/{store_id}/conversations/{session_id}/takeover")
async def store_takeover(store_id: str, session_id: str):
    await cs.restore_to_memory(session_id)
    cs.set_session_bot(session_id, False)
    cs.mark_admin_read(session_id)
    # Persist the bot_enabled change so it survives restart
    await cs.flush(session_id)
    # Push to widget — it shows the "human took over" banner without polling.
    await realtime.publish(f"session:{session_id}", "bot_toggle", {
        "session_id":  session_id,
        "bot_enabled": False,
    })
    # Push to admin dashboard — sidebar can re-paint the takeover badge.
    await realtime.publish(f"store:{store_id}", "bot_toggle", {
        "session_id":  session_id,
        "bot_enabled": False,
    })
    return {"status": "ok", "bot_enabled": False, "session_id": session_id}


@app.post("/admin/{store_id}/conversations/{session_id}/handback")
async def store_handback(store_id: str, session_id: str):
    await cs.restore_to_memory(session_id)
    cs.set_session_bot(session_id, True)
    await cs.add_message(session_id, "admin",
                   "✅ تم إعادة توصيلك بالمساعد الذكي. كيف يمكنني مساعدتك؟",
                   store_id)
    # bot_enabled flipped back on — widget hides the "human" banner.
    await realtime.publish(f"session:{session_id}", "bot_toggle", {
        "session_id":  session_id,
        "bot_enabled": True,
    })
    await realtime.publish(f"store:{store_id}", "bot_toggle", {
        "session_id":  session_id,
        "bot_enabled": True,
    })
    return {"status": "ok", "bot_enabled": True, "session_id": session_id}


# ── End a conversation: farewell from agent → bot thanks → CSAT survey ───────
@app.post("/admin/{store_id}/conversations/{session_id}/end")
async def store_end_conversation(
    store_id: str,
    session_id: str,
    req: EndConversationRequest,
    request: Request,
):
    """
    Close out a conversation with the same flow large brands use (e.g. Kiabi):
      1. The agent's farewell line is posted as an admin message (with the
         employee's name when an employee token was used).
      2. The virtual assistant follows up with a thank-you line.
      3. A CSAT survey ("How satisfied are you with the agent?") is posted as
         an assistant message tagged so widget + admin UI render rating
         buttons inline instead of a normal bubble.
      4. The bot is re-enabled so any later message from the customer goes
         back through the assistant.
    """
    await cs.restore_to_memory(session_id)
    conv = cs.all_conversations().get(session_id)
    if not conv:
        raise HTTPException(404, "المحادثة غير موجودة")

    token   = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    emp     = _auth.token_employee(token)
    agent_name = (emp or {}).get("name", "") if emp else ""

    store_info = sm.get_store_info(store_id) or {}
    store_name = store_info.get("store_name", "فريق الدعم")
    cfg        = sm.get_ai_config(store_id) or {}
    bot_name   = cfg.get("bot_name") or f"مساعد {store_name}"

    # 1. Agent farewell
    farewell_default = (
        "شكراً لتواصلكم معنا 🌷\n"
        "إذا كان لديكم أي استفسار آخر لا تترددوا بالتواصل معنا.\n"
        "نتمنى لكم يوماً سعيداً."
    )
    farewell = (req.farewell or "").strip() or farewell_default
    await cs.add_message(session_id, "admin", farewell, store_id)
    # Stamp the employee name on the message we just appended so the UI
    # can display "Shurog" or whoever ended the chat.
    if agent_name and conv.get("messages"):
        conv["messages"][-1]["employee_name"] = agent_name
        if emp:
            conv["messages"][-1]["employee_id"] = emp.get("id")
        # Also tag the pending-for-widget entry that add_message just queued
        if conv.get("pending_for_widget"):
            conv["pending_for_widget"][-1]["employee_name"] = agent_name

    # 2. Bot thank-you handoff
    thanks_line = f"شكراً لتواصلكم مع {store_name} — {bot_name} هنا إذا احتجتم أي مساعدة لاحقاً."
    await cs.add_message(session_id, "assistant", thanks_line, store_id)
    # add_message only queues admin role for the widget — manually queue this
    # bot follow-up so the widget polls it and renders it immediately.
    conv["pending_for_widget"].append({
        "role":    "bot",
        "content": thanks_line,
        "ts":      conv["messages"][-1]["ts"],
    })

    # 3. CSAT survey as an assistant message tagged so widget/admin UI render
    #    rating buttons inline. The agent_name is included so the question is
    #    "How satisfied with <agent_name>?" — like the Kiabi flow.
    if not req.skip_csat:
        target = agent_name or "ممثل خدمة العملاء"
        question = f"كيف كانت تجربتك مع {target}؟"
        await cs.add_message(session_id, "assistant", question, store_id)
        csat_meta = {
            "kind": "csat",
            "target_agent_id":   (emp or {}).get("id") if emp else None,
            "target_agent_name": agent_name,
            "question":          question,
            "options": [
                {"value": 5, "label": "راضٍ تماماً"},
                {"value": 4, "label": "راضٍ"},
                {"value": 3, "label": "محايد"},
                {"value": 2, "label": "غير راضٍ"},
                {"value": 1, "label": "غير راضٍ تماماً"},
            ],
        }
        # Add meta to the persisted message
        conv["messages"][-1]["meta"] = csat_meta
        # And queue for widget polling
        conv["pending_for_widget"].append({
            "role":    "bot",
            "content": question,
            "ts":      conv["messages"][-1]["ts"],
            "meta":    csat_meta,
        })

    # 4. Hand back to the bot so the next customer message is auto-handled.
    cs.set_session_bot(session_id, True)
    conv["ended_at"] = _dt.datetime.utcnow().isoformat()
    if agent_name:
        conv["ended_by"] = {"id": (emp or {}).get("id"), "name": agent_name}
    cs.mark_dirty(session_id)
    await cs.flush(session_id)

    # 5. WhatsApp delivery — for wa: sessions push the same three messages
    #    over the Cloud API so the customer actually receives them. The
    #    admin dashboard already has them in the transcript (steps 1-3);
    #    this just bridges them to the real chat.
    if session_id.startswith("wa:"):
        import whatsapp as wa
        cfg = sm.get_ai_config(store_id) or {}
        wa_token    = (cfg.get("whatsapp_token") or "").strip()
        wa_phone_id = (cfg.get("whatsapp_phone_id") or "").strip()
        to          = session_id[3:]
        if wa_token and wa_phone_id and to:
            async def _deliver_to_whatsapp():
                try:
                    await wa.send_text(wa_token, wa_phone_id, to, farewell)
                    await wa.send_text(wa_token, wa_phone_id, to, thanks_line)
                    if not req.skip_csat:
                        target = agent_name or "ممثل خدمة العملاء"
                        question_wa = f"كيف كانت تجربتك مع {target}؟"
                        # Try the interactive list first (renders as nice
                        # buttons in WhatsApp). Fall back to numbered text
                        # so the question still arrives even if the list
                        # API call is blocked by Meta for this phone.
                        ok = await wa.send_list(
                            wa_token, wa_phone_id, to,
                            body=question_wa,
                            button="اختر تقييماً",
                            header="استطلاع رضا",
                            rows=[
                                {"id": "csat:5", "title": "راضٍ تماماً"},
                                {"id": "csat:4", "title": "راضٍ"},
                                {"id": "csat:3", "title": "محايد"},
                                {"id": "csat:2", "title": "غير راضٍ"},
                                {"id": "csat:1", "title": "غير راضٍ تماماً"},
                            ],
                        )
                        if not ok:
                            fallback = (
                                f"{question_wa}\n\n"
                                "ردّ بالرقم المناسب:\n"
                                "1️⃣ غير راضٍ تماماً\n"
                                "2️⃣ غير راضٍ\n"
                                "3️⃣ محايد\n"
                                "4️⃣ راضٍ\n"
                                "5️⃣ راضٍ تماماً"
                            )
                            await wa.send_text(wa_token, wa_phone_id, to, fallback)
                except Exception as exc:
                    print(f"[end-conversation] WhatsApp delivery error: {exc}")
            asyncio.create_task(_deliver_to_whatsapp())

    return {"status": "ok", "session_id": session_id, "messages": conv.get("messages", [])[-3:]}


# ── Employees CRUD ──────────────────────────────────────────────────────────
def _require_store_owner(request: Request, store_id: str):
    """Reject employee-token callers so only the store owner (or super) can
    manage employees. The middleware already verified the token belongs to
    this store — here we just block employees from managing themselves."""
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token) or {}
    if claims.get("su"):
        return
    if "eid" in claims:
        raise HTTPException(403, "هذا الإجراء مخصّص لمالك المتجر")


def _require_manager_or_owner(request: Request):
    """Allow super, store owner (no eid), or manager-role employees.
    Rejects agent-role employees so they can't reach settings / training /
    AI brain / analytics endpoints by hitting the API directly.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token) or {}
    if claims.get("su"):
        return
    if "eid" not in claims:
        return  # store owner
    role = claims.get("er", "agent")
    if role != "manager":
        raise HTTPException(403, "صلاحيتك لا تسمح بهذا الإجراء")


@app.get("/admin/{store_id}/employees")
async def list_store_employees(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    rows = await db.list_employees(store_id)
    return {"employees": rows, "count": len(rows)}


@app.get("/admin/{store_id}/employees/ratings")
async def store_employees_ratings(store_id: str):
    """
    Per-employee CSAT aggregation. Walks every conversation in the store,
    groups ratings by `rating_employee_id` (stamped at /chat/rate time
    from the CSAT message meta), and returns avg + count + the histogram
    + last 10 detailed ratings for each employee.

    Ratings on conversations that don't carry an employee id (legacy
    rating bar, or rated before the CSAT flow) land in `unattributed`.
    """
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    employees = await db.list_employees(store_id)
    stats: dict = {}
    for e in employees:
        stats[int(e["id"])] = {
            "employee_id":  int(e["id"]),
            "name":         e["name"],
            "email":        e["email"],
            "role":         e.get("role", "agent"),
            "active":       bool(e["active"]),
            "count":        0,
            "_sum":         0,
            "avg":          0.0,
            "distribution": [0, 0, 0, 0, 0],  # buckets for 1..5
            "recent":       [],
        }

    unattributed = {
        "count": 0, "_sum": 0, "avg": 0.0,
        "distribution": [0, 0, 0, 0, 0],
        "recent": [],
    }

    convs = await cs.get_all_conversations_for_store(store_id)
    for sid, conv in convs.items():
        rating = conv.get("rating")
        try:
            r = int(rating) if rating is not None else 0
        except (TypeError, ValueError):
            r = 0
        if not (1 <= r <= 5):
            continue

        eid = conv.get("rating_employee_id")
        cust = conv.get("customer_info") or {}
        entry = {
            "session_id":    sid,
            "rating":        r,
            "comment":       conv.get("rating_comment", "") or "",
            "rated_at":      conv.get("rated_at", conv.get("last_activity", "")),
            "customer_name": cust.get("name", ""),
        }

        bucket = stats.get(int(eid)) if eid else None
        if bucket:
            bucket["count"]               += 1
            bucket["_sum"]                += r
            bucket["distribution"][r - 1] += 1
            bucket["recent"].append(entry)
        else:
            unattributed["count"]               += 1
            unattributed["_sum"]                += r
            unattributed["distribution"][r - 1] += 1
            unattributed["recent"].append(entry)

    for s in stats.values():
        s["avg"] = round(s["_sum"] / s["count"], 2) if s["count"] else 0.0
        s["recent"].sort(key=lambda x: x["rated_at"], reverse=True)
        s["recent"] = s["recent"][:10]
        del s["_sum"]

    unattributed["avg"] = (
        round(unattributed["_sum"] / unattributed["count"], 2)
        if unattributed["count"] else 0.0
    )
    unattributed["recent"].sort(key=lambda x: x["rated_at"], reverse=True)
    unattributed["recent"] = unattributed["recent"][:10]
    del unattributed["_sum"]

    return {
        "employees":    sorted(stats.values(), key=lambda x: x["count"], reverse=True),
        "unattributed": unattributed,
    }


@app.post("/admin/{store_id}/employees")
async def create_store_employee(
    store_id: str,
    req: EmployeeCreateRequest,
    request: Request,
):
    _require_store_owner(request, store_id)
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    name  = (req.name or "").strip()
    email = (req.email or "").strip().lower()
    if not name or not email or not req.password:
        raise HTTPException(400, "الاسم والبريد وكلمة المرور مطلوبة")
    if len(req.password) < 6:
        raise HTTPException(400, "كلمة المرور قصيرة جداً (6 أحرف على الأقل)")
    existing = await db.get_employee_by_email(store_id, email)
    if existing:
        raise HTTPException(409, "هذا البريد مسجّل لموظف آخر بالفعل")

    emp_id = await db.add_employee(
        store_id, name, email, _auth.hash_password(req.password),
        role=(req.role or "agent"),
        active=bool(req.active if req.active is not None else True),
    )
    if not emp_id:
        raise HTTPException(500, "تعذّر حفظ الموظف — تحقق من اتصال قاعدة البيانات")
    return {"id": emp_id, "name": name, "email": email, "role": req.role or "agent"}


@app.patch("/admin/{store_id}/employees/{employee_id}")
async def update_store_employee(
    store_id: str,
    employee_id: int,
    req: EmployeeUpdateRequest,
    request: Request,
):
    _require_store_owner(request, store_id)
    emp = await db.get_employee(employee_id)
    if not emp or emp["store_id"] != store_id:
        raise HTTPException(404, "الموظف غير موجود")

    new_password_hash = None
    if req.password:
        if len(req.password) < 6:
            raise HTTPException(400, "كلمة المرور قصيرة جداً (6 أحرف على الأقل)")
        new_password_hash = _auth.hash_password(req.password)

    new_email = req.email.strip().lower() if req.email else None
    if new_email and new_email != emp["email"]:
        collision = await db.get_employee_by_email(store_id, new_email)
        if collision and collision["id"] != employee_id:
            raise HTTPException(409, "هذا البريد مسجّل لموظف آخر")

    ok = await db.update_employee(
        employee_id,
        name=(req.name.strip() if req.name else None),
        email=new_email,
        password_hash=new_password_hash,
        role=req.role,
        active=req.active,
    )
    if not ok:
        raise HTTPException(500, "تعذّر تحديث بيانات الموظف")
    return {"status": "ok"}


@app.delete("/admin/{store_id}/employees/{employee_id}")
async def delete_store_employee(store_id: str, employee_id: int, request: Request):
    _require_store_owner(request, store_id)
    emp = await db.get_employee(employee_id)
    if not emp or emp["store_id"] != store_id:
        raise HTTPException(404, "الموظف غير موجود")
    ok = await db.delete_employee(employee_id)
    if not ok:
        raise HTTPException(500, "تعذّر حذف الموظف")
    return {"status": "ok"}


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
#
# The previous version kept a per-store collections.deque(maxlen=500) cache
# of abandoned carts in memory. That cache is gone in Phase 1 — read direct
# from the abandoned_carts table. Reason: a multi-instance deploy meant
# instance A's deque was stale to instance B, so admins saw different lists
# depending on which pod served the request.


# _log_event + _verify_signature + all _handle_* + _process_salla_event +
# /webhook/salla + /admin/{store_id}/webhooks/log + /webhook/salla/debug
# + /whatsapp/webhook + /whatsapp/debug + _handle_whatsapp_message +
# _parse_csat_reply ALL live in routers/webhooks.py now.



    return {"store_id": store_id, "count": len(events), "events": events}


# ── Abandoned carts ────────────────────────────────────────────────────────────

@app.get("/admin/{store_id}/abandoned-carts")
async def store_abandoned_carts(store_id: str, source: str = "cache"):
    """
    Return abandoned carts for a store.

    ?source=cache  (default) — abandoned_carts table (populated from webhooks).
    ?source=api    — live fetch from Salla GET /carts/abandoned (requires carts.read scope).

    Note: the legacy ?source=cache name is kept for frontend backward compat,
    but it now reads from PostgreSQL — there is no in-memory cache anymore.
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

    carts = await db.load_abandoned_carts(store_id) if db.available() else []
    return {"source": "db", "carts": carts, "count": len(carts)}


@app.post("/admin/{store_id}/abandoned-carts/{cart_id}/recover")
async def mark_cart_recovered(store_id: str, cart_id: str):
    """Mark an abandoned cart notification as handled / recovered."""
    await db.mark_cart_recovered(store_id, cart_id)
    return {"status": "ok", "cart_id": cart_id, "recovered": True}


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
async def chat(req: ChatRequest, request: Request):
    if not req.message.strip():
        raise HTTPException(400, "الرسالة فارغة")

    # Hard cap on message size — prevents a single request from blowing the
    # LLM context window or being used as a JSON-payload DoS vector.
    if len(req.message) > 4000:
        raise HTTPException(413, "الرسالة طويلة جداً. اختصرها وحاول مجدداً.")

    store_id   = req.store_id or "default"

    # Sanitize store_id — if Salla's template wasn't resolved server-side
    # (e.g. widget tested outside Salla Snippets), "{{ merchant.id }}" is
    # passed literally.  Fall back to "default" to avoid polluting the registry.
    if "{{" in store_id or "}}" in store_id:
        store_id = "default"

    # ── Rate limit (public endpoint — protects LLM spend) ─────────────────
    ip = request.client.host if request.client else "unknown"
    rl_session_key = (req.session_id or "no-session")[:64]
    tripped = await _chat_rate_limited(store_id, rl_session_key, ip)
    if tripped:
        print(f"[chat] ⛔ rate-limited axis={tripped} store={store_id!r} sid={rl_session_key!r} ip={ip}")
        raise HTTPException(
            429,
            "عدد رسائل كبير في وقت قصير. انتظر دقيقة وحاول مجدداً.",
        )

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

    # When the widget reports the placeholder "default" store_id (i.e. it was
    # embedded outside Salla Snippets so the template wasn't resolved), we
    # still allow the env-var fallback so dev / direct embeds work.
    if agent is None and store_id == "default":
        env_token = os.getenv("SALLA_ACCESS_TOKEN", "")
        if env_token:
            if not sm.is_registered("default"):
                sm.register_store(
                    "default", env_token,
                    os.getenv("SALLA_REFRESH_TOKEN", ""),
                    {"name": "المتجر الافتراضي"},
                )
            agent = sm.get_agent("default")

    # A *specific* store_id that isn't registered is NOT silently rerouted
    # anymore — previously we fell back to the first registered store, which
    # leaked one merchant's customer chats into another merchant's dashboard.
    # Now we refuse with a setup-required reply so the merchant sees they need
    # to install / reinstall the Salla app.
    if agent is None:
        if requested_store_id != "default":
            print(
                f"[chat] ⛔ ORPHAN STORE REFUSED: widget requested {requested_store_id!r} "
                f"(not registered). Refusing to merge into another store. "
                f"Fix: install the app on {requested_store_id!r}, or call "
                f"/admin/stores/register if you have valid tokens."
            )
            err_reply = (
                "عذراً، هذا المتجر لم يُربط بعد بنظام البوت. "
                "يرجى تثبيت التطبيق من سوق سلة أو التواصل مع الدعم."
            )
            # Do NOT persist this message under a misleading store_id; use the
            # requested id so a future registration picks up the right thread.
            await cs.add_message(session_id, "assistant", err_reply, requested_store_id)
            return ChatResponse(
                reply=err_reply,
                session_id=session_id,
                bot_enabled=True,   # error ≠ admin takeover
            )

        # default store + no env token + no registered stores → still respond
        err_reply = (
            "عذراً، المتجر غير مُعدّ بعد. "
            "يرجى ربط المتجر من لوحة التحكم أو التواصل مع الدعم."
        )
        await cs.add_message(session_id, "assistant", err_reply, store_id)
        return ChatResponse(
            reply=err_reply,
            session_id=session_id,
            bot_enabled=True,
        )

    # ── Daily token-budget circuit breaker (LLM cost protection) ──────────
    # Checked AFTER the orphan-store check so an unregistered store gets a
    # specific "install the app" message instead of a generic over-budget
    # one. Fails open when DB is down (see _budget_exhausted).
    exhausted, used_today, budget = await _budget_exhausted(store_id)
    if exhausted:
        print(
            f"[chat] 🛑 LLM budget exhausted store={store_id!r} "
            f"used={used_today} budget={budget} — refusing"
        )
        err_reply = (
            "عذراً، النظام في صيانة مؤقتة لهذا اليوم. "
            "يرجى المحاولة لاحقاً أو التواصل مع فريق الدعم."
        )
        # Don't persist as a regular assistant message — it would skew the
        # transcript. Just respond. The realtime publish stays out too;
        # admin sees the spike in the LLM-usage dashboard instead.
        return ChatResponse(
            reply=err_reply,
            session_id=session_id,
            bot_enabled=True,
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

    # Record this turn's token usage into the daily budget counter. UPSERT
    # is single-statement; we don't await before returning to the user — but
    # we do await here because pushing it into a background task would race
    # with the next request and let a burst slip past the limit further.
    _usage = getattr(agent, "last_usage", None) or {}
    _ti, _to = int(_usage.get("in", 0)), int(_usage.get("out", 0))
    if _ti or _to:
        await db.llm_usage_record(store_id, _ti, _to)

    # Pick up any rich UI component set by the agent tools this turn
    component  = cs.pop_last_component(session_id)
    cart_count = len(cs.get_cart(session_id))

    # ── Fire new-conversation notification (first message only) ──────────────
    conv_msgs = cs.all_conversations().get(session_id, {}).get("messages", [])
    if len(conv_msgs) == 1:  # exactly 1 message = brand new session
        conv_data = cs.all_conversations().get(session_id, {})
        cust_name = conv_data.get("customer_name") or ""
        asyncio.create_task(_notif.notify(store_id, "new_conversation", {
            "customer_name": cust_name,
            "session_id":    session_id,
            "first_message": req.message[:200],
        }))
        # Realtime: tell every admin watching this store that a brand-new
        # conversation just opened. Their inbox list refreshes without a
        # poll. add_message already published 'new_message' so this is the
        # ONE extra event marking the session-start moment.
        await realtime.publish(f"store:{store_id}", "new_conversation", {
            "session_id":    session_id,
            "customer_name": cust_name,
            "first_message": req.message[:200],
        })

    return ChatResponse(
        reply      = reply,
        session_id = session_id,
        bot_enabled= True,
        components = [component] if component else None,
        cart_count = cart_count,
    )


@app.post("/chat/rate")
async def chat_rate(req: RateRequest):
    """Customer rates a conversation 1-5 stars.

    If the rating answers a CSAT survey we posted at end-of-chat, stamp the
    target employee's id/name onto the conversation so the per-agent
    ratings dashboard can attribute it. Scans the last CSAT message in the
    transcript (added by /end) and lifts target_agent_id from its meta.
    """
    if not 1 <= req.rating <= 5:
        raise HTTPException(400, "التقييم يجب أن يكون بين 1 و 5")
    await cs.restore_to_memory(req.session_id)
    await cs.set_rating(req.session_id, req.rating, req.comment)

    # Realtime push so the admin dashboard's CSAT widget updates without
    # waiting for the next page refresh. Comment intentionally omitted from
    # the NOTIFY payload — admin can see it in the detail view.
    await realtime.publish(f"store:{req.store_id}", "rating", {
        "session_id": req.session_id,
        "rating":     req.rating,
    })

    conv = cs.all_conversations().get(req.session_id)
    if conv:
        # Walk newest → oldest for the most-recent CSAT prompt
        for m in reversed(conv.get("messages", [])):
            meta = m.get("meta") if isinstance(m, dict) else None
            if isinstance(meta, dict) and meta.get("kind") == "csat":
                conv["rating_employee_id"]   = meta.get("target_agent_id")
                conv["rating_employee_name"] = meta.get("target_agent_name", "")
                conv["rated_at"]             = _dt.datetime.utcnow().isoformat()
                cs.mark_dirty(req.session_id)
                await cs.flush(req.session_id)
                break

    # ── Fire low-rating notification ─────────────────────────────────────────
    if req.rating <= 2 and conv:
        cust_name = conv.get("customer_name") or conv.get("customer", {}).get("name", "")
        asyncio.create_task(_notif.notify(req.store_id, "low_rating", {
            "customer_name": cust_name,
            "rating":        req.rating,
            "comment":       req.comment or "",
        }))

    return {"status": "ok", "message": "شكراً لتقييمك! 😊"}


@app.get("/chat/poll")
async def chat_poll(session_id: str):
    """
    LEGACY polling endpoint. The widget moved to SSE in Phase 3
    (/chat/stream). This stays for one release cycle as a fallback for
    clients that can't open EventSource (corporate proxies that strip
    text/event-stream, very old browsers).
    """
    await cs.restore_to_memory(session_id)
    pending = cs.pop_pending_for_widget(session_id)
    bot_on  = cs.is_bot_enabled(session_id)
    return {"messages": pending, "bot_enabled": bot_on}


# ─────────────────────────────────────────────────────────────────────────
# Server-Sent Events — replaces polling for both widget and admin
# ─────────────────────────────────────────────────────────────────────────
#
# Why SSE and not WebSocket:
#   • Half-duplex (server → client) is enough for chat updates. The
#     client → server side stays HTTP POST.
#   • Works through every corporate proxy / CDN that supports HTTP/1.1
#     chunked transfer. WebSockets get blocked more often.
#   • Auto-reconnect with Last-Event-ID is built into EventSource — we
#     don't have to write reconnection logic on the client.
#
# Auth: EventSource (the W3C API the widget uses) can NOT send custom
# headers. For the admin stream we need Bearer auth, so the admin SPA:
#   1. POST /admin/{store_id}/stream/ticket (with Authorization header)
#   2. → {"ticket": "<short-lived-id>"}
#   3. GET /admin/{store_id}/stream?ticket=...
# Tickets are single-use, 5-minute TTL, in-memory (per-instance fine
# because each instance issues its own and the user's SSE will hit the
# same instance immediately).
#
# The widget /chat/stream needs no auth — like /chat itself — and is
# scoped by the (unguessable) session_id UUID.

import secrets as _secrets
import time as _stream_time

# ticket → (store_id, expires_at_unix). 5-min TTL; lazy cleanup on read.
_STREAM_TICKETS: dict[str, tuple[str, float]] = {}
_TICKET_TTL_SECONDS = 300


def _issue_stream_ticket(store_id: str) -> str:
    """Generate a single-use ticket bound to a store_id, with TTL."""
    # GC expired tickets opportunistically — keeps the dict small.
    now = _stream_time.time()
    expired = [t for t, (_, exp) in _STREAM_TICKETS.items() if exp < now]
    for t in expired:
        _STREAM_TICKETS.pop(t, None)

    tok = _secrets.token_urlsafe(24)
    _STREAM_TICKETS[tok] = (store_id, now + _TICKET_TTL_SECONDS)
    return tok


def _consume_stream_ticket(ticket: str, store_id: str) -> bool:
    """Validate a ticket and remove it. Single-use."""
    entry = _STREAM_TICKETS.pop(ticket, None)
    if entry is None:
        return False
    bound_store, exp = entry
    if exp < _stream_time.time():
        return False
    return bound_store == store_id


@app.post("/admin/{store_id}/stream/ticket")
async def admin_stream_ticket(store_id: str, request: Request):
    """
    Exchange a Bearer token (in the Authorization header) for a single-use
    stream ticket. The admin SPA calls this right before opening the
    EventSource. The auth middleware has already validated the bearer for
    this store_id by the time we get here.
    """
    # auth middleware already ran for /admin/{store_id}/* paths — but
    # this specific route uses 'stream' which isn't in the regex (it
    # only matches conversations|bot|sync|... etc). Validate explicitly.
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims:
        raise HTTPException(401, "يرجى تسجيل الدخول")
    if not claims.get("su") and claims.get("s") != store_id:
        raise HTTPException(403, "غير مصرح لك بالوصول")
    return {"ticket": _issue_stream_ticket(store_id), "ttl_seconds": _TICKET_TTL_SECONDS}


def _format_sse(event_type: str, data: dict) -> str:
    """Standard SSE wire format: `event: <type>\\ndata: <json>\\n\\n`."""
    import json as _json
    payload = _json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


@app.get("/admin/{store_id}/stream")
async def admin_stream(store_id: str, ticket: str = "", request: Request = None):
    """
    Server-Sent Events stream for the admin dashboard. Pushes events as
    they happen across this store:
      • new_message     — customer sent something (or admin replied elsewhere)
      • new_conversation— first message on a brand-new session
      • rating          — customer submitted a CSAT
      • bot_toggle      — global / per-store / per-session bot state changed
    """
    if not ticket or not _consume_stream_ticket(ticket, store_id):
        raise HTTPException(401, "Invalid or expired stream ticket")
    if not realtime.available():
        raise HTTPException(503, "Realtime channel unavailable — DB listener down")

    async def event_gen():
        # Initial hello so the client knows the connection is alive.
        yield _format_sse("connected", {"store_id": store_id})
        # Heartbeat task — pushes a comment every 25s to keep proxies
        # (Cloudflare, nginx, Railway) from closing idle connections.
        last_beat = _stream_time.time()
        async for event in realtime.subscribe(f"store:{store_id}"):
            if event["type"] == "_shutdown":
                yield _format_sse("shutdown", {"reason": "server restart"})
                return
            yield _format_sse(event["type"], event["data"])
            # Opportunistic heartbeat inside the event loop.
            now = _stream_time.time()
            if now - last_beat > 25:
                yield ": heartbeat\n\n"
                last_beat = now

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache, no-transform",
            "X-Accel-Buffering": "no",   # nginx hint: don't buffer
            "Connection":        "keep-alive",
        },
    )


@app.get("/chat/stream")
async def chat_stream(session_id: str):
    """
    Server-Sent Events stream for the widget. Pushes events for this
    specific session:
      • admin_message — admin (or employee) replied
      • bot_toggle    — bot was turned off/on for this session

    Authenticated by possession of session_id (unguessable UUID) — same
    contract as /chat itself.
    """
    if not session_id or len(session_id) > 200:
        raise HTTPException(400, "session_id required")
    if not realtime.available():
        raise HTTPException(503, "Realtime channel unavailable")

    async def event_gen():
        yield _format_sse("connected", {"session_id": session_id})
        # On reconnect, flush any messages that landed while the client
        # was disconnected. This is the bridge between Phase 1's
        # pending_for_widget queue and the new SSE delivery.
        try:
            await cs.restore_to_memory(session_id)
            pending = cs.pop_pending_for_widget(session_id)
            for msg in pending:
                yield _format_sse("admin_message", msg)
        except Exception as exc:
            print(f"[stream] flush-on-connect for {session_id} failed: {exc}")

        last_beat = _stream_time.time()
        async for event in realtime.subscribe(f"session:{session_id}"):
            if event["type"] == "_shutdown":
                yield _format_sse("shutdown", {"reason": "server restart"})
                return
            yield _format_sse(event["type"], event["data"])
            now = _stream_time.time()
            if now - last_beat > 25:
                yield ": heartbeat\n\n"
                last_beat = now

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


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
        # Map to the widget's three visual roles. "admin" stays so the widget
        # can show the employee caption ("Shurog") and the right bubble style;
        # "assistant" becomes "bot".
        if role == "user":
            ui_role = "user"
        elif role == "admin":
            ui_role = "admin"
        else:
            ui_role = "bot"
        entry = {
            "role":    ui_role,
            "content": m.get("content", ""),
            "ts":      m.get("ts", ""),
        }
        if m.get("employee_name"):
            entry["employee_name"] = m["employee_name"]
        if isinstance(m.get("meta"), dict):
            entry["meta"] = m["meta"]
        out.append(entry)
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
