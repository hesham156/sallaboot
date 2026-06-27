"""
store_manager multi-number WhatsApp support: a store can connect several numbers
(sales + support …), all served by the same bot; an inbound message is answered
from the number it arrived on. The legacy flat fields mirror the primary number.
"""
from __future__ import annotations

import pytest

import store_manager as sm


pytestmark = pytest.mark.unit


@pytest.fixture
def env(monkeypatch):
    stores: dict = {}
    reg: dict = {}
    monkeypatch.setattr(sm, "_registry", reg, raising=False)
    monkeypatch.setattr(sm, "get_ai_config", lambda sid: dict(stores.get(sid, {})))

    async def _set(sid, cfg):
        stores[sid] = dict(cfg)
        reg[sid] = {}

    monkeypatch.setattr(sm, "set_ai_config", _set)

    def add(sid, cfg):
        stores[sid] = dict(cfg)
        reg[sid] = {}

    class _E:
        pass
    e = _E()
    e.stores = stores
    e.add = add
    return e


def test_legacy_flat_fields_become_one_number(env):
    env.add("s1", {"whatsapp_phone_id": "P1", "whatsapp_token": "T1",
                   "whatsapp_waba_id": "W1", "whatsapp_enabled": True})
    nums = sm.get_whatsapp_numbers("s1")
    assert len(nums) == 1
    assert nums[0]["phone_id"] == "P1" and nums[0]["token"] == "T1"
    assert nums[0]["enabled"] is True


def test_multi_number_list_is_returned(env):
    env.add("s1", {"whatsapp_numbers": [
        {"phone_id": "P1", "token": "T1", "enabled": True},
        {"phone_id": "P2", "token": "T2", "enabled": True},
    ]})
    assert [n["phone_id"] for n in sm.get_whatsapp_numbers("s1")] == ["P1", "P2"]


def test_find_number_matches_any_and_returns_its_token(env):
    env.add("s1", {"whatsapp_numbers": [
        {"phone_id": "P1", "token": "T1", "enabled": True},
        {"phone_id": "P2", "token": "T2", "enabled": True},
    ]})
    sid, num = sm.find_whatsapp_number("P2")
    assert sid == "s1" and num["token"] == "T2"   # reply uses THIS number's token
    assert sm.find_whatsapp_number("nope") == ("", {})


def test_find_number_prefers_enabled_with_token(env):
    env.add("stale", {"whatsapp_numbers": [{"phone_id": "P1", "token": "", "enabled": False}]})
    env.add("live",  {"whatsapp_numbers": [{"phone_id": "P1", "token": "T1", "enabled": True}]})
    assert sm.find_whatsapp_number("P1")[0] == "live"


async def test_upsert_adds_and_syncs_primary(env):
    env.add("s1", {"whatsapp_numbers": [{"phone_id": "P1", "token": "T1", "enabled": True}]})
    await sm.upsert_whatsapp_number("s1", {"phone_id": "P2", "token": "T2", "enabled": True})
    nums = sm.get_whatsapp_numbers("s1")
    assert {n["phone_id"] for n in nums} == {"P1", "P2"}
    # flat primary mirrors the first enabled number
    assert env.stores["s1"]["whatsapp_phone_id"] == "P1"
    assert env.stores["s1"]["whatsapp_enabled"] is True


async def test_upsert_updates_existing_number(env):
    env.add("s1", {"whatsapp_numbers": [{"phone_id": "P1", "token": "OLD", "enabled": True}]})
    await sm.upsert_whatsapp_number("s1", {"phone_id": "P1", "token": "NEW", "enabled": True})
    nums = sm.get_whatsapp_numbers("s1")
    assert len(nums) == 1 and nums[0]["token"] == "NEW"


async def test_remove_number_leaves_the_rest(env):
    env.add("s1", {"whatsapp_numbers": [
        {"phone_id": "P1", "token": "T1", "enabled": True},
        {"phone_id": "P2", "token": "T2", "enabled": True},
    ]})
    assert await sm.remove_whatsapp_number("s1", "P1") is True
    assert [n["phone_id"] for n in sm.get_whatsapp_numbers("s1")] == ["P2"]
    # primary re-synced to the remaining number
    assert env.stores["s1"]["whatsapp_phone_id"] == "P2"
    assert await sm.remove_whatsapp_number("s1", "missing") is False


async def test_upsert_migrates_legacy_single_number(env):
    env.add("s1", {"whatsapp_phone_id": "P1", "whatsapp_token": "T1", "whatsapp_enabled": True})
    await sm.upsert_whatsapp_number("s1", {"phone_id": "P2", "token": "T2", "enabled": True})
    assert {n["phone_id"] for n in sm.get_whatsapp_numbers("s1")} == {"P1", "P2"}
