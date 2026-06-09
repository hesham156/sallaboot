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
from models import AdminReplyRequest, BotToggleRequest, EndConversationRequest
from routers.deps import audit, super_viewing_other_store, _REASON_MIN_LENGTH, _REASON_MAX_LENGTH

router = APIRouter()


# ── Bot toggle ────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/bot/status")
async def store_bot_status(store_id: str):
    return {"bot_globally_enabled": cs.get_store_bot(store_id)}


@router.post("/admin/{store_id}/bot/toggle")
async def store_bot_toggle(store_id: str, req: BotToggleRequest):
    cs.set_store_bot(store_id, req.enabled)
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

    await cs.restore_to_memory(session_id)
    conv = cs.all_conversations().get(session_id)
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
    await cs.restore_to_memory(session_id)
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

    return {"status": "sent", "message": msg}


# ── Takeover / handback ───────────────────────────────────────────────────────

@router.post("/admin/{store_id}/conversations/{session_id}/takeover")
async def store_takeover(store_id: str, session_id: str):
    await cs.restore_to_memory(session_id)
    await cs.set_session_bot(session_id, False)
    await cs.mark_admin_read(session_id)
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
async def store_handback(store_id: str, session_id: str):
    await cs.restore_to_memory(session_id)
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

    return {"status": "ok", "session_id": session_id, "messages": conv.get("messages", [])[-3:]}


# ── Backward-compat aliases ───────────────────────────────────────────────────

@router.get("/admin/conversations")
async def admin_conversations_compat(limit: int = 100, offset: int = 0):
    stores = sm.list_stores()
    if not stores:
        return {"total": 0, "conversations": []}
    return await cs.summary_list(stores[0]["store_id"], limit=limit, offset=offset)


@router.get("/admin/conversations/{session_id}")
async def admin_conversation_detail_compat(session_id: str):
    await cs.restore_to_memory(session_id)
    conv = cs.all_conversations().get(session_id)
    if not conv:
        return {"session_id": session_id, "messages": [], "bot_enabled": True}
    return conv


@router.post("/admin/conversations/{session_id}/reply")
async def admin_reply_compat(session_id: str, req: AdminReplyRequest):
    await cs.restore_to_memory(session_id)
    msg = await cs.add_message(session_id, "admin", req.message, "default")
    return {"status": "sent", "message": msg}


@router.post("/admin/conversations/{session_id}/takeover")
async def admin_takeover_compat(session_id: str):
    await cs.restore_to_memory(session_id)
    await cs.set_session_bot(session_id, False)
    return {"status": "ok", "bot_enabled": False}


@router.post("/admin/conversations/{session_id}/handback")
async def admin_handback_compat(session_id: str):
    await cs.restore_to_memory(session_id)
    await cs.set_session_bot(session_id, True)
    return {"status": "ok", "bot_enabled": True}
