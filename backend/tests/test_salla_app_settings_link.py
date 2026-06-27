"""
Unit tests for routers.webhooks._handle_app_settings_updated — the Salla
App Settings linking flow (canonical model: store_id == Salla merchant_id).

The merchant pastes their 7ayak email + API key into the Salla app's settings
form; Salla fires app.settings.updated with the fields under data.settings. The
handler resolves the home 7ayak account by API key (the secret proof of
ownership) and moves its login identity (email + chosen password + API key) onto
the canonical Salla store, then merges + deletes the pure-signup placeholder so
the merchant ends with ONE account they log into by email. An account already on
another platform is never hijacked.
"""
from __future__ import annotations

import pytest

from routers import webhooks as w


pytestmark = pytest.mark.unit


class _DBStub:
    def __init__(self, *, by_key=None, by_email=None, integrations=None):
        self._by_key = by_key or {}
        self._by_email = by_email or {}
        self._integrations = integrations or {}
        self.owner_email_set: dict = {}
        self.api_key_set: dict = {}
        self.merged: list = []
        self.forwards: list = []

    async def find_store_by_api_key(self, key):
        return self._by_key.get((key or "").strip())

    async def find_store_by_owner_email(self, email):
        return self._by_email.get((email or "").strip().lower())

    async def get_integrations(self, store_id):
        return self._integrations.get(store_id, {})

    async def set_store_owner_email(self, store_id, email):
        self.owner_email_set[store_id] = email
        return True

    async def set_api_key(self, store_id, key):
        self.api_key_set[store_id] = key

    async def merge_placeholder_into(self, placeholder_id, target_id):
        self.merged.append((placeholder_id, target_id))
        return True

    async def record_account_forward(self, old_store_id, new_store_id):
        self.forwards.append((old_store_id, new_store_id))


class _SMStub:
    def __init__(self, pwd="argon2$home", registered=True, access_token=""):
        self._pwd = pwd
        self._registered = registered
        self._access_token = access_token
        self.password_set: dict = {}
        self.reset: list = []
        self.unregistered: list = []

    def is_registered(self, store_id):
        return self._registered

    async def sync_one_from_db(self, store_id):
        return self._registered

    def get_access_token(self, store_id):
        return self._access_token

    def unregister(self, store_id):
        self.unregistered.append(store_id)

    def get_store_info(self, store_id):
        return {"owner_email": "home@acct.com"}

    def get_admin_password_hash(self, store_id):
        return self._pwd

    async def set_admin_password(self, store_id, h):
        self.password_set[store_id] = h

    def reset_agent(self, store_id):
        self.reset.append(store_id)


@pytest.fixture
def patched(monkeypatch):
    def _apply(db_stub, sm_stub):
        # The handler + linker live in the webhooks.salla submodule after the
        # package split, so patch the dependency aliases there (not on the
        # re-exporting package, whose names are separate bindings).
        monkeypatch.setattr(w.salla, "db", db_stub)
        monkeypatch.setattr(w.salla, "sm", sm_stub)
        monkeypatch.setattr(w.salla, "_log_event", lambda *a, **k: None)
        return db_stub, sm_stub
    return _apply


# ── field extraction ─────────────────────────────────────────────────────────

def test_extract_handles_salla_arabic_slugs():
    email, api_key = w.extract_app_settings_fields(
        {"alaemel": "Sales@Najdc.com", "al_api_key": "7yk_ABC", "merchant": 123}
    )
    assert email == "sales@najdc.com"
    assert api_key == "7yk_ABC"


def test_extract_email_by_value_shape():
    email, api_key = w.extract_app_settings_fields(
        {"some_weird_label": "user@example.com", "another_field": "7yk_K"}
    )
    assert email == "user@example.com"


def test_extract_clean_slugs_still_work():
    email, api_key = w.extract_app_settings_fields({"email": "a@b.com", "api_key": "7yk_K"})
    assert (email, api_key) == ("a@b.com", "7yk_K")


# ── canonical link (identity moved onto the Salla store) ─────────────────────

async def test_links_by_api_key(patched):
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "home_acct"}, integrations={"home_acct": {}}),
        _SMStub(pwd="argon2$chosen"),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}
    )
    # email + password + api_key moved onto the Salla store (canonical id)
    assert db.owner_email_set["merchant_99"] == "me@store.com"
    assert sm.password_set["merchant_99"] == "argon2$chosen"
    assert db.owner_email_set["home_acct"] == ""        # detached from placeholder
    assert db.api_key_set["home_acct"] is None
    assert db.api_key_set["merchant_99"] == "7yk_K"
    assert sm.reset == ["merchant_99"]


async def test_no_link_when_salla_store_not_yet_created(patched):
    """Guard: if the link arrives before app.store.authorize created the Salla
    store (and it isn't in the shared DB), bail without touching anything."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "home_acct"}, integrations={"home_acct": {}}),
        _SMStub(registered=False),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}
    )
    assert db.owner_email_set == {}
    assert db.api_key_set == {}
    assert sm.password_set == {}


async def test_placeholder_merged_and_deleted(patched):
    """A pure signup placeholder (no access token) is merged into the Salla store
    and removed, so the merchant ends with ONE account + a session breadcrumb."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "home_acct"}, integrations={"home_acct": {}}),
        _SMStub(access_token=""),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}
    )
    assert db.merged == [("home_acct", "merchant_99")]
    assert sm.unregistered == ["home_acct"]
    assert db.forwards == [("home_acct", "merchant_99")]


async def test_home_with_access_token_is_not_deleted(patched):
    """If the matched account is itself a real store (has a token), move identity
    but never delete it."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "home_acct"}, integrations={"home_acct": {}}),
        _SMStub(access_token="real-salla-token"),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}
    )
    assert db.merged == []
    assert sm.unregistered == []


async def test_email_only_does_not_link(patched):
    """C-4: linking requires the API key (the secret proof of ownership), so an
    email-only payload is a no-op."""
    db, sm = patched(
        _DBStub(by_email={"me@store.com": "home_acct"}, integrations={"home_acct": {}}),
        _SMStub(),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com"}}
    )
    assert db.owner_email_set == {} and db.api_key_set == {} and sm.password_set == {}


async def test_no_match_is_noop(patched):
    db, sm = patched(_DBStub(), _SMStub())
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "x@y.com", "api_key": "nope"}}
    )
    assert db.owner_email_set == {} and sm.password_set == {}


async def test_already_linked_same_store_is_noop(patched):
    db, sm = patched(_DBStub(by_key={"7yk_K": "merchant_99"}), _SMStub())
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "x@y.com", "api_key": "7yk_K"}}
    )
    assert db.owner_email_set == {}


async def test_live_platform_home_not_hijacked(patched):
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "real_store"},
                integrations={"real_store": {"shopify": {"shop": "x.myshopify.com"}}}),
        _SMStub(),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "x@y.com", "api_key": "7yk_K"}}
    )
    assert db.owner_email_set == {} and db.api_key_set == {}


async def test_live_salla_home_not_hijacked(patched):
    """An account already a live Salla store is protected from being re-pointed."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "real_salla_store"},
                integrations={"real_salla_store": {"salla": {"connected": True}}}),
        _SMStub(),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "x@y.com", "api_key": "7yk_K"}}
    )
    assert db.owner_email_set == {} and db.api_key_set == {}
