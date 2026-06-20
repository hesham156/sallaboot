"""
Security regression tests for the contacts router authorization (finding C-1).

The contacts routes (/admin/{store}/contacts, /contacts/sync, /contacts/export)
sat OUTSIDE the middleware's _PROTECTED_RE allowlist and only called
_require_store() (an existence check), so they were reachable UNAUTHENTICATED
and cross-store — a full CRM/PII dump (name/phone/email) of any store.

The fix adds an inline require_store_member() guard to every contacts route.
These tests lock in the guard's contract:
  • no/garbage token            → 401
  • token for a different store → 403   (cross-store IDOR closed)
  • owner / manager / agent of the SAME store → pass (page keeps working)
  • super admin                → pass (any store)
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import auth as _auth
from routers.deps import require_store_member


pytestmark = pytest.mark.unit


class _Req:
    def __init__(self, token: str = ""):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


# require_store_member is async (the H-2 revocation check needs a DB read for
# employees); without a DB the revocation helper fails open, so the "allowed"
# cases below still pass exactly as before.

# ── Rejected ────────────────────────────────────────────────────────────────

async def test_no_token_is_rejected():
    with pytest.raises(HTTPException) as ei:
        await require_store_member(_Req(), "store_a")
    assert ei.value.status_code == 401


async def test_garbage_token_is_rejected():
    with pytest.raises(HTTPException) as ei:
        await require_store_member(_Req("not-a-valid-token"), "store_a")
    assert ei.value.status_code == 401


async def test_owner_of_other_store_is_rejected():
    token = _auth.create_token("store_a")
    with pytest.raises(HTTPException) as ei:
        await require_store_member(_Req(token), "store_b")
    assert ei.value.status_code == 403


async def test_manager_of_other_store_is_rejected():
    token = _auth.create_token("store_a", employee_id=7, employee_name="m", employee_role="manager")
    with pytest.raises(HTTPException) as ei:
        await require_store_member(_Req(token), "store_b")
    assert ei.value.status_code == 403


async def test_agent_of_other_store_is_rejected():
    token = _auth.create_token("store_a", employee_id=9, employee_name="a", employee_role="agent")
    with pytest.raises(HTTPException) as ei:
        await require_store_member(_Req(token), "store_b")
    assert ei.value.status_code == 403


# ── Allowed (backward compatibility — every role that used the page) ─────────

async def test_owner_of_same_store_passes():
    token = _auth.create_token("store_a")
    await require_store_member(_Req(token), "store_a")  # no exception


async def test_manager_of_same_store_passes():
    token = _auth.create_token("store_a", employee_id=7, employee_name="m", employee_role="manager")
    await require_store_member(_Req(token), "store_a")  # no exception


async def test_agent_of_same_store_passes():
    token = _auth.create_token("store_a", employee_id=9, employee_name="a", employee_role="agent")
    await require_store_member(_Req(token), "store_a")  # no exception


async def test_super_passes_any_store():
    token = _auth.create_token("super", is_super=True)
    await require_store_member(_Req(token), "any_store")  # no exception
