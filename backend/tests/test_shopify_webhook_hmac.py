"""
Unit tests for routers.webhooks._verify_shopify_webhook.

Shopify signs webhooks with a base64 HMAC-SHA256 over the raw body using the
app's client secret (NB: base64, unlike the OAuth callback HMAC which is hex,
and unlike Salla's hex X-Salla-Signature). A regression here would let an
attacker forge product/order/uninstall events for any store.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from routers import webhooks as w


pytestmark = pytest.mark.unit


def _sign(body: bytes, secret: str) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode("ascii")


def test_no_secret_accepts_dev_mode(monkeypatch):
    monkeypatch.delenv("SHOPIFY_CLIENT_SECRET", raising=False)
    ok, detail = w._verify_shopify_webhook(b"any body", {})
    assert ok is True
    assert detail == "no_secret_configured"


def test_valid_signature_passes(monkeypatch):
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "shpss_test")
    body = b'{"id":123,"title":"Test"}'
    headers = {"X-Shopify-Hmac-Sha256": _sign(body, "shpss_test")}
    ok, detail = w._verify_shopify_webhook(body, headers)
    assert ok is True
    assert detail == "signature_ok"


def test_signature_mismatch_rejected(monkeypatch):
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "real-secret")
    body = b'{"topic":"app/uninstalled"}'
    headers = {"X-Shopify-Hmac-Sha256": _sign(body, "attacker-secret")}
    ok, detail = w._verify_shopify_webhook(body, headers)
    assert ok is False
    assert detail == "signature_mismatch"


def test_missing_signature_rejected(monkeypatch):
    """Secret set but no header → reject (can't be a genuine Shopify call)."""
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "real-secret")
    ok, detail = w._verify_shopify_webhook(b'{"x":1}', {})
    assert ok is False
    assert detail == "signature_absent"


def test_hex_signature_is_not_accepted(monkeypatch):
    """Guard the base64-vs-hex distinction: a hex digest must NOT validate."""
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "real-secret")
    body = b'{"id":1}'
    hex_sig = hmac.new(b"real-secret", body, hashlib.sha256).hexdigest()
    ok, _ = w._verify_shopify_webhook(body, {"X-Shopify-Hmac-Sha256": hex_sig})
    assert ok is False


# ── Phone normalisation (shared Shopify/Zid helper) ───────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("0501234567",     "+966501234567"),   # bare Saudi local
    ("501234567",      "+966501234567"),    # 9-digit Saudi
    ("+966501234567",  "+966501234567"),    # already E.164
    ("966501234567",   "+966501234567"),    # country code, no plus
    ("00966501234567", "+966501234567"),    # 00 international prefix
    ("",               ""),                  # empty → empty
])
def test_normalize_phone(raw, expected):
    assert w._normalize_phone(raw) == expected
