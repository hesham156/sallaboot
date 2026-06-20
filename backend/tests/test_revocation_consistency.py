"""
Verification that token revocation (H-2) is enforced CONSISTENTLY across every
authorization boundary, not just the middleware.

The earlier independent review found that require_store_member and the stream
ticket endpoint did NOT perform revocation, so a fired/deactivated/demoted
employee (or an owner after a password change) kept access to contacts,
campaigns and the live stream. The fix routes all of them through the single
shared deps.session_is_revoked() helper.

These tests monkeypatch deps.db / deps.sm so the revocation logic can be
exercised without a real database.
"""
from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

import auth as _auth
from routers import deps
from routers import stream


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
    if db is not None:
        monkeypatch.setattr(deps, "db", db)
    if sm is not None:
        monkeypatch.setattr(deps, "sm", sm)


# ── session_is_revoked: the single source of truth ───────────────────────────

async def test_super_token_never_revoked(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(), sm=_FakeSM())
    claims = _auth.verify_token(_auth.create_token("super", is_super=True))
    assert await deps.session_is_revoked(claims, "store_a") is False


async def test_active_employee_not_revoked(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(employee={"id": 5, "active": True, "role": "agent"}))
    claims = _auth.verify_token(_auth.create_token("store_a", employee_id=5, employee_role="agent"))
    assert await deps.session_is_revoked(claims, "store_a") is False


async def test_deactivated_employee_revoked(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(employee={"id": 5, "active": False, "role": "agent"}))
    claims = _auth.verify_token(_auth.create_token("store_a", employee_id=5, employee_role="agent"))
    assert await deps.session_is_revoked(claims, "store_a") is True


async def test_deleted_employee_revoked(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(employee=None))
    claims = _auth.verify_token(_auth.create_token("store_a", employee_id=5, employee_role="agent"))
    assert await deps.session_is_revoked(claims, "store_a") is True


async def test_role_downgrade_revoked(monkeypatch):
    # token says manager; DB now says agent → revoke
    _patch(monkeypatch, db=_FakeDB(employee={"id": 5, "active": True, "role": "agent"}))
    claims = _auth.verify_token(_auth.create_token("store_a", employee_id=5, employee_role="manager"))
    assert await deps.session_is_revoked(claims, "store_a") is True


async def test_employee_failopen_when_db_down(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(available=False, employee=None))
    claims = _auth.verify_token(_auth.create_token("store_a", employee_id=5, employee_role="agent"))
    # DB unreachable → cannot verify → fail-open (do NOT lock staff out)
    assert await deps.session_is_revoked(claims, "store_a") is False


async def test_owner_revoked_after_password_change(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(), sm=_FakeSM(pwd_changed_at=int(time.time()) + 60))
    claims = _auth.verify_token(_auth.create_token("store_a"))
    assert await deps.session_is_revoked(claims, "store_a") is True


async def test_owner_valid_without_password_change(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(), sm=_FakeSM(pwd_changed_at=0))
    claims = _auth.verify_token(_auth.create_token("store_a"))
    assert await deps.session_is_revoked(claims, "store_a") is False


# ── require_store_member (contacts / campaigns) now enforces revocation ───────

async def test_member_guard_rejects_deactivated_employee(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(employee={"id": 5, "active": False, "role": "agent"}))
    token = _auth.create_token("store_a", employee_id=5, employee_role="agent")
    with pytest.raises(HTTPException) as ei:
        await deps.require_store_member(_Req(token), "store_a")
    assert ei.value.status_code == 401


async def test_member_guard_rejects_owner_after_password_change(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(), sm=_FakeSM(pwd_changed_at=int(time.time()) + 60))
    token = _auth.create_token("store_a")
    with pytest.raises(HTTPException) as ei:
        await deps.require_store_member(_Req(token), "store_a")
    assert ei.value.status_code == 401


async def test_member_guard_allows_active_employee(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(employee={"id": 5, "active": True, "role": "agent"}))
    token = _auth.create_token("store_a", employee_id=5, employee_role="agent")
    await deps.require_store_member(_Req(token), "store_a")  # no exception


# ── require_store_owner now enforces password-change revocation ───────────────

def test_owner_guard_rejects_after_password_change(monkeypatch):
    _patch(monkeypatch, sm=_FakeSM(pwd_changed_at=int(time.time()) + 60))
    token = _auth.create_token("store_a")
    with pytest.raises(HTTPException) as ei:
        deps.require_store_owner(_Req(token), "store_a")
    assert ei.value.status_code == 401


def test_owner_guard_allows_current_owner(monkeypatch):
    _patch(monkeypatch, sm=_FakeSM(pwd_changed_at=0))
    token = _auth.create_token("store_a")
    deps.require_store_owner(_Req(token), "store_a")  # no exception


# ── stream ticket (outside _PROTECTED_RE) now enforces revocation ─────────────

async def test_stream_ticket_rejects_deactivated_employee(monkeypatch):
    _patch(monkeypatch, db=_FakeDB(employee={"id": 5, "active": False, "role": "agent"}))
    token = _auth.create_token("store_a", employee_id=5, employee_role="agent")
    with pytest.raises(HTTPException) as ei:
        await stream.admin_stream_ticket("store_a", _Req(token))
    assert ei.value.status_code == 401
