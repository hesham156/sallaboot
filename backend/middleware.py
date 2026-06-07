"""
HTTP middleware — auth + CORS.

Both middlewares are designed to be registered on a FastAPI app via
`app.middleware('http')(fn)`. They were lifted from main.py during the
Phase 2 modularisation; behaviour is unchanged.

Order of registration matters: Starlette wraps in reverse registration
order, so the LAST registered becomes the OUTERMOST. In main.py we
register admin_auth_middleware first, cors_middleware second → CORS
wraps auth → preflight responses + auth-rejection responses both carry
the right Access-Control headers.
"""
from __future__ import annotations

import os
import re

from fastapi import Request
from fastapi.responses import JSONResponse

import auth as _auth


# ─────────────────────────────────────────────────────────────────────────
# Auth middleware
# ─────────────────────────────────────────────────────────────────────────
# Protects all per-store admin API routes (not the HTML pages or auth
# endpoints themselves).

_PROTECTED_RE = re.compile(
    r"^/admin/(?!stores$|auth/)([^/]+)/(conversations|bot|sync|products|debug|settings|webhooks|abandoned-carts|analytics|orders|info|employees)"
)
_SUPER_PROTECTED_RE = re.compile(r"^/admin/stores$")

# Paths that an "agent" employee MUST NOT reach (manager + owner only).
# Conversations / orders / abandoned-carts / info / bot status stay open
# because that's the customer-service work they're hired to do.
_MANAGER_ONLY_RE = re.compile(
    r"^/admin/(?!stores$|auth/)[^/]+/(settings|analytics|sync|products|debug|webhooks|training|brain|pricing)"
)
# Owner-only paths (blocks BOTH agents and managers).
_OWNER_ONLY_RE = re.compile(
    r"^/admin/(?!stores$|auth/)[^/]+/(employees|settings/password)"
)


async def admin_auth_middleware(request: Request, call_next):
    """
    Bearer-token enforcement for per-store admin routes + role-based
    gating for employees. Adds defensive security headers to all
    responses on the way back.
    """
    path = request.url.path

    # Per-store API routes
    m = _PROTECTED_RE.match(path)
    if m:
        store_id = m.group(1)
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        claims = _auth.verify_token(token)
        if not claims:
            return JSONResponse({"detail": "يرجى تسجيل الدخول"}, status_code=401)
        if not claims.get("su") and claims.get("s") != store_id:
            return JSONResponse({"detail": "غير مصرح لك بالوصول"}, status_code=403)

        # Role-based gating (super always passes). The store owner has no
        # "eid" claim; managers have eid+er=manager; agents have eid+er=agent.
        if not claims.get("su") and "eid" in claims:
            role = claims.get("er", "agent")
            if _OWNER_ONLY_RE.match(path):
                return JSONResponse(
                    {"detail": "هذا الإجراء مخصّص لمالك المتجر"}, status_code=403,
                )
            if role == "agent" and _MANAGER_ONLY_RE.match(path):
                return JSONResponse(
                    {"detail": "صلاحيتك لا تسمح بهذا الإجراء"}, status_code=403,
                )

    # Super admin: protect store list
    elif _SUPER_PROTECTED_RE.match(path):
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        claims = _auth.verify_token(token)
        if not claims or not claims.get("su"):
            return JSONResponse({"detail": "يرجى تسجيل الدخول كمدير عام"}, status_code=401)

    response = await call_next(request)

    # ── Security hardening headers (defense-in-depth) ─────────────────
    # nosniff + a sane referrer policy are safe everywhere. Clickjacking
    # protection is applied only to the admin dashboard pages — never the
    # script-injected widget or the /chat API, so embedding still works.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if path == "/admin" or path.startswith("/admin/"):
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


# ─────────────────────────────────────────────────────────────────────────
# CORS middleware (split by path)
# ─────────────────────────────────────────────────────────────────────────
# The widget runs cross-origin from every merchant's storefront domain,
# so /chat, /chat/poll, /upload, /file/, /widget.js, /whatsapp/webhook
# must keep allow_origins=*. The admin SPA, however, is served from
# BASE_URL (and optionally from a configured dev origin). Leaving
# /admin/* with allow_* would let any rogue page in any browser tab
# make authenticated calls to a logged-in merchant's account if they
# could steal a Bearer token via XSS.
#
# Implementation: one custom middleware decides per-request whether to
# echo the request Origin (allowed) or omit ACAO entirely (browser
# blocks).
#
# Configure via env:
#   BASE_URL              — admin SPA origin (e.g. https://sallabot.app)
#   ADMIN_ALLOWED_ORIGINS — extra CSV (e.g. http://localhost:3000,...)

def _build_admin_origin_allowlist() -> set[str]:
    raw = os.getenv("ADMIN_ALLOWED_ORIGINS", "")
    origins = {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}
    base = os.getenv("BASE_URL", "").strip().rstrip("/")
    if base:
        origins.add(base)
    # Always include localhost dev ports (no harm; reqs to prod need
    # cred-less bearer tokens which a local page can't see anyway).
    origins.update({
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:5173", "http://127.0.0.1:5173",
    })
    return origins


_ADMIN_ORIGIN_ALLOWLIST = _build_admin_origin_allowlist()
_ADMIN_CORS_PATH_RE = re.compile(r"^/(admin|store)(/|$)")

# Methods/headers/exposed-headers used in both the strict and permissive paths.
_CORS_METHODS = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
_CORS_HEADERS = "Authorization, Content-Type, X-Salla-Signature, X-Requested-With"


async def cors_middleware(request: Request, call_next):
    """
    Outermost middleware (declared last → wraps everything). Echoes
    Origin selectively depending on path. CORS-preflight (OPTIONS) is
    short-circuited without invoking downstream handlers.
    """
    origin = request.headers.get("Origin", "")
    path   = request.url.path
    is_admin_path = bool(_ADMIN_CORS_PATH_RE.match(path))

    if is_admin_path:
        allow = origin in _ADMIN_ORIGIN_ALLOWLIST
        allowed_origin = origin if allow else ""
    else:
        # Public widget surface — any origin OK.
        allowed_origin = origin if origin else "*"

    if request.method == "OPTIONS":
        # Preflight — answer directly so an unauthenticated OPTIONS
        # doesn't trip auth middleware.
        headers = {
            "Access-Control-Allow-Methods": _CORS_METHODS,
            "Access-Control-Allow-Headers": request.headers.get(
                "Access-Control-Request-Headers", _CORS_HEADERS
            ),
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        }
        if allowed_origin:
            headers["Access-Control-Allow-Origin"] = allowed_origin
        return JSONResponse({}, status_code=204, headers=headers)

    response = await call_next(request)
    if allowed_origin:
        response.headers["Access-Control-Allow-Origin"] = allowed_origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Expose-Headers"] = "*"
    return response


def register(app) -> None:
    """
    Register both middlewares on a FastAPI app in the correct order so
    CORS wraps auth (last-registered = outermost in Starlette).
    """
    app.middleware("http")(admin_auth_middleware)
    app.middleware("http")(cors_middleware)
