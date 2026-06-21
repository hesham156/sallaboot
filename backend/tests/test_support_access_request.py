"""
Admin-initiated support-access REQUEST flow:
  super-admin requests → owner/manager approves (picks duration) or rejects.

Two layers:
  • Unit  — the `_decider_label` authorization guard (no DB).
  • Integration (DB) — the security invariant that a PENDING request grants
    NO access until approved, plus approve/reject transitions.
"""
from __future__ import annotations

import pytest

import auth as _auth


# ── _Req shim (mirrors test_security_fixes) ──────────────────────────────────
class _Req:
    def __init__(self, token: str = ""):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


# ═════════════════════════ Unit: authorization guard ═════════════════════════

unit = pytest.mark.unit


@unit
def test_decider_rejects_super():
    """The super-admin is the REQUESTER — must not approve their own request."""
    from fastapi import HTTPException
    from routers.platform import _decider_label
    tok = _auth.create_token("storeA", is_super=True)
    with pytest.raises(HTTPException) as ei:
        _decider_label(_Req(tok), "storeA")
    assert ei.value.status_code == 403


@unit
def test_decider_allows_owner():
    from routers.platform import _decider_label
    tok = _auth.create_token("storeA")
    assert _decider_label(_Req(tok), "storeA") == "owner"


@unit
def test_decider_allows_manager():
    from routers.platform import _decider_label
    tok = _auth.create_token("storeA", employee_id=7, employee_role="manager")
    assert _decider_label(_Req(tok), "storeA") == "emp:7"


@unit
def test_decider_rejects_agent():
    from fastapi import HTTPException
    from routers.platform import _decider_label
    tok = _auth.create_token("storeA", employee_id=9, employee_role="agent")
    with pytest.raises(HTTPException) as ei:
        _decider_label(_Req(tok), "storeA")
    assert ei.value.status_code == 403


@unit
def test_decider_rejects_other_store_owner():
    """An owner of storeB cannot decide storeA's request."""
    from fastapi import HTTPException
    from routers.platform import _decider_label
    tok = _auth.create_token("storeB")
    with pytest.raises(HTTPException) as ei:
        _decider_label(_Req(tok), "storeA")
    assert ei.value.status_code == 403


# ═════════════════════════ Integration: DB invariant ═════════════════════════

integration = pytest.mark.integration


@integration
async def test_pending_request_grants_no_access(clean_db):
    import database as db
    sid = "req-store-1"
    req = await db.support_access_request(sid, requested_by="root@x", note="debugging")
    assert req and req["status"] == "pending"
    # The security invariant: a pending request must NOT open access.
    assert await db.support_access_active(sid) is None
    pend = await db.support_access_pending(sid)
    assert len(pend) == 1 and pend[0]["id"] == req["id"]


@integration
async def test_approve_opens_time_boxed_access(clean_db):
    import database as db
    sid = "req-store-2"
    req = await db.support_access_request(sid, requested_by="root@x")
    grant = await db.support_access_approve(
        req["id"], sid, decided_by="owner", duration_minutes=60,
    )
    assert grant and grant["status"] == "active" and grant["active"] is True
    active = await db.support_access_active(sid)
    assert active is not None and active["id"] == req["id"]
    # No longer pending.
    assert await db.support_access_pending(sid) == []


@integration
async def test_reject_keeps_access_closed(clean_db):
    import database as db
    sid = "req-store-3"
    req = await db.support_access_request(sid, requested_by="root@x")
    ok = await db.support_access_reject(req["id"], sid, decided_by="owner")
    assert ok is True
    assert await db.support_access_active(sid) is None
    assert await db.support_access_pending(sid) == []


@integration
async def test_approve_is_idempotent_guarded(clean_db):
    """Approving a non-pending (or foreign) id returns None — no access leak."""
    import database as db
    sid = "req-store-4"
    req = await db.support_access_request(sid, requested_by="root@x")
    await db.support_access_approve(req["id"], sid, decided_by="owner", duration_minutes=15)
    # Second approve of the same (now active) row → None.
    again = await db.support_access_approve(req["id"], sid, decided_by="owner", duration_minutes=15)
    assert again is None
    # Wrong store can't approve.
    req2 = await db.support_access_request("other-store", requested_by="root@x")
    assert await db.support_access_approve(req2["id"], sid, decided_by="owner", duration_minutes=15) is None
