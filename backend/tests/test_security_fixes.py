"""
Regression tests for the security-hardening batch.

Each fix gets positive, negative, cross-tenant/attack, and edge cases. These are
pure-unit (no DB, no network): the security decisions live in small helpers and
in-memory state, so we exercise them directly.

Covers:
  1. Cross-tenant conversation IDOR  (routers.conversations._load_owned_conv)
  2. LLM tool BOLA                   (agent.* tools + helpers)
  4. Reflected XSS                   (public.test_widget_page, integrations.shopify_widget_script)
  5. CSV formula injection           (contacts._csv_safe)
  6. Upload memory DoS               (deps.read_upload_bounded)
  7. Webhook SSRF                    (notifications.is_webhook_url_allowed)
  8. Clickjacking headers            (middleware._apply_security_headers)
  9. Input validation               (models.* length bounds)

Training-resource IDOR (#3) is DB-backed → tests/test_training_idor.py.
"""
from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.unit


async def _anoop(*args, **kwargs):
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Cross-tenant conversation IDOR — routers.conversations._load_owned_conv
# ─────────────────────────────────────────────────────────────────────────────

class _Req:
    def __init__(self, token: str = ""):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}


def _seed_conv(session_id: str, store_id: str, **extra):
    import conversation_store as cs
    conv = {"store_id": store_id, "messages": [], "customer_info": {}, "cart": []}
    conv.update(extra)
    cs._conversations.set({session_id: conv})


async def test_conv_owner_match_returns_conv(monkeypatch):
    import conversation_store as cs
    from routers import conversations as conv
    monkeypatch.setattr(cs, "restore_to_memory", _anoop)
    _seed_conv("sid1", "storeA")
    out = await conv._load_owned_conv("sid1", "storeA", _Req())
    assert out is not None and out["store_id"] == "storeA"


async def test_conv_cross_tenant_raises_404(monkeypatch):
    """A store must NOT read another tenant's conversation by session id."""
    import conversation_store as cs
    from routers import conversations as conv
    monkeypatch.setattr(cs, "restore_to_memory", _anoop)
    _seed_conv("wa:+966500000000", "storeA")     # enumerable channel id
    with pytest.raises(HTTPException) as ei:
        await conv._load_owned_conv("wa:+966500000000", "storeB", _Req())
    assert ei.value.status_code == 404


async def test_conv_super_bypasses_ownership(monkeypatch):
    """Super admin viewing a foreign store passes (gated elsewhere by grant)."""
    import auth as _auth
    import conversation_store as cs
    from routers import conversations as conv
    monkeypatch.setattr(cs, "restore_to_memory", _anoop)
    _seed_conv("sid1", "storeA")
    super_tok = _auth.create_token("super", is_super=True)
    out = await conv._load_owned_conv("sid1", "storeB", _Req(super_tok))
    assert out is not None


async def test_conv_missing_returns_none(monkeypatch):
    import conversation_store as cs
    from routers import conversations as conv
    monkeypatch.setattr(cs, "restore_to_memory", _anoop)
    cs._conversations.set({})
    assert await conv._load_owned_conv("nope", "storeA", _Req()) is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. LLM tool BOLA — tools authorize against a backend-trusted SessionIdentity
#
# The old model trusted a per-session ``salla_customer_id`` from the conversation
# store. It's gone: customer-scoped tools now read identity ONLY from the
# immutable ``SessionIdentity`` threaded into ``_run_tool(..., identity=...)`` and
# fetch through an ``OwnedResourceResolver`` that enforces ownership in one place
# (see backend/identity/). These tests drive that object directly.
# ─────────────────────────────────────────────────────────────────────────────

class _FakeSalla:
    def __init__(self, *, order=None, customer=None, carts=None,
                 invoice=None, inv_list=None):
        self.calls: list = []
        self._order = order or {}
        self._customer = customer or {}
        self._carts = carts or []
        self._invoice = invoice or {}
        self._inv_list = inv_list or {"data": []}

    async def get_order(self, ref):
        self.calls.append(("get_order", ref))
        return {"data": self._order}

    async def get_orders(self, **kw):
        self.calls.append(("get_orders", kw))
        return {"data": [self._order] if self._order else []}

    async def get_customer(self, cid, fields=None):
        self.calls.append(("get_customer", cid))
        return {"data": self._customer}

    async def get_customer_by_phone(self, term):
        self.calls.append(("get_customer_by_phone", term))
        return {"data": []}

    async def get_abandoned_carts(self, per_page=10):
        self.calls.append(("get_abandoned_carts", per_page))
        return {"data": self._carts}

    async def get_invoice(self, iid):
        self.calls.append(("get_invoice", iid))
        return {"data": self._invoice}

    async def list_order_invoices(self, oid):
        self.calls.append(("list_order_invoices", oid))
        return self._inv_list


def _bare_agent(salla):
    import agent
    a = agent.PrintingAgent.__new__(agent.PrintingAgent)
    a.salla = salla
    a.store_id = "teststore"
    return a


def _seed_session_claim(session_id="s", *, cid=""):
    """Seed a conversation-store ``salla_customer_id`` — a client/tool CLAIM, not a
    verified identity. Used to prove customer-scoped tools ignore it (SI-1)."""
    import conversation_store as cs
    cs._conversations.set({session_id: {
        "store_id": "teststore", "salla_customer_id": cid,
        "messages": [], "customer_info": {}, "cart": [],
    }})


def _verified_identity(*, cid: str | None = "555", phone: str | None = None,
                       session_id="s", store_id="teststore"):
    """A backend-trusted, verified-customer ``SessionIdentity`` — the ONLY thing a
    customer-scoped tool reads identity from. Mirrors what
    ``IdentityService.upgrade_to_verified`` produces, minus the minted token."""
    from identity import IdentityLevel, LifecycleState, SessionIdentity
    return SessionIdentity(
        session_id=session_id, store_id=store_id,
        identity_level=IdentityLevel.verified_customer,
        lifecycle_state=LifecycleState.verified,
        verified_customer_id=cid, verified_phone=phone,
        verification_method="test",
    )


def _anon_identity(session_id="s", store_id="teststore"):
    from identity import SessionIdentity
    return SessionIdentity.anonymous_for(session_id, store_id)


def test_order_customer_id_shapes():
    import agent
    assert agent._order_customer_id({"customer": {"id": 555}}) == "555"
    assert agent._order_customer_id({"customer_id": 777}) == "777"
    assert agent._order_customer_id({"customer": {}}) == ""
    assert agent._order_customer_id({}) == ""
    assert agent._order_customer_id(None) == ""


def test_identity_levels_gate_customer_reads():
    """Structural replacement for the old per-session cid lookup: identity is a
    backend-issued value object whose level — not a conversation-store field —
    decides whether customer data may be read."""
    assert _anon_identity().is_verified_customer is False
    assert _verified_identity(cid="555").is_verified_customer is True


async def test_tool_ignores_conversation_store_customer_id_claim(monkeypatch):
    """SI-1: a ``salla_customer_id`` sitting in the conversation store (a tool/body
    CLAIM) must NOT authorize a read. With an anonymous identity the tool refuses
    and never touches Salla — even though the store says the visitor is 999."""
    import agent
    import conversation_store as cs
    monkeypatch.setattr(cs, "restore_to_memory", _anoop)
    _seed_session_claim(cid="999")                       # forged / legacy claim
    salla = _FakeSalla(order={"id": 1, "customer": {"id": "999"}})
    a = _bare_agent(salla)
    out = await a._run_tool("track_order", {"order_reference": "10234"}, "s",
                            identity=_anon_identity())
    assert out == agent._VERIFY_REQUIRED_MSG
    assert salla.calls == []


async def test_run_tool_without_identity_fails_closed():
    """When a caller forgets to thread identity, _run_tool resolves it itself. A
    plain (non-channel) session has no verifier, so it resolves ANONYMOUS and the
    tool fails CLOSED rather than open."""
    import agent
    salla = _FakeSalla(order={"id": 1, "customer": {"id": "555"}})
    a = _bare_agent(salla)
    out = await a._run_tool("track_order", {"order_reference": "10234"}, "s")  # no identity
    assert out == agent._VERIFY_REQUIRED_MSG
    assert salla.calls == []


# ── track_order ───────────────────────────────────────────────────────────────

async def test_track_order_unverified_refuses_without_query():
    import agent
    salla = _FakeSalla(order={"id": 1, "customer": {"id": "999"}})
    a = _bare_agent(salla)
    out = await a._run_tool("track_order", {"order_reference": "10234"}, "s",
                            identity=_anon_identity())   # not verified
    assert out == agent._VERIFY_REQUIRED_MSG
    assert salla.calls == []                             # never queried Salla


async def test_track_order_owned_succeeds(monkeypatch):
    import conversation_store as cs
    monkeypatch.setattr(cs, "set_last_component", _anoop)
    salla = _FakeSalla(order={
        "id": 1, "reference_id": "10234", "customer": {"id": "555"},
        "status": {"slug": "completed", "name": "مكتمل"},
        "amounts": {"total": {"amount": "100", "currency": "SAR"}},
    })
    a = _bare_agent(salla)
    out = await a._run_tool("track_order", {"order_reference": "10234"}, "s",
                            identity=_verified_identity(cid="555"))
    assert "10234" in out


async def test_track_order_other_customer_refused():
    """Verified as 555 but the order belongs to 999 → the resolver returns nothing
    and the tool renders a neutral 'not on your account' refusal — never a
    disclosure or an existence oracle."""
    salla = _FakeSalla(order={"id": 1, "reference_id": "10234",
                              "customer": {"id": "999"}})
    a = _bare_agent(salla)
    out = await a._run_tool("track_order", {"order_reference": "10234"}, "s",
                            identity=_verified_identity(cid="555"))
    assert "حسابك" in out                                # "your account" refusal


# ── lookup_customer ───────────────────────────────────────────────────────────

async def test_lookup_customer_unverified_refuses_no_phone_lookup():
    import agent
    salla = _FakeSalla(customer={"id": "555"})
    a = _bare_agent(salla)
    out = await a._run_tool("lookup_customer", {"phone": "0555123456"}, "s",
                            identity=_anon_identity())
    assert out == agent._VERIFY_REQUIRED_MSG
    assert salla.calls == []                             # NO arbitrary phone lookup


async def test_lookup_customer_verified_returns_only_own(monkeypatch):
    import conversation_store as cs
    monkeypatch.setattr(cs, "get_customer_info", lambda sid: {})
    monkeypatch.setattr(cs, "set_customer_info", _anoop)
    monkeypatch.setattr(cs, "flush", _anoop)
    salla = _FakeSalla(customer={"id": "555", "first_name": "Sara",
                                 "mobile": "555", "mobile_code": "966"})
    a = _bare_agent(salla)
    out = await a._run_tool("lookup_customer", {"phone": "0999"}, "s",  # phone ignored
                            identity=_verified_identity(cid="555"))
    assert "Sara" in out
    assert ("get_customer", 555) in salla.calls          # looked up the identity's id
    assert not any(c[0] == "get_customer_by_phone" for c in salla.calls)


# ── get_order_invoice ─────────────────────────────────────────────────────────

async def test_invoice_unverified_refuses():
    import agent
    salla = _FakeSalla(invoice={"invoice_number": "INV1"})
    a = _bare_agent(salla)
    out = await a._run_tool("get_order_invoice", {"order_reference": "10234"}, "s",
                            identity=_anon_identity())
    assert out == agent._VERIFY_REQUIRED_MSG


async def test_invoice_other_customer_refused():
    # order owned by 999, session verified as 555 → no invoice disclosed
    salla = _FakeSalla(order={"id": 1, "customer": {"id": "999"}},
                       inv_list={"data": [{"id": 7}]},
                       invoice={"invoice_number": "INV-SECRET"})
    a = _bare_agent(salla)
    out = await a._run_tool("get_order_invoice", {"order_reference": "10234"}, "s",
                            identity=_verified_identity(cid="555"))
    assert "INV-SECRET" not in out


# ── get_abandoned_carts ───────────────────────────────────────────────────────

async def test_abandoned_carts_unverified_refuses():
    import agent
    salla = _FakeSalla(carts=[{"customer": {"id": "555"}, "total": {"amount": "50"}}])
    a = _bare_agent(salla)
    out = await a._run_tool("get_abandoned_carts", {}, "s", identity=_anon_identity())
    assert out == agent._VERIFY_REQUIRED_MSG
    assert salla.calls == []


async def test_abandoned_carts_only_own():
    salla = _FakeSalla(carts=[
        {"customer": {"id": "555"}, "total": {"amount": "50", "currency": "SAR"},
         "checkout_url": "http://x", "age_in_minutes": 30, "name": "me"},
        {"customer": {"id": "999"}, "total": {"amount": "99", "currency": "SAR"},
         "checkout_url": "http://y", "age_in_minutes": 30, "name": "victim"},
    ])
    a = _bare_agent(salla)
    out = await a._run_tool("get_abandoned_carts", {}, "s",
                            identity=_verified_identity(cid="555"))
    assert "50" in out and "99" not in out               # only the caller's own cart


async def test_abandoned_carts_phone_verified_channel_owns_by_phone():
    """A WhatsApp session is verified by its Meta-authenticated sender — no token,
    no customer_id. ``IdentityService.resolve`` derives that authority from the
    ``wa:`` session id, and the resolver then authorizes carts by phone
    equivalence (country-code prefix tolerated)."""
    from identity import identity_service
    sid = "wa:+966500000000"
    identity = identity_service.resolve("teststore", sid)
    assert identity.is_verified_customer and identity.verified_phone
    salla = _FakeSalla(carts=[
        {"customer": {"id": "555", "mobile": "500000000"},
         "total": {"amount": "50", "currency": "SAR"},
         "checkout_url": "http://x", "age_in_minutes": 30, "name": "me"},
        {"customer": {"id": "999", "mobile": "511111111"},
         "total": {"amount": "99", "currency": "SAR"},
         "checkout_url": "http://y", "age_in_minutes": 30, "name": "victim"},
    ])
    a = _bare_agent(salla)
    out = await a._run_tool("get_abandoned_carts", {}, sid, identity=identity)
    assert "50" in out and "99" not in out               # matched by phone, not id


# ─────────────────────────────────────────────────────────────────────────────
# 4. Reflected XSS
# ─────────────────────────────────────────────────────────────────────────────

async def test_test_widget_rejects_unsafe_store_id():
    from routers import public
    with pytest.raises(HTTPException) as ei:
        await public.test_widget_page('"><script>alert(1)</script>')
    assert ei.value.status_code == 404


async def test_test_widget_encodes_store_id():
    from routers import public
    resp = await public.test_widget_page("good_store-1")
    body = resp.body.decode()
    assert "<script>alert" not in body
    assert '"good_store-1"' in body                       # json.dumps-quoted in JS


async def test_shopify_widget_rejects_unsafe_store_id():
    from routers import integrations
    with pytest.raises(HTTPException) as ei:
        await integrations.shopify_widget_script('a";evil()//')
    assert ei.value.status_code == 404


async def test_shopify_widget_encodes_store_id():
    from routers import integrations
    resp = await integrations.shopify_widget_script("shop_42")
    body = resp.body.decode()
    assert 'storeId  = "shop_42"' in body


# ─────────────────────────────────────────────────────────────────────────────
# 5. CSV formula injection
# ─────────────────────────────────────────────────────────────────────────────

def test_csv_safe_escapes_formula_triggers():
    from routers import contacts
    for bad in ("=cmd|'/c calc'!A1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"):
        assert contacts._csv_safe(bad).startswith("'")
    assert contacts._csv_safe("+966500000000") == "'+966500000000"


def test_csv_safe_leaves_normal_values_untouched():
    from routers import contacts
    assert contacts._csv_safe("Ahmed") == "Ahmed"
    assert contacts._csv_safe("ahmed@example.com") == "ahmed@example.com"
    assert contacts._csv_safe(None) == ""
    assert contacts._csv_safe(123) == "123"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Upload memory DoS
# ─────────────────────────────────────────────────────────────────────────────

class _FakeUpload:
    def __init__(self, data: bytes):
        self._buf = data
        self._pos = 0

    async def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            chunk = self._buf[self._pos:]
            self._pos = len(self._buf)
        else:
            chunk = self._buf[self._pos:self._pos + n]
            self._pos += len(chunk)
        return chunk


async def test_read_bounded_returns_small_file_intact():
    from routers import deps
    data = b"x" * 100
    out = await deps.read_upload_bounded(_FakeUpload(data), max_bytes=1000)
    assert out == data


async def test_read_bounded_aborts_oversized_stream():
    from routers import deps
    with pytest.raises(HTTPException) as ei:
        await deps.read_upload_bounded(_FakeUpload(b"x" * 5000), max_bytes=1000)
    assert ei.value.status_code == 413


async def test_read_bounded_early_rejects_via_content_length():
    from routers import deps
    with pytest.raises(HTTPException) as ei:
        await deps.read_upload_bounded(
            _FakeUpload(b"x" * 10), max_bytes=1000, content_length=10_000_000,
        )
    assert ei.value.status_code == 413


# ─────────────────────────────────────────────────────────────────────────────
# 7. Webhook SSRF
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://example.com/hook",          # not https
    "https://localhost/hook",           # loopback name
    "https://127.0.0.1/hook",           # loopback literal
    "https://10.0.0.5/hook",            # private
    "https://192.168.1.1/hook",         # private
    "https://172.16.0.1/hook",          # private
    "https://169.254.169.254/latest",   # link-local (cloud metadata)
    "https://[::1]/hook",               # ipv6 loopback
    "",                                 # empty
    "https:///nohost",                  # missing host
])
def test_webhook_url_blocked(url):
    import notifications
    assert notifications.is_webhook_url_allowed(url) is False


def test_webhook_url_public_allowed():
    import notifications
    # 8.8.8.8 is a public literal → resolvable offline, never private.
    assert notifications.is_webhook_url_allowed("https://8.8.8.8/hook") is True


def test_webhook_url_public_hostname_allowed(monkeypatch):
    import notifications
    monkeypatch.setattr(
        notifications._socket, "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    assert notifications.is_webhook_url_allowed("https://hooks.example.com/x") is True


# ─────────────────────────────────────────────────────────────────────────────
# 8. Clickjacking headers
# ─────────────────────────────────────────────────────────────────────────────

def _headers_for(path: str) -> dict:
    import middleware
    resp = types.SimpleNamespace(headers={})
    middleware._apply_security_headers(resp, path)
    return resp.headers


@pytest.mark.parametrize("path", ["/admin", "/admin/x", "/store", "/store/abc", "/login"])
def test_dashboard_paths_get_frame_protection(path):
    h = _headers_for(path)
    assert h.get("X-Frame-Options") == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in h.get("Content-Security-Policy", "")


@pytest.mark.parametrize("path", ["/widget.js", "/chat", "/file/abc", "/upload"])
def test_widget_paths_not_frame_blocked(path):
    h = _headers_for(path)
    assert "X-Frame-Options" not in h
    # nosniff is still applied everywhere (defense in depth).
    assert h.get("X-Content-Type-Options") == "nosniff"


# ─────────────────────────────────────────────────────────────────────────────
# 9. Input validation (length bounds)
# ─────────────────────────────────────────────────────────────────────────────

def test_chat_request_bounds_aux_fields():
    from pydantic import ValidationError
    from models import ChatRequest
    ChatRequest(message="hi", store_id="x" * 120)           # ok at the limit
    with pytest.raises(ValidationError):
        ChatRequest(message="hi", store_id="x" * 121)
    with pytest.raises(ValidationError):
        ChatRequest(message="hi", session_id="s" * 201)


def test_login_password_capped():
    from pydantic import ValidationError
    from models import LoginRequest
    LoginRequest(password="ok", email="a@b.com")            # normal
    with pytest.raises(ValidationError):
        LoginRequest(password="x" * 1025)                   # argon2-DoS guard


def test_signup_fields_bounded():
    from pydantic import ValidationError
    from models import SignupRequest
    SignupRequest(name="A", email="a@b.com", password="secret12")
    with pytest.raises(ValidationError):
        SignupRequest(name="n" * 201, email="a@b.com", password="secret12")
