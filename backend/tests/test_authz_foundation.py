"""
Tests for the H-3 Phase-1 authorization foundation (routers/authz.py).

store_guard() is the future single base dependency. These tests lock in its
contract BEFORE any route is migrated onto it:

  • JWT verification (missing/invalid → 401)
  • Tenant isolation (cross-store → 403)
  • Session revocation (H-2) reused, not duplicated
  • Correct Principal shape for super / owner / manager / agent

No routes use store_guard yet — it is exercised directly.
"""
from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

import auth as _auth
from routers import deps
from routers.authz import store_guard, Principal


pytestmark = pytest.mark.unit


class _Req:
    def __init__(self, token: str = ""):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


class _FakeDB:
    def __init__(self, available=True, employee=None):
        self._available = available
        self._employee = employee

    def available(self):
        return self._available

    async def get_employee(self, eid):
        return self._employee


class _FakeSM:
    def __init__(self, pwd_changed_at=0):
        self._pwd_changed_at = pwd_changed_at

    def get_store_info(self, store_id):
        return {"pwd_changed_at": self._pwd_changed_at}


def _patch(monkeypatch, *, db=None, sm=None):
    # store_guard delegates revocation to deps.session_is_revoked, which reads
    # deps.db / deps.sm — patch those module globals.
    if db is not None:
        monkeypatch.setattr(deps, "db", db)
    if sm is not None:
        monkeypatch.setattr(deps, "sm", sm)


# ── JWT verification ──────────────────────────────────────────────────────────

async def test_missing_token_rejected():
    with pytest.raises(HTTPException) as ei:
        await store_guard("store_a", _Req())
    assert ei.value.status_code == 401


async def test_invalid_token_rejected():
    with pytest.raises(HTTPException) as ei:
        await store_guard("store_a", _Req("garbage.token"))
    assert ei.value.status_code == 401


# ── Tenant isolation ──────────────────────────────────────────────────────────

async def test_owner_cross_store_rejected(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(), sm=_FakeSM())
    token = _auth.create_token("store_a")
    with pytest.raises(HTTPException) as ei:
        await store_guard("store_b", _Req(token))
    assert ei.value.status_code == 403


async def test_employee_cross_store_rejected(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(employee={"id": 5, "active": True, "role": "agent"}))
    token = _auth.create_token("store_a", employee_id=5, employee_role="agent")
    with pytest.raises(HTTPException) as ei:
        await store_guard("store_b", _Req(token))
    assert ei.value.status_code == 403


# ── Principal shape ───────────────────────────────────────────────────────────

async def test_super_principal(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(), sm=_FakeSM())
    token = _auth.create_token("super", is_super=True)
    p = await store_guard("any_store", _Req(token))
    assert isinstance(p, Principal)
    assert p.is_super is True and p.role == "super"
    assert p.store_id == "any_store" and p.employee_id is None


async def test_owner_principal(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(), sm=_FakeSM())
    token = _auth.create_token("store_a")
    p = await store_guard("store_a", _Req(token))
    assert p.role == "owner" and p.is_owner is True
    assert p.is_super is False and p.employee_id is None and p.store_id == "store_a"


async def test_manager_principal(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(employee={"id": 7, "active": True, "role": "manager"}))
    token = _auth.create_token("store_a", employee_id=7, employee_role="manager")
    p = await store_guard("store_a", _Req(token))
    assert p.role == "manager" and p.is_manager is True
    assert p.employee_id == 7 and p.is_super is False


async def test_agent_principal(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(employee={"id": 9, "active": True, "role": "agent"}))
    token = _auth.create_token("store_a", employee_id=9, employee_role="agent")
    p = await store_guard("store_a", _Req(token))
    assert p.role == "agent" and p.is_agent is True
    assert p.employee_id == 9


# ── Revocation reused (H-2) ───────────────────────────────────────────────────

async def test_deactivated_employee_rejected(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(employee={"id": 5, "active": False, "role": "agent"}))
    token = _auth.create_token("store_a", employee_id=5, employee_role="agent")
    with pytest.raises(HTTPException) as ei:
        await store_guard("store_a", _Req(token))
    assert ei.value.status_code == 401


async def test_owner_after_password_change_rejected(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(), sm=_FakeSM(pwd_changed_at=int(time.time()) + 60))
    token = _auth.create_token("store_a")
    with pytest.raises(HTTPException) as ei:
        await store_guard("store_a", _Req(token))
    assert ei.value.status_code == 401


# ── Principal is immutable ────────────────────────────────────────────────────

def test_principal_is_frozen():
    p = Principal(store_id="s", role="owner")
    with pytest.raises(Exception):
        p.role = "super"  # type: ignore[misc]
