"""
Seamless session migration after signup → Salla linking (/auth/resolve-link).

The endpoint trades a session token bound to a just-merged signup placeholder
(whose store_id was deleted) for a fresh token on the canonical Salla store, so
the merchant's dashboard recovers WITHOUT a re-login. These tests pin the
authorization rules: only a valid OWNER token whose store is gone AND has a
recorded forward gets migrated; everything else is a clean 404 (and a token for
a live store can never be used to hop to another store).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import auth as _auth
import routers.auth as ra

pytestmark = pytest.mark.unit


class _Req:
    def __init__(self, token: str = ""):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        # resolve_link audit-logs a successful migration; deps.audit reads
        # request.client (None is fine — it records an empty ip).
        self.client = None


@pytest.fixture
def patched(monkeypatch):
    """Patch the sm/db the endpoint reads. `registered` is the set of live store
    ids; `forwards` maps old_store_id → new_store_id."""
    def _apply(registered: set, forwards: dict):
        class _SM:
            def is_registered(self, sid):
                return sid in registered

            def get_store_info(self, sid):
                return {"store_name": f"متجر {sid}"}

        class _DB:
            async def resolve_account_forward(self, old):
                return forwards.get(old)

        monkeypatch.setattr(ra, "sm", _SM())
        monkeypatch.setattr(ra, "db", _DB())
    return _apply


async def test_migrates_deleted_placeholder_to_salla_store(patched):
    patched(registered={"merchant_99"}, forwards={"ahmed": "merchant_99"})
    token = _auth.create_token("ahmed")            # placeholder, now deleted
    out = await ra.resolve_link(_Req(token))
    assert out["store_id"] == "merchant_99"
    assert out["is_super"] is False and out["employee"] is None
    # The returned token is a valid owner token bound to the canonical store.
    claims = _auth.verify_token(out["token"])
    assert claims["s"] == "merchant_99" and "eid" not in claims and not claims.get("su")


async def test_live_store_token_is_not_forwarded(patched):
    # ahmed is still registered → must NOT hop to another store even if a forward exists.
    patched(registered={"ahmed", "merchant_99"}, forwards={"ahmed": "merchant_99"})
    token = _auth.create_token("ahmed")
    with pytest.raises(HTTPException) as ei:
        await ra.resolve_link(_Req(token))
    assert ei.value.status_code == 404


async def test_no_forward_record_is_404(patched):
    patched(registered=set(), forwards={})
    token = _auth.create_token("ghost")
    with pytest.raises(HTTPException) as ei:
        await ra.resolve_link(_Req(token))
    assert ei.value.status_code == 404


async def test_forward_target_missing_is_404(patched):
    # Breadcrumb points at a store that no longer exists locally → refuse.
    patched(registered=set(), forwards={"ahmed": "merchant_99"})
    token = _auth.create_token("ahmed")
    with pytest.raises(HTTPException) as ei:
        await ra.resolve_link(_Req(token))
    assert ei.value.status_code == 404


async def test_super_token_rejected(patched):
    patched(registered={"merchant_99"}, forwards={"super": "merchant_99"})
    token = _auth.create_token("super", is_super=True)
    with pytest.raises(HTTPException) as ei:
        await ra.resolve_link(_Req(token))
    assert ei.value.status_code == 404


async def test_employee_token_rejected(patched):
    patched(registered={"merchant_99"}, forwards={"ahmed": "merchant_99"})
    token = _auth.create_token("ahmed", employee_id=5, employee_name="x", employee_role="agent")
    with pytest.raises(HTTPException) as ei:
        await ra.resolve_link(_Req(token))
    assert ei.value.status_code == 404


async def test_invalid_token_is_401(patched):
    patched(registered=set(), forwards={})
    with pytest.raises(HTTPException) as ei:
        await ra.resolve_link(_Req("garbage.token"))
    assert ei.value.status_code == 401


# ── TTL on the forwarding breadcrumb (database.resolve_account_forward) ──────

async def test_resolve_forward_honours_ttl(monkeypatch):
    """A fresh breadcrumb resolves; one older than the TTL is treated as inert
    (the only token that could follow it has long since expired)."""
    import time as _t
    import database as db

    fresh = {"to": "merchant_1", "at": int(_t.time()) - 60}
    stale = {"to": "merchant_1", "at": int(_t.time()) - db._LINK_FORWARD_TTL_SECS - 60}

    async def _get(key, default=None):
        return {"link_forward:fresh": fresh, "link_forward:stale": stale}.get(key)

    monkeypatch.setattr(db, "get_app_setting", _get)
    assert await db.resolve_account_forward("fresh") == "merchant_1"
    assert await db.resolve_account_forward("stale") is None
