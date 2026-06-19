"""
Tests for Shopify shipment (fulfillment) → WhatsApp parity with Salla's
shipment.created handler.
"""
from __future__ import annotations

import pytest

from routers import webhooks as w


pytestmark = pytest.mark.unit


@pytest.fixture
def wa(monkeypatch):
    sent = []

    async def _wa(store_id, cfg, phone, text):
        sent.append({"store_id": store_id, "phone": phone, "text": text})

    monkeypatch.setattr(w, "_log_event", lambda *a, **k: None)
    monkeypatch.setattr(w, "_wa_send", _wa)
    monkeypatch.setattr(w.sm, "get_ai_config", lambda sid: {})
    monkeypatch.setattr(w.sm, "get_store_info", lambda sid: {"store_name": "متجري"})
    return sent


async def test_fulfillment_sends_tracking_whatsapp(wa):
    data = {
        "name": "#1042",
        "order_id": 1042,
        "tracking_company": "Aramex",
        "tracking_number": "TRK999",
        "tracking_url": "https://track/TRK999",
        "destination": {"name": "Mona", "phone": "+966500000001"},
    }
    await w._handle_shopify_fulfillment("store_a", data)
    assert len(wa) == 1
    msg = wa[0]["text"]
    assert "#1042" in msg
    assert "Aramex" in msg
    assert "TRK999" in msg
    assert "track/TRK999" in msg


async def test_fulfillment_without_phone_is_skipped(wa):
    data = {"order_id": 7, "tracking_number": "X", "destination": {}}
    await w._handle_shopify_fulfillment("store_a", data)
    assert wa == []


async def test_fulfillment_tracking_numbers_array_fallback(wa):
    data = {
        "order_id": 8,
        "tracking_numbers": ["AA", "BB"],
        "tracking_urls": ["https://t/AA"],
        "destination": {"name": "Sara", "phone": "966500000002"},
    }
    await w._handle_shopify_fulfillment("store_a", data)
    assert len(wa) == 1
    assert "AA" in wa[0]["text"]
