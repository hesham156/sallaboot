"""
Unit tests for the custom-store integration (self-built stores that push
catalog + events to 7ayak over HMAC-signed webhooks).

Covers the security boundary (signature verification) and the data-shaping
(raw push JSON → cache_data product format, abandoned-cart mapping). A
regression in _verify_signature would let an attacker forge catalog/order
events for any store that has a custom integration.
"""
from __future__ import annotations

import hashlib
import hmac

import pytest

import custom_sync as cs
from routers import webhooks as w


pytestmark = pytest.mark.unit


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ── Signature verification ────────────────────────────────────────────────────

def test_valid_signature_passes():
    body = b'{"event":"order.created","data":{}}'
    headers = {"X-Hayyak-Signature": "sha256=" + _sign(body, "whsec_abc")}
    ok, detail = w._verify_custom_signature(body, "whsec_abc", headers)
    assert ok is True
    assert detail == "signature_ok"


def test_signature_without_prefix_passes():
    """Accept a bare hex digest as well as the sha256= prefixed form."""
    body = b'{"x":1}'
    headers = {"X-Hayyak-Signature": _sign(body, "whsec_abc")}
    ok, _ = w._verify_custom_signature(body, "whsec_abc", headers)
    assert ok is True


def test_signature_mismatch_rejected():
    body = b'{"event":"catalog"}'
    headers = {"X-Hayyak-Signature": "sha256=" + _sign(body, "attacker")}
    ok, detail = w._verify_custom_signature(body, "whsec_real", headers)
    assert ok is False
    assert detail.startswith("signature_mismatch")


def test_missing_signature_rejected():
    ok, detail = w._verify_custom_signature(b'{"x":1}', "whsec_real", {})
    assert ok is False
    assert detail == "signature_required_but_absent"


def test_no_secret_fails_closed():
    """No stored secret → reject (never accept unsigned writes)."""
    ok, detail = w._verify_custom_signature(b'{"x":1}', "", {"X-Hayyak-Signature": "x"})
    assert ok is False
    assert detail == "no_signing_secret_configured"


def test_tampered_body_rejected():
    """Signature computed over a different body must not validate."""
    headers = {"X-Hayyak-Signature": "sha256=" + _sign(b'{"total":10}', "s")}
    ok, _ = w._verify_custom_signature(b'{"total":9999}', "s", headers)
    assert ok is False


# ── Product formatter ─────────────────────────────────────────────────────────

def test_format_product_basic():
    p = cs.format_custom_product({
        "id": 42, "name": "حذاء", "price": 100, "quantity": 5,
        "categories": ["أحذية"], "image": "https://x/img.png",
    }, currency="SAR")
    assert p["id"] == "42"
    assert p["name"] == "حذاء"
    assert p["status"] == "sale"          # published + in stock
    assert p["categories"] == ["أحذية"]
    assert p["image"] == "https://x/img.png"
    assert p["type"] == "product"


def test_format_product_out_of_stock():
    p = cs.format_custom_product({"id": 1, "name": "x", "quantity": 0})
    assert p["status"] == "out"


def test_format_product_sale_price_when_discounted():
    p = cs.format_custom_product({"id": 1, "name": "x", "price": 80, "regular_price": 100})
    assert p["sale_price"] == "80"
    assert p["regular_price"] == "100"


def test_format_product_aliases_and_image_list():
    """Lenient aliases: title/stock/images-list/category-string."""
    p = cs.format_custom_product({
        "id": 7, "title": "Bag", "price": 50, "stock": 3,
        "category": "Bags", "images": [{"url": "https://x/a.png"}],
    })
    assert p["name"] == "Bag"
    assert p["status"] == "sale"
    assert p["categories"] == ["Bags"]
    assert p["image"] == "https://x/a.png"


def test_apply_catalog_summary(monkeypatch):
    captured = {}
    monkeypatch.setattr(cs.sm, "set_cache", lambda sid, data: captured.update({sid: data}))
    monkeypatch.setattr(cs.sm, "reset_agent", lambda sid: None)
    result = cs.apply_catalog("store1", {
        "store": {"name": "متجري", "currency": "SAR"},
        "products": [{"id": 1, "name": "a", "price": 10},
                     {"id": 2, "name": "b", "price": 20}],
        "categories": [{"id": "c1", "name": "قسم"}],
    })
    assert result == {"products": 2, "categories": 1}
    cache = captured["store1"]
    assert cache["platform"] == "custom"
    assert cache["products_count"] == 2
    assert cache["store_info"]["type"] == "custom"


# ── Abandoned-cart mapper ─────────────────────────────────────────────────────

def test_cart_to_notification():
    notif, phone = cs.custom_cart_to_notification({
        "id": "cart9", "customer_name": "سارة", "customer_phone": "0501234567",
        "total": 250, "currency": "SAR", "items_count": 3,
        "checkout_url": "https://shop/cart/9",
    })
    assert notif["id"] == "cart9"
    assert phone == "+966501234567"
    assert notif["customer_phone"] == "+966501234567"
    assert notif["total"] == "250"
    assert notif["checkout_url"] == "https://shop/cart/9"
    assert notif["status"] == "active"
