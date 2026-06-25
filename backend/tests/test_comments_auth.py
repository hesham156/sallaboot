"""
Authorization contract for the comments router (Phase C).

Locks the role gating that protects the comment APIs:
  • store_guard maps the employee `er` claim to a Principal role (incl. viewer)
  • viewer  → may read, may NOT act (_ensure_act raises 403)
  • agent   → may act, may NOT manage settings/rules (_ensure_manage raises 403)
  • manager/owner → may manage
  • only super may toggle the entitlement (_ensure_super)
  • cross-store tokens are rejected by store_guard (tenant isolation)

Pure-unit: like test_contacts_auth, the H-2 revocation read is forced fail-open
so results don't depend on suite ordering / DB availability.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import auth as _auth
from routers.authz import store_guard, Principal
from routers import comments as cr

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _fail_open_revocation(monkeypatch):
    import database as _db
    monkeypatch.setattr(_db, "available", lambda: False)


class _Req:
    def __init__(self, token: str = ""):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


def _token(store="store_a", *, is_super=False, role=None, eid=None):
    return _auth.create_token(store, is_super=is_super, employee_id=eid,
                              employee_name="x" if eid else "",
                              employee_role=role or "")


# ── store_guard role mapping ─────────────────────────────────────────────────

async def test_guard_maps_roles():
    owner = await store_guard("store_a", _Req(_token()))
    assert owner.role == "owner"
    mgr = await store_guard("store_a", _Req(_token(role="manager", eid=2)))
    assert mgr.role == "manager"
    agent = await store_guard("store_a", _Req(_token(role="agent", eid=3)))
    assert agent.role == "agent"
    viewer = await store_guard("store_a", _Req(_token(role="viewer", eid=4)))
    assert viewer.role == "viewer"
    sup = await store_guard("store_a", _Req(_token(is_super=True)))
    assert sup.role == "super" and sup.is_super


async def test_guard_rejects_cross_store():
    with pytest.raises(HTTPException) as ei:
        await store_guard("store_b", _Req(_token("store_a")))
    assert ei.value.status_code == 403


async def test_guard_rejects_no_token():
    with pytest.raises(HTTPException) as ei:
        await store_guard("store_a", _Req())
    assert ei.value.status_code == 401


# ── role helper gates ────────────────────────────────────────────────────────

def _p(role, *, is_super=False, eid=None):
    return Principal(store_id="store_a", role=role, is_super=is_super, employee_id=eid)


def test_viewer_cannot_act():
    with pytest.raises(HTTPException) as ei:
        cr._ensure_act(_p("viewer", eid=4))
    assert ei.value.status_code == 403
    # agent/manager/owner can act (no raise)
    for r in ("agent", "manager", "owner"):
        cr._ensure_act(_p(r))


def test_only_managers_can_manage():
    for r in ("agent", "viewer"):
        with pytest.raises(HTTPException) as ei:
            cr._ensure_manage(_p(r))
        assert ei.value.status_code == 403
    for r in ("manager", "owner"):
        cr._ensure_manage(_p(r))                 # no raise
    cr._ensure_manage(_p("super", is_super=True))  # no raise


def test_only_super_sets_entitlement():
    for r in ("owner", "manager", "agent", "viewer"):
        with pytest.raises(HTTPException) as ei:
            cr._ensure_super(_p(r))
        assert ei.value.status_code == 403
    cr._ensure_super(_p("super", is_super=True))   # no raise


def test_actor_label():
    assert cr._actor(_p("super", is_super=True)) == "super"
    assert cr._actor(_p("owner")) == "owner"
    assert cr._actor(_p("agent", eid=7)) == "emp:7"
