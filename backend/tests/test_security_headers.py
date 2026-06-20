"""
Security response-header tests (finding M-18).

Verifies the defensive headers added in middleware:
  • HSTS + Permissions-Policy on every response (safe everywhere).
  • X-Frame-Options + a frame-ancestors/base-uri/object-src CSP on the admin
    dashboard only — NOT on the public widget/API surface, so storefront
    embedding keeps working.
  • The CSP intentionally carries no script-src/style-src (would break the
    Salla OAuth callback's inline <script>) — asserted here so a future change
    that adds one is a conscious, tested decision.

No DB needed — headers are applied by middleware before the route runs.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.unit


@pytest.fixture
async def client():
    import main
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Global safe headers (public surface) ─────────────────────────────────────

async def test_hsts_present_on_public_response(client):
    r = await client.get("/health")
    hsts = r.headers.get("strict-transport-security", "")
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts


async def test_permissions_policy_present(client):
    r = await client.get("/health")
    pp = r.headers.get("permissions-policy", "")
    assert "geolocation=()" in pp and "camera=()" in pp


async def test_nosniff_and_referrer_present(client):
    r = await client.get("/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


# ── Public surface must NOT get the dashboard-only headers ───────────────────

async def test_public_surface_has_no_frame_or_csp(client):
    """The widget/API must stay embeddable — no X-Frame-Options / CSP on /health."""
    r = await client.get("/health")
    keys = {k.lower() for k in r.headers}
    assert "x-frame-options" not in keys
    assert "content-security-policy" not in keys


# ── Admin dashboard gets clickjacking + CSP hardening ────────────────────────

async def test_admin_has_frame_options_and_csp(client):
    # /admin/stores returns 401 (no token) but the headers are added on the way out.
    r = await client.get("/admin/stores")
    assert r.headers.get("x-frame-options") == "SAMEORIGIN"
    csp = r.headers.get("content-security-policy", "")
    assert "frame-ancestors 'self'" in csp
    assert "base-uri 'self'" in csp
    assert "object-src 'none'" in csp


async def test_admin_csp_has_no_script_src(client):
    """Guard against accidentally adding a script-src that would break the
    Salla OAuth callback's inline <script>. Removing this needs a nonce pass."""
    r = await client.get("/admin/stores")
    csp = r.headers.get("content-security-policy", "")
    assert "script-src" not in csp
