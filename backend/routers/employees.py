"""Employees CRUD + compat aliases."""
from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import database as db
import store_manager as sm
import conversation_store as cs
from models import EmployeeCreateRequest, EmployeeUpdateRequest
from routers.deps import require_store_owner

router = APIRouter()


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/employees")
async def list_store_employees(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    rows = await db.list_employees(store_id)
    return {"employees": rows, "count": len(rows)}


@router.get("/admin/{store_id}/employees/ratings")
async def store_employees_ratings(store_id: str):
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
            "distribution": [0, 0, 0, 0, 0],
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


# ── Create ─────────────────────────────────────────────────────────────────────

@router.post("/admin/{store_id}/employees")
async def create_store_employee(
    store_id: str,
    req: EmployeeCreateRequest,
    request: Request,
):
    require_store_owner(request, store_id)
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

    role = (req.role or "agent").strip().lower()
    if role not in ("agent", "manager"):
        raise HTTPException(400, "role must be 'agent' or 'manager'")

    emp_id = await db.add_employee(
        store_id = store_id,
        name     = name,
        email    = email,
        password_hash = _auth.hash_password(req.password),
        role     = role,
    )
    if not emp_id:
        raise HTTPException(503, "تعذّر الحفظ — قاعدة البيانات غير متاحة")
    return {"status": "ok", "id": emp_id, "message": "تمت إضافة الموظف ✅"}


# ── Update ────────────────────────────────────────────────────────────────────

@router.patch("/admin/{store_id}/employees/{employee_id}")
async def update_store_employee(
    store_id: str,
    employee_id: int,
    req: EmployeeUpdateRequest,
    request: Request,
):
    require_store_owner(request, store_id)
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    updates: dict = {}
    if req.name is not None:
        updates["name"] = req.name.strip()
    if req.email is not None:
        updates["email"] = req.email.strip().lower()
    if req.role is not None:
        role = req.role.strip().lower()
        if role not in ("agent", "manager"):
            raise HTTPException(400, "role must be 'agent' or 'manager'")
        updates["role"] = role
    if req.active is not None:
        updates["active"] = bool(req.active)
    if req.password:
        if len(req.password) < 6:
            raise HTTPException(400, "كلمة المرور قصيرة جداً")
        updates["password_hash"] = _auth.hash_password(req.password)

    if not updates:
        raise HTTPException(400, "لا توجد تغييرات")

    ok = await db.update_employee(employee_id, store_id, **updates)
    if not ok:
        raise HTTPException(404, "الموظف غير موجود")
    return {"status": "ok", "message": "تم تحديث بيانات الموظف ✅"}


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/admin/{store_id}/employees/{employee_id}")
async def delete_store_employee(store_id: str, employee_id: int, request: Request):
    require_store_owner(request, store_id)
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    ok = await db.delete_employee(employee_id, store_id)
    if not ok:
        raise HTTPException(404, "الموظف غير موجود")
    return {"status": "ok", "message": "تم حذف الموظف ✅"}
