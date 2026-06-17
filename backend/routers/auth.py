"""
Auth routes — super-admin login, per-store owner login, per-store
employee login, lightweight token verify.

The bearer-token enforcement for /admin/{store_id}/* is handled by
middleware.admin_auth_middleware. These endpoints sit OUTSIDE that
protection because they're the entry points that mint the tokens in
the first place — they have their own auth checks (password) plus a
DB-backed rate limiter.

Naming note: this module imports `auth as _auth` — that resolves to
the top-level backend/auth.py (the crypto primitives), NOT to itself.
Python's import order makes the package-internal name win only inside
this package, which we never do.
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import database as db
import store_manager as sm
from models import EmployeeLoginRequest, LoginRequest
from routers.deps import is_rate_limited as _is_rate_limited


router = APIRouter()


@router.post("/admin/auth/login")
async def super_login(req: LoginRequest, request: Request):
    """
    Super-admin login. Email + password are env-var driven
    (SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD). Constant-time compare
    on both fields to avoid timing side-channels.
    """
    ip          = request.client.host if request.client else "unknown"
    super_email = os.getenv("SUPER_ADMIN_EMAIL", "").strip().lower()
    super_pass  = os.getenv("SUPER_ADMIN_PASSWORD", "")

    if not super_email or not super_pass:
        raise HTTPException(503, "Super-admin credentials are not configured on this server")

    if await _is_rate_limited(f"super:{ip}"):
        raise HTTPException(429, "محاولات تسجيل دخول كثيرة جداً. انتظر 5 دقائق وحاول مجدداً.")

    email_in = (req.email or "").strip().lower()
    email_ok = hmac.compare_digest(email_in, super_email)
    pass_ok  = bool(req.password) and hmac.compare_digest(req.password, super_pass)
    if not (email_ok and pass_ok):
        print(f"[auth] ❌ Failed admin login attempt from {ip} (email={email_in!r})")
        raise HTTPException(401, "البريد الإلكتروني أو كلمة المرور غير صحيحة")

    print(f"[auth] ✅ Admin login ({email_in}) from {ip}")
    token = _auth.create_token("super", is_super=True)
    return {"token": token, "store_id": "super", "is_super": True}


@router.post("/admin/{store_id}/auth/login")
async def store_login(store_id: str, req: LoginRequest, request: Request):
    """Store-owner login (one password per store, set on registration)."""
    ip = request.client.host if request.client else "unknown"

    if await _is_rate_limited(f"{store_id}:{ip}"):
        raise HTTPException(429, "محاولات تسجيل دخول كثيرة جداً. انتظر 5 دقائق وحاول مجدداً.")

    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    stored_hash = sm.get_admin_password_hash(store_id)
    if not stored_hash or not _auth.check_password(req.password, stored_hash):
        print(f"[auth] ❌ Failed login for store {store_id!r} from {ip}")
        raise HTTPException(401, "كلمة المرور غير صحيحة")

    # Silent password-hash upgrade: legacy SHA-256 → argon2id. Safe
    # because we just confirmed the password is correct.
    if _auth.needs_rehash(stored_hash):
        try:
            await sm.set_admin_password(store_id, _auth.hash_password(req.password))
            print(f"[auth] 🔁 Upgraded password hash for store {store_id!r}")
        except Exception as exc:
            print(f"[auth] ⚠️ Password hash upgrade failed for {store_id!r}: {exc}")

    print(f"[auth] ✅ Store login: {store_id!r} from {ip}")
    token = _auth.create_token(store_id)
    info  = sm.get_store_info(store_id)
    return {
        "token":      token,
        "store_id":   store_id,
        "store_name": info.get("store_name", f"متجر {store_id}"),
    }


@router.post("/admin/{store_id}/auth/employee-login")
async def employee_login(store_id: str, req: EmployeeLoginRequest, request: Request):
    """Per-store employee login (agents + managers)."""
    ip = request.client.host if request.client else "unknown"

    if await _is_rate_limited(f"{store_id}:emp:{ip}"):
        raise HTTPException(429, "محاولات تسجيل دخول كثيرة جداً. انتظر 5 دقائق وحاول مجدداً.")

    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    emp = await db.get_employee_by_email(store_id, (req.email or "").strip())
    if not emp or not emp.get("active"):
        print(f"[auth] ❌ Employee login miss for {store_id!r}/{req.email!r} from {ip}")
        raise HTTPException(401, "بريد إلكتروني أو كلمة مرور غير صحيحة")
    stored_emp_hash = emp.get("password_hash", "")
    if not _auth.check_password(req.password, stored_emp_hash):
        print(f"[auth] ❌ Employee bad password for {store_id!r}/{req.email!r}")
        raise HTTPException(401, "بريد إلكتروني أو كلمة مرور غير صحيحة")

    if _auth.needs_rehash(stored_emp_hash):
        try:
            await db.update_employee(emp["id"], password_hash=_auth.hash_password(req.password))
            print(f"[auth] 🔁 Upgraded password hash for employee {emp['email']!r}")
        except Exception as exc:
            print(f"[auth] ⚠️ Employee password hash upgrade failed: {exc}")

    token = _auth.create_token(
        store_id,
        employee_id=emp["id"],
        employee_name=emp["name"],
        employee_role=emp.get("role", "agent"),
    )
    info = sm.get_store_info(store_id)
    print(f"[auth] ✅ Employee login {emp['email']!r} for store {store_id!r}")
    return {
        "token":      token,
        "store_id":   store_id,
        "store_name": info.get("store_name", f"متجر {store_id}"),
        "employee":   {
            "id":   emp["id"],
            "name": emp["name"],
            "role": emp.get("role", "agent"),
        },
    }


# ─────────────────────────────────────────────────────────────────────────
# Unified email/password login
# ─────────────────────────────────────────────────────────────────────────
#
# Single endpoint the SPA calls regardless of who's logging in. We resolve
# the account from the email alone, then verify the password.
#
# Resolution order is intentional:
#   1. Super admin (env-driven, exact email match)
#   2. Employee (globally — emails are unique per store but we don't know
#      the store yet; if the same email exists in multiple stores we pick
#      the newest, see db.find_employee_by_email_any_store)
#   3. Store owner (owner_email column on stores, populated during
#      OAuth/install)
#
# Returns a uniform shape so the frontend doesn't have to switch on which
# endpoint succeeded. Same generic 401 message on every miss so callers
# can't probe whether an email exists.

@router.post("/auth/login")
async def unified_login(req: LoginRequest, request: Request):
    """
    Single email+password entry point. Replaces the three legacy paths:
      • POST /admin/auth/login                    → super admin
      • POST /admin/{store_id}/auth/login         → store owner
      • POST /admin/{store_id}/auth/employee-login → store employee

    The legacy endpoints are kept for back-compat with old clients.
    """
    ip        = request.client.host if request.client else "unknown"
    email_raw = (req.email or "").strip()
    email_in  = email_raw.lower()
    pwd_in    = req.password or ""

    if not email_in or not pwd_in:
        raise HTTPException(400, "البريد الإلكتروني وكلمة المرور مطلوبان")

    # One rate-limit bucket per email — keeps an attacker from spreading
    # attempts across accounts to bypass the per-account lockout.
    if await _is_rate_limited(f"login:{email_in}"):
        raise HTTPException(429, "محاولات تسجيل دخول كثيرة جداً. انتظر 5 دقائق وحاول مجدداً.")
    if await _is_rate_limited(f"login_ip:{ip}", max_attempts=20, window=300):
        raise HTTPException(429, "محاولات تسجيل دخول كثيرة جداً من هذا الجهاز.")

    generic_401 = HTTPException(401, "البريد الإلكتروني أو كلمة المرور غير صحيحة")

    # ── 1. Super admin ──────────────────────────────────────────────────
    super_email = os.getenv("SUPER_ADMIN_EMAIL", "").strip().lower()
    super_pass  = os.getenv("SUPER_ADMIN_PASSWORD", "")
    if hmac.compare_digest(email_in, super_email):
        if not hmac.compare_digest(pwd_in, super_pass):
            print(f"[auth] ❌ Super login bad password from {ip}")
            raise generic_401
        token = _auth.create_token("super", is_super=True)
        print(f"[auth] ✅ Super login ({email_in}) from {ip}")
        return {
            "token":      token,
            "store_id":   "super",
            "store_name": "لوحة الإدارة العامة",
            "is_super":   True,
            "employee":   None,
        }

    # ── 2. Employee (any store) ─────────────────────────────────────────
    emp = await db.find_employee_by_email_any_store(email_in)
    if emp:
        stored_hash = emp.get("password_hash", "")
        if not _auth.check_password(pwd_in, stored_hash):
            print(f"[auth] ❌ Employee bad password for {email_in!r} from {ip}")
            raise generic_401
        store_id = emp["store_id"]
        if _auth.needs_rehash(stored_hash):
            try:
                await db.update_employee(emp["id"], password_hash=_auth.hash_password(pwd_in))
            except Exception as exc:
                print(f"[auth] ⚠️ Employee hash upgrade failed: {exc}")
        token = _auth.create_token(
            store_id,
            employee_id   = emp["id"],
            employee_name = emp["name"],
            employee_role = emp.get("role", "agent"),
        )
        info = sm.get_store_info(store_id) or {}
        print(f"[auth] ✅ Employee login {email_in!r} for store {store_id!r}")
        return {
            "token":      token,
            "store_id":   store_id,
            "store_name": info.get("store_name", f"متجر {store_id}"),
            "is_super":   False,
            "employee":   {"id": emp["id"], "name": emp["name"], "role": emp.get("role", "agent")},
        }

    # ── 3. Store owner ──────────────────────────────────────────────────
    store_id = await db.find_store_by_owner_email(email_in)
    if store_id:
        stored_hash = sm.get_admin_password_hash(store_id)
        if not stored_hash or not _auth.check_password(pwd_in, stored_hash):
            print(f"[auth] ❌ Store owner bad password for {email_in!r} ({store_id!r}) from {ip}")
            raise generic_401
        if _auth.needs_rehash(stored_hash):
            try:
                await sm.set_admin_password(store_id, _auth.hash_password(pwd_in))
            except Exception as exc:
                print(f"[auth] ⚠️ Owner hash upgrade failed: {exc}")
        token = _auth.create_token(store_id)
        info  = sm.get_store_info(store_id) or {}
        print(f"[auth] ✅ Store owner login {email_in!r} ({store_id!r}) from {ip}")
        return {
            "token":      token,
            "store_id":   store_id,
            "store_name": info.get("store_name", f"متجر {store_id}"),
            "is_super":   False,
            "employee":   None,
        }

    # ── 4. Store ID direct lookup ───────────────────────────────────────
    # Allows owners who don't remember their email to log in with store_id + password.
    # Use raw (pre-lowercase) input so mixed-case store IDs are found correctly.
    store_id_candidate = email_raw
    if sm.is_registered(store_id_candidate):
        stored_hash = sm.get_admin_password_hash(store_id_candidate)
        if not stored_hash or not _auth.check_password(pwd_in, stored_hash):
            print(f"[auth] ❌ Store ID bad password for {store_id_candidate!r} from {ip}")
            raise generic_401
        if _auth.needs_rehash(stored_hash):
            try:
                await sm.set_admin_password(store_id_candidate, _auth.hash_password(pwd_in))
            except Exception as exc:
                print(f"[auth] ⚠️ Owner hash upgrade failed: {exc}")
        token = _auth.create_token(store_id_candidate)
        info  = sm.get_store_info(store_id_candidate) or {}
        print(f"[auth] ✅ Store ID login {store_id_candidate!r} from {ip}")
        return {
            "token":      token,
            "store_id":   store_id_candidate,
            "store_name": info.get("store_name", f"متجر {store_id_candidate}"),
            "is_super":   False,
            "employee":   None,
        }

    # No account matches — generic 401 (don't leak which side failed)
    print(f"[auth] ❌ No account for {email_in!r} from {ip}")
    raise generic_401


@router.get("/admin/{store_id}/auth/verify")
async def verify_store_token(store_id: str, request: Request):
    """
    Lightweight endpoint the admin SPA calls on page load to check
    whether its stored token is still valid without triggering a heavy
    data load. Returns 200 {ok: true} or 401.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims:
        raise HTTPException(401, "توكن منتهي أو غير صحيح")
    if not claims.get("su") and claims.get("s") != store_id:
        raise HTTPException(403, "غير مصرح")
    emp = None
    if "eid" in claims:
        emp = {
            "id":   int(claims.get("eid", 0)),
            "name": claims.get("en", ""),
            "role": claims.get("er", "agent"),
        }
    return {
        "ok":       True,
        "store_id": store_id,
        "is_super": claims.get("su", False),
        "employee": emp,
    }
