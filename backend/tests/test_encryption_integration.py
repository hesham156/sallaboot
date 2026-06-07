"""
End-to-end encryption tests.

Verifies the contract Phase C9 ships: secrets land in DB as ciphertext
but are returned as plaintext to in-process callers. Anyone who dumps
the DB sees gibberish; anyone reading the in-memory store dict sees
working keys.

Requires DB (testcontainers or TEST_DATABASE_URL).
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


async def test_save_store_writes_ciphertext_to_db(clean_db):
    """The DB column must contain enc:v1: prefixes after a normal save."""
    db = clean_db

    tokens_plain = {
        "access_token":  "salla-tok-PLAINTEXT",
        "refresh_token": "salla-ref-PLAINTEXT",
        "store_name":    "متجر اختبار",
        "ai_config": {
            "groq_api_key":      "sk-groq-PLAINTEXT",
            "anthropic_api_key": "sk-ant-PLAINTEXT",
            "openai_api_key":    "",
            "bot_name":          "Sara",
        },
    }
    await db.save_store("test-store-enc", tokens_plain)

    # Read the raw JSONB directly (bypassing our load helpers) to assert
    # what's ACTUALLY on disk.
    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tokens FROM stores WHERE store_id=$1", "test-store-enc"
        )
    raw = row["tokens"]
    if isinstance(raw, str):
        import json as _json
        raw = _json.loads(raw)

    # The big guarantee.
    assert raw["access_token"].startswith("enc:v1:"), \
        "access_token landed in DB as plaintext — encryption boundary broken!"
    assert raw["refresh_token"].startswith("enc:v1:")
    assert raw["ai_config"]["groq_api_key"].startswith("enc:v1:")
    assert raw["ai_config"]["anthropic_api_key"].startswith("enc:v1:")

    # Non-secrets stay readable
    assert raw["store_name"] == "متجر اختبار"
    assert raw["ai_config"]["bot_name"] == "Sara"
    assert raw["ai_config"]["openai_api_key"] == "", \
        "empty fields should round-trip as empty, not as a big ciphertext"

    # AND none of the plaintext values appear anywhere in the raw JSON —
    # a regression guard against a future refactor missing a field.
    raw_json = str(raw)
    for sensitive in ("salla-tok-PLAINTEXT", "salla-ref-PLAINTEXT",
                      "sk-groq-PLAINTEXT", "sk-ant-PLAINTEXT"):
        assert sensitive not in raw_json, \
            f"PLAINTEXT leak in DB row: {sensitive!r} found in {raw_json[:200]!r}..."


async def test_load_all_stores_returns_plaintext(clean_db):
    """The mirror — load_all_stores must decrypt transparently so the rest
    of the codebase keeps reading `tokens['access_token']` unchanged."""
    db = clean_db
    await db.save_store("test-store-load", {
        "access_token":  "the-real-salla-token",
        "refresh_token": "the-real-refresh-token",
        "store_name":    "متجر",
        "ai_config":     {"groq_api_key": "sk-the-real-one"},
    })

    rows = await db.load_all_stores()
    found = next((r for r in rows if r["store_id"] == "test-store-load"), None)
    assert found is not None
    assert found["tokens"]["access_token"]  == "the-real-salla-token"
    assert found["tokens"]["refresh_token"] == "the-real-refresh-token"
    # ai_config is merged from BOTH tokens.ai_config and the separate
    # ai_config column. The provider key was set inside tokens.ai_config,
    # so we read it from tokens["ai_config"] here.
    assert found["tokens"]["ai_config"]["groq_api_key"] == "sk-the-real-one"


async def test_save_ai_config_encrypts_provider_keys(clean_db):
    """The dedicated ai_config column (separate from tokens.ai_config) also
    needs to be encrypted — it's a parallel write path used by the
    settings UI."""
    db = clean_db
    await db.save_store("test-aicfg", {
        "access_token": "tok",
        "ai_config":    {},
    })
    await db.save_ai_config("test-aicfg", {
        "groq_api_key":      "sk-from-settings-ui",
        "anthropic_api_key": "sk-ant-from-settings",
        "bot_name":          "Public Bot",
    })

    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT ai_config FROM stores WHERE store_id=$1", "test-aicfg"
        )
    raw = row["ai_config"]
    if isinstance(raw, str):
        import json as _json
        raw = _json.loads(raw)

    assert raw["groq_api_key"].startswith("enc:v1:")
    assert raw["anthropic_api_key"].startswith("enc:v1:")
    assert raw["bot_name"] == "Public Bot"  # not a secret


async def test_force_save_all_stores_encrypts_too(clean_db):
    """The bulk re-save path (admin → Force Save) must encrypt — was a
    common source of plaintext leaks in the original review."""
    db = clean_db
    stores = [
        {
            "store_id": "bulk-1",
            "tokens": {
                "access_token": "tok-bulk-1",
                "ai_config":    {"openai_api_key": "sk-openai-bulk"},
            },
        },
        {
            "store_id": "bulk-2",
            "tokens": {
                "access_token": "tok-bulk-2",
                "ai_config":    {"groq_api_key": "sk-groq-bulk"},
            },
        },
    ]
    saved = await db.force_save_all_stores(stores)
    assert saved == 2

    async with db._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT store_id, tokens, ai_config FROM stores "
            "WHERE store_id IN ('bulk-1', 'bulk-2') ORDER BY store_id"
        )
    import json as _json
    for r in rows:
        tokens = _json.loads(r["tokens"]) if isinstance(r["tokens"], str) else r["tokens"]
        assert tokens["access_token"].startswith("enc:v1:")


async def test_legacy_plaintext_row_loads_without_error(clean_db):
    """Migration window safety: a row written before C9 (plaintext on disk)
    must still load correctly — crypto.decrypt passes legacy values through
    unchanged."""
    db = clean_db
    # Hand-write a legacy-shaped row directly into the DB.
    import json as _json
    legacy_blob = {
        "access_token":  "old-plaintext-token",
        "refresh_token": "old-plaintext-refresh",
        "store_name":    "Legacy Store",
        "ai_config":     {"groq_api_key": "sk-still-plaintext"},
    }
    async with db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO stores (store_id, tokens) VALUES ($1, $2::jsonb)",
            "legacy-store",
            _json.dumps(legacy_blob, ensure_ascii=False),
        )

    rows = await db.load_all_stores()
    found = next((r for r in rows if r["store_id"] == "legacy-store"), None)
    assert found is not None
    assert found["tokens"]["access_token"]  == "old-plaintext-token"
    assert found["tokens"]["refresh_token"] == "old-plaintext-refresh"
    assert found["tokens"]["ai_config"]["groq_api_key"] == "sk-still-plaintext"


async def test_resave_legacy_row_encrypts_it(clean_db):
    """The migration path: load plaintext → save → next load returns
    plaintext again (transparent), but the DB now holds ciphertext."""
    db = clean_db
    import json as _json
    async with db._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO stores (store_id, tokens) VALUES ($1, $2::jsonb)",
            "to-be-migrated",
            _json.dumps({"access_token": "legacy-plain"}, ensure_ascii=False),
        )

    # Load (decrypt passes-through), then save (encrypts).
    rows = await db.load_all_stores()
    found = next(r for r in rows if r["store_id"] == "to-be-migrated")
    assert found["tokens"]["access_token"] == "legacy-plain"

    await db.save_store("to-be-migrated", found["tokens"])

    # Raw read — now it's a ciphertext.
    async with db._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tokens FROM stores WHERE store_id='to-be-migrated'"
        )
    raw = row["tokens"]
    if isinstance(raw, str):
        raw = _json.loads(raw)
    assert raw["access_token"].startswith("enc:v1:"), \
        "row should be encrypted after re-save"
