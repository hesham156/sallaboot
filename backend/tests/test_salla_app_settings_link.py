"""
Unit tests for routers.webhooks._handle_app_settings_updated — the Salla
App Settings linking flow (account-preserving model).

The merchant pastes their 7ayak email + API key into the Salla app's settings
form; Salla fires app.settings.updated with the fields under data.settings. The
handler resolves the home 7ayak account by API key (the secret proof of
ownership) and ATTACHES Salla to it: the Salla OAuth tokens are moved onto the
account, a merchant_id → account map is recorded so future Salla webhooks route
to the account, and the redundant merchant store row is deleted. The account
keeps its own store_id / email / password — it must never be deleted or
re-keyed — and an account already running another platform is never hijacked.
"""
from __future__ import annotations

import pytest

from routers import webhooks as w


pytestmark = pytest.mark.unit


class _DBStub:
    def __init__(self, *, by_key=None, by_email=None, integrations=None, mapped=None):
        self._by_key = by_key or {}
        self._by_email = by_email or {}
        self._integrations = integrations or {}
        self._mapped = mapped or {}          # merchant_id -> account (pre-existing maps)
        self.saved: dict = {}                # store_id -> tokens passed to save_store
        self.maps: list = []                 # (merchant_id, account) from set_salla_merchant_map
        self.purged: list = []               # store_ids passed to purge_store

    async def find_store_by_api_key(self, key):
        return self._by_key.get((key or "").strip())

    async def find_store_by_owner_email(self, email):
        return self._by_email.get((email or "").strip().lower())

    async def get_integrations(self, store_id):
        return self._integrations.get(store_id, {})

    async def resolve_merchant_to_account(self, merchant_id):
        return self._mapped.get(str(merchant_id))

    async def set_salla_merchant_map(self, merchant_id, account):
        self.maps.append((str(merchant_id), str(account)))

    async def save_store(self, store_id, tokens, owner_email=""):
        self.saved[store_id] = dict(tokens)

    async def purge_store(self, store_id):
        self.purged.append(store_id)
        return {}


class _SMStub:
    def __init__(self, *, registered=True, infos=None, caches=None):
        self._registered = registered
        # per-store token blobs returned by get_store_info
        self._infos = infos or {
            "merchant_99": {"access_token": "salla-tok", "refresh_token": "ref-tok",
                            "expires_at": "2026-07-01T00:00:00", "store_name": "متجر"},
            "home_acct":   {"owner_email": "home@acct.com", "admin_password_hash": "argon2$home"},
        }
        self._caches = caches or {}
        self.updated: dict = {}
        self.cache_set: dict = {}
        self.reset: list = []
        self.unregistered: list = []

    def is_registered(self, store_id):
        return self._registered

    async def sync_one_from_db(self, store_id):
        return self._registered

    def get_store_info(self, store_id):
        return self._infos.get(store_id, {})

    def update_store_info(self, store_id, tokens):
        self.updated[store_id] = dict(tokens)
        self._infos[store_id] = dict(tokens)

    def get_cache(self, store_id):
        return self._caches.get(store_id, {})

    def set_cache(self, store_id, data):
        self.cache_set[store_id] = data

    def reset_agent(self, store_id):
        self.reset.append(store_id)

    def unregister(self, store_id):
        self.unregistered.append(store_id)


@pytest.fixture
def patched(monkeypatch):
    def _apply(db_stub, sm_stub):
        monkeypatch.setattr(w, "db", db_stub)
        monkeypatch.setattr(w, "sm", sm_stub)
        monkeypatch.setattr(w, "_log_event", lambda *a, **k: None)
        return db_stub, sm_stub
    return _apply


# ── field extraction ─────────────────────────────────────────────────────────

def test_extract_handles_salla_arabic_slugs():
    """Salla derives field keys from Arabic labels: الايميل→alaemel, الـ API Key→al_api_key."""
    email, api_key = w.extract_app_settings_fields(
        {"alaemel": "Sales@Najdc.com", "al_api_key": "7yk_ABC", "merchant": 123}
    )
    assert email == "sales@najdc.com"
    assert api_key == "7yk_ABC"


def test_extract_email_by_value_shape():
    """Even with an unknown email slug, an @-bearing value is recognised."""
    email, api_key = w.extract_app_settings_fields(
        {"some_weird_label": "user@example.com", "another_field": "7yk_K"}
    )
    assert email == "user@example.com"


def test_extract_clean_slugs_still_work():
    email, api_key = w.extract_app_settings_fields({"email": "a@b.com", "api_key": "7yk_K"})
    assert (email, api_key) == ("a@b.com", "7yk_K")


# ── account-preserving attach ────────────────────────────────────────────────

async def test_attaches_salla_to_account_and_keeps_account(patched):
    """Happy path: Salla tokens move onto the account, a merchant→account map is
    recorded, and the redundant merchant store is deleted — the account keeps its
    own id, email, and password."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "home_acct"}, integrations={"home_acct": {}}),
        _SMStub(),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}
    )
    # Salla tokens landed on the ACCOUNT (home_acct), not a new merchant store.
    saved = db.saved["home_acct"]
    assert saved["access_token"] == "salla-tok"
    assert saved["refresh_token"] == "ref-tok"
    assert saved["salla_merchant_id"] == "merchant_99"
    # Account identity preserved.
    assert saved["owner_email"] == "home@acct.com"
    assert saved["admin_password_hash"] == "argon2$home"
    # Webhooks now route merchant_99 → home_acct, and the merchant row is gone.
    assert db.maps == [("merchant_99", "home_acct")]
    assert db.purged == ["merchant_99"]
    assert sm.unregistered == ["merchant_99"]
    assert sm.reset == ["home_acct"]


async def test_no_link_when_salla_store_not_yet_created(patched):
    """If the link arrives before app.store.authorize created the Salla store
    (and it isn't in the shared DB either), bail without touching anything."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "home_acct"}, integrations={"home_acct": {}}),
        _SMStub(registered=False),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}
    )
    assert db.saved == {}
    assert db.maps == []
    assert db.purged == []


async def test_account_is_never_deleted(patched):
    """The account row must never be purged/unregistered — only the merchant row."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "home_acct"}, integrations={"home_acct": {}}),
        _SMStub(),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}
    )
    assert "home_acct" not in db.purged
    assert "home_acct" not in sm.unregistered


async def test_email_only_does_not_link(patched):
    """C-4: the email is NOT a secret. Linking requires the API key (the secret
    proof of ownership), so an email-only payload is a no-op."""
    db, sm = patched(
        _DBStub(by_email={"me@store.com": "home_acct"}, integrations={"home_acct": {}}),
        _SMStub(),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com"}}
    )
    assert db.saved == {} and db.maps == [] and db.purged == []


async def test_no_match_is_noop(patched):
    db, sm = patched(_DBStub(), _SMStub())
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "x@y.com", "api_key": "nope"}}
    )
    assert db.saved == {} and db.maps == []


async def test_already_linked_same_store_is_noop(patched):
    """Salla-first: the account already IS the merchant store → nothing to do."""
    db, sm = patched(_DBStub(by_key={"7yk_K": "merchant_99"}), _SMStub())
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "x@y.com", "api_key": "7yk_K"}}
    )
    assert db.saved == {} and db.maps == [] and db.purged == []


async def test_already_mapped_is_noop(patched):
    """A retried webhook for an already-attached merchant is idempotent."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "home_acct"}, mapped={"merchant_99": "home_acct"}),
        _SMStub(),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "x@y.com", "api_key": "7yk_K"}}
    )
    assert db.saved == {} and db.maps == [] and db.purged == []


async def test_live_platform_home_not_hijacked(patched):
    """An account already on another platform (Shopify) is never attached to."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "real_store"},
                integrations={"real_store": {"shopify": {"shop": "x.myshopify.com"}}}),
        _SMStub(),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "x@y.com", "api_key": "7yk_K"}}
    )
    assert db.saved == {} and db.maps == [] and db.purged == []


async def test_resaving_same_salla_account_is_idempotent(patched):
    """The exact bug: an account ALREADY connected to Salla re-saves its key. The
    separate merchant store row is long gone, so the link must NOT report
    'salla_store_not_ready' (the 'لم يكتمل التثبيت بعد' loop). A same-merchant
    re-save is idempotent success and mutates nothing."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "home_acct"},
                integrations={"home_acct": {"salla": {"connected": True}}}),
        _SMStub(registered=False,
                infos={"home_acct": {"salla_merchant_id": "merchant_99",
                                     "owner_email": "home@acct.com"}}),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}
    )
    # Idempotent: no token move, no purge. But it DOES (re)record the
    # merchant→account map so the storefront widget resolves (self-heal).
    assert db.saved == {} and db.purged == []
    assert db.maps == [("merchant_99", "home_acct")]
    assert sm.unregistered == []


async def test_resave_with_no_recorded_merchant_id_self_heals(patched):
    """Legacy state: the account has Salla tokens but no recorded merchant_id /
    map (connected before the mapping existed) — exactly the case that left the
    widget orphaned. A re-save records BOTH the map and the merchant id."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "home_acct"},
                integrations={"home_acct": {"salla": {"connected": True}}}),
        _SMStub(registered=False, infos={"home_acct": {"owner_email": "home@acct.com"}}),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}
    )
    assert db.maps == [("merchant_99", "home_acct")]
    assert db.saved.get("home_acct", {}).get("salla_merchant_id") == "merchant_99"
    assert db.purged == []


async def test_account_linked_to_a_different_salla_is_refused(patched):
    """An account already bound to a DIFFERENT Salla merchant must not be silently
    re-pointed at another one."""
    db, sm = patched(
        _DBStub(by_key={"7yk_K": "home_acct"},
                integrations={"home_acct": {"salla": {"connected": True}}}),
        _SMStub(infos={"home_acct": {"salla_merchant_id": "another_merchant"}}),
    )
    await w._handle_app_settings_updated(
        "merchant_99", {"settings": {"email": "me@store.com", "api_key": "7yk_K"}}
    )
    assert db.saved == {} and db.maps == [] and db.purged == []
