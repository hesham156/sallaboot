"""
Unit tests for routers.integrations.salla_app_settings_validation — the Salla
App-Settings Validation URL endpoint.

Salla POSTs the merchant's settings form (7ayak email + API key) here before
persisting. The endpoint must bind the store synchronously and return a 2xx so
the save completes, while never blocking a legitimate save and rejecting only a
genuinely wrong signature.
"""
from __future__ import annotations

import json

import pytest
from fastapi.responses import JSONResponse

from routers import integrations as ig
from routers import webhooks as w


pytestmark = pytest.mark.unit


class _FakeRequest:
    def __init__(self, payload, headers=None):
        self._body = json.dumps(payload).encode() if not isinstance(payload, (bytes, str)) else (
            payload.encode() if isinstance(payload, str) else payload
        )
        self.headers = headers or {}

    async def body(self):
        return self._body


@pytest.fixture
def patched(monkeypatch):
    calls = {"link": []}

    async def _fake_link(store_id, email, api_key):
        calls["link"].append((store_id, email, api_key))
        # by_key holds the "valid" api key → success
        if api_key == "7yk_K" or email == "ok@store.com":
            return True, "linked to 7ayak account (was 'home')"
        if api_key == "other-platform":
            return False, "home account 'home' already has another platform"
        if api_key == "notready":
            return False, "salla_store_not_ready"
        return False, "no 7ayak account matched the email/API key provided"

    monkeypatch.setattr(w, "_verify_signature", lambda body, headers: (True, "token_ok"))
    monkeypatch.setattr(w, "link_store_via_app_settings", _fake_link)
    return calls


async def test_valid_settings_link_returns_success(patched):
    req = _FakeRequest({"merchant": 123, "data": {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}})
    res = await ig.salla_app_settings_validation(req)
    assert res == {"success": True}
    assert patched["link"] == [("123", "me@store.com", "7yk_K")]


async def test_settings_at_top_level(patched):
    req = _FakeRequest({"merchant_id": "99", "settings": {"email": "ok@store.com", "key": "anything"}})
    res = await ig.salla_app_settings_validation(req)
    assert res == {"success": True}
    assert patched["link"][0][0] == "99"


async def test_no_merchant_id_does_not_block_save(patched):
    req = _FakeRequest({"data": {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}})
    res = await ig.salla_app_settings_validation(req)
    assert res == {"success": True}
    assert patched["link"] == []  # nothing to bind → webhook will handle it


async def test_no_match_returns_422(patched):
    req = _FakeRequest({"merchant": 123, "data": {"settings": {"email": "x@y.com", "api_key": "nope"}}})
    res = await ig.salla_app_settings_validation(req)
    assert isinstance(res, JSONResponse)
    assert res.status_code == 422
    assert b'"success": false' in res.body or b'"success":false' in res.body


async def test_other_platform_returns_422(patched):
    req = _FakeRequest({"merchant": 123, "data": {"settings": {"api_key": "other-platform"}}})
    res = await ig.salla_app_settings_validation(req)
    assert isinstance(res, JSONResponse)
    assert res.status_code == 422


async def test_not_ready_does_not_block_save(patched):
    """Timing race: the Salla store isn't registered on this process yet. The
    app.settings.updated webhook completes the link, so validation must NOT block
    the merchant's save — this is the 'لم يكتمل التثبيت بعد' loop the merchant hit."""
    req = _FakeRequest({"merchant": 123, "data": {"settings": {"api_key": "notready"}}})
    res = await ig.salla_app_settings_validation(req)
    assert res == {"success": True}


async def test_wrong_signature_rejected(monkeypatch):
    monkeypatch.setattr(w, "_verify_signature",
                        lambda body, headers: (False, "token_mismatch got=abc"))
    called = []
    async def _link(*a):
        called.append(a)
        return True, "x"
    monkeypatch.setattr(w, "link_store_via_app_settings", _link)
    req = _FakeRequest({"merchant": 1, "data": {"settings": {"api_key": "7yk_K"}}})
    res = await ig.salla_app_settings_validation(req)
    assert isinstance(res, JSONResponse)
    assert res.status_code == 401
    assert called == []  # never attempt linking on a forged credential
