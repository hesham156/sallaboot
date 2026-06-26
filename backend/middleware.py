"""
HTTP middleware — request-id, auth + CORS.

Three middlewares registered in order. Starlette wraps in reverse
registration order, so the LAST registered becomes the OUTERMOST. We
register:
  1. request_id_middleware   (innermost — first to run on the request,
                              last to run on the response)
  2. admin_auth_middleware
  3. cors_middleware         (outermost — sees every preflight + reply)

Result: CORS wraps auth (so preflight + 401/403 responses carry the
right Access-Control headers), and BOTH are wrapped by request_id so
even an auth-rejection log line carries the request id.
"""
from __future__ import annotations

import os
import re
import time

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.datastructures import MutableHeaders

import auth as _auth
import log as _logmod


def _is_browser_navigation(request: Request) -> bool:
    """
    True when the caller looks like a person typing/pasting a URL rather
    than the SPA's fetch() wrapper. We use this to redirect them to the
    login screen instead of returning raw JSON 401 they can't read.

    Heuristic: text/html in Accept AND it's a GET (POSTing JSON via
    browser address bar isn't a thing). Same idea as main._wants_html
    but localised here so the middleware doesn't depend on main.
    """
    if request.method != "GET":
        return False
    accept = (request.headers.get("Accept") or "").lower()
    return "text/html" in accept


# ─────────────────────────────────────────────────────────────────────────
# Auth middleware
# ─────────────────────────────────────────────────────────────────────────
# Protects all per-store admin API routes (not the HTML pages or auth
# endpoints themselves).

_PROTECTED_RE = re.compile(
    r"^/admin/(?!stores$|auth/)([^/]+)/(conversations|bot|sync|products|debug|settings|webhooks|abandoned-carts|analytics|orders|info|employees|llm-usage|llm-budget|audit-log|support-access|whatsapp|meta|segments|integrations|channels|api-key)"
)
_SUPER_PROTECTED_RE = re.compile(r"^/admin/stores$")

# Sub-paths that a super admin can hit on a foreign store WITHOUT an
# active grant: viewing/managing grants is how access gets enabled in
# the first place, and conversations-list summaries are no worse than
# the platform-ops aggregates we already expose.
_SUPER_NO_GRANT_NEEDED_SUFFIXES = ("support-access",)

# System-owned stores that have no human owner — the super admin is the
# owner, so the JIT support-access gate doesn't make sense. Currently
# just the demo store registered by bootstrap.py. Kept in sync with
# routers/webhooks._RESERVED_IDS via review (small enough to duplicate).
_SYSTEM_STORES = {"sallabot"}

# Paths that an "agent" employee MUST NOT reach (manager + owner only).
# Conversations / orders / abandoned-carts / info / bot status stay open
# because that's the customer-service work they're hired to do.
_MANAGER_ONLY_RE = re.compile(
    r"^/admin/(?!stores$|auth/)[^/]+/(settings|analytics|sync|products|debug|webhooks|training|brain|pricing|llm-usage|llm-budget|audit-log|whatsapp|meta|segments)"
)
# Owner-only paths (blocks BOTH agents and managers). llm-budget is here
# because raising/lowering the daily token cap is a financial-risk knob —
# managers can VIEW usage (above) but only the owner can change the cap.
_OWNER_ONLY_RE = re.compile(
    r"^/admin/(?!stores$|auth/)[^/]+/(employees|settings/password|settings/account-email|llm-budget)"
)


async def _auth_reject(request: Request):
    """
    Bearer-token enforcement for per-store admin routes + role-based gating for
    employees. Returns a Response to REJECT the request, or None to allow it.
    Also performs the best-effort cross-process registry sync side-effect.

    Pure decision function (no call_next) so it can run inside the pure-ASGI
    GatewayMiddleware below.
    """
    path = request.url.path

    # Per-store API routes
    m = _PROTECTED_RE.match(path)
    if m:
        store_id = m.group(1)
        sub_path = m.group(2)
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        claims = _auth.verify_token(token)
        if not claims:
            # Browser-typed URL on an API endpoint → redirect to login
            # (the SPA shell handles the rest, including the post-login
            # navigation). Without this the user sees a raw JSON 401.
            if _is_browser_navigation(request):
                return RedirectResponse(url="/login", status_code=302)
            return JSONResponse({"detail": "يرجى تسجيل الدخول"}, status_code=401)
        if not claims.get("su") and claims.get("s") != store_id:
            return JSONResponse({"detail": "غير مصرح لك بالوصول"}, status_code=403)

        # ── Session revocation (H-2) ───────────────────────────────────
        # verify_token() only checks signature + expiry. Re-validate the
        # principal against current backing state so a fired / deactivated /
        # demoted employee — or an owner who just reset their password — loses
        # access immediately instead of riding a still-valid 7-day token. Shared
        # with the inline guards (deps.session_is_revoked) so enforcement is
        # identical everywhere; the helper fails open on any backend hiccup.
        from routers import deps as _deps
        if await _deps.session_is_revoked(claims, store_id):
            return JSONResponse(
                {"detail": "انتهت الجلسة، يرجى تسجيل الدخول مجدداً"},
                status_code=401,
            )

        # ── Super-admin JIT access gate ────────────────────────────────
        # Cross-store super reads now REQUIRE a time-boxed grant from the
        # merchant. The store's owner endpoints for granting (under
        # /support-access) are whitelisted so the merchant can actually
        # let the super in. Auth paths aren't reached here (PROTECTED_RE
        # excludes them already).
        is_super_cross_store = (
            claims.get("su") and (claims.get("s") or "") != store_id
        )
        # System-owned stores (no human owner) have no one to grant
        # access — super is the de-facto owner. Skip the JIT gate.
        if is_super_cross_store and store_id in _SYSTEM_STORES:
            is_super_cross_store = False
        if is_super_cross_store and not any(
            sub_path == s or sub_path.startswith(s + "/")
            for s in _SUPER_NO_GRANT_NEEDED_SUFFIXES
        ):
            # Import lazily — keeps middleware light at import time and
            # avoids pulling main.py's heavy dependency tree into this
            # module's load path.
            import database as _db
            grant = await _db.support_access_active(store_id)
            if not grant:
                # Distinct error code so the frontend can render a
                # specific "ask the merchant" page rather than a generic
                # 403. Localised message in 'detail_ar' for the UI.
                return JSONResponse(
                    {
                        "detail":     "support_access_required",
                        "detail_ar":  "يلزم إذن من مالك المتجر قبل الدخول.",
                    },
                    status_code=403,
                )

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

        # ── Cross-process registry coherence ───────────────────────────
        # The in-memory store registry is PER-PROCESS. A store registered (new
        # install) or re-pointed (signup→Salla link migration) on another web
        # replica / the worker is invisible here until reload — so the handler
        # would see an empty/stale store. If it's missing locally but lives in
        # the shared DB, load it now. Best-effort and only on a miss: one DB
        # read per unknown store per process lifetime, never blocks the request.
        try:
            import store_manager as _sm
            if not _sm.is_registered(store_id):
                await _sm.sync_one_from_db(store_id)
        except Exception:
            pass

    # Super admin: protect store list
    elif _SUPER_PROTECTED_RE.match(path):
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        claims = _auth.verify_token(token)
        if not claims or not claims.get("su"):
            # Browser typed /admin/stores expecting the stores page — the
            # SPA route for that is /admin (this URL is the JSON API it
            # calls internally). Redirect to /admin: if not logged in,
            # the SPA's RequireSuper bounces to /login; if logged in as
            # super, the SPA renders the page and re-fetches this same
            # endpoint with the Bearer header attached.
            if _is_browser_navigation(request):
                return RedirectResponse(url="/admin", status_code=302)
            return JSONResponse({"detail": "يرجى تسجيل الدخول كمدير عام"}, status_code=401)

    # Allowed — GatewayMiddleware applies CORS + security headers on the way out.
    return None


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
#   BASE_URL              — admin SPA origin (e.g. https://7ayak.app)
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


def _apply_security_headers(headers, path: str) -> None:
    """Defensive response headers (finding M-18). Applied to EVERY response —
    including the auth-rejection 401/403s and streaming responses. `headers` is a
    MutableHeaders (a Response.headers or one built over a raw ASGI header list).

    nosniff + referrer + HSTS + Permissions-Policy are safe everywhere. The
    clickjacking/CSP set is scoped to the dashboard only (never the
    script-injected widget or the /chat API, so storefront embedding keeps
    working).
    """
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # HSTS — pin clients to HTTPS for a year (incl. subdomains). Browsers honour
    # it only over HTTPS, so it's safe to send everywhere (Railway terminates TLS).
    headers.setdefault(
        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
    )
    headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), browsing-topics=()",
    )
    # Anti-clickjacking on every authenticated dashboard surface (finding A-1):
    # the SPA is served at /admin*, the per-merchant dashboard at /store/*, and
    # the credential entry at /login. The storefront widget (/widget.js, /chat,
    # /file, /upload) is intentionally excluded so it keeps embedding in
    # merchant themes.
    is_dashboard = (
        path in ("/admin", "/store", "/login")
        or path.startswith("/admin/")
        or path.startswith("/store/")
    )
    if is_dashboard:
        headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        # `script-src 'self'` is the core anti-XSS control for the dashboard (M4):
        # blocks injected inline + externally-hosted scripts from exfiltrating the
        # bearer token. The SPA loads only its own /assets bundle (same-origin);
        # inline JSON-LD is a non-executable data block; the inline-<script> pages
        # (OAuth callback, /snippet) aren't dashboard paths and never get this CSP.
        #
        # connect.facebook.net is the ONE allowed external script origin: it serves
        # the Facebook JS SDK that powers the WhatsApp Embedded Signup and the
        # Messenger/Instagram (and comment) page-connect popup. Without it the SDK
        # <script> is blocked, onerror fires, and the connect UI shows
        # "غير متاح" even when META_APP_ID is configured. Meta's CDN is trusted;
        # no 'unsafe-inline' is granted, so the anti-token-exfil property holds.
        #
        # static.cloudflareinsights.com serves the Web-Analytics beacon that
        # Cloudflare auto-injects when the site is proxied through it. It is not
        # ours to remove, so allow it to stop the noisy CSP violation in the
        # console; it only reads page-load timings (no token access).
        headers.setdefault(
            "Content-Security-Policy",
            "script-src 'self' https://connect.facebook.net https://static.cloudflareinsights.com; "
            "frame-ancestors 'self'; base-uri 'self'; object-src 'none'",
        )


def _cors_allowed_origin(request: Request, path: str) -> str:
    """The Origin to echo in Access-Control-Allow-Origin, or '' to omit it."""
    origin = request.headers.get("Origin", "")
    if _ADMIN_CORS_PATH_RE.match(path):
        return origin if origin in _ADMIN_ORIGIN_ALLOWLIST else ""
    # Public widget surface — any origin OK.
    return origin if origin else "*"


# ─────────────────────────────────────────────────────────────────────────
# Request-ID middleware (innermost)
# ─────────────────────────────────────────────────────────────────────────

_log = _logmod.get_logger("backend.request")

# Endpoints we DON'T log per-request (high-volume, low-value). Keeps the
# log volume sane in production. Errors and slow requests still surface
# because each subsystem logs its own important events.
_QUIET_PATHS = (
    "/health",
    "/widget.js",
    "/assets/",
    "/uploads/",
    "/admin/",  # we log admin requests but only when they fail or are slow — see below
)


def _is_quiet_path(path: str) -> bool:
    # Always-quiet paths: health/widget/assets — these get hit constantly.
    if path in ("/health", "/widget.js"):
        return True
    if path.startswith("/assets/") or path.startswith("/uploads/"):
        return True
    return False


class GatewayMiddleware:
    """
    Single PURE-ASGI middleware: request-id + auth gating + CORS + security
    headers + request logging, in one pass.

    Why pure ASGI (not BaseHTTPMiddleware / @app.middleware("http")):
    BaseHTTPMiddleware buffers the response through an anyio memory stream and
    re-emits it, which is incompatible with streaming responses and intermittently
    raised `RuntimeError: Response content longer than Content-Length` on the SSE
    endpoints (/chat/stream, /admin/{store}/stream) and other paths. A pure ASGI
    middleware instead injects headers on the `http.response.start` message and
    forwards every `http.response.body` chunk untouched, so streaming works and
    the Content-Length the downstream set is never invalidated.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        path = request.url.path
        allowed_origin = _cors_allowed_origin(request, path)

        rid = request.headers.get("X-Request-ID", "").strip() or _logmod.new_request_id()
        _logmod.set_request_id(rid)

        # ── CORS preflight — answer directly (an unauthenticated OPTIONS must not
        #    trip the auth gate). ───────────────────────────────────────────────
        if request.method == "OPTIONS":
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
            # 204 No Content MUST have an empty body — a JSONResponse({}) would
            # emit a 2-byte `{}` and uvicorn rejects body-on-204 with "Response
            # content longer than Content-Length". Use a bodiless Response.
            resp = Response(status_code=204, headers=headers)
            _apply_security_headers(resp.headers, path)
            resp.headers.setdefault("X-Request-ID", rid)
            await resp(scope, receive, send)
            return

        # ── Auth gate — reject early with a fully-decorated response. ───────────
        reject = await _auth_reject(request)
        if reject is not None:
            if allowed_origin:
                reject.headers["Access-Control-Allow-Origin"] = allowed_origin
                reject.headers["Vary"] = "Origin"
                reject.headers["Access-Control-Expose-Headers"] = "*"
            _apply_security_headers(reject.headers, path)
            reject.headers.setdefault("X-Request-ID", rid)
            await reject(scope, receive, send)
            return

        # ── Pass through, injecting headers on response.start. ──────────────────
        started = time.perf_counter()
        status_holder = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                headers = MutableHeaders(raw=message["headers"])
                if allowed_origin:
                    headers["Access-Control-Allow-Origin"] = allowed_origin
                    headers["Vary"] = "Origin"
                    headers["Access-Control-Expose-Headers"] = "*"
                _apply_security_headers(headers, path)
                headers.setdefault("X-Request-ID", rid)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            _log.exception("request_failed", extra={
                "method": request.method, "path": path, "duration_ms": elapsed_ms,
            })
            raise
        else:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            code = status_holder["code"]
            if code >= 400 or elapsed_ms >= 500 or not _is_quiet_path(path):
                _log.info("request_finished", extra={
                    "method": request.method, "path": path,
                    "status": code, "duration_ms": elapsed_ms,
                })


def register(app) -> None:
    """Install the single pure-ASGI gateway middleware."""
    app.add_middleware(GatewayMiddleware)
