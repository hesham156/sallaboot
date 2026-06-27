"""
Tests for the Messenger + Instagram transport and webhook routing.

The bot is channel-agnostic; these lock the channel-specific bits:
  • webhook payload parsing (Messenger vs Instagram, echo/non-text skipping)
  • the Send API request shape (recipient + page /messages edge)
  • store reverse-lookup by page_id / ig_id
  • the unified webhook routing by `object`
"""
from __future__ import annotations

import pytest

import messenger as ms

pytestmark = pytest.mark.unit


def test_extract_messenger_message():
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE_1",
            "messaging": [{
                "sender": {"id": "PSID_1"},
                "recipient": {"id": "PAGE_1"},
                "message": {"mid": "m_1", "text": "السلام عليكم"},
            }],
        }],
    }
    out = ms.extract_messages(payload)
    assert out == [{
        "channel": "messenger", "recipient_id": "PAGE_1", "from": "PSID_1",
        "text": "السلام عليكم", "msg_id": "m_1", "name": "", "standby": False,
    }]


def test_extract_instagram_message():
    payload = {
        "object": "instagram",
        "entry": [{
            "id": "IG_1",
            "messaging": [{
                "sender": {"id": "IGSID_1"},
                "recipient": {"id": "IG_1"},
                "message": {"mid": "m_2", "text": "مرحبا"},
            }],
        }],
    }
    out = ms.extract_messages(payload)
    assert len(out) == 1
    assert out[0]["channel"] == "instagram"
    assert out[0]["recipient_id"] == "IG_1"
    assert out[0]["from"] == "IGSID_1"


def test_extract_skips_echo_and_delivery():
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE_1",
            "messaging": [
                {"sender": {"id": "PAGE_1"}, "recipient": {"id": "PSID"},
                 "message": {"is_echo": True, "mid": "e1", "text": "our reply"}},
                {"sender": {"id": "PSID"}, "recipient": {"id": "PAGE_1"},
                 "delivery": {"mids": ["e1"]}},
            ],
        }],
    }
    assert ms.extract_messages(payload) == []


def test_extract_postback_and_quick_reply():
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE_1",
            "messaging": [
                {"sender": {"id": "PSID"}, "recipient": {"id": "PAGE_1"},
                 "postback": {"title": "ابدأ", "payload": "GET_STARTED"}},
                {"sender": {"id": "PSID2"}, "recipient": {"id": "PAGE_1"},
                 "message": {"mid": "q1", "quick_reply": {"payload": "WANT_PRICE"}}},
            ],
        }],
    }
    out = ms.extract_messages(payload)
    assert out[0]["text"] == "ابدأ"
    assert out[1]["text"] == "WANT_PRICE"


async def test_send_text_posts_to_page_messages(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        text = ""

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["json"] = json
            captured["auth"] = headers.get("Authorization")
            return _Resp()

    monkeypatch.setattr(ms.httpx, "AsyncClient", _Client)
    ok = await ms.send_text("PAGE_TOKEN", "PAGE_1", "PSID_1", "أهلاً", channel="messenger")
    assert ok is True
    assert captured["url"].endswith("/PAGE_1/messages")
    assert captured["json"]["recipient"] == {"id": "PSID_1"}
    assert captured["json"]["messaging_type"] == "RESPONSE"
    assert captured["auth"] == "Bearer PAGE_TOKEN"


def test_store_lookup_by_page_and_ig_id(monkeypatch):
    import store_manager as sm
    monkeypatch.setattr(sm, "_registry", {
        "store_a": {"tokens": {"ai_config": {"page_id": "PAGE_A", "ig_id": "IG_A"}}},
        "store_b": {"tokens": {"ai_config": {"page_id": "PAGE_B"}}},
    })
    assert sm.find_store_by_page_id("PAGE_A") == "store_a"
    assert sm.find_store_by_page_id("IG_A") == "store_a"   # matches ig_id too
    assert sm.find_store_by_page_id("PAGE_B") == "store_b"
    assert sm.find_store_by_page_id("UNKNOWN") == ""
