"""
Tests for the omni-channel broadcast feature.

Unit: channel-availability detection (no DB).
Integration: recipient resolution + run_broadcast delivery across widget
(via conversation_store) and an external channel (telegram, mocked send).
"""
from __future__ import annotations

import json

import pytest

import broadcast_sender as bs
import database as db

pytestmark = pytest.mark.unit


# ── Unit: which channels are "connected" ───────────────────────────────────

def test_available_channels_full_config(monkeypatch):
    monkeypatch.setattr(bs.sm, "get_ai_config", lambda sid: {
        "telegram_bot_token": "t",
        "whatsapp_token": "w", "whatsapp_phone_id": "p",
        "page_token": "pt", "page_id": "pid",
        "instagram_enabled": True,
    })
    chans = set(bs.available_channels("s"))
    assert chans == {"widget", "email", "telegram", "whatsapp",
                     "messenger", "instagram"}


def test_available_channels_minimal(monkeypatch):
    """No integrations → only the always-on channels (widget + email)."""
    monkeypatch.setattr(bs.sm, "get_ai_config", lambda sid: {})
    assert set(bs.available_channels("s")) == {"widget", "email"}


def test_instagram_needs_explicit_enable(monkeypatch):
    monkeypatch.setattr(bs.sm, "get_ai_config", lambda sid: {"page_token": "pt"})
    chans = set(bs.available_channels("s"))
    assert "messenger" in chans            # page_token alone enables messenger
    assert "instagram" not in chans        # but IG needs instagram_enabled


# ── Integration: delivery ──────────────────────────────────────────────────

@pytest.mark.integration
async def test_run_broadcast_widget_delivers_to_outbox(
    db_pool, clean_db, register_test_store
):
    store_id = await register_test_store("bc-store")
    # A website-widget conversation (no 'channel' tag, random session id).
    async with db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (session_id, store_id, data, updated_at) "
            "VALUES ($1, $2, $3::jsonb, NOW())",
            "widget-sess-1", store_id, json.dumps({"customer_name": "Sara"}),
        )

    bid = await db.broadcast_create(store_id, "تخفيضات اليوم!", ["widget"])
    await bs.run_broadcast(bid)

    # The message landed in the widget's durable queue (payloads returned directly).
    pending = await db.widget_outbox_claim_pending("widget-sess-1")
    assert any(p.get("content") == "تخفيضات اليوم!" for p in pending)

    bc = await db.broadcast_get(store_id, bid)
    assert bc["status"] == "sent"
    assert bc["sent_count"] == 1 and bc["failed_count"] == 0
    assert bc["per_channel"]["widget"]["sent"] == 1


@pytest.mark.integration
async def test_run_broadcast_telegram_calls_send(
    db_pool, clean_db, register_test_store, monkeypatch
):
    store_id = await register_test_store(
        "bc-tg", ai_config={"telegram_bot_token": "tok"})
    async with db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (session_id, store_id, data, updated_at) "
            "VALUES ($1, $2, $3::jsonb, NOW())",
            f"tg:{store_id}:99887", store_id,
            json.dumps({"channel": "telegram", "customer_name": "Ali"}),
        )

    calls = []
    async def fake_send(token, chat_id, text):
        calls.append((token, chat_id, text))
        return True
    import telegram as tg
    monkeypatch.setattr(tg, "send_text", fake_send)

    bid = await db.broadcast_create(store_id, "مرحبا", ["telegram"])
    await bs.run_broadcast(bid)

    assert calls == [("tok", "99887", "مرحبا")]   # chat_id parsed from session_id
    bc = await db.broadcast_get(store_id, bid)
    assert bc["sent_count"] == 1 and bc["status"] == "sent"


@pytest.mark.integration
async def test_whatsapp_respects_24h_window(
    db_pool, clean_db, register_test_store, monkeypatch
):
    store_id = await register_test_store(
        "bc-wa", ai_config={"whatsapp_token": "t", "whatsapp_phone_id": "p"})
    async with db._pool.acquire() as conn:
        # One recent (in-window), one 3 days old (out of window).
        await conn.execute(
            "INSERT INTO conversations (session_id, store_id, data, updated_at) "
            "VALUES ($1,$2,$3::jsonb, NOW()), ($4,$2,$5::jsonb, NOW() - INTERVAL '3 days')",
            f"wa:{store_id}:111", store_id, json.dumps({"channel": "whatsapp"}),
            f"wa:{store_id}:222", json.dumps({"channel": "whatsapp"}),
        )
    recips = await db.broadcast_channel_recipients(store_id, "whatsapp", within_hours=24)
    ids = {r["recipient"] for r in recips}
    assert ids == {"111"}        # the 3-day-old one is excluded by the window
