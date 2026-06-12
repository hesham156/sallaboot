"""
Customer Segments & Follow-up — API endpoints.

GET    /admin/{store_id}/segments                — list + counts
GET    /admin/{store_id}/segments/stats          — counts by segment type
POST   /admin/{store_id}/segments/scan           — scan conversations → classify
PUT    /admin/{store_id}/segments/{customer_id}/pause   — pause/resume follow-up
POST   /admin/{store_id}/segments/{customer_id}/followup-now — send immediately
GET    /admin/{store_id}/settings/followup       — get follow-up config
PUT    /admin/{store_id}/settings/followup       — save follow-up config
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

import database as db
import store_manager as sm
from log import get_logger
from customer_followup import (
    classify_customer, scan_store_conversations,
    send_followup, _get_followup_config, _save_followup_config,
)

router = APIRouter()
log = get_logger(__name__)


def _require_store(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")


def _json_safe(v):
    """Convert asyncpg non-JSON-serializable types to Python primitives."""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "__int__") and not isinstance(v, (bool, int)):
        return int(v)
    if hasattr(v, "__float__") and not isinstance(v, float):
        return float(v)
    return v


# ── List customers with their segments ────────────────────────────────────────

@router.get("/admin/{store_id}/segments")
async def list_segments(store_id: str, segment: str = "", limit: int = 100, offset: int = 0):
    _require_store(store_id)
    try:
        rows = await db.seg_list(store_id, segment or None, limit=limit, offset=offset)
        def _clean(r: dict) -> dict:
            return {k: _json_safe(v) for k, v in r.items()}
        return {"customers": [_clean(r) for r in rows], "count": len(rows)}
    except Exception as exc:
        log.error("segments_list_error", extra={"store_id": store_id, "error": str(exc)})
        raise HTTPException(500, f"خطأ في قاعدة البيانات: {exc}")


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/segments/stats")
async def segment_stats(store_id: str):
    _require_store(store_id)
    try:
        counts = await db.seg_count_by_type(store_id)
        total  = sum(int(v) for v in counts.values())
        return {"counts": {k: int(v) for k, v in counts.items()}, "total": total}
    except Exception as exc:
        log.error("segments_stats_error", extra={"store_id": store_id, "error": str(exc)})
        raise HTTPException(500, f"خطأ في قاعدة البيانات: {exc}")


# ── Scan existing conversations and classify ──────────────────────────────────

@router.post("/admin/{store_id}/segments/scan")
async def trigger_scan(store_id: str):
    _require_store(store_id)
    n = await scan_store_conversations(store_id)
    return {"status": "ok", "classified": n,
            "message": f"✅ تم تصنيف {n} عميل من المحادثات الموجودة"}


# ── Manual update: segment + notes ───────────────────────────────────────────

@router.put("/admin/{store_id}/segments/{customer_id}")
async def update_customer(store_id: str, customer_id: str, request: Request):
    _require_store(store_id)
    body = await request.json()

    allowed_segments = {"new", "inquiry", "hesitant", "buyer", "loyal", "inactive"}
    new_segment = body.get("segment", "").strip()
    notes       = body.get("notes", "").strip()

    if new_segment and new_segment not in allowed_segments:
        raise HTTPException(400, f"تصنيف غير صالح: {new_segment}")

    pool = db._pool
    if not pool:
        raise HTTPException(503, "قاعدة البيانات غير متاحة")

    fields, vals = [], []
    idx = 1
    if new_segment:
        fields.append(f"segment = ${idx}")
        vals.append(new_segment)
        idx += 1
        fields.append(f"segment_reason = ${idx}")
        vals.append("تم التصنيف يدوياً")
        idx += 1
    if "notes" in body:
        fields.append(f"notes = ${idx}")
        vals.append(notes)
        idx += 1

    if not fields:
        raise HTTPException(400, "لا توجد حقول للتحديث")

    fields.append(f"updated_at = NOW()")
    vals += [store_id, customer_id]
    q = (
        f"UPDATE customer_segments SET {', '.join(fields)} "
        f"WHERE store_id = ${idx} AND customer_id = ${idx + 1} "
        f"RETURNING *"
    )
    async with pool.acquire() as conn:
        row = await conn.fetchrow(q, *vals)
    if not row:
        raise HTTPException(404, "العميل غير موجود")
    return {"status": "ok", "customer": dict(row)}


# ── Pause / resume a customer's follow-up ────────────────────────────────────

@router.put("/admin/{store_id}/segments/{customer_id}/pause")
async def pause_customer(store_id: str, customer_id: str, request: Request):
    _require_store(store_id)
    body   = await request.json()
    paused = bool(body.get("paused", True))
    await db.seg_pause(store_id, customer_id, paused)
    return {"status": "ok", "paused": paused}


# ── Send follow-up immediately (manual trigger) ───────────────────────────────

@router.post("/admin/{store_id}/segments/{customer_id}/followup-now")
async def send_followup_now(store_id: str, customer_id: str):
    _require_store(store_id)
    rows = await db.seg_list(store_id, limit=1, offset=0)
    # Find this specific customer
    pool = db._pool
    if not pool:
        raise HTTPException(503, "قاعدة البيانات غير متاحة")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM customer_segments WHERE store_id=$1 AND customer_id=$2",
            store_id, customer_id,
        )
    if not row:
        raise HTTPException(404, "العميل غير موجود")
    customer = dict(row)
    ok = await send_followup(store_id, customer)
    if not ok:
        raise HTTPException(400,
            "فشل الإرسال — تحقق من تفعيل WhatsApp وأن الرقم محفوظ")
    return {"status": "ok", "message": "✅ تم إرسال رسالة المتابعة"}


# ── Get follow-up settings ────────────────────────────────────────────────────

@router.get("/admin/{store_id}/settings/followup")
async def get_followup_settings(store_id: str):
    _require_store(store_id)
    cfg = _get_followup_config(store_id)
    return cfg


# ── Save follow-up settings ───────────────────────────────────────────────────

@router.put("/admin/{store_id}/settings/followup")
async def save_followup_settings(store_id: str, request: Request):
    _require_store(store_id)
    body = await request.json()

    # Validate structure
    if not isinstance(body, dict):
        raise HTTPException(400, "body يجب أن يكون object")
    if "segments" not in body:
        raise HTTPException(400, "segments مطلوب")

    _save_followup_config(store_id, body)

    # Save to DB as well (persists across restarts)
    ai_cfg = sm.get_ai_config(store_id) or {}
    import json
    ai_cfg["followup_config"] = body
    sm.update_ai_config(store_id, ai_cfg)
    if db.available():
        store_info = sm.get_store_info(store_id) or {}
        await db.save_store(store_id, store_info)

    return {"status": "ok", "message": "✅ تم حفظ إعدادات المتابعة التلقائية"}
