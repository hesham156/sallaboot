"""SSE streaming: admin stream tickets + admin stream + widget stream."""
import hmac
import hashlib
import secrets as _secrets
import time as _time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

import auth as _auth
import realtime
import conversation_store as cs
from routers.deps import audit, super_viewing_other_store, _REASON_MIN_LENGTH, _REASON_MAX_LENGTH

router = APIRouter()

# ── Ticket helpers ────────────────────────────────────────────────────────────
_TICKET_TTL_SECONDS = 300
_TICKET_SIG_LEN     = 16


def _stream_ticket_sig(payload: str) -> str:
    return hmac.new(
        _auth.ADMIN_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:_TICKET_SIG_LEN]


def _issue_stream_ticket(store_id: str) -> str:
    exp     = int(_time.time()) + _TICKET_TTL_SECONDS
    nonce   = _secrets.token_urlsafe(9)
    payload = f"{store_id}:{exp}:{nonce}"
    sig     = _stream_ticket_sig(payload)
    return f"{payload}:{sig}"


def _consume_stream_ticket(ticket: str, store_id: str) -> bool:
    if not ticket or ticket.count(":") != 3:
        return False
    try:
        bound_store, exp_str, nonce, sig = ticket.split(":", 3)
        exp = int(exp_str)
    except (ValueError, TypeError):
        return False
    if bound_store != store_id:
        return False
    if exp < int(_time.time()):
        return False
    expected = _stream_ticket_sig(f"{bound_store}:{exp}:{nonce}")
    return hmac.compare_digest(expected, sig)


def _format_sse(event_type: str, data: dict) -> str:
    import json as _json
    payload = _json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


# ── Admin stream ticket ───────────────────────────────────────────────────────

@router.post("/admin/{store_id}/stream/ticket")
async def admin_stream_ticket(store_id: str, request: Request, reason: str = ""):
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims:
        raise HTTPException(401, "يرجى تسجيل الدخول")
    if not claims.get("su") and claims.get("s") != store_id:
        raise HTTPException(403, "غير مصرح لك بالوصول")

    if super_viewing_other_store(request, store_id):
        reason_clean = (reason or "").strip()
        if len(reason_clean) < _REASON_MIN_LENGTH:
            raise HTTPException(403, "reason_required")
        await audit(
            request,
            "super_opened_stream",
            target_store=store_id,
            details={"reason": reason_clean[:_REASON_MAX_LENGTH]},
        )

    return {"ticket": _issue_stream_ticket(store_id), "ttl_seconds": _TICKET_TTL_SECONDS}


# ── Admin SSE stream ──────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/stream")
async def admin_stream(store_id: str, ticket: str = "", request: Request = None):
    if not ticket or not _consume_stream_ticket(ticket, store_id):
        raise HTTPException(401, "Invalid or expired stream ticket")
    if not realtime.available():
        raise HTTPException(503, "Realtime channel unavailable — DB listener down")

    async def event_gen():
        yield _format_sse("connected", {"store_id": store_id})
        last_beat = _time.time()
        async for event in realtime.subscribe(f"store:{store_id}"):
            if event["type"] == "_shutdown":
                yield _format_sse("shutdown", {"reason": "server restart"})
                return
            yield _format_sse(event["type"], event["data"])
            now = _time.time()
            if now - last_beat > 25:
                yield ": heartbeat\n\n"
                last_beat = now

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ── Widget SSE stream ─────────────────────────────────────────────────────────

@router.get("/chat/stream")
async def chat_stream(session_id: str):
    if not session_id or len(session_id) > 200:
        raise HTTPException(400, "session_id required")
    if not realtime.available():
        raise HTTPException(503, "Realtime channel unavailable")

    async def event_gen():
        yield _format_sse("connected", {"session_id": session_id})
        try:
            await cs.restore_to_memory(session_id)
            pending = await cs.pop_pending_for_widget(session_id)
            for msg in pending:
                yield _format_sse("admin_message", msg)
        except Exception as exc:
            print(f"[stream] flush-on-connect for {session_id} failed: {exc}")

        last_beat = _time.time()
        async for event in realtime.subscribe(f"session:{session_id}"):
            if event["type"] == "_shutdown":
                yield _format_sse("shutdown", {"reason": "server restart"})
                return
            yield _format_sse(event["type"], event["data"])
            now = _time.time()
            if now - last_beat > 25:
                yield ": heartbeat\n\n"
                last_beat = now

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )
