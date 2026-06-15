"""
Tests for the live shipping + inventory tools.

Focus is the schema-sensitive layer: the exact Salla requests (estimate-rate
needs city_id + country_id), and the geo-resolution cache that turns a city
NAME into the city_id Salla wants (cities have no search param, so we lazily
scan + cache pages — major cities sit on page 1).
"""
from __future__ import annotations

import pytest

import salla_client
from salla_client import SallaClient

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_geo_cache():
    """Geo caches are process-wide; reset them so tests don't bleed into each other."""
    salla_client._COUNTRY_CACHE.clear()
    salla_client._CITY_CACHE.clear()
    salla_client._CITY_PAGES_SCANNED.clear()
    yield


async def test_estimate_rate_sends_city_and_country(monkeypatch):
    captured: dict = {}

    async def fake_request(self, method, path, **kwargs):
        captured["path"] = path
        captured["params"] = kwargs.get("params")
        return {"data": []}

    monkeypatch.setattr(SallaClient, "_request", fake_request)
    client = SallaClient("tok", store_id="s1")
    await client.estimate_shipping_rates(city_id=42, country_id=99)

    assert captured["path"] == "/shipping/companies/estimate-rate"
    assert captured["params"]["city_id"] == 42
    assert captured["params"]["country_id"] == 99


async def test_variants_and_tracking_paths(monkeypatch):
    seen: list = []

    async def fake_request(self, method, path, **kwargs):
        seen.append((method, path))
        return {"data": {}}

    monkeypatch.setattr(SallaClient, "_request", fake_request)
    client = SallaClient("tok", store_id="s1")
    await client.get_product_variants(123)
    await client.get_shipment_tracking(456)
    await client.get_shipments(order_id=789)

    assert ("GET", "/products/123/variants") in seen
    assert ("GET", "/shipments/456/tracking") in seen


async def test_resolve_country_defaults_to_saudi(monkeypatch):
    async def fake_list_countries(self, page=1):
        return {
            "data": [
                {"id": 111, "name": "السعودية", "name_en": "Saudi Arabia", "code": "SA"},
                {"id": 222, "name": "الكويت", "name_en": "Kuwait", "code": "KW"},
            ],
            "pagination": {"links": {}},
        }

    monkeypatch.setattr(SallaClient, "list_countries", fake_list_countries)
    client = SallaClient("tok", store_id="s1")

    # No name → defaults to Saudi Arabia.
    assert await client.resolve_country_id("") == 111
    # By Arabic name.
    assert await client.resolve_country_id("الكويت") == 222
    # Cached now — a second call must not need the network (sabotage the fetch).
    async def boom(self, page=1):
        raise AssertionError("should have hit the cache")
    monkeypatch.setattr(SallaClient, "list_countries", boom)
    assert await client.resolve_country_id("الكويت") == 222


async def test_resolve_city_scans_and_caches(monkeypatch):
    pages = {
        1: {"data": [{"id": 10, "name": "الرياض", "name_en": "Riyadh", "country_id": 111}],
            "pagination": {"links": {"next": "p2"}}},
        2: {"data": [{"id": 20, "name": "جدة", "name_en": "Jeddah", "country_id": 111}],
            "pagination": {"links": {}}},
    }
    calls = {"n": 0}

    async def fake_list_cities(self, country_id, page=1):
        calls["n"] += 1
        return pages.get(page, {"data": [], "pagination": {"links": {}}})

    monkeypatch.setattr(SallaClient, "list_cities", fake_list_cities)
    client = SallaClient("tok", store_id="s1")

    # City on page 2 — the scan must walk to it.
    assert await client.resolve_city_id(111, "جدة") == 20
    # Page 1 city is now cached from the same scan — no extra fetches.
    before = calls["n"]
    assert await client.resolve_city_id(111, "الرياض") == 10
    assert calls["n"] == before
    # Alef/tatweel-insensitive match.
    assert await client.resolve_city_id(111, "جده") == 20


async def test_resolve_city_unknown_returns_none(monkeypatch):
    async def fake_list_cities(self, country_id, page=1):
        return {"data": [{"id": 10, "name": "الرياض", "country_id": 111}],
                "pagination": {"links": {}}}

    monkeypatch.setattr(SallaClient, "list_cities", fake_list_cities)
    client = SallaClient("tok", store_id="s1")
    assert await client.resolve_city_id(111, "مدينة وهمية لا توجد") is None
