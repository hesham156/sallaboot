"""
CORS middleware tests (C6 — admin allowlist vs public wildcard).

The middleware is in main.cors_middleware. Two requirements:
  • Admin/store paths (`/admin/*`, `/store/*`) only echo Origin when it's
    in the allowlist (BASE_URL + ADMIN_ALLOWED_ORIGINS + localhost dev ports).
  • Public paths (`/chat`, `/widget.js`, etc) echo any Origin.

We hit the app via httpx.ASGITransport — no real DB needed for these checks
because CORS happens before the route runs. Health endpoint is a safe target.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.unit


@pytest.fixture
async def cors_client():
    """Standalone client — no DB fixtures since CORS is path-routed."""
    import main
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Public surface: any Origin echoed ────────────────────────────────────

async def test_public_path_echoes_any_origin(cors_client):
    """Widget on a merchant's storefront must work cross-origin."""
    r = await cors_client.get(
        "/health",
        headers={"Origin": "https://random-merchant.example.com"},
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "https://random-merchant.example.com"


async def test_public_path_without_origin_uses_wildcard(cors_client):
    """Server-to-server callers (no Origin header) get '*' — never blocked."""
    r = await cors_client.get("/health")
    assert r.status_code == 200
    # When there's no Origin, we fall through to '*' for public paths.
    assert r.headers.get("access-control-allow-origin") == "*"


# ── Admin surface: allowlist only ────────────────────────────────────────

async def test_admin_path_allowed_from_base_url(cors_client):
    """BASE_URL is implicitly in the allowlist (set in conftest)."""
    r = await cors_client.get(
        "/admin/stores",
        headers={"Origin": "https://test.sallabot.example"},
    )
    # Returns 401 (no auth), but CORS header must be present.
    assert r.headers.get("access-control-allow-origin") == "https://test.sallabot.example"


async def test_admin_path_allowed_from_csv_origin(cors_client):
    """ADMIN_ALLOWED_ORIGINS CSV in conftest includes https://admin.example."""
    r = await cors_client.get(
        "/admin/stores",
        headers={"Origin": "https://admin.example"},
    )
    assert r.headers.get("access-control-allow-origin") == "https://admin.example"


async def test_admin_path_blocked_from_random_origin(cors_client):
    """The whole point of C6 — random origins do NOT get an ACAO header."""
    r = await cors_client.get(
        "/admin/stores",
        headers={"Origin": "https://evil.example.com"},
    )
    # No ACAO header → browser blocks the response from being read.
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


async def test_admin_path_allows_localhost_dev(cors_client):
    """Dev work on vite or CRA must keep working without env tweaks."""
    for origin in (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
    ):
        r = await cors_client.get(
            "/admin/stores",
            headers={"Origin": origin},
        )
        assert r.headers.get("access-control-allow-origin") == origin, \
            f"localhost dev origin {origin!r} must be allowed"


# ── Preflight short-circuit ──────────────────────────────────────────────

async def test_preflight_options_returns_204_without_calling_route(cors_client):
    """OPTIONS doesn't trigger auth — it short-circuits with CORS headers."""
    r = await cors_client.request(
        "OPTIONS",
        "/admin/some-store/conversations",
        headers={
            "Origin":                           "https://admin.example",
            "Access-Control-Request-Method":    "POST",
            "Access-Control-Request-Headers":   "Authorization, Content-Type",
        },
    )
    assert r.status_code == 204
    assert r.headers.get("access-control-allow-origin")  == "https://admin.example"
    assert "POST" in r.headers.get("access-control-allow-methods", "")
    # Should echo the requested headers list back
    assert "Authorization" in r.headers.get("access-control-allow-headers", "")


async def test_preflight_for_blocked_origin_omits_acao(cors_client):
    """A preflight from a non-allowlisted origin still returns 204 but with no
    ACAO header — the browser then refuses to send the real request."""
    r = await cors_client.request(
        "OPTIONS",
        "/admin/some-store/conversations",
        headers={
            "Origin":                         "https://evil.example",
            "Access-Control-Request-Method":  "POST",
        },
    )
    assert r.status_code == 204
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# ── Vary: Origin header (caching correctness) ────────────────────────────

async def test_vary_origin_set_when_origin_echoed(cors_client):
    """Without Vary: Origin, CDN caches mix responses for different origins."""
    r = await cors_client.get(
        "/health",
        headers={"Origin": "https://m1.example.com"},
    )
    assert "origin" in r.headers.get("vary", "").lower()
