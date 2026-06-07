"""
Unit tests for backend/auth.py.

These are pure-function tests: no DB, no httpx, no event loop required.
They run on any machine in ~50ms total.

Coverage:
  • argon2id round-trip (hash → verify)
  • Legacy SHA-256+salt verify still works (backward compat)
  • needs_rehash discriminates the two formats correctly
  • check_password rejects wrong passwords and tampered hashes
  • create_token / verify_token round-trip
  • Token tampering / expiry / wrong signature all return None
  • Employee claims survive the round-trip
"""
from __future__ import annotations

import hashlib
import secrets
import time

import pytest

import auth


pytestmark = pytest.mark.unit


# ── argon2id ──────────────────────────────────────────────────────────────

def test_argon2_round_trip():
    """A freshly-hashed password verifies; a wrong one doesn't."""
    h = auth.hash_password("correct horse battery staple")
    assert h.startswith("$argon2"), "hash_password should default to argon2id"
    assert auth.check_password("correct horse battery staple", h) is True
    assert auth.check_password("wrong password",               h) is False
    assert auth.check_password("",                             h) is False


def test_argon2_different_salts_per_hash():
    """Two hashes of the same password are different (proves randomised salt)."""
    h1 = auth.hash_password("same-password")
    h2 = auth.hash_password("same-password")
    assert h1 != h2
    # Both still verify
    assert auth.check_password("same-password", h1)
    assert auth.check_password("same-password", h2)


def test_check_password_rejects_garbage_input():
    """Random non-hashes never verify — and never crash."""
    for bad in ("", "not-a-hash", "abc:def", "$argon2-broken$", ":::"):
        assert auth.check_password("anything", bad) is False


# ── Legacy SHA-256 verify ────────────────────────────────────────────────

def _legacy_hash(password: str) -> str:
    """Reproduce the pre-Phase-0 hash format for migration tests."""
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def test_legacy_sha256_still_verifies():
    """Old DB rows continue to authenticate without manual migration."""
    h = _legacy_hash("legacy-password")
    assert ":" in h and not h.startswith("$argon2"), "fixture must mimic the old format"
    assert auth.check_password("legacy-password", h) is True
    assert auth.check_password("legacy-password ", h) is False  # whitespace matters


def test_legacy_check_rejects_wrong_password():
    h = _legacy_hash("right")
    assert auth.check_password("wrong", h) is False


# ── needs_rehash ─────────────────────────────────────────────────────────

def test_needs_rehash_legacy_signals_upgrade():
    """A legacy hash is always due for upgrade when argon2 is available."""
    assert auth.needs_rehash(_legacy_hash("pw")) is True


def test_needs_rehash_fresh_argon2_is_clean():
    """A hash from hash_password() at default params doesn't need rehash."""
    assert auth.needs_rehash(auth.hash_password("pw")) is False


def test_needs_rehash_empty_hash_is_false():
    """Edge case — we don't want UPDATE loops on empty stored values."""
    assert auth.needs_rehash("") is False


# ── Token creation / verification ────────────────────────────────────────

def test_token_round_trip_store_owner():
    tok = auth.create_token("store-123")
    claims = auth.verify_token(tok)
    assert claims is not None
    assert claims["s"]  == "store-123"
    assert claims["su"] is False
    assert "eid" not in claims, "store owner tokens should not carry an employee id"


def test_token_round_trip_super_admin():
    tok = auth.create_token("super", is_super=True)
    claims = auth.verify_token(tok)
    assert claims is not None
    assert claims["su"] is True


def test_token_round_trip_employee():
    tok = auth.create_token(
        "store-x", employee_id=42, employee_name="Sara", employee_role="manager"
    )
    claims = auth.verify_token(tok)
    assert claims is not None
    assert claims["s"]   == "store-x"
    assert claims["eid"] == 42
    assert claims["en"]  == "Sara"
    assert claims["er"]  == "manager"
    # Helper accessors stay consistent
    emp = auth.token_employee(tok)
    assert emp == {"id": 42, "name": "Sara", "role": "manager"}


def test_tampered_signature_rejected():
    """Flipping a byte of the signature makes the token unverifiable."""
    tok = auth.create_token("store-1")
    data, sig = tok.rsplit(".", 1)
    flipped_sig = ("0" if sig[0] != "0" else "1") + sig[1:]
    assert auth.verify_token(f"{data}.{flipped_sig}") is None


def test_tampered_payload_rejected():
    """Editing the base64 payload invalidates the signature."""
    tok = auth.create_token("store-1")
    data, sig = tok.rsplit(".", 1)
    # Truncate one byte from the end of the payload — same length still
    # parses as base64 but the HMAC won't match.
    bad_data = data[:-1] + ("A" if data[-1] != "A" else "B")
    assert auth.verify_token(f"{bad_data}.{sig}") is None


def test_expired_token_rejected(monkeypatch):
    """Tokens past their exp claim are rejected."""
    tok = auth.create_token("store-1")
    # Fast-forward time past the 7-day expiry.
    monkeypatch.setattr(time, "time", lambda: time.time() + 8 * 24 * 3600)
    assert auth.verify_token(tok) is None


def test_empty_token_returns_none():
    """The hot path of the auth middleware passes "" when no header is set."""
    assert auth.verify_token("") is None
    assert auth.verify_token(None) is None  # type: ignore[arg-type]
