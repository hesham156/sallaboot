"""
deps.resolve_store_id — the storefront widget addresses the bot by Salla's
merchant_id, but account-preserving linking moves the bot onto the owning 7ayak
account and deletes the merchant store row. Public widget endpoints must map the
merchant_id back to the account or the widget gets "orphan store refused".
"""
from __future__ import annotations

import pytest

from routers import deps


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_cache():
    deps._merchant_map_cache.clear()
    yield
    deps._merchant_map_cache.clear()


@pytest.fixture
def patched(monkeypatch):
    def _apply(mapping: dict, available: bool = True):
        class _DB:
            def available(self):
                return available

            async def resolve_merchant_to_account(self, mid):
                return mapping.get(str(mid))

        monkeypatch.setattr(deps, "db", _DB())
    return _apply


async def test_maps_merchant_id_to_account(patched):
    patched({"19314436": "h123asham"})
    assert await deps.resolve_store_id("19314436") == "h123asham"


async def test_unmapped_id_passes_through(patched):
    """Salla-first / non-Salla stores have no mapping → unchanged."""
    patched({})
    assert await deps.resolve_store_id("salla_first_store") == "salla_first_store"


async def test_blank_becomes_default(patched):
    patched({})
    assert await deps.resolve_store_id("") == "default"


async def test_no_db_passes_through(patched):
    patched({"19314436": "h123asham"}, available=False)
    assert await deps.resolve_store_id("19314436") == "19314436"


async def test_result_is_cached(patched, monkeypatch):
    calls = {"n": 0}

    class _DB:
        def available(self):
            return True

        async def resolve_merchant_to_account(self, mid):
            calls["n"] += 1
            return "h123asham"

    monkeypatch.setattr(deps, "db", _DB())
    assert await deps.resolve_store_id("19314436") == "h123asham"
    assert await deps.resolve_store_id("19314436") == "h123asham"
    assert calls["n"] == 1   # second call served from the TTL cache


# ── DB-layer fallback: resolve via the account's salla_merchant_id ──────────────

async def test_resolve_merchant_falls_back_to_salla_merchant_id(monkeypatch):
    """When the app_settings breadcrumb is missing, resolve_merchant_to_account
    finds the account by its plaintext salla_merchant_id and self-heals the map."""
    import database as db
    healed = {}

    async def _no_setting(key, default=None):
        return default

    async def _find(mid):
        return "h123asham" if mid == "19314436" else None

    async def _set_map(mid, acct):
        healed["map"] = (mid, acct)

    monkeypatch.setattr(db, "get_app_setting", _no_setting)
    monkeypatch.setattr(db, "find_account_by_salla_merchant", _find)
    monkeypatch.setattr(db, "set_salla_merchant_map", _set_map)

    assert await db.resolve_merchant_to_account("19314436") == "h123asham"
    assert healed["map"] == ("19314436", "h123asham")   # breadcrumb self-healed
    assert await db.resolve_merchant_to_account("nope") is None
