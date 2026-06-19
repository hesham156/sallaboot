"""
Tests for the Shopify catalogue-context formatters that give the bot parity with
Salla's deeper sync (branches / shipping zones / offers).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

import shopify_sync as s


pytestmark = pytest.mark.unit


def test_location_maps_to_branch_shape():
    b = s._format_location({
        "id": 5, "name": "الفرع الرئيسي", "address1": "شارع 1", "address2": "مبنى 2",
        "city": "الرياض", "country_name": "السعودية", "phone": "0500",
    })
    assert b == {"id": 5, "name": "الفرع الرئيسي", "city": "الرياض",
                 "country": "السعودية", "address": "شارع 1 مبنى 2", "phone": "0500"}


def test_shipping_zone_flattens_countries_and_provinces():
    z = s._format_shipping_zone({
        "id": 1, "name": "الخليج",
        "countries": [
            {"name": "السعودية", "provinces": [{"name": "الرياض"}, {"name": "جدة"}]},
            {"name": "الإمارات", "provinces": []},
        ],
    })
    assert z["name"] == "الخليج"
    assert "السعودية" in z["country"] and "الإمارات" in z["country"]
    assert z["cities"] == ["الرياض", "جدة"]


def test_price_rule_percentage_becomes_offer():
    future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    o = s._format_price_rule({
        "id": 9, "title": "عيد", "value_type": "percentage", "value": "-15.0",
        "starts_at": future, "ends_at": future, "target_selection": "all",
    })
    assert o is not None
    assert o["name"] == "عيد"
    assert o["message"] == "خصم 15.0%"
    assert o["applied_to"] == "all"


def test_price_rule_fixed_amount_message():
    o = s._format_price_rule({"id": 1, "title": "خصم ثابت",
                              "value_type": "fixed_amount", "value": "-30"})
    assert o["message"] == "خصم 30"


def test_expired_price_rule_is_dropped():
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert s._format_price_rule({"id": 1, "title": "قديم", "value_type": "percentage",
                                 "value": "-10", "ends_at": past}) is None


def test_price_rule_without_end_date_is_kept():
    o = s._format_price_rule({"id": 1, "title": "دائم", "value_type": "percentage", "value": "-5"})
    assert o is not None and o["end_date"] == ""
