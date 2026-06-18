"""
Unit tests for store_manager.reassign_owner_email — the Salla account
unification step.

When a merchant signs up on 7ayak first (platform-less placeholder) and then
installs Salla, the email must end up on exactly ONE account (the Salla store)
so unified login is unambiguous. The helper detaches the email from a genuine
placeholder and carries its password over — but must NEVER steal the email of
an account that already has a live platform connected.
"""
from __future__ import annotations

import pytest

import store_manager as sm


pytestmark = pytest.mark.unit


class _DBStub:
    """Stand-in for the db module functions reassign_owner_email touches."""
    def __init__(self, *, owner_lookup=None, integrations=None):
        self._owner_lookup = owner_lookup or {}
        self._integrations = integrations or {}
        self.cleared: list[str] = []

    async def find_store_by_owner_email(self, email):
        return self._owner_lookup.get((email or "").strip().lower())

    async def get_integrations(self, store_id):
        return self._integrations.get(store_id, {})

    async def set_store_owner_email(self, store_id, email):
        if not email:
            self.cleared.append(store_id)
        return True


@pytest.fixture
def patched(monkeypatch):
    """Patch sm.db with a stub and stub the password-hash reader."""
    def _apply(stub: _DBStub, pwd_hash: str = "argon2$placeholder"):
        monkeypatch.setattr(sm, "db", stub)
        monkeypatch.setattr(sm, "get_admin_password_hash", lambda sid: pwd_hash)
        return stub
    return _apply


async def test_no_email_is_noop(patched):
    stub = patched(_DBStub())
    assert await sm.reassign_owner_email("", "merchant_42") == ""
    assert stub.cleared == []


async def test_no_existing_account_is_noop(patched):
    stub = patched(_DBStub(owner_lookup={}))
    assert await sm.reassign_owner_email("new@store.com", "merchant_42") == ""
    assert stub.cleared == []


async def test_same_store_is_noop(patched):
    # Email already belongs to the Salla store itself (reinstall) → nothing to do.
    stub = patched(_DBStub(owner_lookup={"a@b.com": "merchant_42"}))
    assert await sm.reassign_owner_email("a@b.com", "merchant_42") == ""
    assert stub.cleared == []


async def test_placeholder_is_relinked_and_password_carried(patched):
    # A platform-less placeholder owns the email → detach + carry its password.
    stub = patched(
        _DBStub(owner_lookup={"a@b.com": "signup_abc"}, integrations={"signup_abc": {}}),
        pwd_hash="argon2$chosen",
    )
    out = await sm.reassign_owner_email("a@b.com", "merchant_42")
    assert out == "argon2$chosen"
    assert stub.cleared == ["signup_abc"]


async def test_live_platform_account_is_left_untouched(patched):
    # The other account already runs on Shopify → it's real, never steal its email.
    stub = patched(
        _DBStub(
            owner_lookup={"a@b.com": "real_store"},
            integrations={"real_store": {"shopify": {"shop": "x.myshopify.com"}}},
        ),
    )
    out = await sm.reassign_owner_email("a@b.com", "merchant_42")
    assert out == ""
    assert stub.cleared == []   # email NOT detached


async def test_synthetic_salla_account_is_left_untouched(patched):
    # get_integrations injects a synthetic 'salla' key for stores with tokens.
    stub = patched(
        _DBStub(
            owner_lookup={"a@b.com": "other_salla"},
            integrations={"other_salla": {"salla": {"connected": True}}},
        ),
    )
    out = await sm.reassign_owner_email("a@b.com", "merchant_42")
    assert out == ""
    assert stub.cleared == []
