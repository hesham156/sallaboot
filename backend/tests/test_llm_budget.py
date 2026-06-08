"""
Tests for the daily LLM token-budget circuit breaker.

What this covers
────────────────
• db.llm_usage_record + llm_usage_today: UPSERT semantics, accumulation
  across multiple calls on the same day, isolation between stores.
• db.llm_usage_report: returns N days newest-first with zero-filled gaps.
• _daily_token_budget + _budget_exhausted in main.py: precedence
  (per-store override > env > built-in default), and the exhausted path.
• /chat circuit breaker: returns a friendly Arabic refusal once usage
  meets the budget — without hitting the LLM at all (we monkeypatch
  agent.chat to make sure no real provider is called).
• GET /admin/{store_id}/llm-usage: returned shape (today / budget / history).
• PUT /admin/{store_id}/llm-budget: owner-only, integer validation,
  null clears the override.

DB-backed (so the integration marker is set) — relies on the conftest
testcontainer / TEST_DATABASE_URL fixture chain.
"""
from __future__ import annotations

import os

import pytest

import database as db
import main
import store_manager as sm


pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────────
# DB-layer tests
# ─────────────────────────────────────────────────────────────────────────

async def test_record_and_today_accumulate(clean_db):
    """Two records on the same day add up; another store is independent."""
    await db.llm_usage_record("store-a", 100, 50)
    await db.llm_usage_record("store-a", 250, 75)
    await db.llm_usage_record("store-b",  10,  5)

    a = await db.llm_usage_today("store-a")
    b = await db.llm_usage_today("store-b")

    assert a["tokens_in"]    == 350
    assert a["tokens_out"]   == 125
    assert a["tokens_total"] == 475
    assert a["requests"]     == 2
    assert b["tokens_in"]    == 10
    assert b["tokens_out"]   == 5
    assert b["requests"]     == 1


async def test_today_zero_when_no_row(clean_db):
    """Fresh store with no usage today returns zeros, not None."""
    today = await db.llm_usage_today("never-used")
    assert today == {
        "tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "requests": 0,
    }


async def test_record_ignores_negative_values(clean_db):
    """Defensive: caller passing -1 doesn't decrement the counter."""
    await db.llm_usage_record("store-x", 100, 50)
    await db.llm_usage_record("store-x", -999, -999)  # malformed input
    today = await db.llm_usage_today("store-x")
    assert today["tokens_total"] == 150  # untouched


async def test_report_zero_fills_missing_days(clean_db):
    """report(days=7) returns 7 rows even when only today has data."""
    await db.llm_usage_record("store-a", 100, 50)
    history = await db.llm_usage_report("store-a", days=7)
    assert len(history) == 7
    # Newest first — today has tokens, the rest are zero.
    assert history[0]["tokens_total"] == 150
    assert all(h["tokens_total"] == 0 for h in history[1:])


# ─────────────────────────────────────────────────────────────────────────
# Budget resolution (env / override / default)
# ─────────────────────────────────────────────────────────────────────────

def test_budget_uses_env_default_when_no_override(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "123456")
    # Empty config → fall back to env
    monkeypatch.setattr(sm, "get_ai_config", lambda _sid: {})
    assert main._daily_token_budget("any") == 123456


def test_budget_store_override_wins(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "999999")
    monkeypatch.setattr(sm, "get_ai_config", lambda _sid: {"daily_token_budget": 7000})
    assert main._daily_token_budget("any") == 7000


def test_budget_override_zero_disables_breaker(monkeypatch):
    """0 must be honoured (paying customer with unlimited agreement)."""
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "500000")
    monkeypatch.setattr(sm, "get_ai_config", lambda _sid: {"daily_token_budget": 0})
    assert main._daily_token_budget("any") == 0


def test_budget_malformed_override_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "42")
    monkeypatch.setattr(sm, "get_ai_config", lambda _sid: {"daily_token_budget": "not-a-number"})
    assert main._daily_token_budget("any") == 42


# ─────────────────────────────────────────────────────────────────────────
# /chat circuit breaker (end-to-end via ASGI client)
# ─────────────────────────────────────────────────────────────────────────

class _FakeAgent:
    """Stand-in for AIAgent — records that chat() was called, never calls a real provider."""
    def __init__(self):
        self.last_usage = {"in": 250, "out": 100}
        self.called = False

    async def chat(self, message: str, session_id: str) -> str:
        self.called = True
        return "fake reply"


async def test_chat_refuses_when_budget_exhausted(
    app_client, register_test_store, monkeypatch
):
    """Existing usage at-or-above budget → refusal without invoking the agent."""
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "1000")
    await register_test_store("store-broke")
    # Push usage past the limit so the next /chat call trips the breaker.
    await db.llm_usage_record("store-broke", 700, 400)  # 1100 > 1000

    fake = _FakeAgent()
    monkeypatch.setattr(sm, "get_agent", lambda _sid: fake)

    r = await app_client.post("/chat", json={
        "message":  "اختبار",
        "store_id": "store-broke",
    })
    assert r.status_code == 200
    body = r.json()
    assert "صيانة" in body["reply"]   # the refusal text
    assert fake.called is False        # agent.chat must NOT have been invoked


async def test_chat_allows_when_within_budget(
    app_client, register_test_store, monkeypatch
):
    """Under the limit → request proceeds and usage is recorded."""
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "10000")
    await register_test_store("store-ok")

    fake = _FakeAgent()
    monkeypatch.setattr(sm, "get_agent", lambda _sid: fake)

    r = await app_client.post("/chat", json={
        "message":  "مرحبا",
        "store_id": "store-ok",
    })
    assert r.status_code == 200
    assert fake.called is True
    today = await db.llm_usage_today("store-ok")
    assert today["tokens_total"] == 350   # 250 + 100 from _FakeAgent.last_usage
    assert today["requests"]     == 1


async def test_chat_allows_when_breaker_disabled(
    app_client, register_test_store, monkeypatch
):
    """Per-store override of 0 = unlimited (breaker off)."""
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "100")
    await register_test_store("store-unlimited", ai_config={"daily_token_budget": 0})
    await db.llm_usage_record("store-unlimited", 9_999_999, 9_999_999)

    fake = _FakeAgent()
    monkeypatch.setattr(sm, "get_agent", lambda _sid: fake)

    r = await app_client.post("/chat", json={
        "message":  "test",
        "store_id": "store-unlimited",
    })
    assert r.status_code == 200
    assert fake.called is True


# ─────────────────────────────────────────────────────────────────────────
# Admin endpoints
# ─────────────────────────────────────────────────────────────────────────

async def test_llm_usage_endpoint_returns_today_and_history(
    app_client, register_test_store, make_token, monkeypatch
):
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "5000")
    sid = await register_test_store("store-view")
    await db.llm_usage_record(sid, 200, 100)

    token = make_token(sid)
    r = await app_client.get(
        f"/admin/{sid}/llm-usage?days=3",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["today"]["tokens_total"] == 300
    assert body["today"]["budget"]       == 5000
    assert body["today"]["remaining"]    == 4700
    assert body["today"]["exhausted"]    is False
    assert body["budget"]["source"]      == "env_default"
    assert len(body["history"]) == 3


async def test_put_budget_owner_can_set_override(
    app_client, register_test_store, make_token, monkeypatch
):
    sid = await register_test_store("store-set")
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "500000")

    token = make_token(sid)   # owner token (no employee_id)
    r = await app_client.put(
        f"/admin/{sid}/llm-budget",
        headers={"Authorization": f"Bearer {token}"},
        json={"daily_token_budget": 1234},
    )
    assert r.status_code == 200
    assert r.json()["effective_budget"] == 1234

    # Round-trip: GET reflects the new budget
    r2 = await app_client.get(
        f"/admin/{sid}/llm-usage",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.json()["budget"]["value"]  == 1234
    assert r2.json()["budget"]["source"] == "store_override"


async def test_put_budget_employee_rejected(
    app_client, register_test_store, make_token
):
    """Employees (any role) must NOT be able to change the budget."""
    sid = await register_test_store("store-emp")
    employee_token = make_token(sid, employee_id=42, role="manager")
    r = await app_client.put(
        f"/admin/{sid}/llm-budget",
        headers={"Authorization": f"Bearer {employee_token}"},
        json={"daily_token_budget": 1},
    )
    # Middleware blocks owner-only routes for employees with 403
    assert r.status_code == 403


async def test_put_budget_null_clears_override(
    app_client, register_test_store, make_token, monkeypatch
):
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "99")
    sid = await register_test_store("store-clear", ai_config={"daily_token_budget": 555})
    token = make_token(sid)

    r = await app_client.put(
        f"/admin/{sid}/llm-budget",
        headers={"Authorization": f"Bearer {token}"},
        json={"daily_token_budget": None},
    )
    assert r.status_code == 200
    assert r.json()["effective_budget"] == 99
