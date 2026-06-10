"""
Public chat routes: /chat, /chat/rate, /chat/poll, /chat/history.
Also handles Salla OAuth callback (/auth/salla, /auth/callback).
"""
import os
import asyncio
import hmac
import secrets
import uuid
import datetime as _dt

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse

import auth as _auth
import database as db
import store_manager as sm
import conversation_store as cs
import realtime
import notifications as _notif
from models import ChatRequest, ChatResponse, RateRequest
from salla_oauth import get_auth_url, exchange_code, get_user_info, save_tokens
from routers.deps import chat_rate_limited, budget_exhausted, daily_token_budget
import log as _logmod

log = _logmod.get_logger("backend.chat")

router = APIRouter()

# Lazy-bound by main.py after lifecycle is wired
_sync_task = None

def set_sync_task(fn):
    global _sync_task
    _sync_task = fn


# ── Salla OAuth ───────────────────────────────────────────────────────────────
#
# Custom-mode OAuth flow (the Easy-mode path goes via the `app.store.authorize`
# webhook in routers/webhooks.py instead). Two hardening invariants:
#
#  1. CSRF state: /auth/salla generates a 256-bit random token, drops it in a
#     short-lived HttpOnly cookie scoped to /auth, and includes it as the
#     `state` query param. /auth/callback rejects the request unless the
#     query state matches the cookie via timing-safe compare. Without this
#     an attacker could trick a logged-in merchant into linking the
#     attacker's store to the victim's session.
#
#  2. Real merchant_id: we DON'T trust the redirect URI alone to identify
#     which store just authorised — we call GET /oauth2/user/info with the
#     fresh access token and use the returned store.id as the canonical
#     store_id. Previously we hardcoded "default", which overwrote every
#     other tenant's slot on each new install.

_OAUTH_STATE_COOKIE = "salla_oauth_state"
_OAUTH_STATE_MAX_AGE = 600   # 10 min — install flow finishes much faster


def _cookie_secure() -> bool:
    """HTTPS cookies in prod, plain in dev. Detected from BASE_URL scheme."""
    return os.getenv("BASE_URL", "").startswith("https://")


@router.get("/auth/salla")
async def salla_auth():
    base         = os.getenv("BASE_URL", "http://localhost:8000")
    redirect_uri = f"{base}/auth/callback"
    state        = secrets.token_urlsafe(32)

    resp = RedirectResponse(get_auth_url(redirect_uri, state=state))
    resp.set_cookie(
        key       = _OAUTH_STATE_COOKIE,
        value     = state,
        max_age   = _OAUTH_STATE_MAX_AGE,
        httponly  = True,
        secure    = _cookie_secure(),
        samesite  = "lax",   # required: OAuth redirect is a top-level GET
        path      = "/auth",
    )
    return resp


@router.get("/auth/callback")
async def salla_callback(request: Request, code: str = "", error: str = "",
                         state: str = ""):
    # ── 1. CSRF state check ──────────────────────────────────────────────
    cookie_state = request.cookies.get(_OAUTH_STATE_COOKIE, "")
    if not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
        log.warning("oauth_state_mismatch", extra={
            "has_query_state":  bool(state),
            "has_cookie_state": bool(cookie_state),
        })
        return HTMLResponse(
            "<h2 style='color:red;font-family:Arial'>فشل التحقق من جلسة التفويض. "
            "أعد بدء التثبيت من البداية.</h2>",
            status_code=400,
        )

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

        # ── 2. Resolve the REAL merchant id ──────────────────────────────
        # Without this every install would clobber the "default" slot.
        store_id   = ""
        store_name = ""
        try:
            info = await get_user_info(access_token)
            data = info.get("data") or {}
            merchant_blob = data.get("store") or data.get("merchant") or {}
            sid = merchant_blob.get("id")
            if sid:
                store_id   = str(sid)
                store_name = merchant_blob.get("name", "") or ""
        except Exception as exc:
            log.error("oauth_user_info_failed", extra={"err": str(exc)[:200]})

        if not store_id:
            # We refuse to register an unidentified merchant rather than
            # silently overwriting the "default" slot like the old code.
            return HTMLResponse(
                "<h2 style='color:red;font-family:Arial'>تعذّر تحديد المتجر "
                "بعد التفويض. يرجى المحاولة مجدداً أو التواصل مع الدعم.</h2>",
                status_code=502,
            )

        sm.register_store(
            store_id      = store_id,
            access_token  = access_token,
            refresh_token = refresh_token,
            store_info    = {"store_name": store_name} if store_name else None,
        )
        if _sync_task:
            asyncio.create_task(_sync_task(store_id, access_token))

        resp = HTMLResponse(f"""
        <html><body style='font-family:Arial;text-align:center;padding:60px;direction:rtl'>
          <h2 style='color:#16a34a'>✅ تم ربط متجر "{store_name or store_id}" بنجاح!</h2>
          <p>يمكنك إغلاق هذه الصفحة والعودة لاستخدام الشات بوت.</p>
          <a href='/admin' style='color:#3b82f6'>← فتح لوحة التحكم</a>
        </body></html>
        """)
        # State cookie consumed — invalidate it so it can't be reused.
        resp.delete_cookie(_OAUTH_STATE_COOKIE, path="/auth")
        return resp
    except Exception as e:
        log.exception("oauth_callback_failed")
        # Never echo the raw exception back to the browser — could leak
        # httpx request internals (URL, headers).
        return HTMLResponse(
            "<h2 style='color:red;font-family:Arial'>حدث خطأ أثناء ربط المتجر. "
            "أعد المحاولة من جديد.</h2>",
            status_code=500,
        )


# ── Customer profile helper ───────────────────────────────────────────────────

async def _fetch_salla_customer(store_id: str, customer_id: str,
                                 fallback_name: str = "") -> dict:
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
        resp   = await client.get_customer(
            int(customer_id),
            fields=["orders_count", "orders_amount"],
        )
        c = resp.get("data") or {}
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
        "salla_customer_id": str(c.get("id") or customer_id),
    }
    oc = c.get("orders_count")
    if oc is not None:
        data["orders_count"] = oc
    oa = c.get("orders_amount")
    if isinstance(oa, dict) and oa.get("amount") is not None:
        data["orders_amount"] = f"{oa.get('amount')} {oa.get('currency', 'SAR')}"
    return data


# ── Chat ──────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    if not req.message.strip():
        raise HTTPException(400, "الرسالة فارغة")
    if len(req.message) > 4000:
        raise HTTPException(413, "الرسالة طويلة جداً. اختصرها وحاول مجدداً.")

    store_id = req.store_id or "default"
    if "{{" in store_id or "}}" in store_id:
        store_id = "default"

    ip = request.client.host if request.client else "unknown"
    rl_session_key = (req.session_id or "no-session")[:64]
    tripped = await chat_rate_limited(store_id, rl_session_key, ip)
    if tripped:
        log.warning("chat_rate_limited", extra={
            "axis": tripped, "store_id": store_id,
            "sid": rl_session_key, "ip": ip,
        })
        raise HTTPException(429, "عدد رسائل كبير في وقت قصير. انتظر دقيقة وحاول مجدداً.")

    raw_cid = (req.customer_id or "").strip()
    if raw_cid in ("0", "null", "undefined") or "{{" in raw_cid:
        raw_cid = ""

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

    if raw_cid:
        conv_now = cs.all_conversations().get(session_id) or cs.get_or_create(session_id, store_id)
        if str(conv_now.get("salla_customer_id", "")) != raw_cid:
            customer_data = await _fetch_salla_customer(store_id, raw_cid, req.customer_name)
            await cs.link_customer(session_id, raw_cid, customer_data)
            await cs.flush(session_id)

    bot_on = cs.is_bot_enabled(session_id)

    if not bot_on:
        await cs.add_message(session_id, "user", req.message, store_id)
        return ChatResponse(
            reply="شكراً لرسالتك، سيتواصل معك أحد أعضاء فريق الدعم قريباً. 👨‍💼",
            session_id=session_id,
            bot_enabled=False,
        )

    agent = sm.get_agent(store_id)
    requested_store_id = store_id

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

    if agent is None:
        if requested_store_id != "default":
            print(f"[chat] ⛔ ORPHAN STORE REFUSED: widget requested {requested_store_id!r}")
            err_reply = (
                "عذراً، هذا المتجر لم يُربط بعد بنظام البوت. "
                "يرجى تثبيت التطبيق من سوق سلة أو التواصل مع الدعم."
            )
            await cs.add_message(session_id, "assistant", err_reply, requested_store_id)
            return ChatResponse(reply=err_reply, session_id=session_id, bot_enabled=True)

        err_reply = (
            "عذراً، المتجر غير مُعدّ بعد. "
            "يرجى ربط المتجر من لوحة التحكم أو التواصل مع الدعم."
        )
        await cs.add_message(session_id, "assistant", err_reply, store_id)
        return ChatResponse(reply=err_reply, session_id=session_id, bot_enabled=True)

    exhausted, used_today, budget = await budget_exhausted(store_id)
    if exhausted:
        log.warning("chat_budget_exhausted", extra={
            "store_id": store_id, "used_today": used_today, "budget": budget,
        })
        err_reply = (
            "عذراً، المساعد غير متاح مؤقتاً. "
            "يمكنك ترك رسالتك وسيقوم الفريق بالرد عليك قريباً."
        )
        return ChatResponse(reply=err_reply, session_id=session_id, bot_enabled=True)

    try:
        reply = await agent.chat(message=req.message, session_id=session_id)
    except Exception as e:
        err_msg  = str(e)
        err_type = type(e).__name__
        log.exception("chat_agent_error", extra={
            "store_id": store_id, "session_id": session_id,
            "err_type": err_type, "err_msg": err_msg[:300],
        })
        err_lower = err_msg.lower()
        if (
            "401" in err_lower or "authentication" in err_lower
            or ("invalid" in err_lower and "key" in err_lower)
            or "incorrect api key" in err_lower or "invalid_api_key" in err_lower
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
        return ChatResponse(reply=friendly, session_id=session_id, bot_enabled=True)

    _usage = getattr(agent, "last_usage", None) or {}
    _ti, _to = int(_usage.get("in", 0)), int(_usage.get("out", 0))
    if _ti or _to:
        _delta  = await db.llm_usage_record(store_id, _ti, _to)
        _budget = daily_token_budget(store_id)
        if _budget > 0:
            _before_pct = (_delta["before"] / _budget) * 100
            _after_pct  = (_delta["after"]  / _budget) * 100
            for _t in (80, 90, 100):
                if _before_pct < _t <= _after_pct:
                    log.warning("llm_budget_threshold", extra={
                        "store_id":     store_id,
                        "threshold":    _t,
                        "used_today":   _delta["after"],
                        "daily_budget": _budget,
                        "percent_used": round(_after_pct, 1),
                    })
                    try:
                        await _notif.notify(store_id, "llm_budget_warning", {
                            "threshold":    _t,
                            "used_today":   _delta["after"],
                            "daily_budget": _budget,
                            "percent_used": round(_after_pct, 1),
                        })
                    except Exception:
                        log.exception("llm_alert_notify_failed", extra={
                            "store_id": store_id, "threshold": _t,
                        })

    component  = await cs.pop_last_component(session_id)
    cart_count = len(cs.get_cart(session_id))

    conv_msgs = cs.all_conversations().get(session_id, {}).get("messages", [])
    if len(conv_msgs) == 1:
        conv_data = cs.all_conversations().get(session_id, {})
        cust_name = conv_data.get("customer_name") or ""
        asyncio.create_task(_notif.notify(store_id, "new_conversation", {
            "customer_name": cust_name,
            "session_id":    session_id,
            "first_message": req.message[:200],
        }))
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


# ── Rate ──────────────────────────────────────────────────────────────────────

@router.post("/chat/rate")
async def chat_rate(req: RateRequest):
    if not 1 <= req.rating <= 5:
        raise HTTPException(400, "التقييم يجب أن يكون بين 1 و 5")
    await cs.restore_to_memory(req.session_id)
    await cs.set_rating(req.session_id, req.rating, req.comment)

    await realtime.publish(f"store:{req.store_id}", "rating", {
        "session_id": req.session_id,
        "rating":     req.rating,
    })

    conv = cs.all_conversations().get(req.session_id)
    if conv:
        for m in reversed(conv.get("messages", [])):
            meta = m.get("meta") if isinstance(m, dict) else None
            if isinstance(meta, dict) and meta.get("kind") == "csat":
                conv["rating_employee_id"]   = meta.get("target_agent_id")
                conv["rating_employee_name"] = meta.get("target_agent_name", "")
                conv["rated_at"]             = _dt.datetime.utcnow().isoformat()
                cs.mark_dirty(req.session_id)
                await cs.flush(req.session_id)
                break

    if req.rating <= 2 and conv:
        cust_name = conv.get("customer_name") or conv.get("customer", {}).get("name", "")
        asyncio.create_task(_notif.notify(req.store_id, "low_rating", {
            "customer_name": cust_name,
            "rating":        req.rating,
            "comment":       req.comment or "",
        }))

    return {"status": "ok", "message": "شكراً لتقييمك! 😊"}


# ── Poll (legacy) ─────────────────────────────────────────────────────────────

@router.get("/chat/poll")
async def chat_poll(session_id: str):
    await cs.restore_to_memory(session_id)
    pending = await cs.pop_pending_for_widget(session_id)
    bot_on  = cs.is_bot_enabled(session_id)
    return {"messages": pending, "bot_enabled": bot_on}


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/chat/history")
async def chat_history(session_id: str):
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
