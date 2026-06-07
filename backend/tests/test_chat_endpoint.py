"""
/chat endpoint guardrails (Phase 0 C4 + C10).

C4 = rate limit per session / IP / store.
C10 = orphan-store refusal (widget asks for an unregistered store_id →
      friendly error, NOT silent reroute into another merchant's inbox).

Some checks (input validation, orphan refusal) don't need a DB and run as
unit. Others (rate-limit counter, normal happy path) need clean_db.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


# ── No-DB tests (validation + orphan refusal) ─────────────────────────────

class TestChatValidation:
    pytestmark = pytest.mark.unit

    @pytest.fixture
    async def chat_client(self):
        """Bare client, no DB fixture. Rate limit is DB-backed so it
        fail-opens here (intended — we're testing other code paths)."""
        import main
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    async def test_empty_message_rejected(self, chat_client):
        r = await chat_client.post("/chat", json={"message": "  "})
        assert r.status_code == 400
        assert "فارغة" in r.json()["detail"]

    async def test_oversized_message_rejected(self, chat_client):
        """4000-char cap is the C4 DoS guard — keeps a single request from
        blowing the LLM context window OR being used as a JSON DoS."""
        r = await chat_client.post("/chat", json={"message": "x" * 4001})
        assert r.status_code == 413
        assert "طويلة" in r.json()["detail"]

    async def test_message_at_cap_is_accepted(self, chat_client):
        """Boundary case — exactly 4000 chars should NOT trip the cap.
        Returns 200 with the "store not set up" canned reply (no agent
        registered in this minimal env)."""
        r = await chat_client.post("/chat", json={"message": "x" * 4000})
        # We accept anything ≠ 413 here — the rest of the request flow
        # may fail with 200+error message, but the size check passed.
        assert r.status_code != 413


class TestChatOrphanRefusal:
    """C10: an unregistered store_id must NOT be silently merged."""
    pytestmark = pytest.mark.unit

    @pytest.fixture
    async def chat_client(self):
        import main
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    async def test_unregistered_store_gets_setup_required_reply(self, chat_client):
        """
        The exact regression test for C10. Pre-hardening: widget calling
        with an unknown store_id was rerouted to the first registered
        store, leaking customer chats. Now: friendly refusal.
        """
        r = await chat_client.post("/chat", json={
            "message":  "مرحبا",
            "store_id": "definitely-not-registered-12345",
        })
        assert r.status_code == 200, "still 200 — widget shouldn't break"
        body = r.json()
        assert body["bot_enabled"] is True, \
            "must NOT flip to admin-takeover mode (that triggers the loop bug)"
        # Arabic "store not linked yet" copy
        assert "لم يُربط" in body["reply"] or "تثبيت" in body["reply"], \
            f"expected setup-required reply, got: {body['reply']!r}"

    async def test_default_store_still_falls_back_when_env_token_present(self, chat_client, monkeypatch):
        """
        The "default" store_id is a special case — when SALLA_ACCESS_TOKEN
        is set, that token registers as the default store for direct
        embeds outside Salla Snippets. C10 didn't break this path.
        """
        monkeypatch.setenv("SALLA_ACCESS_TOKEN", "test-env-token-fake")
        r = await chat_client.post("/chat", json={
            "message":  "test",
            "store_id": "default",
        })
        # Still returns 200; either a real reply or a canned "store not set up"
        # if the agent can't be built — either way, NO 5xx.
        assert r.status_code == 200

    async def test_unresolved_template_falls_back_to_default(self, chat_client):
        """
        When Salla doesn't resolve `{{ merchant.id }}` server-side
        (widget embedded outside Salla Snippets), the literal string
        comes through. Treated as 'default', not as orphan refusal.
        """
        r = await chat_client.post("/chat", json={
            "message":  "test",
            "store_id": "{{ merchant.id }}",
        })
        assert r.status_code == 200
        # Should NOT contain the orphan-store specific copy
        assert "لم يُربط" not in r.json().get("reply", "")


# ── DB-dependent tests (rate limit) ───────────────────────────────────────

class TestChatRateLimit:
    """C4 rate-limit axes: session, IP, store. Requires a DB to persist
    the attempt counter."""
    pytestmark = pytest.mark.integration

    async def test_session_axis_trips_at_limit(self, app_client, register_test_store):
        """40 msgs/60s/session is the lowest cap — flood one session to trip it.
        Note: each request increments the counter once; the cap is INCLUSIVE
        (the 41st request is the one rejected)."""
        await register_test_store("test-store")
        session_id = "test-session-rl-1"

        # Track when we hit the cap. Send 50 to be safe.
        rejected = 0
        for _ in range(50):
            r = await app_client.post("/chat", json={
                "message":    "hi",
                "store_id":   "test-store",
                "session_id": session_id,
            })
            if r.status_code == 429:
                rejected += 1
        # We expect SOME rejections once we cross 40.
        assert rejected > 0, "session-axis rate limit didn't trip after 50 requests"
        # And the rejection message points the user at the right action.
        # (Get one fresh rejection to check the body.)
        r = await app_client.post("/chat", json={
            "message":    "hi",
            "store_id":   "test-store",
            "session_id": session_id,
        })
        assert r.status_code == 429
        assert "كثير" in r.json()["detail"] or "انتظر" in r.json()["detail"]

    async def test_different_sessions_dont_share_quota(self, app_client, register_test_store):
        """Two different session_ids must each have their own bucket."""
        await register_test_store("test-store-2")

        # Burn 20 on session A — should NOT block session B.
        for _ in range(20):
            await app_client.post("/chat", json={
                "message":    "a",
                "store_id":   "test-store-2",
                "session_id": "session-A",
            })

        # Session B's first message goes through fine.
        r = await app_client.post("/chat", json={
            "message":    "b",
            "store_id":   "test-store-2",
            "session_id": "session-B",
        })
        assert r.status_code != 429, \
            "session-B should not inherit session-A's rate-limit count"
