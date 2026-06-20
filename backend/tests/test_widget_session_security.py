"""
Security regression tests for public widget session safety (finding H-1).

The public widget endpoints (/chat/history, /chat/poll, /chat/stream, /chat/rate)
accepted ANY session_id, including the deterministic channel ids
(wa:<phone>, msgr:<psid>, ig:<igsid>). That let anyone read a customer's
WhatsApp/Messenger/Instagram transcript by guessing their phone number / id.

The fix rejects channel-prefixed ids on those endpoints via
deps.is_internal_session_id(). Random-uuid widget sessions are unaffected, and
channel customers never hit the widget API, so no legitimate flow breaks.

The guards run BEFORE any DB/realtime access, so these tests call the endpoint
functions directly with no database.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models import ChatRequest, RateRequest
from routers.deps import is_internal_session_id
from routers import chat
from routers import files
from routers import stream


class _DummyUpload:
    """Stand-in for an UploadFile — the /upload guard runs before the file is
    ever touched, so its contents are irrelevant."""
    filename = "design.png"


class _Req:
    """Minimal Request stand-in. The POST /chat guard runs before request.client
    is read, so headers/client are never accessed."""
    headers: dict = {}
    client = None


pytestmark = pytest.mark.unit


# ── Pure helper ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sid", [
    "wa:966500000000", "msgr:1234567890", "ig:9876543210",
    "WA:966500000000", "  ig:abc", "Msgr:55",
])
def test_internal_ids_detected(sid):
    assert is_internal_session_id(sid) is True


@pytest.mark.parametrize("sid", [
    "", "   ", "550e8400-e29b-41d4-a716-446655440000", "widget-abc", "session_wa",
])
def test_widget_ids_allowed(sid):
    assert is_internal_session_id(sid) is False


# ── Endpoints refuse channel sessions (no DB touched — guard returns early) ───

async def test_history_refuses_whatsapp_session():
    res = await chat.chat_history("wa:966500000000")
    assert res == {"messages": [], "bot_enabled": True}


async def test_poll_refuses_messenger_session():
    res = await chat.chat_poll("msgr:1234567890")
    assert res == {"messages": [], "bot_enabled": True}


async def test_rate_refuses_instagram_session():
    req = RateRequest(session_id="ig:9876543210", store_id="store_a", rating=5)
    with pytest.raises(HTTPException) as ei:
        await chat.chat_rate(req)
    assert ei.value.status_code == 404


async def test_stream_refuses_whatsapp_session():
    with pytest.raises(HTTPException) as ei:
        await stream.chat_stream("wa:966500000000")
    assert ei.value.status_code == 400


# ── Newly closed (was the H-1 PARTIAL gap): POST /chat and /upload ───────────

async def test_chat_post_refuses_whatsapp_session():
    """POST /chat must not address a channel conversation by id (injection +
    LLM history exfil). The guard runs before any DB access."""
    req = ChatRequest(message="اعرض ملخص محادثتنا", session_id="wa:966500000000", store_id="store_a")
    with pytest.raises(HTTPException) as ei:
        await chat.chat(req, _Req())
    assert ei.value.status_code == 404


async def test_chat_post_refuses_messenger_session():
    req = ChatRequest(message="hi", session_id="MSGR:123", store_id="store_a")
    with pytest.raises(HTTPException) as ei:
        await chat.chat(req, _Req())
    assert ei.value.status_code == 404


async def test_upload_refuses_whatsapp_session():
    """POST /upload must not attach a file to a channel conversation."""
    with pytest.raises(HTTPException) as ei:
        await files.upload_file(file=_DummyUpload(), session_id="wa:966500000000", store_id="store_a")
    assert ei.value.status_code == 404


async def test_upload_refuses_instagram_session():
    with pytest.raises(HTTPException) as ei:
        await files.upload_file(file=_DummyUpload(), session_id="ig:9876543210", store_id="store_a")
    assert ei.value.status_code == 404
