"""
Security regression tests for the Meta webhook signature check (finding C-3).

POST /whatsapp/webhook (WhatsApp + Messenger + Instagram) used to parse JSON
with NO X-Hub-Signature-256 verification, so anyone could forge inbound events.
The fix adds _verify_meta_signature(), mirroring the Salla/Shopify verifiers:
  • META_APP_SECRET unset            → accept (dev mode) — keeps local/tests working
  • secret set + valid signature     → accept
  • secret set + missing signature   → reject
  • secret set + wrong signature     → reject
"""
from __future__ import annotations

import hashlib
import hmac

import pytest

from routers import webhooks as w


pytestmark = pytest.mark.unit


def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_dev_mode_accepts_when_secret_unset(monkeypatch):
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    ok, detail = w._verify_meta_signature(b'{"object":"x"}', {})
    assert ok is True
    assert detail == "no_secret_configured"


def test_valid_signature_accepted(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", "app-secret-123")
    body = b'{"object":"whatsapp_business_account"}'
    ok, detail = w._verify_meta_signature(body, {"X-Hub-Signature-256": _sig("app-secret-123", body)})
    assert ok is True
    assert detail == "signature_ok"


def test_missing_signature_rejected_when_secret_set(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", "app-secret-123")
    ok, detail = w._verify_meta_signature(b'{"object":"x"}', {})
    assert ok is False
    assert detail == "signature_required_but_absent"


def test_wrong_signature_rejected(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", "app-secret-123")
    body = b'{"object":"x"}'
    ok, detail = w._verify_meta_signature(body, {"X-Hub-Signature-256": "sha256=deadbeef"})
    assert ok is False
    assert detail == "signature_mismatch"


def test_signature_for_different_body_rejected(monkeypatch):
    """A valid signature for a DIFFERENT body must not validate a forged body."""
    monkeypatch.setenv("META_APP_SECRET", "app-secret-123")
    good_sig = _sig("app-secret-123", b'{"amount":1}')
    ok, _ = w._verify_meta_signature(b'{"amount":9999}', {"X-Hub-Signature-256": good_sig})
    assert ok is False
