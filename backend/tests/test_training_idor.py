"""
Cross-tenant IDOR regression for bot-training rows (finding M-1).

db.update_training_enabled / db.delete_training used to filter on the global
integer id alone, so an authenticated manager/owner of store A could toggle or
delete store B's training by guessing the id. Both are now scoped by store_id.

DB-backed → auto-skips when no Postgres is available.
"""
from __future__ import annotations

import pytest

import database as db

pytestmark = pytest.mark.integration


async def test_delete_training_scoped_by_store(clean_db, register_test_store):
    await register_test_store("storeA")
    await register_test_store("storeB")
    tid = await db.add_training("storeA", "instruction", "secret", "content")
    assert tid is not None

    # Cross-tenant attack: storeB must not delete storeA's row.
    ok, fid = await db.delete_training(tid, "storeB")
    assert ok is False and fid is None

    # The row survives and the owner can still delete it (positive case).
    ok2, _ = await db.delete_training(tid, "storeA")
    assert ok2 is True

    # Idempotent / not-found: deleting again returns False.
    ok3, _ = await db.delete_training(tid, "storeA")
    assert ok3 is False


async def test_toggle_training_scoped_by_store(clean_db, register_test_store):
    await register_test_store("storeA")
    tid = await db.add_training("storeA", "instruction", "t", "c")
    assert tid is not None

    # Cross-tenant attack: foreign store cannot toggle.
    assert await db.update_training_enabled(tid, False, "storeB") is False
    # Owner can toggle (positive case).
    assert await db.update_training_enabled(tid, False, "storeA") is True
    # Unknown id → False.
    assert await db.update_training_enabled(999999, False, "storeA") is False
