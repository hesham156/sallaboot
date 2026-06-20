"""
Security regression tests for token/session revocation (finding H-2).

verify_token() is stateless (signature + expiry only), so a fired/deactivated/
demoted employee — or an owner who reset their password — kept access for up to
7 days. auth.session_invalidated() lets the auth boundary reject such tokens by
comparing the token against the current backing state.

  • Employee tokens: revoked when the DB record is gone / inactive / role-changed.
  • Owner tokens:    revoked when issued before the store's pwd_changed_at.
"""
from __future__ import annotations

import time

import pytest

import auth as _auth


pytestmark = pytest.mark.unit


# ── create_token now stamps iat (needed for owner revocation) ────────────────

def test_create_token_includes_iat():
    before = int(time.time())
    claims = _auth.verify_token(_auth.create_token("store_a"))
    assert "iat" in claims
    assert claims["iat"] >= before


# ── Employee revocation ──────────────────────────────────────────────────────

def _emp_claims(role="agent"):
    return _auth.verify_token(
        _auth.create_token("store_a", employee_id=5, employee_name="e", employee_role=role)
    )


def test_active_employee_same_role_is_valid():
    claims = _emp_claims("manager")
    emp = {"id": 5, "active": True, "role": "manager"}
    assert _auth.session_invalidated(claims, employee=emp) is False


def test_deleted_employee_is_revoked():
    claims = _emp_claims("agent")
    assert _auth.session_invalidated(claims, employee=None) is True


def test_deactivated_employee_is_revoked():
    claims = _emp_claims("agent")
    emp = {"id": 5, "active": False, "role": "agent"}
    assert _auth.session_invalidated(claims, employee=emp) is True


def test_role_change_revokes_old_token():
    claims = _emp_claims("agent")               # token says agent
    emp = {"id": 5, "active": True, "role": "manager"}  # DB now says manager
    assert _auth.session_invalidated(claims, employee=emp) is True


# ── Owner password-change revocation ─────────────────────────────────────────

def test_owner_token_valid_when_no_password_change():
    claims = _auth.verify_token(_auth.create_token("store_a"))
    assert _auth.session_invalidated(claims, pwd_changed_at=0) is False


def test_owner_token_issued_before_change_is_revoked():
    claims = _auth.verify_token(_auth.create_token("store_a"))
    future_change = claims["iat"] + 10        # password changed AFTER token issued
    assert _auth.session_invalidated(claims, pwd_changed_at=future_change) is True


def test_owner_token_issued_after_change_is_valid():
    past_change = int(time.time()) - 100      # password changed BEFORE token issued
    claims = _auth.verify_token(_auth.create_token("store_a"))
    assert _auth.session_invalidated(claims, pwd_changed_at=past_change) is False


def test_legacy_owner_token_without_iat_revoked_after_change():
    """A token minted before this feature has no iat (→ 0); a later password
    change must still revoke it."""
    claims = {"s": "store_a"}                  # no iat, no eid → legacy owner token
    assert _auth.session_invalidated(claims, pwd_changed_at=int(time.time())) is True
