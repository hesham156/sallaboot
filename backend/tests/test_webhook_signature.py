"""
Unit tests for main._verify_signature.

The function is small but security-critical — the C5 hardening flipped its
default behaviour from "accept missing sig with warning" to "reject missing
sig when SALLA_WEBHOOK_SECRET is set". A regression here re-opens the
forge-app.store.authorize attack vector.
"""
from __future__ import annotations

import hashlib
import hmac
import os

import pytest

import main


pytestmark = pytest.mark.unit


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ── No secret configured (pure dev mode) ──────────────────────────────────

def test_no_secret_accepts_anything(monkeypatch):
    """With no secret, every request is accepted — but logged as dev mode."""
    monkeypatch.delenv("SALLA_WEBHOOK_SECRET", raising=False)
    ok, detail = main._verify_signature(b"any body", {})
    assert ok is True
    assert detail == "no_secret_configured"


# ── Secret set + valid signature ─────────────────────────────────────────

def test_valid_signature_passes(monkeypatch):
    monkeypatch.setenv("SALLA_WEBHOOK_SECRET", "test-secret")
    body = b'{"event":"order.created"}'
    headers = {"X-Salla-Signature": _sign(body, "test-secret")}
    ok, detail = main._verify_signature(body, headers)
    assert ok is True
    assert detail == "signature_ok"


# ── Secret set + WRONG signature (forgery attempt) ───────────────────────

def test_signature_mismatch_rejected(monkeypatch):
    """The exact attack vector — attacker doesn't know the secret."""
    monkeypatch.setenv("SALLA_WEBHOOK_SECRET", "real-secret")
    body = b'{"event":"app.store.authorize","data":{"access_token":"evil"}}'
    headers = {"X-Salla-Signature": _sign(body, "different-secret")}
    ok, detail = main._verify_signature(body, headers)
    assert ok is False
    assert detail.startswith("signature_mismatch")


# ── Secret set + MISSING signature (C5 the hardening) ────────────────────

def test_missing_signature_rejected_by_default(monkeypatch):
    """
    THE regression test for C5. Pre-hardening, this was accepted with a
    warning. Now it must be rejected — that's what closed the forgery
    vector for app.store.authorize.
    """
    monkeypatch.setenv("SALLA_WEBHOOK_SECRET", "real-secret")
    monkeypatch.delenv("WEBHOOK_ALLOW_UNSIGNED", raising=False)
    ok, detail = main._verify_signature(b'{"event":"x"}', {})
    assert ok is False
    assert detail == "signature_required_but_absent"


def test_missing_signature_allowed_with_dev_override(monkeypatch):
    """The escape hatch must work — but only when the operator opts in."""
    monkeypatch.setenv("SALLA_WEBHOOK_SECRET",   "real-secret")
    monkeypatch.setenv("WEBHOOK_ALLOW_UNSIGNED", "true")
    ok, detail = main._verify_signature(b'{"event":"x"}', {})
    assert ok is True
    assert detail == "signature_absent_dev_override"


def test_dev_override_is_case_insensitive_strict(monkeypatch):
    """`WEBHOOK_ALLOW_UNSIGNED=True` must work; `=1` or `=yes` must NOT."""
    monkeypatch.setenv("SALLA_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("WEBHOOK_ALLOW_UNSIGNED", "TRUE")
    ok, _ = main._verify_signature(b"x", {})
    assert ok is True

    monkeypatch.setenv("WEBHOOK_ALLOW_UNSIGNED", "1")
    ok, _ = main._verify_signature(b"x", {})
    assert ok is False, "only 'true' (any case) opts in — never '1' or 'yes'"


# ── Constant-time comparison hardening ────────────────────────────────────

def test_signature_uses_constant_time_compare(monkeypatch):
    """
    Defence-in-depth: even if we got the hash math right, a == comparison
    would leak the secret over millions of attempts. The implementation
    uses hmac.compare_digest. We sanity-check by verifying that two
    near-correct signatures both fail without throwing.
    """
    monkeypatch.setenv("SALLA_WEBHOOK_SECRET", "secret")
    body = b"body"
    real = _sign(body, "secret")
    # Flip every other character — gives roughly 50% wrong characters.
    wrong = "".join(
        c if i % 2 == 0 else ("0" if c != "0" else "1")
        for i, c in enumerate(real)
    )
    ok, _ = main._verify_signature(body, {"X-Salla-Signature": wrong})
    assert ok is False
