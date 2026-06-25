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
import re

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import database as db
import notifications as _notif
import store_manager as sm
from models import (EmployeeLoginRequest, ForgotPasswordRequest, LoginRequest,
                    OtpVerifyRequest, ResetPasswordRequest, SignupRequest)
from routers.deps import audit as _audit, is_rate_limited as _is_rate_limited


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

def _otp_enabled() -> bool:
    """Email-OTP gate. Default OFF so deploying the backend never breaks an
    older frontend that can't render the OTP step. Turn ON with OTP_ENABLED=true
    once the frontend OTP step is live AND RESEND_API_KEY is configured
    (otherwise users couldn't receive the code)."""
    return os.getenv("OTP_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


async def _resolve_login(email_raw: str, pwd_in: str) -> dict | None:
    """
    Resolve email/store-id + password to a full session-response dict, or None
    on any miss. Order: super → employee → owner(email) → owner(store-id).
    Single source of truth shared by unified_login and the OTP verify step.
    Legacy SHA-256 hashes are transparently upgraded on success (unchanged).
    """
    email_raw = (email_raw or "").strip()
    email_in  = email_raw.lower()
    pwd_in    = pwd_in or ""
    if not email_in or not pwd_in:
        return None

    # 1. Super admin (env-driven, exact email match)
    super_email = os.getenv("SUPER_ADMIN_EMAIL", "").strip().lower()
    super_pass  = os.getenv("SUPER_ADMIN_PASSWORD", "")
    if super_email and hmac.compare_digest(email_in, super_email):
        if not hmac.compare_digest(pwd_in, super_pass):
            return None
        return {
            "token":      _auth.create_token("super", is_super=True),
            "store_id":   "super",
            "store_name": "لوحة الإدارة العامة",
            "is_super":   True,
            "employee":   None,
        }

    # 2. Employee (any store)
    emp = await db.find_employee_by_email_any_store(email_in)
    if emp:
        stored_hash = emp.get("password_hash", "")
        if not _auth.check_password(pwd_in, stored_hash):
            return None
        store_id = emp["store_id"]
        if _auth.needs_rehash(stored_hash):
            try:
                await db.update_employee(emp["id"], password_hash=_auth.hash_password(pwd_in))
            except Exception as exc:
                print(f"[auth] ⚠️ Employee hash upgrade failed: {exc}")
        info = sm.get_store_info(store_id) or {}
        return {
            "token":      _auth.create_token(store_id, employee_id=emp["id"],
                                             employee_name=emp["name"],
                                             employee_role=emp.get("role", "agent")),
            "store_id":   store_id,
            "store_name": info.get("store_name", f"متجر {store_id}"),
            "is_super":   False,
            "employee":   {"id": emp["id"], "name": emp["name"], "role": emp.get("role", "agent")},
        }

    # 3. Store owner (by owner_email)
    store_id = await db.find_store_by_owner_email(email_in)
    if store_id:
        stored_hash = sm.get_admin_password_hash(store_id)
        if not stored_hash or not _auth.check_password(pwd_in, stored_hash):
            return None
        if _auth.needs_rehash(stored_hash):
            try:
                await sm.set_admin_password(store_id, _auth.hash_password(pwd_in))
            except Exception as exc:
                print(f"[auth] ⚠️ Owner hash upgrade failed: {exc}")
        info = sm.get_store_info(store_id) or {}
        return {
            "token":      _auth.create_token(store_id),
            "store_id":   store_id,
            "store_name": info.get("store_name", f"متجر {store_id}"),
            "is_super":   False,
            "employee":   None,
        }

    # 4. Store-id direct (raw input — store ids can be mixed-case)
    cand = email_raw
    if cand and sm.is_registered(cand):
        stored_hash = sm.get_admin_password_hash(cand)
        if not stored_hash or not _auth.check_password(pwd_in, stored_hash):
            return None
        if _auth.needs_rehash(stored_hash):
            try:
                await sm.set_admin_password(cand, _auth.hash_password(pwd_in))
            except Exception as exc:
                print(f"[auth] ⚠️ Owner hash upgrade failed: {exc}")
        info = sm.get_store_info(cand) or {}
        return {
            "token":      _auth.create_token(cand),
            "store_id":   cand,
            "store_name": info.get("store_name", f"متجر {cand}"),
            "is_super":   False,
            "employee":   None,
        }

    return None


async def _begin_otp(email: str, purpose: str, send_to: str = "") -> dict:
    """Generate a code, email it, and return the signed challenge for the client
    to echo back at /auth/otp/verify. Raises 502 if the email can't be sent.

    `email`   — used for the HMAC challenge (may be a store_id or real email).
    `send_to` — the actual email address to deliver to; falls back to `email`
                when not provided (the normal path where the input IS an email).
    """
    code      = _auth.generate_otp_code()
    challenge = _auth.make_otp_challenge(email, purpose, code)
    dest      = (send_to or email).strip()
    if not dest or "@" not in dest:
        raise HTTPException(502, "تعذّر إرسال رمز التحقق — لا يوجد بريد إلكتروني مرتبط بهذا الحساب. يرجى التواصل مع الدعم.")
    if not await _notif.send_otp_email(dest, code, purpose):
        raise HTTPException(502, "تعذّر إرسال رمز التحقق إلى بريدك الإلكتروني. حاول لاحقاً.")
    return {"otp_required": True, "challenge": challenge}


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

    resolved = await _resolve_login(email_raw, pwd_in)
    if not resolved:
        print(f"[auth] ❌ Failed unified login from {ip}")
        raise generic_401

    # Super admin uses env credentials only — never gated by email OTP.
    if resolved.get("is_super"):
        print(f"[auth] ✅ Super login from {ip}")
        return resolved

    # Email 2FA: require a one-time code unless this device already passed one
    # within the 30-day trust window. Transparent no-op when OTP is disabled.
    if _otp_enabled() and not _auth.device_trust_valid(req.device_token or "", email_in):
        print(f"[auth] 🔐 OTP required for login from {ip}")
        # When the user logged in with a store_id (no "@"), we need the real
        # owner email as the OTP destination — store_id is not a valid email.
        send_to = email_in
        if "@" not in email_in:
            send_to = (await db.get_store_owner_email(email_raw) or "").lower()
        return await _begin_otp(email_in, "login", send_to=send_to)

    print(f"[auth] ✅ Unified login ({resolved['store_id']!r}) from {ip}")
    return resolved


# ─────────────────────────────────────────────────────────────────────────
# Self-service signup
# ─────────────────────────────────────────────────────────────────────────
#
# Creates a platform-independent 7ayak account. Salla auto-provisions accounts
# on install and Zid offers a "create account" tab in its marketplace start
# page, but a merchant on Shopify (or no platform yet) previously had no way to
# sign up at all. This endpoint closes that gap: the merchant gets an account +
# token immediately and links a platform afterwards from the Integrations page.
#
# Reuses the exact account-creation sequence as routers.integrations.zid_start_post.

async def _create_signup_account(name: str, email: str, pwd: str) -> dict:
    """Create a platform-less 7ayak account + return a session response. Re-checks
    validation + uniqueness so it's safe to call after the OTP step (raises 409 if
    the email got taken in the meantime)."""
    name  = (name or "").strip()
    email = (email or "").strip().lower()
    pwd   = pwd or ""
    if not name:
        raise HTTPException(400, "الاسم الكامل مطلوب")
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "البريد الإلكتروني غير صالح")
    if len(pwd) < 8:
        raise HTTPException(400, "كلمة المرور يجب أن تكون 8 أحرف على الأقل")

    taken = HTTPException(409, "هذا البريد مستخدم بالفعل. سجّل الدخول بدلاً من ذلك.")
    super_email = os.getenv("SUPER_ADMIN_EMAIL", "").strip().lower()
    if super_email and hmac.compare_digest(email, super_email):
        raise taken
    if await db.find_store_by_owner_email(email):
        raise taken
    if await db.find_employee_by_email_any_store(email):
        raise taken

    slug = re.sub(r"[^a-z0-9]", "_", email.split("@")[0].lower())[:20] or "store"
    store_id = slug
    suffix = 2
    while sm.is_registered(store_id):
        store_id = f"{slug}_{suffix}"
        suffix += 1

    try:
        await sm.register_store(store_id=store_id, access_token="",
                                store_info={"name": name}, owner_email=email)
        tokens = sm.get_store_info(store_id)
        await db.save_store(store_id, tokens)
        await db.set_store_owner_email(store_id, email)
        await sm.set_admin_password(store_id, _auth.hash_password(pwd))
        print(f"[auth] ✅ Self-service signup: store_id={store_id!r}")
    except Exception as exc:
        print(f"[auth] ❌ signup creation failed: {exc}")
        raise HTTPException(500, "تعذّر إنشاء الحساب، يرجى المحاولة مرة أخرى")

    return {
        "token":      _auth.create_token(store_id),
        "store_id":   store_id,
        "store_name": name,
        "is_super":   False,
        "employee":   None,
    }


@router.post("/auth/signup")
async def signup(req: SignupRequest, request: Request):
    ip    = request.client.host if request.client else "unknown"
    name  = (req.name or "").strip()
    email = (req.email or "").strip().lower()
    pwd   = req.password or ""

    # Throttle automated account creation by IP.
    if await _is_rate_limited(f"signup_ip:{ip}", max_attempts=10, window=600):
        raise HTTPException(429, "محاولات كثيرة جداً. انتظر قليلاً ثم حاول مجدداً.")

    # ── Validation ──────────────────────────────────────────────────────
    if not name:
        raise HTTPException(400, "الاسم الكامل مطلوب")
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "البريد الإلكتروني غير صالح")
    if len(pwd) < 8:
        raise HTTPException(400, "كلمة المرور يجب أن تكون 8 أحرف على الأقل")

    # ── Email must be unique across every account type, so unified login
    #    resolves it unambiguously (super admin → employee → owner). ──────
    taken = HTTPException(409, "هذا البريد مستخدم بالفعل. سجّل الدخول بدلاً من ذلك.")
    super_email = os.getenv("SUPER_ADMIN_EMAIL", "").strip().lower()
    if super_email and hmac.compare_digest(email, super_email):
        raise taken
    if await db.find_store_by_owner_email(email):
        raise taken
    if await db.find_employee_by_email_any_store(email):
        raise taken

    # OTP gate — confirm the email owns this address before creating the account.
    if _otp_enabled():
        print(f"[auth] 🔐 OTP required for signup from {ip}")
        return await _begin_otp(email, "signup")

    return await _create_signup_account(name, email, pwd)


@router.post("/auth/otp/verify")
async def otp_verify(req: OtpVerifyRequest, request: Request):
    """
    Second step of OTP-gated signup/login: validate the emailed 6-digit code
    against the signed challenge, then complete the original action and return a
    session (plus a 30-day device-trust token when remember_device is set).
    """
    ip      = request.client.host if request.client else "unknown"
    email   = (req.email or "").strip().lower()
    purpose = (req.purpose or "").strip()
    if purpose not in ("login", "signup"):
        raise HTTPException(400, "نوع تحقق غير صالح")

    # Brute-force cap on the verify endpoint. The challenge carries only an
    # HMAC of the code (keyed by ADMIN_SECRET), so offline guessing is
    # impossible; this bounds online attempts.
    if await _is_rate_limited(f"otp_vrf:{email}", max_attempts=6, window=600):
        raise HTTPException(429, "محاولات كثيرة. اطلب رمزاً جديداً وحاول لاحقاً.")

    if not _auth.verify_otp_challenge(req.challenge or "", email, purpose, req.code or ""):
        raise HTTPException(401, "رمز التحقق غير صحيح أو منتهي الصلاحية")

    if purpose == "login":
        # Re-resolve with the RAW email so store-id (mixed-case) login still works.
        resolved = await _resolve_login(req.email or "", req.password or "")
        if not resolved:
            raise HTTPException(401, "البريد الإلكتروني أو كلمة المرور غير صحيحة")
        resp = dict(resolved)
        print(f"[auth] ✅ OTP login verified ({resp['store_id']!r}) from {ip}")
    else:  # signup
        resp = await _create_signup_account(req.name or "", email, req.password or "")
        print(f"[auth] ✅ OTP signup verified ({resp['store_id']!r}) from {ip}")

    if req.remember_device:
        resp["device_token"] = _auth.make_device_trust(email)
    return resp


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


# ─────────────────────────────────────────────────────────────────────────
# Seamless session migration after signup → Salla linking
# ─────────────────────────────────────────────────────────────────────────

@router.post("/auth/resolve-link")
async def resolve_link(request: Request):
    """
    Trade a session token bound to a just-merged signup placeholder for a fresh
    token on the canonical Salla store — so the merchant's dashboard recovers
    WITHOUT a re-login after they link Salla.

    Flow it fixes: /auth/signup creates a placeholder store keyed by an email
    slug, and the browser's token is bound to that id. When the merchant links
    Salla (app-settings API key / authorize webhook), the placeholder is merged
    into the Salla merchant store and deleted — leaving the still-open token
    pointing at a dead store (→ 403 "no access"). This endpoint follows the
    forwarding breadcrumb (db.record_account_forward) and mints a new token.

    Authorization: the presented token must be a cryptographically valid OWNER
    token (signature + unexpired) whose store no longer exists locally AND has a
    recorded forward. That triple-binds it to the legitimate signer — the only
    party that ever held this token — so it cannot be used to jump between live
    stores (a token for a still-registered store is rejected).
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims:
        raise HTTPException(401, "يرجى تسجيل الدخول")

    no_pending = HTTPException(404, "لا يوجد ربط معلّق لهذه الجلسة")

    # Super + employee tokens are never placeholder owners — nothing to migrate.
    if claims.get("su") or "eid" in claims:
        raise no_pending

    old_store = (claims.get("s") or "").strip()
    if not old_store:
        raise no_pending

    # DB-authoritative — the in-memory registry is PER-PROCESS, so on a multi
    # web-replica / worker deploy the merge+unregister can happen on a different
    # process than the one serving this request. Relying on sm.is_registered()
    # here returned a false 404 ("h123asham still registered locally") even
    # though the placeholder was already merged + deleted in the shared DB. The
    # forwarding breadcrumb lives in the DB, so it's the source of truth.
    new_store = await db.resolve_account_forward(old_store)
    if not new_store:
        raise no_pending

    # A token for a STILL-LIVE store must not be forwarded (reused-slug guard):
    # the old placeholder must be GONE from the shared DB. sync_one_from_db also
    # evicts the stale local registry entry as a side effect. True ⇒ still live.
    if await sm.sync_one_from_db(old_store):
        raise no_pending

    # Load the canonical store into THIS process so the minted token works here
    # immediately; refuse if it doesn't actually exist in the DB.
    if not await sm.sync_one_from_db(new_store):
        raise no_pending

    info      = sm.get_store_info(new_store)
    new_token = _auth.create_token(new_store)
    print(f"[auth] 🔁 seamless link migration: {old_store!r} → {new_store!r}")
    # Security-relevant: a new owner token was minted off a dead placeholder
    # token. Record who/where for post-incident review.
    await _audit(request, "session_migrated_after_link",
                 target_store=new_store, details={"from": old_store})
    return {
        "token":      new_token,
        "store_id":   new_store,
        "store_name": info.get("store_name", f"متجر {new_store}"),
        "is_super":   False,
        "employee":   None,
    }


# ─────────────────────────────────────────────────────────────────────────
# Forgot / Reset password
# ─────────────────────────────────────────────────────────────────────────

@router.post("/auth/forgot-password")
async def forgot_password(req: ForgotPasswordRequest, request: Request):
    """
    Send a password-reset link to the given email or store-id.
    Always returns 200 so callers cannot probe whether an account exists.
    """
    ip    = request.client.host if request.client else "unknown"
    raw   = (req.email or "").strip()

    if not raw:
        raise HTTPException(400, "يرجى إدخال البريد الإلكتروني أو معرّف المتجر")

    if await _is_rate_limited(f"forgot:{raw.lower()}", max_attempts=3, window=600):
        raise HTTPException(429, "طلبات كثيرة جداً. انتظر 10 دقائق وحاول مجدداً.")

    # Resolve the email address to send to
    if "@" in raw:
        # Input is an email address
        email = raw.lower()
    else:
        # Input is a store_id — look up its owner email
        owner_email = await db.get_store_owner_email(raw)
        if not owner_email:
            # Could also be an employee — but employees don't have a store_id login.
            # Silently succeed so we don't reveal whether a store_id exists.
            print(f"[auth] 🔑 Forgot password for unknown store_id {raw!r} — silently ignored")
            return {"ok": True, "message": "إذا كان المعرّف مسجّلاً، ستصلك رسالة بتعليمات إعادة التعيين."}
        email = owner_email.strip().lower()

    token     = _auth.make_reset_token(email)
    reset_url = f"{os.getenv('BASE_URL', 'https://7ayak.app')}/reset-password?token={token}"

    store_id = await db.find_store_by_owner_email(email)
    emp      = await db.find_employee_by_email_any_store(email)
    if store_id or emp:
        await _notif.send_password_reset_email(email, reset_url)
        print(f"[auth] 🔑 Password reset email sent to {email!r} from {ip}")
    else:
        print(f"[auth] 🔑 Forgot password for unknown email {email!r} — silently ignored")

    return {"ok": True, "message": "إذا كان الحساب مسجّلاً، ستصلك رسالة بتعليمات إعادة التعيين."}


@router.post("/auth/reset-password")
async def reset_password_with_token(req: ResetPasswordRequest, request: Request):
    """Consume a reset token and update the account password."""
    ip = request.client.host if request.client else "unknown"

    if await _is_rate_limited(f"reset_ip:{ip}", max_attempts=10, window=600):
        raise HTTPException(429, "محاولات كثيرة. انتظر قليلاً ثم حاول مجدداً.")

    email = _auth.verify_reset_token(req.token or "")
    if not email:
        raise HTTPException(400, "رابط إعادة التعيين غير صالح أو منتهي الصلاحية")

    new_pwd = req.new_password or ""
    if len(new_pwd) < 8:
        raise HTTPException(400, "كلمة المرور يجب أن تكون 8 أحرف على الأقل")

    new_hash = _auth.hash_password(new_pwd)

    store_id = await db.find_store_by_owner_email(email)
    if store_id:
        await sm.set_admin_password(store_id, new_hash)
        print(f"[auth] ✅ Password reset: owner {email!r} (store {store_id!r}) from {ip}")
        return {"ok": True, "message": "تم تحديث كلمة المرور بنجاح. يمكنك تسجيل الدخول الآن."}

    emp = await db.find_employee_by_email_any_store(email)
    if emp:
        await db.update_employee(emp["id"], password_hash=new_hash)
        print(f"[auth] ✅ Password reset: employee {email!r} from {ip}")
        return {"ok": True, "message": "تم تحديث كلمة المرور بنجاح. يمكنك تسجيل الدخول الآن."}

    raise HTTPException(404, "لم يُعثر على حساب مرتبط بهذا البريد الإلكتروني")
