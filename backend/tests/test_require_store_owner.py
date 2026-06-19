"""
Security regression tests for routers.deps.require_store_owner.

The guard used to fall through to an implicit allow for any non-super, non-employee
token — and for NO token at all — without ever binding the token's store to the
store_id being acted on. Because the api-key / integrations owner routes sit
outside the middleware's _PROTECTED_RE allowlist, that made them reachable
unauthenticated and cross-store (IDOR → read another merchant's linking key →
account takeover). These tests lock the fix in.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import auth as _auth
from routers.deps import require_store_owner


pytestmark = pytest.mark.unit


class _Req:
    def __init__(self, token: str = ""):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


def test_no_token_is_rejected():
    with pytest.raises(HTTPException) as ei:
        require_store_owner(_Req(), "store_a")
    assert ei.value.status_code == 401


def test_garbage_token_is_rejected():
    with pytest.raises(HTTPException) as ei:
        require_store_owner(_Req("not-a-valid-token"), "store_a")
    assert ei.value.status_code == 401


def test_owner_of_other_store_is_rejected():
    token = _auth.create_token("store_a")
    with pytest.raises(HTTPException) as ei:
        require_store_owner(_Req(token), "store_b")
    assert ei.value.status_code == 403


def test_owner_of_same_store_passes():
    token = _auth.create_token("store_a")
    require_store_owner(_Req(token), "store_a")  # no exception


def test_super_passes_any_store():
    token = _auth.create_token("super", is_super=True)
    require_store_owner(_Req(token), "any_store")  # no exception


def test_employee_of_same_store_is_rejected_as_not_owner():
    token = _auth.create_token("store_a", employee_id=7, employee_name="x", employee_role="manager")
    with pytest.raises(HTTPException) as ei:
        require_store_owner(_Req(token), "store_a")
    assert ei.value.status_code == 403


def test_employee_of_other_store_is_rejected():
    token = _auth.create_token("store_a", employee_id=7, employee_name="x", employee_role="manager")
    with pytest.raises(HTTPException) as ei:
        require_store_owner(_Req(token), "store_b")
    assert ei.value.status_code == 403
