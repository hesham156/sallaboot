"""
Tests for AI-issued discount coupons.

The risky part of this feature is the request body sent to Salla's
`POST /coupons`: the schema's `is_group` defaults to TRUE, so omitting it
creates a *group* coupon instead of the single one-use code we intend. These
tests lock the verified contract (single, one-use, percentage with a SAR cap)
and the agent-side guard rails (opt-in, percent clamp, one coupon per session)
without needing real Salla credentials.
"""
from __future__ import annotations

import pytest

from salla_client import SallaClient

pytestmark = pytest.mark.unit


async def test_create_coupon_builds_single_use_percentage_body(monkeypatch):
    captured: dict = {}

    async def fake_request(self, method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs.get("json")
        return {"data": {"id": 1, "code": kwargs["json"]["code"]}}

    monkeypatch.setattr(SallaClient, "_request", fake_request)

    client = SallaClient("tok", store_id="s1")
    await client.create_coupon(
        code="AIABC123",
        amount=15,
        coupon_type="percentage",
        expiry_date="2026-06-17 23:59:59",
        maximum_amount=200,
        minimum_amount=50,
        usage_limit=1,
        usage_limit_per_user=1,
    )

    body = captured["json"]
    assert captured["method"] == "POST"
    assert captured["path"] == "/coupons"
    # The critical gotcha: must be an explicit single coupon, not a group.
    assert body["is_group"] is False
    assert body["type"] == "percentage"
    assert body["amount"] == 15
    assert body["maximum_amount"] == 200      # required for percentage
    assert body["minimum_amount"] == 50
    assert body["usage_limit"] == 1
    assert body["usage_limit_per_user"] == 1
    assert body["free_shipping"] is False
    assert body["exclude_sale_products"] is True
    assert body["status"] == "active"


async def test_create_coupon_fixed_type_omits_maximum_amount(monkeypatch):
    captured: dict = {}

    async def fake_request(self, method, path, **kwargs):
        captured["json"] = kwargs.get("json")
        return {"data": {"id": 2}}

    monkeypatch.setattr(SallaClient, "_request", fake_request)

    client = SallaClient("tok", store_id="s1")
    await client.create_coupon(
        code="AIFIX",
        amount=30,
        coupon_type="fixed",
        expiry_date="2026-06-17 23:59:59",
        maximum_amount=200,   # should be ignored for fixed
    )
    body = captured["json"]
    assert body["type"] == "fixed"
    assert "maximum_amount" not in body


def test_coupon_tool_gated_by_optin():
    """The coupon tool is exposed to the model only when the merchant opts in."""
    import agent
    off = [t["name"] for t in agent.active_tools(printing=True, coupons=False)]
    on = [t["name"] for t in agent.active_tools(printing=True, coupons=True)]
    assert "generate_discount_coupon" not in off
    assert "generate_discount_coupon" in on
    # Coupons are independent of printing — a general store can still issue them.
    gen_on = [t["name"] for t in agent.active_tools(printing=False, coupons=True)]
    assert "generate_discount_coupon" in gen_on
    assert "calculate_advanced_quote" not in gen_on


def test_clamp_helpers_bound_config():
    import agent
    assert agent._clamp_int(999, 15, lo=1, hi=90) == 90
    assert agent._clamp_int(-5, 15, lo=1, hi=90) == 1
    assert agent._clamp_int("nope", 15, lo=1, hi=90) == 15
    assert agent._clamp_float(1e9, 200.0, lo=0.0, hi=100000.0) == 100000.0
    assert agent._clamp_float(None, 200.0, lo=0.0, hi=100000.0) == 200.0
