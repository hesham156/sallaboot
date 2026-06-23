"""
Tests for backend/crypto.py — provider key encryption.

The crypto module is the single weakest link in C9: if any of these
contracts break, every merchant's API keys leak. The tests cover:
  • Round-trip (encrypt → decrypt = identity)
  • Versioned prefix discriminates legacy plaintext
  • Idempotent encrypt (double-encrypt is a no-op)
  • Empty / None handled without crashing
  • Wrong key → ValueError, not silent garbage
  • Dict helpers ignore non-secret fields
  • MultiFernet rotation: old key decrypts, new key encrypts
"""
from __future__ import annotations

import importlib
import os

import pytest
from cryptography.fernet import Fernet


pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def reset_crypto(monkeypatch):
    """
    Reload backend/crypto.py with the env we set so the module-level
    _fernet picks up the right key. Returns the reloaded module so each
    test can call crypto.encrypt etc. directly.
    """
    def _reload(active: str, *old_keys: str) -> object:
        monkeypatch.setenv("ENCRYPTION_KEY", active)
        if old_keys:
            monkeypatch.setenv("ENCRYPTION_KEYS_OLD", ",".join(old_keys))
        else:
            monkeypatch.delenv("ENCRYPTION_KEYS_OLD", raising=False)
        import crypto
        return importlib.reload(crypto)
    return _reload


@pytest.fixture
def crypto_mod(reset_crypto):
    """Single fresh crypto module with a single known key."""
    return reset_crypto(Fernet.generate_key().decode())


# ── Core round-trip ───────────────────────────────────────────────────────

def test_round_trip_preserves_value(crypto_mod):
    for plain in ("sk-1234567890", "أ", "", "with spaces and 中文",
                  "long-" * 100):
        ct = crypto_mod.encrypt(plain)
        if plain == "":
            assert ct == "", "empty input must stay empty"
        else:
            assert ct.startswith("enc:v1:"), f"missing prefix on: {ct!r}"
        assert crypto_mod.decrypt(ct) == plain


def test_is_encrypted_discriminates(crypto_mod):
    ct = crypto_mod.encrypt("secret")
    assert crypto_mod.is_encrypted(ct)            is True
    assert crypto_mod.is_encrypted("secret")      is False
    assert crypto_mod.is_encrypted("")            is False
    assert crypto_mod.is_encrypted(None)          is False  # type: ignore[arg-type]
    assert crypto_mod.is_encrypted("enc:v2:x")    is False, \
        "only our exact prefix counts — future versions need explicit support"


def test_encrypt_is_idempotent(crypto_mod):
    """Double-encrypting must be a no-op — otherwise save_store re-saves
    after restore_to_memory would wrap ciphertext in another ciphertext."""
    once  = crypto_mod.encrypt("payload")
    twice = crypto_mod.encrypt(once)
    assert twice == once


def test_decrypt_passes_through_legacy_plaintext(crypto_mod):
    """Migration window safety: a row that hasn't been encrypted yet
    decrypts to itself, not to an error."""
    assert crypto_mod.decrypt("plain-legacy-token") == "plain-legacy-token"


def test_encrypt_handles_non_string_input(crypto_mod):
    """Defensive — JSONB sometimes brings ints back instead of strings."""
    ct = crypto_mod.encrypt(12345)  # type: ignore[arg-type]
    assert crypto_mod.decrypt(ct) == "12345"


# ── Failure modes ─────────────────────────────────────────────────────────

def test_decrypt_with_wrong_key_raises_value_error(reset_crypto):
    """The whole point of authenticated encryption — wrong key MUST fail
    loudly, never return garbage that the agent then sends to Anthropic."""
    crypto_a = reset_crypto(Fernet.generate_key().decode())
    ct = crypto_a.encrypt("sk-secret")

    crypto_b = reset_crypto(Fernet.generate_key().decode())  # fresh key
    with pytest.raises(ValueError, match="Cannot decrypt"):
        crypto_b.decrypt(ct)


def test_decrypt_with_old_key_in_rotation_succeeds(reset_crypto):
    """The whole point of key rotation — old ciphertexts must still decrypt
    while the previous key is listed in ENCRYPTION_KEYS_OLD."""
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()

    crypto_old = reset_crypto(old)
    ct_old = crypto_old.encrypt("from-yesterday")

    crypto_new = reset_crypto(new, old)
    assert crypto_new.decrypt(ct_old) == "from-yesterday"

    # New encrypts use the new (active) key.
    ct_new = crypto_new.encrypt("from-today")
    # Without the OLD key in rotation, old ct fails — verifying the
    # rotation window is the only place old keys are needed.
    crypto_new_only = reset_crypto(new)
    assert crypto_new_only.decrypt(ct_new) == "from-today"
    with pytest.raises(ValueError):
        crypto_new_only.decrypt(ct_old)


# ── Dict helpers ──────────────────────────────────────────────────────────

def test_encrypt_fields_only_touches_named_fields(crypto_mod):
    plain = {
        "groq_api_key":  "sk-groq",
        "openai_api_key": "sk-openai",
        "bot_name":       "Sara",       # not a secret
        "store_type":     "printing",   # not a secret
    }
    out = crypto_mod.encrypt_fields(plain, crypto_mod.AI_CONFIG_SECRET_FIELDS)
    assert out["groq_api_key"].startswith("enc:v1:")
    assert out["openai_api_key"].startswith("enc:v1:")
    assert out["bot_name"]   == "Sara",     "non-secret field must not be encrypted"
    assert out["store_type"] == "printing"


def test_encrypt_fields_does_not_mutate_input(crypto_mod):
    """The in-memory dict caller passed in must stay plaintext — only the
    returned copy is encrypted."""
    plain = {"groq_api_key": "sk-test"}
    crypto_mod.encrypt_fields(plain, ("groq_api_key",))
    assert plain["groq_api_key"] == "sk-test", "input dict was mutated!"


def test_encrypt_fields_skips_missing_and_empty(crypto_mod):
    plain = {"groq_api_key": "", "anthropic_api_key": None}
    out = crypto_mod.encrypt_fields(plain, crypto_mod.AI_CONFIG_SECRET_FIELDS)
    assert out["groq_api_key"]      == ""
    assert out["anthropic_api_key"] is None


def test_decrypt_fields_logs_and_zeros_corrupt_value(crypto_mod, capsys):
    """A single corrupt value must NOT take down the whole store load.
    It zeros out and is reported on stdout."""
    plain = {"groq_api_key": "enc:v1:totally-corrupt-base64"}
    out = crypto_mod.decrypt_fields(plain, ("groq_api_key",))
    assert out["groq_api_key"] == ""
    captured = capsys.readouterr()
    assert "Failed to decrypt" in captured.out


# ── Full store blob ───────────────────────────────────────────────────────

def test_store_blob_round_trip_with_nested_ai_config(crypto_mod):
    """The shape used by stores.tokens JSONB: top-level access/refresh
    tokens plus a nested ai_config with the provider keys."""
    blob = {
        "access_token":  "salla-tok-abc",
        "refresh_token": "salla-ref-xyz",
        "store_name":    "متجر",
        "ai_config": {
            "groq_api_key":      "sk-groq",
            "anthropic_api_key": "sk-ant",
            "openai_api_key":    "",
            "bot_name":          "Sara",
        },
    }
    enc = crypto_mod.encrypt_store_blob(blob)
    # Secrets encrypted
    assert enc["access_token"].startswith("enc:v1:")
    assert enc["refresh_token"].startswith("enc:v1:")
    assert enc["ai_config"]["groq_api_key"].startswith("enc:v1:")
    assert enc["ai_config"]["anthropic_api_key"].startswith("enc:v1:")
    # Non-secrets untouched
    assert enc["store_name"] == "متجر"
    assert enc["ai_config"]["bot_name"] == "Sara"
    assert enc["ai_config"]["openai_api_key"] == ""

    dec = crypto_mod.decrypt_store_blob(enc)
    assert dec["access_token"]    == "salla-tok-abc"
    assert dec["refresh_token"]   == "salla-ref-xyz"
    assert dec["ai_config"]["groq_api_key"]      == "sk-groq"
    assert dec["ai_config"]["anthropic_api_key"] == "sk-ant"


def test_store_blob_handles_empty_inputs(crypto_mod):
    """Common path during onboarding: store row exists but no tokens yet."""
    assert crypto_mod.encrypt_store_blob(None) == {}
    assert crypto_mod.encrypt_store_blob({})   == {}
    assert crypto_mod.decrypt_store_blob({})   == {}


# ── Key rotation (reencrypt onto the active key) ───────────────────────────

def test_reencrypt_moves_ciphertext_onto_new_key(reset_crypto):
    """The core rotation guarantee: a value encrypted with the OLD key, once
    reencrypt()'d under (new + old), must decrypt with the NEW key ALONE.
    Plain encrypt() can't do this — it's idempotent on ciphertext."""
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()

    crypto_old = reset_crypto(old)
    ct_old = crypto_old.encrypt("salla-token")

    crypto_rot = reset_crypto(new, old)            # active=new, fallback=old
    # encrypt() is a no-op on ciphertext → would NOT rotate:
    assert crypto_rot.encrypt(ct_old) == ct_old
    # reencrypt() decrypts (via old) then re-encrypts (via new):
    ct_new = crypto_rot.reencrypt(ct_old)
    assert crypto_rot.decrypt(ct_new) == "salla-token"

    # After dropping the old key, the rotated value still reads; the original
    # would not — proving the rewrite was necessary and effective.
    crypto_new_only = reset_crypto(new)
    assert crypto_new_only.decrypt(ct_new) == "salla-token"
    with pytest.raises(ValueError):
        crypto_new_only.decrypt(ct_old)


def test_reencrypt_store_blob_rotates_all_secrets(reset_crypto):
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()

    crypto_old = reset_crypto(old)
    enc = crypto_old.encrypt_store_blob({
        "access_token":  "tok",
        "refresh_token": "ref",
        "store_name":    "متجر",
        "ai_config": {"groq_api_key": "gsk", "bot_name": "Sara"},
    })

    crypto_rot = reset_crypto(new, old)
    rot = crypto_rot.reencrypt_store_blob(enc)

    crypto_new_only = reset_crypto(new)
    dec = crypto_new_only.decrypt_store_blob(rot)
    assert dec["access_token"] == "tok"
    assert dec["refresh_token"] == "ref"
    assert dec["ai_config"]["groq_api_key"] == "gsk"
    assert dec["store_name"] == "متجر"            # non-secret preserved
    assert dec["ai_config"]["bot_name"] == "Sara"


def test_reencrypt_missing_old_key_raises(reset_crypto):
    """If the matching old key isn't configured, reencrypt must raise rather
    than silently corrupt/drop the secret."""
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()
    ct_old = reset_crypto(old).encrypt("secret")

    crypto_new_only = reset_crypto(new)            # old key NOT provided
    with pytest.raises(ValueError):
        crypto_new_only.reencrypt(ct_old)


def test_dev_key_fallback_emits_warning(reset_crypto, capsys, monkeypatch):
    """When ENCRYPTION_KEY is unset, dev fallback must scream so the
    operator notices BEFORE shipping to prod."""
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ENCRYPTION_KEYS_OLD", raising=False)
    import crypto
    importlib.reload(crypto)
    captured = capsys.readouterr()
    assert "ENCRYPTION_KEY is NOT set" in captured.out
    assert crypto.ENCRYPTION_KEY_STABLE is False
