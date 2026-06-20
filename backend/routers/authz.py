"""
Authorization foundation — H-3 Phase 1.

A single base dependency, ``store_guard()``, that every per-store route will
eventually depend on. It centralises what is today scattered across three
places (the middleware regex, the ``deps.require_*`` helpers, and ad-hoc
``verify_token()`` checks):

  • JWT verification (signature + expiry)        → auth.verify_token
  • Tenant isolation (token store == path store) → unless super
  • Session revocation (H-2)                      → deps.session_is_revoked
  • Super-admin recognition

It returns an immutable :class:`Principal` describing the caller.

Scope of THIS phase
───────────────────
Phase 1 only BUILDS the foundation. **No routes are migrated** — the middleware
and the inline ``deps.require_*`` guards remain the live enforcement, so there
is no behaviour change and nothing to roll back. Role-specific dependencies
(``require_member`` / ``require_manager`` / ``require_owner`` / ``require_super``)
are layered on top of this in Phase 2.

Deliberately deferred
─────────────────────
The super-admin **JIT support-access grant** (cross-store reads require a
time-boxed merchant grant) stays in ``middleware.admin_auth_middleware`` for now
— it carries nuances (system-owned stores, whitelisted sub-paths) that will be
folded in when we decide middleware's final role (Phase 6). ``store_guard``
recognises super and returns a Principal; it does not yet re-implement the JIT
gate. Because store_guard is wired to no routes this phase, the existing gate is
unaffected.

No logic is duplicated here: JWT decoding lives in ``auth`` and the revocation
decision lives in ``auth.session_invalidated`` (reached via
``deps.session_is_revoked``). This module only assembles them into a Principal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, Request

import auth as _auth
from routers import deps as _deps


# ── Principal ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Principal:
    """
    The authenticated caller, already validated against a specific store.

    Immutable so it can be passed around freely once produced by store_guard.

    Fields
    ──────
    store_id     : the tenant scope — the {store_id} path segment the caller was
                   validated against (for super this is just the store they're
                   currently acting on).
    role         : "super" | "owner" | "manager" | "agent".
    is_super     : platform super-admin.
    employee_id  : the employees.id for employee tokens, else None (owners/super).
    permissions  : reserved for future fine-grained permissions; empty for now.
    claims       : the raw verified token payload (escape hatch; avoid relying on
                   it in new code — prefer the typed fields above).
    """
    store_id: str
    role: str
    is_super: bool = False
    employee_id: Optional[int] = None
    permissions: frozenset[str] = frozenset()
    claims: dict = field(default_factory=dict)

    # Read-only convenience predicates (no logic — just readability at call sites)
    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"

    @property
    def is_agent(self) -> bool:
        return self.role == "agent"


# ── Base dependency ──────────────────────────────────────────────────────────

def _bearer(request: Request) -> str:
    return request.headers.get("Authorization", "").replace("Bearer ", "").strip()


async def store_guard(store_id: str, request: Request) -> Principal:
    """
    Base per-store authorization dependency.

    Verifies the bearer token, binds it to ``{store_id}`` (tenant isolation),
    enforces H-2 session revocation, and returns a :class:`Principal`. Raises
    HTTPException(401/403) on failure — identical status codes and Arabic
    messages to the existing guards, so migrating a route to this dependency is
    behaviour-preserving.

    FastAPI wires ``store_id`` from the path and ``request`` automatically:

        from routers.authz import store_guard, Principal
        @router.get("/admin/{store_id}/thing")
        async def thing(store_id: str, p: Principal = Depends(store_guard)):
            ...
    """
    claims = _auth.verify_token(_bearer(request))
    if not claims:
        raise HTTPException(401, "يرجى تسجيل الدخول")

    # Super admin — cross-store by design. (JIT support-access grant remains in
    # middleware for this phase; see module docstring.)
    if claims.get("su"):
        return Principal(store_id=store_id, role="super", is_super=True,
                         employee_id=None, claims=claims)

    # Tenant isolation — the token must belong to the store being acted on.
    if (claims.get("s") or "") != store_id:
        raise HTTPException(403, "غير مصرح لك بالوصول")

    # Session revocation (H-2): fired/deactivated/demoted employee, or an owner
    # whose password changed after the token was issued. Reuses the single
    # shared helper — no duplicated logic, fail-open on backend errors.
    if await _deps.session_is_revoked(claims, store_id):
        raise HTTPException(401, "انتهت الجلسة، يرجى تسجيل الدخول مجدداً")

    # Employee token (manager / agent).
    if "eid" in claims:
        role = str(claims.get("er", "agent")) or "agent"
        return Principal(store_id=store_id, role=role, is_super=False,
                         employee_id=int(claims.get("eid", 0)), claims=claims)

    # No employee id → the store owner.
    return Principal(store_id=store_id, role="owner", is_super=False,
                     employee_id=None, claims=claims)
