"""
WhatsApp Campaign endpoints.

POST   /admin/{store}/campaigns              — create draft
GET    /admin/{store}/campaigns              — list (newest first)
GET    /admin/{store}/campaigns/{id}         — detail + live stats
DELETE /admin/{store}/campaigns/{id}         — delete (draft/failed only)
POST   /admin/{store}/campaigns/{id}/launch  — send now or schedule
GET    /admin/{store}/campaigns/{id}/preview — resolve audience count (dry-run)
"""
from __future__ import annotations

import asyncio
import datetime as _dt

from fastapi import APIRouter, HTTPException, Request

import database as db
import store_manager as sm
from campaign_sender import resolve_audience, run_campaign

router = APIRouter()


def _require_store(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")


def _require_wa(store_id: str) -> tuple[str, str]:
    cfg      = sm.get_ai_config(store_id) or {}
    token    = (cfg.get("whatsapp_token")    or "").strip()
    phone_id = (cfg.get("whatsapp_phone_id") or "").strip()
    if not token or not phone_id:
        raise HTTPException(400, "واتساب غير مربوط — أضف whatsapp_token و whatsapp_phone_id في الإعدادات")
    return token, phone_id


# ── Create draft ───────────────────────────────────────────────────────────────

@router.post("/admin/{store_id}/campaigns")
async def create_campaign(store_id: str, request: Request):
    _require_store(store_id)
    body = await request.json()

    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name مطلوب")
    template_name = (body.get("template_name") or "").strip()
    if not template_name:
        raise HTTPException(400, "template_name مطلوب")

    audience_type = (body.get("audience_type") or "chat_users").strip()
    if audience_type not in ("chat_users", "salla_customers", "abandoned_carts", "manual"):
        raise HTTPException(400, f"audience_type غير مقبول: {audience_type!r}")

    phone_list = body.get("phone_list") or []
    if audience_type == "manual" and not phone_list:
        raise HTTPException(400, "phone_list مطلوب عند اختيار 'manual'")

    row = await db.campaign_create(store_id, {
        "name":          name,
        "template_name": template_name,
        "template_lang": (body.get("template_lang") or "ar").strip(),
        "header_params": body.get("header_params") or [],
        "body_params":   body.get("body_params")   or [],
        "audience_type": audience_type,
        "phone_list":    phone_list,
        "status":        "draft",
    })
    if not row:
        raise HTTPException(500, "فشل إنشاء الحملة")
    return {"id": row["id"], "status": "draft", "message": "تم إنشاء الحملة ✅"}


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/campaigns")
async def list_campaigns(store_id: str):
    _require_store(store_id)
    campaigns = await db.campaign_list(store_id)
    return {"campaigns": campaigns, "count": len(campaigns)}


# ── Detail + stats ─────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/campaigns/{campaign_id}")
async def get_campaign(store_id: str, campaign_id: int):
    _require_store(store_id)
    row = await db.campaign_get(campaign_id)
    if not row or row["store_id"] != store_id:
        raise HTTPException(404, "الحملة غير موجودة")
    stats = await db.campaign_recipient_stats(campaign_id)
    import json as _j
    return {
        "id":            row["id"],
        "name":          row["name"],
        "template_name": row["template_name"],
        "template_lang": row["template_lang"],
        "header_params": _j.loads(row["header_params"]) if isinstance(row["header_params"], str) else (row["header_params"] or []),
        "body_params":   _j.loads(row["body_params"])   if isinstance(row["body_params"],   str) else (row["body_params"]   or []),
        "audience_type": row["audience_type"],
        "phone_list":    _j.loads(row["phone_list"])    if isinstance(row["phone_list"],    str) else (row["phone_list"]    or []),
        "status":        row["status"],
        "scheduled_at":  row["scheduled_at"].isoformat() if row["scheduled_at"] else None,
        "sent_at":       row["sent_at"].isoformat()       if row["sent_at"]       else None,
        "total_count":   row["total_count"],
        "sent_count":    row["sent_count"],
        "failed_count":  row["failed_count"],
        "created_at":    row["created_at"].isoformat(),
        "stats":         dict(stats),
    }


# ── Audience preview (dry-run count) ──────────────────────────────────────────

@router.get("/admin/{store_id}/campaigns/{campaign_id}/preview")
async def preview_campaign(store_id: str, campaign_id: int):
    _require_store(store_id)
    row = await db.campaign_get(campaign_id)
    if not row or row["store_id"] != store_id:
        raise HTTPException(404, "الحملة غير موجودة")
    import json as _j
    phone_list = row.get("phone_list") or []
    if isinstance(phone_list, str):
        try: phone_list = _j.loads(phone_list)
        except Exception: phone_list = []
    recipients = await resolve_audience(store_id, row["audience_type"], phone_list)
    return {"count": len(recipients), "sample": recipients[:5]}


# ── Launch (send now or schedule) ─────────────────────────────────────────────

@router.post("/admin/{store_id}/campaigns/{campaign_id}/launch")
async def launch_campaign(store_id: str, campaign_id: int, request: Request):
    _require_store(store_id)
    _require_wa(store_id)

    row = await db.campaign_get(campaign_id)
    if not row or row["store_id"] != store_id:
        raise HTTPException(404, "الحملة غير موجودة")
    if row["status"] not in ("draft", "failed"):
        raise HTTPException(400, f"لا يمكن إطلاق الحملة بالحالة الحالية: {row['status']}")

    body = await request.json()
    scheduled_at_str = (body.get("scheduled_at") or "").strip()

    if scheduled_at_str:
        try:
            scheduled_at = _dt.datetime.fromisoformat(scheduled_at_str.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "scheduled_at غير صالح — استخدم ISO 8601")
        if scheduled_at <= _dt.datetime.now(_dt.timezone.utc):
            raise HTTPException(400, "scheduled_at يجب أن يكون في المستقبل")
        # Update to scheduled
        if not db._pool:
            raise HTTPException(503, "قاعدة البيانات غير متاحة")
        async with db._pool.acquire() as conn:
            await conn.execute(
                "UPDATE wa_campaigns SET status='scheduled', scheduled_at=$2, updated_at=NOW() WHERE id=$1",
                campaign_id, scheduled_at,
            )
        return {"message": f"تمت جدولة الحملة ليوم {scheduled_at.strftime('%Y-%m-%d %H:%M')} ✅", "status": "scheduled"}

    # Send immediately
    asyncio.create_task(run_campaign(campaign_id))
    return {"message": "بدأ إرسال الحملة في الخلفية ✅", "status": "sending"}


# ── Delete ─────────────────────────────────────────────────────────────────────

@router.delete("/admin/{store_id}/campaigns/{campaign_id}")
async def delete_campaign(store_id: str, campaign_id: int):
    _require_store(store_id)
    row = await db.campaign_get(campaign_id)
    if not row or row["store_id"] != store_id:
        raise HTTPException(404, "الحملة غير موجودة")
    if row["status"] == "sending":
        raise HTTPException(400, "لا يمكن حذف حملة جارية")
    ok = await db.campaign_delete(store_id, campaign_id)
    if not ok:
        raise HTTPException(500, "فشل الحذف")
    return {"message": "تم حذف الحملة ✅"}
