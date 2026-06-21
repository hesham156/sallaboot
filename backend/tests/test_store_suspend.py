"""
Store suspension (super-admin "pause subscription"):
  • store_manager flag round-trips and surfaces in list_stores
  • agent.chat refuses to serve a suspended store on EVERY channel (the one
    chokepoint) — without calling the LLM.

Pure-unit: seeds the in-memory registry directly (conftest clears it between
tests) — no DB, no network.
"""
from __future__ import annotations

import pytest

import store_manager as sm

pytestmark = pytest.mark.unit


def _seed(store_id: str, **tokens):
    sm._registry[store_id] = {"tokens": {"store_name": store_id, **tokens}, "cache": {}}


def test_is_suspended_defaults_false():
    _seed("s1")
    assert sm.is_suspended("s1") is False


async def test_set_suspended_toggles():
    _seed("s1")
    assert await sm.set_suspended("s1", True) is True
    assert sm.is_suspended("s1") is True
    assert await sm.set_suspended("s1", False) is True
    assert sm.is_suspended("s1") is False


async def test_set_suspended_unknown_store():
    assert await sm.set_suspended("ghost", True) is False
    assert sm.is_suspended("ghost") is False


def test_list_stores_exposes_suspended_flag():
    _seed("s1", suspended=True)
    _seed("s2")
    rows = {r["store_id"]: r for r in sm.list_stores()}
    assert rows["s1"]["suspended"] is True
    assert rows["s2"]["suspended"] is False


# A dummy provider key so PrintingAgent(...) constructs; the suspension gate
# returns BEFORE any provider call, so the key is never used.
_AI = {"groq_api_key": "test-key"}


async def test_agent_chat_blocked_when_suspended():
    """A suspended store gets a paused notice instead of an LLM reply."""
    import agent as agent_mod
    _seed("s1", suspended=True, ai_config=_AI)
    a = agent_mod.PrintingAgent(store_id="s1")
    reply = await a.chat("مرحبا", "sess-1")
    assert "متوقفة" in reply


async def test_agent_not_blocked_when_active(monkeypatch):
    """An active store passes the gate (here it answers via the fast path,
    proving no suspension short-circuit) — and never hits a real LLM."""
    import agent as agent_mod
    import conversation_store as cs
    _seed("s1", ai_config=_AI)  # not suspended

    async def _fp(*_a, **_k):
        return {"type": "text", "text": "FP-OK", "source": "test"}
    async def _noop(*_a, **_k):
        return {}

    monkeypatch.setattr(agent_mod.smart_router, "route", _fp)
    monkeypatch.setattr(cs, "add_message", _noop)

    a = agent_mod.PrintingAgent(store_id="s1")
    reply = await a.chat("مرحبا", "sess-2")
    assert reply == "FP-OK"
