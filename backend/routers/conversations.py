"""
Per-store conversation routes: bot toggle, list, detail, reply, takeover,
handback, end-conversation (with CSAT flow).
"""
import asyncio
import datetime as _dt

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import database as db
import store_manager as sm
import conversation_store as cs
import realtime
from models import AddNoteRequest, AdminReplyRequest, BotToggleRequest, EndConversationRequest
from routers.deps import audit, super_viewing_other_store, _REASON_MIN_LENGTH, _REASON_MAX_LENGTH

router = APIRouter()


# ── Cross-tenant ownership guard (finding C-1) ─────────────────────────────────
async def _load_owned_conv(session_id: str, store_id: str, request: Request) -> dict | None:
    """
    Restore + fetch a conversation, enforcing tenant ownership.

    Conversations live in one global map keyed by session_id, and channel
    session ids (wa:/msgr:/ig:) are enumerable. Without this guard a store could
    read or mutate ANOTHER tenant's conversation by passing its session id to
    this store's own (authorised) route. We reject with 404 — never 403, so the
    response can't confirm the foreign session exists — when the conversation
    belongs to a different store.

    Returns the conv dict, or None when the session doesn't exist yet, so callers
    keep their existing miss behaviour (detail returns an empty shell; end raises
    404). Super admins viewing a foreign store pass through: their cross-store
    access is already gated by the support-access grant enforced in
    middleware.admin_auth_middleware.
    """
    await cs.restore_to_memory(session_id)
    conv = cs.all_conversations().get(session_id)
    if conv is not None:
        owner = conv.get("store_id")
        if owner and owner != store_id and not super_viewing_other_store(request, store_id):
            raise HTTPException(404, "المحادثة غير موجودة")
    return conv


# ── Bot toggle ────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/bot/status")
async def store_bot_status(store_id: str):
    return {"bot_globally_enabled": cs.get_store_bot(store_id)}


@router.post("/admin/{store_id}/bot/toggle")
async def store_bot_toggle(store_id: str, req: BotToggleRequest):
    await cs.set_store_bot(store_id, req.enabled)
    return {"bot_globally_enabled": cs.get_store_bot(store_id)}


# ── Conversation list ─────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/conversations")
async def store_conversations(
    store_id: str,
    limit:  int = 100,
    offset: int = 0,
):
    await cs.get_all_conversations_for_store(store_id)
    return await cs.summary_list(store_id, limit=limit, offset=offset)


@router.get("/admin/conversations-all")
async def all_conversations_superadmin(
    request: Request,
    limit:   int = 200,
    offset:  int = 0,
):
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    base = await cs.summary_list(store_id=None, limit=limit, offset=offset)
    registered_ids = {s["store_id"] for s in sm.list_stores()}
    for s in base.get("conversations", []):
        sid = s.get("store_id", "default")
        s["is_orphan"] = (sid == "default") or (sid not in registered_ids)
    return base


# ── Conversation detail ───────────────────────────────────────────────────────

@router.get("/admin/{store_id}/conversations/{session_id}")
async def store_conversation_detail(
    store_id: str,
    session_id: str,
    request: Request,
    reason: str = "",
):
    if super_viewing_other_store(request, store_id):
        reason_clean = (reason or "").strip()
        if len(reason_clean) < _REASON_MIN_LENGTH:
            raise HTTPException(403, "reason_required")
        await audit(
            request,
            "super_viewed_conversation",
            target_store=store_id,
            details={
                "session_id": session_id,
                "reason":     reason_clean[:_REASON_MAX_LENGTH],
            },
        )

    conv = await _load_owned_conv(session_id, store_id, request)
    if not conv:
        return {"session_id": session_id, "messages": [], "bot_enabled": True}
    await cs.mark_admin_read(session_id)
    return {
        "session_id":    session_id,
        "messages":      conv.get("messages", []),
        "bot_enabled":   cs.is_bot_enabled(session_id),
        "customer_info": conv.get("customer_info") or conv.get("customer", {}),
        "created_at":    conv.get("created_at", ""),
        "last_activity": conv.get("last_activity", ""),
        "rating":        conv.get("rating"),
        "store_id":      conv.get("store_id", store_id),
    }


# ── Admin reply ───────────────────────────────────────────────────────────────

@router.post("/admin/{store_id}/conversations/{session_id}/reply")
async def store_admin_reply(
    store_id: str,
    session_id: str,
    req: AdminReplyRequest,
    request: Request,
):
    if not req.message.strip():
        raise HTTPException(400, "الرسالة فارغة")
    # C-1: bind the session to this store before writing into it.
    await _load_owned_conv(session_id, store_id, request)
    text = req.message.strip()
    msg = await cs.add_message(session_id, "admin", text, store_id)

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

    await cs.mark_admin_read(session_id)
    # Support has engaged → resolve any "needs support" escalation so the
    # conversation leaves that queue.
    await cs.clear_escalation(session_id)
    import bot_learning
    asyncio.create_task(bot_learning.capture_admin_correction(store_id, session_id, text))

    if session_id.startswith("wa:"):
        cfg = sm.get_ai_config(store_id) or {}
        wa_token   = (cfg.get("whatsapp_token") or "").strip()
        wa_phone_id = (cfg.get("whatsapp_phone_id") or "").strip()
        if wa_token and wa_phone_id:
            await db.outbox_enqueue(
                kind     = "whatsapp_send",
                store_id = store_id,
                payload  = {
                    "phone_id": wa_phone_id,
                    "to":       session_id[3:],
                    "text":     text,
                },
            )
    elif session_id.startswith("tg:"):
        cfg = sm.get_ai_config(store_id) or {}
        tg_token = (cfg.get("telegram_bot_token") or "").strip()
        if tg_token:
            await db.outbox_enqueue(
                kind     = "telegram_send",
                store_id = store_id,
                payload  = {
                    "chat_id": session_id[3:],
                    "text":    text,
                },
            )

    return {"status": "sent", "message": msg}


# ── Internal note (@mentions) ─────────────────────────────────────────────────
# A note is staff-only: stored as role="note", never enqueued for the widget and
# never delivered to any channel. chat_history filters to user/assistant/admin so
# it can't leak to the customer. @mentions are resolved from the text against the
# store's employees so a mentioned teammate finds the conversation in "Mentions".

@router.post("/admin/{store_id}/conversations/{session_id}/note")
async def store_add_note(
    store_id: str,
    session_id: str,
    req: AddNoteRequest,
    request: Request,
):
    text = req.message.strip()
    if not text:
        raise HTTPException(400, "الملاحظة فارغة")
    await _load_owned_conv(session_id, store_id, request)  # C-1: bind to store

    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    emp = _auth.token_employee(token)
    author_name = (emp or {}).get("name", "") if emp else "المالك"
    author_id   = (emp or {}).get("id") if emp else None

    # Resolve @mentions: a teammate is mentioned when "@<their name>" appears in
    # the note. Longest names first so "@محمد علي" wins over "@محمد".
    employees = await db.list_employees(store_id)
    mentions: list[dict] = []
    for e in sorted(employees, key=lambda x: len(str(x.get("name") or "")), reverse=True):
        nm = (e.get("name") or "").strip()
        if nm and f"@{nm}" in text:
            mentions.append({"id": e.get("id"), "name": nm})

    msg = await cs.add_message(session_id, "note", text, store_id)
    conv = cs.all_conversations().get(session_id)
    if conv and conv.get("messages"):
        last = conv["messages"][-1]
        for target in (last, msg):
            target["employee_name"] = author_name
            target["employee_id"]   = author_id
            target["mentions"]      = mentions
        cs.mark_dirty(session_id)
        await cs.flush(session_id)

    return {"status": "ok", "message": msg, "mentions": mentions}


# ── Takeover / handback ───────────────────────────────────────────────────────

@router.post("/admin/{store_id}/conversations/{session_id}/takeover")
async def store_takeover(store_id: str, session_id: str, request: Request):
    await _load_owned_conv(session_id, store_id, request)  # C-1
    await cs.set_session_bot(session_id, False)
    await cs.mark_admin_read(session_id)
    await cs.clear_escalation(session_id)   # support stepped in → leave the queue
    await cs.flush(session_id)
    await realtime.publish(f"session:{session_id}", "bot_toggle", {
        "session_id":  session_id,
        "bot_enabled": False,
    })
    await realtime.publish(f"store:{store_id}", "bot_toggle", {
        "session_id":  session_id,
        "bot_enabled": False,
    })
    return {"status": "ok", "bot_enabled": False, "session_id": session_id}


@router.post("/admin/{store_id}/conversations/{session_id}/handback")
async def store_handback(store_id: str, session_id: str, request: Request):
    await _load_owned_conv(session_id, store_id, request)  # C-1
    await cs.set_session_bot(session_id, True)
    await cs.add_message(session_id, "admin",
                   "✅ تم إعادة توصيلك بالمساعد الذكي. كيف يمكنني مساعدتك؟",
                   store_id)
    await realtime.publish(f"session:{session_id}", "bot_toggle", {
        "session_id":  session_id,
        "bot_enabled": True,
    })
    await realtime.publish(f"store:{store_id}", "bot_toggle", {
        "session_id":  session_id,
        "bot_enabled": True,
    })
    return {"status": "ok", "bot_enabled": True, "session_id": session_id}


# ── End conversation ──────────────────────────────────────────────────────────

@router.post("/admin/{store_id}/conversations/{session_id}/end")
async def store_end_conversation(
    store_id: str,
    session_id: str,
    req: EndConversationRequest,
    request: Request,
):
    conv = await _load_owned_conv(session_id, store_id, request)  # C-1
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
    if agent_name and conv.get("messages"):
        conv["messages"][-1]["employee_name"] = agent_name
        if emp:
            conv["messages"][-1]["employee_id"] = emp.get("id")
        cs.enqueue_widget_message(session_id, {
            "role":          "admin",
            "content":       farewell,
            "ts":            conv["messages"][-1]["ts"],
            "employee_name": agent_name,
        })

    # 2. Bot thank-you handoff
    thanks_line = f"شكراً لتواصلكم مع {store_name} — {bot_name} هنا إذا احتجتم أي مساعدة لاحقاً."
    await cs.add_message(session_id, "assistant", thanks_line, store_id)
    cs.enqueue_widget_message(session_id, {
        "role":    "bot",
        "content": thanks_line,
        "ts":      conv["messages"][-1]["ts"],
    })

    # 3. CSAT survey
    if not req.skip_csat:
        target   = agent_name or "ممثل خدمة العملاء"
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
        conv["messages"][-1]["meta"] = csat_meta
        cs.enqueue_widget_message(session_id, {
            "role":    "bot",
            "content": question,
            "ts":      conv["messages"][-1]["ts"],
            "meta":    csat_meta,
        })

    # 4. Hand back to bot
    await cs.set_session_bot(session_id, True)
    conv["ended_at"] = _dt.datetime.utcnow().isoformat()
    if agent_name:
        conv["ended_by"] = {"id": (emp or {}).get("id"), "name": agent_name}
    cs.mark_dirty(session_id)
    await cs.flush(session_id)

    # 5. WhatsApp delivery for wa: sessions
    if session_id.startswith("wa:"):
        import whatsapp as wa
        wa_token    = (cfg.get("whatsapp_token") or "").strip()
        wa_phone_id = (cfg.get("whatsapp_phone_id") or "").strip()
        to          = session_id[3:]
        if wa_token and wa_phone_id and to:
            async def _deliver_to_whatsapp():
                try:
                    await wa.send_text(wa_token, wa_phone_id, to, farewell)
                    await wa.send_text(wa_token, wa_phone_id, to, thanks_line)
                    if not req.skip_csat:
                        target_wa = agent_name or "ممثل خدمة العملاء"
                        question_wa = f"كيف كانت تجربتك مع {target_wa}؟"
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
                                "1️⃣ غير راضٍ تماماً\n2️⃣ غير راضٍ\n3️⃣ محايد\n"
                                "4️⃣ راضٍ\n5️⃣ راضٍ تماماً"
                            )
                            await wa.send_text(wa_token, wa_phone_id, to, fallback)
                except Exception as exc:
                    print(f"[end-conversation] WhatsApp delivery error: {exc}")
            asyncio.create_task(_deliver_to_whatsapp())

    # 6. Telegram delivery for tg: sessions. Telegram has no interactive list, so
    # CSAT goes out as a numbered text prompt; the rating reply is captured by the
    # CSAT intercept in webhooks.handle_telegram_message (mirrors WhatsApp).
    elif session_id.startswith("tg:"):
        import telegram as tg
        tg_token = (cfg.get("telegram_bot_token") or "").strip()
        chat_id  = session_id[3:]
        if tg_token and chat_id:
            async def _deliver_to_telegram():
                try:
                    await tg.send_text(tg_token, chat_id, farewell)
                    await tg.send_text(tg_token, chat_id, thanks_line)
                    if not req.skip_csat:
                        target_tg = agent_name or "ممثل خدمة العملاء"
                        question_tg = (
                            f"كيف كانت تجربتك مع {target_tg}؟\n\n"
                            "ردّ بالرقم المناسب:\n"
                            "1️⃣ غير راضٍ تماماً\n2️⃣ غير راضٍ\n3️⃣ محايد\n"
                            "4️⃣ راضٍ\n5️⃣ راضٍ تماماً"
                        )
                        await tg.send_text(tg_token, chat_id, question_tg)
                except Exception as exc:
                    print(f"[end-conversation] Telegram delivery error: {exc}")
            asyncio.create_task(_deliver_to_telegram())

    return {"status": "ok", "session_id": session_id, "messages": conv.get("messages", [])[-3:]}


# ── Removed: unauthenticated backward-compat aliases ──────────────────────────
# The store-less /admin/conversations[...] aliases (list, detail, reply,
# takeover, handback) were deleted. They sat OUTSIDE the admin auth middleware
# (single-segment paths the regex doesn't cover) AND carried no inline auth, so
# anyone could read a conversation or post an "admin" reply / toggle the bot
# without logging in. They also operated on stores[0] — meaningless in a
# multi-tenant deployment. The authenticated, store-scoped routes above
# (/admin/{store_id}/conversations/...) are the supported surface; the SPA and
# widget only ever call those.
