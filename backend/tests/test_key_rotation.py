"""
Integration test for database.rotate_encryption() — the DB-level key
rotation that lets ENCRYPTION_KEYS_OLD be retired.

Proves the full round trip against a real Postgres: a store written under
the OLD key is rewritten so it reads under the NEW key alone. Skips when no
DB is available.
"""
from __future__ import annotations

import importlib

import pytest
from cryptography.fernet import Fernet

pytestmark = pytest.mark.integration


async def test_rotate_encryption_rewrites_onto_active_key(
    db_pool, clean_db, monkeypatch
):
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()

    import database as db

    # 1. Write a store while OLD is the active key.
    monkeypatch.setenv("ENCRYPTION_KEY", old)
    monkeypatch.delenv("ENCRYPTION_KEYS_OLD", raising=False)
    import crypto
    importlib.reload(crypto)
    importlib.reload(db)  # rebind db._crypto to the reloaded module
    await db.init()
    await db.save_store("rot-store", {
        "access_token":  "SECRET-ACCESS",
        "refresh_token": "SECRET-REFRESH",
        "ai_config":     {"groq_api_key": "gsk-secret"},
    })

    # 2. Rotate: NEW active, OLD as fallback.
    monkeypatch.setenv("ENCRYPTION_KEY", new)
    monkeypatch.setenv("ENCRYPTION_KEYS_OLD", old)
    importlib.reload(crypto)
    importlib.reload(db)
    await db.init()

    res = await db.rotate_encryption()
    assert res["errors"] == []
    assert res["rotated"] == 1
    # Re-running rotates nothing new (idempotent at the "already on new key" level).
    res2 = await db.rotate_encryption()
    assert res2["rotated"] == 0 and res2["errors"] == []

    # 3. Drop the old key entirely — the rotated row must still decrypt.
    monkeypatch.setenv("ENCRYPTION_KEY", new)
    monkeypatch.delenv("ENCRYPTION_KEYS_OLD", raising=False)
    importlib.reload(crypto)
    importlib.reload(db)
    await db.init()

    stores = await db.load_all_stores()
    row = next(s for s in stores if s["store_id"] == "rot-store")
    assert row["tokens"]["access_token"] == "SECRET-ACCESS"
    assert row["tokens"]["refresh_token"] == "SECRET-REFRESH"
    assert row["tokens"]["ai_config"]["groq_api_key"] == "gsk-secret"
