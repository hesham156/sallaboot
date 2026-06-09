"""
Platform-level admin routes: support access, audit log, LLM usage, budget.
"""
from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import database as db
import store_manager as sm
from routers.deps import audit, require_store_owner, daily_token_budget

router = APIRouter()


# ── Support access ────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/support-access")
async def support_access_status(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    active  = await db.support_access_active(store_id)
    history = await db.support_access_list(store_id, limit=50)
    return {"active": active, "history": history}


@router.post("/admin/{store_id}/support-access")
async def support_access_grant(store_id: str, request: Request):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    require_store_owner(request, store_id)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(400, "Body must be a JSON object")

    try:
        duration = int(body.get("duration_minutes", 60))
    except (TypeError, ValueError):
        raise HTTPException(400, "duration_minutes must be an integer")
    if duration <= 0:
        raise HTTPException(400, "duration_minutes must be > 0")
    if duration > 24 * 60:
        raise HTTPException(400, "duration_minutes > 24h not allowed")

    note = str(body.get("note") or "")[:500]

    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token) or {}
    granted_by = f"emp:{claims.get('eid')}" if claims.get("eid") else "owner"

    grant = await db.support_access_create(
        store_id,
        granted_by       = granted_by,
        duration_minutes = duration,
        note             = note,
    )
    if not grant:
        raise HTTPException(503, "تعذّر إنشاء الإذن — تحقق من اتصال قاعدة البيانات")

    await audit(request, "support_access_granted", target_store=store_id, details={
        "grant_id":         grant["id"],
        "duration_minutes": duration,
        "expires_at":       grant["expires_at"],
        "note":             note[:120],
    })
    return grant


@router.delete("/admin/{store_id}/support-access/{grant_id}")
async def support_access_revoke_endpoint(store_id: str, grant_id: int, request: Request):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    require_store_owner(request, store_id)

    ok = await db.support_access_revoke(grant_id, store_id)
    if not ok:
        raise HTTPException(404, "الإذن غير موجود أو ملغي بالفعل")

    await audit(request, "support_access_revoked", target_store=store_id, details={
        "grant_id": grant_id,
    })
    return {"status": "ok"}


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/audit-log")
async def store_audit_log(store_id: str, limit: int = 200, offset: int = 0,
                           action: str | None = None):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    rows = await db.audit_list(
        store_id = store_id,
        action   = action or None,
        limit    = limit,
        offset   = offset,
    )
    return {"count": len(rows), "rows": rows}


# ── LLM usage ─────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/llm-usage")
async def store_llm_usage(store_id: str, days: int = 7):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    today    = await db.llm_usage_today(store_id)
    history  = await db.llm_usage_report(store_id, days=days)
    budget   = daily_token_budget(store_id)
    override = (sm.get_ai_config(store_id) or {}).get("daily_token_budget")

    used_today = int(today.get("tokens_total", 0))
    return {
        "store_id": store_id,
        "today": {
            **today,
            "budget":       budget,
            "remaining":    max(0, budget - used_today) if budget > 0 else None,
            "percent_used": round(used_today / budget * 100, 1) if budget > 0 else None,
            "exhausted":    budget > 0 and used_today >= budget,
        },
        "budget": {
            "value":         budget,
            "source":        "store_override" if override is not None else "env_default",
            "breaker_active": budget > 0,
        },
        "history": history,
    }


@router.put("/admin/{store_id}/llm-budget")
async def update_llm_budget(store_id: str, request: Request):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    require_store_owner(request, store_id)

    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token) or {}
    is_super = bool(claims.get("su"))

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
            raise HTTPException(400, "daily_token_budget must be ≥ 0")
        if n == 0 and not is_super:
            raise HTTPException(
                403,
                "تعطيل حد الاستهلاك متاح للمدير العام فقط — اختر حداً أعلى بدلاً من الصفر."
            )
        cfg["daily_token_budget"] = n
        applied = n

    sm.set_ai_config(store_id, cfg)
    tokens = sm.get_store_info(store_id)
    await db.save_store(store_id, tokens)
    await db.save_ai_config(store_id, cfg)

    await audit(request, "set_llm_budget", target_store=store_id, details={
        "applied":          applied,
        "effective_budget": daily_token_budget(store_id),
    })

    return {
        "status":             "ok",
        "daily_token_budget": applied,
        "effective_budget":   daily_token_budget(store_id),
    }
