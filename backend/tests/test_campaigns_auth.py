"""
Security regression tests for the campaigns router authorization (finding C-2).

The campaign routes (/admin/{store}/campaigns*) sat OUTSIDE the middleware's
_PROTECTED_RE allowlist and only called _require_store() (an existence check),
so they were reachable UNAUTHENTICATED and cross-store — anyone could create
and LAUNCH a WhatsApp marketing blast on any merchant's account (their token,
their quota, their WABA's spam-ban risk).

The fix adds an inline require_store_member() guard as the FIRST line of every
route, before any DB access — so these tests can call the endpoint functions
directly with a tokenless / wrong-store request and assert the guard fires
without needing a database.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import auth as _auth
from routers import campaigns as c


pytestmark = pytest.mark.unit


class _Req:
    def __init__(self, token: str = ""):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


# ── No token → 401 on every route ────────────────────────────────────────────

async def test_create_requires_auth():
    with pytest.raises(HTTPException) as ei:
        await c.create_campaign("store_a", _Req())
    assert ei.value.status_code == 401


async def test_list_requires_auth():
    with pytest.raises(HTTPException) as ei:
        await c.list_campaigns("store_a", _Req())
    assert ei.value.status_code == 401


async def test_get_requires_auth():
    with pytest.raises(HTTPException) as ei:
        await c.get_campaign("store_a", _Req(), 1)
    assert ei.value.status_code == 401


async def test_preview_requires_auth():
    with pytest.raises(HTTPException) as ei:
        await c.preview_campaign("store_a", _Req(), 1)
    assert ei.value.status_code == 401


async def test_launch_requires_auth():
    with pytest.raises(HTTPException) as ei:
        await c.launch_campaign("store_a", 1, _Req())
    assert ei.value.status_code == 401


async def test_delete_requires_auth():
    with pytest.raises(HTTPException) as ei:
        await c.delete_campaign("store_a", _Req(), 1)
    assert ei.value.status_code == 401


# ── Cross-store token → 403 (the IDOR that let one merchant blast another) ────

async def test_launch_cross_store_is_rejected():
    token = _auth.create_token("store_a")
    with pytest.raises(HTTPException) as ei:
        await c.launch_campaign("store_b", 1, _Req(token))
    assert ei.value.status_code == 403


async def test_list_cross_store_is_rejected():
    token = _auth.create_token("store_a", employee_id=3, employee_name="m", employee_role="manager")
    with pytest.raises(HTTPException) as ei:
        await c.list_campaigns("store_b", _Req(token))
    assert ei.value.status_code == 403
