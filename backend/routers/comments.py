"""
Comments router — Smart Inbox, automation settings, reply rules, analytics, and
the super-admin entitlement toggle for the FB/IG comment feature.

Authorization (via authz.store_guard → Principal):
  • read   (list / get / analytics / settings GET / rules GET) → any member,
                                                                 incl. viewer
  • act    (reply / approve / assign / resolve / hide / ignore) → not viewer
  • manage (settings PUT / rules write)                         → manager+ / owner
  • super  (entitlement toggle)                                 → platform admin

All routes are tenant-scoped: store_guard binds the token to {store_id}, and
every DB call filters by store_id, so no cross-tenant access is possible.
"""
from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import database as db
import store_manager as sm
import comments as cm
from routers.authz import store_guard, Principal

router = APIRouter()


# ── Role helpers ─────────────────────────────────────────────────────────────

def _ensure_act(p: Principal) -> None:
    if p.role == "viewer":
        raise HTTPException(403, "صلاحية العرض فقط لا تسمح بهذا الإجراء")


def _ensure_manage(p: Principal) -> None:
    if p.role not in ("owner", "manager", "super"):
        raise HTTPException(403, "هذا الإجراء مخصّص للمدراء")


def _ensure_super(p: Principal) -> None:
    if not p.is_super:
        raise HTTPException(403, "صلاحية المدير العام فقط")


def _actor(p: Principal) -> str:
    if p.is_super:
        return "super"
    return f"emp:{p.employee_id}" if p.employee_id else "owner"


# ── Pydantic bodies ──────────────────────────────────────────────────────────

class ReplyBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class AssignBody(BaseModel):
    employee_id: int


class SettingsBody(BaseModel):
    comments_fb_enabled: bool | None = None
    comments_ig_enabled: bool | None = None
    comment_mode: str | None = Field(default=None)            # auto|approval|suggest
    comment_confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    comment_personality: dict | None = None
    comment_forbidden_topics: list[str] | None = None
    comment_spam_action: str | None = None                   # hide|flag


class RuleBody(BaseModel):
    match_type: str = Field(pattern="^(keyword|regex|intent)$")
    pattern: str = Field(min_length=1, max_length=500)
    action: str = Field(pattern="^(reply_template|send_contact|escalate|hide|ignore)$")
    template: str = Field(default="", max_length=2000)
    priority: int = Field(default=100, ge=0, le=10000)
    enabled: bool = True


class EntitlementBody(BaseModel):
    comments_enabled: bool
    comments_monthly_limit: int = Field(default=0, ge=0)


_VALID_MODE  = {"auto", "approval", "suggest"}
_VALID_SPAM  = {"hide", "flag"}


# ── Smart Inbox: list ────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/comments")
async def list_comments(
    store_id: str,
    p: Principal = Depends(store_guard),
    status: str = Query(""),
    platform: str = Query(""),
    lead_temp: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows = await db.list_social_comments(
        store_id, status=status, platform=platform, lead_temp=lead_temp,
        limit=limit, offset=offset,
    )
    return {"comments": rows, "count": len(rows)}


@router.get("/admin/{store_id}/comments/analytics")
async def comment_analytics(store_id: str, p: Principal = Depends(store_guard),
                            days: int = Query(30, ge=1, le=365)):
    return await db.social_comment_analytics(store_id, days)


# ── Automation settings ──────────────────────────────────────────────────────

def _settings_view(cfg: dict, ent: dict) -> dict:
    return {
        "comments_enabled":             ent.get("comments_enabled", False),  # entitlement
        "comments_monthly_limit":       ent.get("comments_monthly_limit", 0),
        "comments_fb_enabled":          bool(cfg.get("comments_fb_enabled")),
        "comments_ig_enabled":          bool(cfg.get("comments_ig_enabled")),
        "comment_mode":                 cfg.get("comment_mode", "approval"),
        "comment_confidence_threshold": float(cfg.get("comment_confidence_threshold", 0.8)),
        "comment_personality":          cfg.get("comment_personality") or {"preset": "friendly"},
        "comment_forbidden_topics":     cfg.get("comment_forbidden_topics") or [],
        "comment_spam_action":          cfg.get("comment_spam_action", "flag"),
        "page_connected":               bool((cfg.get("page_token") or "").strip()),
        "ig_connected":                 bool((cfg.get("ig_id") or "").strip()),
    }


@router.get("/admin/{store_id}/comments/settings")
async def get_settings(store_id: str, p: Principal = Depends(store_guard)):
    cfg = sm.get_ai_config(store_id) or {}
    ent = await db.get_entitlements(store_id)
    return _settings_view(cfg, ent)


@router.put("/admin/{store_id}/comments/settings")
async def update_settings(store_id: str, body: SettingsBody,
                          p: Principal = Depends(store_guard)):
    _ensure_manage(p)
    if body.comment_mode is not None and body.comment_mode not in _VALID_MODE:
        raise HTTPException(400, "comment_mode must be auto|approval|suggest")
    if body.comment_spam_action is not None and body.comment_spam_action not in _VALID_SPAM:
        raise HTTPException(400, "comment_spam_action must be hide|flag")

    cfg = dict(sm.get_ai_config(store_id) or {})
    for field, value in body.model_dump(exclude_none=True).items():
        cfg[field] = value
    await sm.set_ai_config(store_id, cfg)
    await db.save_ai_config(store_id, cfg)
    ent = await db.get_entitlements(store_id)
    return _settings_view(cfg, ent)


# ── Reply rules ──────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/comments/rules")
async def list_rules(store_id: str, p: Principal = Depends(store_guard)):
    return {"rules": await db.list_comment_rules(store_id)}


@router.post("/admin/{store_id}/comments/rules")
async def add_rule(store_id: str, body: RuleBody, p: Principal = Depends(store_guard)):
    _ensure_manage(p)
    rid = await db.add_comment_rule(
        store_id, match_type=body.match_type, pattern=body.pattern,
        action=body.action, template=body.template, priority=body.priority,
        enabled=body.enabled,
    )
    if not rid:
        raise HTTPException(500, "تعذّر حفظ القاعدة")
    return {"id": rid}


@router.delete("/admin/{store_id}/comments/rules/{rule_id}")
async def delete_rule(store_id: str, rule_id: int, p: Principal = Depends(store_guard)):
    _ensure_manage(p)
    if not await db.delete_comment_rule(store_id, rule_id):
        raise HTTPException(404, "القاعدة غير موجودة")
    return {"deleted": True}


# ── Inbox actions ────────────────────────────────────────────────────────────

async def _send_reply(store_id: str, comment: dict, text: str, actor: str) -> None:
    """Publicly reply to a comment via the Graph edge, then mark it replied."""
    cfg   = sm.get_ai_config(store_id) or {}
    token = (cfg.get("page_token") or "").strip()
    if not token:
        raise HTTPException(400, "لا يوجد توكن صفحة — أعد ربط فيسبوك/إنستقرام")
    ok = await cm.reply_to_comment(token, comment["external_comment_id"], text,
                                   platform=comment["platform"])
    if not ok:
        # Most common cause is a page token missing pages_manage_engagement /
        # instagram_manage_comments (Graph "(#200) Permissions error"). The exact
        # Graph error is logged server-side by comments._post.
        raise HTTPException(
            502,
            "تعذّر إرسال الرد إلى ميتا. الأرجح أن صلاحية إدارة التعليقات غير "
            "ممنوحة — أعد ربط فيسبوك/إنستقرام ووافق على كل الصلاحيات، ثم حاول مجدداً.",
        )
    await db.update_social_comment(
        store_id, comment["id"], status="replied", final_reply=text,
        replied_by=actor, replied_at=_dt.datetime.now(_dt.timezone.utc),
    )


@router.post("/admin/{store_id}/comments/{pk}/reply")
async def reply_comment(store_id: str, pk: int, body: ReplyBody,
                        p: Principal = Depends(store_guard)):
    _ensure_act(p)
    comment = await db.get_social_comment(store_id, pk)
    if not comment:
        raise HTTPException(404, "التعليق غير موجود")
    await _send_reply(store_id, comment, body.text.strip(), _actor(p))
    return {"status": "replied"}


@router.post("/admin/{store_id}/comments/{pk}/approve")
async def approve_comment(store_id: str, pk: int, p: Principal = Depends(store_guard)):
    """Approve and send the AI's suggested reply as-is."""
    _ensure_act(p)
    comment = await db.get_social_comment(store_id, pk)
    if not comment:
        raise HTTPException(404, "التعليق غير موجود")
    text = (comment.get("suggested_reply") or "").strip()
    if not text:
        raise HTTPException(400, "لا يوجد ردّ مقترح لاعتماده")
    await _send_reply(store_id, comment, text, _actor(p))
    return {"status": "replied"}


@router.post("/admin/{store_id}/comments/{pk}/assign")
async def assign_comment(store_id: str, pk: int, body: AssignBody,
                         p: Principal = Depends(store_guard)):
    _ensure_act(p)
    ok = await db.update_social_comment(store_id, pk, assigned_to=body.employee_id,
                                        status="assigned")
    if not ok:
        raise HTTPException(404, "التعليق غير موجود")
    return {"status": "assigned"}


@router.post("/admin/{store_id}/comments/{pk}/resolve")
async def resolve_comment(store_id: str, pk: int, p: Principal = Depends(store_guard)):
    _ensure_act(p)
    ok = await db.update_social_comment(store_id, pk, status="resolved")
    if not ok:
        raise HTTPException(404, "التعليق غير موجود")
    return {"status": "resolved"}


@router.post("/admin/{store_id}/comments/{pk}/ignore")
async def ignore_comment(store_id: str, pk: int, p: Principal = Depends(store_guard)):
    _ensure_act(p)
    ok = await db.update_social_comment(store_id, pk, status="ignored")
    if not ok:
        raise HTTPException(404, "التعليق غير موجود")
    return {"status": "ignored"}


@router.post("/admin/{store_id}/comments/{pk}/hide")
async def hide_comment_route(store_id: str, pk: int, p: Principal = Depends(store_guard)):
    _ensure_act(p)
    comment = await db.get_social_comment(store_id, pk)
    if not comment:
        raise HTTPException(404, "التعليق غير موجود")
    cfg   = sm.get_ai_config(store_id) or {}
    token = (cfg.get("page_token") or "").strip()
    if not token:
        raise HTTPException(400, "لا يوجد توكن صفحة")
    ok = await cm.hide_comment(token, comment["external_comment_id"],
                               platform=comment["platform"])
    if not ok:
        raise HTTPException(502, "تعذّر إخفاء التعليق")
    await db.update_social_comment(store_id, pk, status="hidden")
    return {"status": "hidden"}


# ── Super-admin: feature entitlement ─────────────────────────────────────────

@router.put("/admin/{store_id}/comments/entitlement")
async def set_entitlement(store_id: str, body: EntitlementBody,
                          p: Principal = Depends(store_guard)):
    """Platform-admin toggle for the comment feature (gating + monthly cap)."""
    _ensure_super(p)
    await db.set_entitlements(store_id, comments_enabled=body.comments_enabled,
                              comments_monthly_limit=body.comments_monthly_limit)
    return await db.get_entitlements(store_id)
