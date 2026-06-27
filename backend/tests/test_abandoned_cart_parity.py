"""
Tests for cross-platform abandoned-cart parity (Shopify poller → shared recorder).

Salla pushes abandoned.cart webhooks; Shopify has none, so we poll its abandoned
checkouts and feed them through the SAME record_abandoned_cart path. These tests
cover the Shopify→notification mapping and the newly-seen gate that stops the
poller from re-spamming a customer every cycle.
"""
from __future__ import annotations

import asyncio

import pytest

from routers import webhooks as w


pytestmark = pytest.mark.unit


def test_shopify_checkout_maps_to_notification():
    checkout = {
        "id": 987654321,
        "email": "buyer@example.com",
        "phone": "+966500000000",
        "total_price": "250.00",
        "currency": "SAR",
        "abandoned_checkout_url": "https://shop.example.com/recover/abc",
        "line_items": [{"id": 1}, {"id": 2}],
        "customer": {"first_name": "Sara", "last_name": "Ali"},
        "updated_at": "2026-06-19T10:00:00Z",
    }
    note, phone = w.shopify_checkout_to_notification(checkout)
    assert note["id"] == "987654321"
    assert note["total"] == "250.00"
    assert note["currency"] == "SAR"
    assert note["items_count"] == 2
    assert note["checkout_url"] == "https://shop.example.com/recover/abc"
    assert note["customer_email"] == "buyer@example.com"
    assert phone and phone != "—"
    assert note["customer_phone"] == phone


def test_shopify_checkout_falls_back_to_token_id():
    note, _ = w.shopify_checkout_to_notification({"token": "tok_123", "line_items": []})
    assert note["id"] == "tok_123"
    assert note["items_count"] == 0


def test_zid_cart_maps_to_notification():
    cart = {
        "id": "b978fcc2-ccd0-45f6-81a7-7ab1f3b8f85d",
        "url": "https://osama.zid.store/checkout/fromBasket/3:694ff",
        "customer_name": "mahmoud",
        "customer_mobile": "966500000005",
        "customer_email": "a@zid.sa",
        "cart_total": 509.83,
        "currency_code": "EGP",
        "products_count": 3,
    }
    note, phone = w.zid_cart_to_notification(cart)
    assert note["id"] == "b978fcc2-ccd0-45f6-81a7-7ab1f3b8f85d"
    assert note["customer_name"] == "mahmoud"
    assert note["currency"] == "EGP"
    assert note["items_count"] == 3
    assert note["checkout_url"].startswith("https://osama.zid.store")
    assert phone and phone != "—"


@pytest.fixture
def patched(monkeypatch):
    calls = {"notify": [], "wa": [], "saved": []}

    async def _notify(store_id, kind, payload):
        calls["notify"].append((store_id, kind, payload))

    async def _wa(store_id, cfg, phone, text):
        calls["wa"].append((store_id, phone, text))

    async def _coupon(store_id, cfg):
        return ""

    # record_abandoned_cart + these helpers live in the webhooks._base submodule
    # after the package split; patch them where they're defined and called.
    monkeypatch.setattr(w._base, "_log_event", lambda *a, **k: None)
    monkeypatch.setattr(w._notif, "notify", _notify)
    monkeypatch.setattr(w._base, "_wa_send", _wa)
    monkeypatch.setattr(w._base, "_recovery_coupon_line", _coupon)
    monkeypatch.setattr(w.sm, "get_ai_config", lambda sid: {})
    monkeypatch.setattr(w.sm, "get_store_info", lambda sid: {"store_name": "متجر"})
    return calls


async def _set_save(monkeypatch, returns: bool):
    async def _save(store_id, cart_id, data):
        return returns
    monkeypatch.setattr(w.db, "save_abandoned_cart", _save)


async def test_new_cart_notifies_and_whatsapps(patched, monkeypatch):
    await _set_save(monkeypatch, True)
    note = {"id": "c1", "customer_name": "Sara", "total": "250", "currency": "SAR",
            "checkout_url": "https://x/recover"}
    ok = await w.record_abandoned_cart("store_a", note, phone="+966500000000")
    await asyncio.sleep(0)  # let the fire-and-forget tasks run
    assert ok is True
    assert len(patched["notify"]) == 1
    assert len(patched["wa"]) == 1
    assert "250 SAR" in patched["wa"][0][2]


async def test_duplicate_cart_is_silent(patched, monkeypatch):
    await _set_save(monkeypatch, False)  # conflict → already recorded
    note = {"id": "c1", "customer_name": "Sara", "total": "250", "currency": "SAR"}
    ok = await w.record_abandoned_cart("store_a", note, phone="+966500000000")
    await asyncio.sleep(0)
    assert ok is False
    assert patched["notify"] == []
    assert patched["wa"] == []


async def test_new_cart_without_phone_still_records_no_wa(patched, monkeypatch):
    await _set_save(monkeypatch, True)
    note = {"id": "c2", "customer_name": "—", "total": "10", "currency": "SAR"}
    ok = await w.record_abandoned_cart("store_a", note, phone="")
    await asyncio.sleep(0)
    assert ok is True
    assert len(patched["notify"]) == 1   # owner still emailed
    assert patched["wa"] == []           # no customer phone → no WhatsApp
