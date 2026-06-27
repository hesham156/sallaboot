"""
crypto.py — Field-level encryption for stored secrets.

The store-secret blob (groq/anthropic/openai/whatsapp keys, Salla OAuth
access+refresh tokens) used to sit in cleartext inside JSONB columns and
JSON files on disk. A DB dump leak or a misconfigured backup would have
exposed every merchant's keys.

Design
─────
• AES-128-CBC + HMAC-SHA256 via Fernet (industry-standard authenticated
  encryption, included in `cryptography` which we already depend on).
• Each encrypted value is prefixed with `enc:v1:` so:
    - We can tell encrypted from legacy plaintext during the migration
      window without scanning the whole value.
    - A future format bump becomes `enc:v2:` with a simple discriminator.
• Memory always holds plaintext. Encryption happens at the persistence
  boundary (database.py / store_manager.py file I/O) so existing code
  reading `cfg["groq_api_key"]` keeps working unchanged.
• Key rotation: pass the previous key(s) via `ENCRYPTION_KEYS_OLD`
  (comma-separated, decrypt-only). New writes use the active key. After
  every old ciphertext has been re-encrypted (the migration script
  handles this), the old key can be removed.

Key generation
──────────────
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Set the output as `ENCRYPTION_KEY` in Railway env vars. NEVER commit it
to git.

Env vars
────────
ENCRYPTION_KEY        — active Fernet key (used for both encrypt + decrypt).
ENCRYPTION_KEYS_OLD   — optional CSV of previous keys (decrypt-only). Each
                        value must be the same base64 Fernet key format.
                        Used during rotation: new ciphertexts get the new
                        key; old ciphertexts still decrypt until the
                        background rewrite finishes.

Fallback
────────
When `ENCRYPTION_KEY` is unset, we generate one in-memory at boot. This
keeps local dev working without configuration BUT is loudly warned:
restarting wipes the key, so any DB state from a previous session can't
be decrypted. Production deploys MUST set the env var.
"""
from __future__ import annotations

import base64
import os
import secrets
from typing import Iterable

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

# ── Sentinel prefix ──────────────────────────────────────────────────────
# Every ciphertext starts with this string. Discriminator for
# legacy plaintext vs. encrypted, and version marker for future format
# upgrades. Don't change the bytes — existing rows depend on it.
_ENC_PREFIX = "enc:v1:"


def is_encrypted(value: str | None) -> bool:
    """True if `value` is one of our ciphertexts (not legacy plaintext)."""
    return bool(value) and isinstance(value, str) and value.startswith(_ENC_PREFIX)


# ── Master key resolution ────────────────────────────────────────────────

def _build_fernet() -> tuple[MultiFernet, bool]:
    """
    Build the MultiFernet used for encryption + decryption.

    Returns (fernet, stable). `stable` is False when we had to generate a
    dev-only ephemeral key — same warning model as auth.ADMIN_SECRET_STABLE.
    """
    primary = (os.getenv("ENCRYPTION_KEY") or "").strip()
    olds = [
        k.strip()
        for k in (os.getenv("ENCRYPTION_KEYS_OLD") or "").split(",")
        if k.strip()
    ]

    if not primary:
        # Dev fallback — random key per process. Tests that don't care
        # about cross-restart encryption use this path. Production
        # MUST set ENCRYPTION_KEY (we warn loudly below).
        primary = Fernet.generate_key().decode()
        stable = False
    else:
        stable = True

    keys: list[Fernet] = []
    for raw in [primary, *olds]:
        try:
            keys.append(Fernet(raw.encode() if isinstance(raw, str) else raw))
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                f"Invalid Fernet key in env: {exc}. Generate with: "
                "python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            ) from exc

    return MultiFernet(keys), stable


_fernet, ENCRYPTION_KEY_STABLE = _build_fernet()

if not ENCRYPTION_KEY_STABLE:
    print("=" * 60)
    print("⚠️  ENCRYPTION_KEY is NOT set!")
    print("    Provider API keys + Salla tokens will be encrypted with a")
    print("    one-shot key generated at boot. Any secrets persisted now")
    print("    will be UNDECRYPTABLE after the next restart.")
    print("    Fix: add ENCRYPTION_KEY=<fernet-key> to Railway env vars.")
    print("    Generate: python -c \"from cryptography.fernet import Fernet;"
          " print(Fernet.generate_key().decode())\"")
    print("=" * 60)


# ── Core encrypt / decrypt ───────────────────────────────────────────────

def encrypt(plaintext: str) -> str:
    """
    Encrypt a single secret. Empty strings pass through unchanged so the
    caller doesn't have to special-case unset fields (an empty API key
    should round-trip as empty, not as a giant ciphertext blob).

    Idempotent: if `plaintext` already looks like a ciphertext, return it
    unchanged. This makes save_store safe to call on freshly-loaded data
    that's still encrypted in memory (some legacy paths do this).
    """
    if plaintext is None or plaintext == "":
        return ""
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    if is_encrypted(plaintext):
        return plaintext
    token = _fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _ENC_PREFIX + token


def decrypt(value: str) -> str:
    """
    Decrypt a ciphertext. Returns plaintext unchanged when it's not one
    of ours — protects the migration window where some rows are still
    legacy plaintext. Returns "" for empty input.

    Raises only on a malformed ciphertext (corrupt prefix or wrong key).
    The caller (DB load) catches and logs so a single bad row doesn't
    fail the whole startup.
    """
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        return str(value)
    if not is_encrypted(value):
        # Legacy plaintext — pass through. Migration will rewrite it
        # next time the row is saved.
        return value
    payload = value[len(_ENC_PREFIX):]
    try:
        return _fernet.decrypt(payload.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        # Wrong key or corrupted ciphertext. Reraise as ValueError so
        # callers can distinguish from "unencrypted" return path above.
        raise ValueError(
            "Cannot decrypt — wrong ENCRYPTION_KEY, or value was encrypted "
            "with a key not in ENCRYPTION_KEYS_OLD"
        ) from exc


# ── Dict-level helpers (the API the rest of the codebase actually calls) ─

# These field name sets are the single source of truth for "what counts as
# a secret." Keep them in sync if a new provider field is added.
TOKENS_SECRET_FIELDS = ("access_token", "refresh_token")
AI_CONFIG_SECRET_FIELDS = (
    "groq_api_key",
    "anthropic_api_key",
    "openai_api_key",
    "whatsapp_token",
    "page_token",        # Facebook Page access token (Messenger + Instagram)
    "ig_access_token",   # Instagram-login long-lived (~60d) token — same blast
                         # radius as page_token, must be encrypted at rest too.
)

# Secret fields inside each per-platform entry of the stores.integrations JSONB
# column (Shopify / Zid / TikTok OAuth tokens). Encrypted on save_integration,
# decrypted on get_integrations + list_stores_with_integration.
INTEGRATION_SECRET_FIELDS = (
    "access_token",
    "refresh_token",
)


def encrypt_fields(blob: dict | None, fields: Iterable[str]) -> dict:
    """
    Return a copy of `blob` with the named fields encrypted. Non-string /
    missing / empty values are passed through (no encryption applied).

    Does NOT mutate the input — callers can safely pass an in-memory
    dict that downstream code still reads as plaintext.
    """
    if not blob:
        return {} if blob is None else blob
    out = dict(blob)
    for f in fields:
        v = out.get(f)
        if isinstance(v, str) and v:
            out[f] = encrypt(v)
    return out


def decrypt_fields(blob: dict | None, fields: Iterable[str]) -> dict:
    """Mirror of encrypt_fields — decrypts in-place on a copy."""
    if not blob:
        return {} if blob is None else blob
    out = dict(blob)
    for f in fields:
        v = out.get(f)
        if isinstance(v, str) and v:
            try:
                out[f] = decrypt(v)
            except ValueError as exc:
                # Log loud but don't crash — a single corrupt field
                # shouldn't kill the whole store load. The field becomes
                # empty so the agent reports a missing key cleanly.
                print(f"[crypto] ⚠️ Failed to decrypt {f!r}: {exc}")
                out[f] = ""
    return out


# ── Convenience: full store-blob round-trip ──────────────────────────────

def encrypt_store_blob(tokens: dict | None) -> dict:
    """
    Encrypt the secret-bearing fields of a stores.tokens JSONB blob.
    Handles the nested ai_config inside tokens as well.

    Input shape (plaintext):
        {
          "access_token":  "...",
          "refresh_token": "...",
          "ai_config": {"groq_api_key": "...", ...},
          ...
        }
    """
    if not tokens:
        return {}
    out = encrypt_fields(tokens, TOKENS_SECRET_FIELDS)
    nested_ai = out.get("ai_config")
    if isinstance(nested_ai, dict) and nested_ai:
        out["ai_config"] = encrypt_fields(nested_ai, AI_CONFIG_SECRET_FIELDS)
    return out


def decrypt_store_blob(tokens: dict | None) -> dict:
    """Mirror of encrypt_store_blob."""
    if not tokens:
        return {}
    out = decrypt_fields(tokens, TOKENS_SECRET_FIELDS)
    nested_ai = out.get("ai_config")
    if isinstance(nested_ai, dict) and nested_ai:
        out["ai_config"] = decrypt_fields(nested_ai, AI_CONFIG_SECRET_FIELDS)
    return out


def encrypt_ai_config_blob(ai_config: dict | None) -> dict:
    """Encrypt the dedicated `ai_config` JSONB column (separate from tokens)."""
    return encrypt_fields(ai_config, AI_CONFIG_SECRET_FIELDS)


def decrypt_ai_config_blob(ai_config: dict | None) -> dict:
    return decrypt_fields(ai_config, AI_CONFIG_SECRET_FIELDS)


# ── Key rotation: re-encrypt onto the ACTIVE key ──────────────────────────
# encrypt() is idempotent on already-ciphertext (returns it unchanged), so it
# can NOT move a value from an old key to the new one. Rotation must DECRYPT
# (MultiFernet tries the active key + every ENCRYPTION_KEYS_OLD) and then
# ENCRYPT again — encrypt() uses the active (first) key, so the rewritten
# value is readable with the new key alone. This is what lets you finally
# drop ENCRYPTION_KEYS_OLD.

def reencrypt(value: str) -> str:
    """
    Re-encrypt one value onto the active key. Empty / non-string pass
    through. Legacy plaintext gets encrypted (so rotation also finishes any
    leftover migration). Raises ValueError if the value can't be decrypted
    by ANY configured key — i.e. the matching old key is missing from
    ENCRYPTION_KEYS_OLD; surfacing it beats silently dropping a secret.
    """
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        return value
    return encrypt(decrypt(value))


def reencrypt_fields(blob: dict | None, fields: Iterable[str]) -> dict:
    """Mirror of encrypt_fields, but decrypt-then-encrypt onto the active key."""
    if not blob:
        return {} if blob is None else blob
    out = dict(blob)
    for f in fields:
        v = out.get(f)
        if isinstance(v, str) and v:
            out[f] = reencrypt(v)
    return out


def reencrypt_store_blob(tokens: dict | None) -> dict:
    """Rotate every secret in a stores.tokens blob (incl. nested ai_config)."""
    if not tokens:
        return {}
    out = reencrypt_fields(tokens, TOKENS_SECRET_FIELDS)
    nested_ai = out.get("ai_config")
    if isinstance(nested_ai, dict) and nested_ai:
        out["ai_config"] = reencrypt_fields(nested_ai, AI_CONFIG_SECRET_FIELDS)
    return out


def reencrypt_ai_config_blob(ai_config: dict | None) -> dict:
    return reencrypt_fields(ai_config, AI_CONFIG_SECRET_FIELDS)


# ── Status (for /env-check diagnostics) ──────────────────────────────────

def get_status() -> dict:
    return {
        "encryption_enabled":     True,
        "encryption_key_stable":  ENCRYPTION_KEY_STABLE,
        "old_keys_configured":    bool(os.getenv("ENCRYPTION_KEYS_OLD", "").strip()),
    }
