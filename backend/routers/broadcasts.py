"""
Omni-channel broadcast endpoints (free-text bulk send).

GET  /admin/{store}/broadcasts            — list (newest first)
GET  /admin/{store}/broadcasts/audience   — connected channels + recipient counts
POST /admin/{store}/broadcasts            — create + send now
GET  /admin/{store}/broadcasts/{id}       — detail + live progress

Unlike /campaigns (WhatsApp template only), this sends a free-text message
to every connected channel's active users. See broadcast_sender for the
per-channel policy (e.g. WhatsApp/Meta's 24h free-text window).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

import database as db
import store_manager as sm
import broadcast_sender as bs
from routers.deps import require_store_member, audit

router = APIRouter()

_MAX_MESSAGE_LEN = 4000


def _require_store(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")


@router.get("/admin/{store_id}/broadcasts/audience")
async def broadcast_audience(store_id: str, request: Request):
    """Connected channels + how many recipients each would reach right now."""
    await require_store_member(request, store_id)
    _require_store(store_id)
    return {
        "channels": bs.available_channels(store_id),
        "counts":   await bs.audience_counts(store_id),
    }


@router.get("/admin/{store_id}/broadcasts")
async def list_broadcasts(store_id: str, request: Request):
    await require_store_member(request, store_id)
    _require_store(store_id)
    items = await db.broadcast_list(store_id)
    return {"broadcasts": items, "count": len(items)}


@router.post("/admin/{store_id}/broadcasts")
async def create_broadcast(store_id: str, request: Request):
    await require_store_member(request, store_id)
    _require_store(store_id)
    body = await request.json()

    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "نص الرسالة مطلوب")
    if len(message) > _MAX_MESSAGE_LEN:
        raise HTTPException(400, f"النص يتجاوز الحد ({_MAX_MESSAGE_LEN} حرف)")

    available = bs.available_channels(store_id)
    if not available:
        raise HTTPException(400, "لا توجد قناة مربوطة للإرسال — اربط واتساب/تيليجرام/… أولاً")

    requested = body.get("channels") or available     # default: all connected
    channels = [c for c in requested if c in available]
    if not channels:
        raise HTTPException(
            400, f"القنوات المطلوبة غير مربوطة. المتاح: {', '.join(available)}")

    bid = await db.broadcast_create(store_id, message, channels)
    if not bid:
        raise HTTPException(503, "تعذّر إنشاء البث — تحقق من قاعدة البيانات")

    # Fire-and-forget delivery so the request returns immediately.
    asyncio.create_task(bs.run_broadcast(bid))

    await audit(request, "broadcast_sent", target_store=store_id, details={
        "broadcast_id": bid, "channels": channels, "chars": len(message),
    })
    return {"id": bid, "status": "sending", "channels": channels,
            "message": "بدأ الإرسال ✅"}


@router.get("/admin/{store_id}/broadcasts/{broadcast_id}")
async def get_broadcast(store_id: str, broadcast_id: int, request: Request):
    await require_store_member(request, store_id)
    _require_store(store_id)
    bc = await db.broadcast_get(store_id, broadcast_id)
    if not bc:
        raise HTTPException(404, "البث غير موجود")
    return bc
