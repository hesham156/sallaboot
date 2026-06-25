"""
Integration tests for the social-comment data layer (database.py).

Needs a real Postgres — auto-skipped when none is available (see conftest).
Locks in: idempotent upsert (Meta retry safety), tenant-scoped list/filter,
whitelisted update, and the entitlement upsert.
"""
from __future__ import annotations

import pytest

import database as db

pytestmark = pytest.mark.integration


def _comment(cid: str, **over) -> dict:
    base = {
        "object_type": "comment", "comment_id": cid, "parent_id": "",
        "post_id": "post_1", "recipient_id": "PAGE_1", "author_id": "U_1",
        "author_name": "Sara", "text": "كم السعر؟", "permalink": "",
    }
    base.update(over)
    return base


async def test_upsert_is_idempotent(clean_db):
    r1 = await db.social_comment_upsert("store_a", "facebook", _comment("c_1"))
    assert r1["inserted"] is True and r1["id"]
    # Same (store, platform, external id) → Meta retry → no second row.
    r2 = await db.social_comment_upsert("store_a", "facebook", _comment("c_1"))
    assert r2["inserted"] is False
    rows = await db.list_social_comments("store_a")
    assert len(rows) == 1
    assert rows[0]["message"] == "كم السعر؟"


async def test_same_id_different_tenant_is_separate(clean_db):
    await db.social_comment_upsert("store_a", "facebook", _comment("c_1"))
    r = await db.social_comment_upsert("store_b", "facebook", _comment("c_1"))
    assert r["inserted"] is True
    assert len(await db.list_social_comments("store_a")) == 1
    assert len(await db.list_social_comments("store_b")) == 1


async def test_list_filters_by_status_and_platform(clean_db):
    await db.social_comment_upsert("s", "facebook", _comment("c_1"))
    ig = await db.social_comment_upsert("s", "instagram", _comment("c_2"))
    await db.update_social_comment("s", ig["id"], status="resolved")
    assert len(await db.list_social_comments("s", platform="instagram")) == 1
    assert len(await db.list_social_comments("s", status="resolved")) == 1
    assert len(await db.list_social_comments("s", status="new")) == 1


async def test_update_only_whitelisted_columns(clean_db):
    ins = await db.social_comment_upsert("s", "facebook", _comment("c_1"))
    ok = await db.update_social_comment(
        "s", ins["id"], sentiment="negative", lead_score=80, lead_temp="hot",
        status="pending_approval", suggested_reply="عرض خاص",
        store_id="hacked",  # not whitelisted — must be ignored
    )
    assert ok is True
    row = await db.get_social_comment("s", ins["id"])
    assert row["sentiment"] == "negative"
    assert row["lead_score"] == 80 and row["lead_temp"] == "hot"
    assert row["status"] == "pending_approval"
    assert row["store_id"] == "s"          # tenant unchanged


async def test_update_wrong_tenant_is_noop(clean_db):
    ins = await db.social_comment_upsert("s", "facebook", _comment("c_1"))
    assert await db.update_social_comment("other", ins["id"], status="resolved") is False


async def test_entitlements_default_and_upsert(clean_db):
    assert await db.get_entitlements("s") == {
        "comments_enabled": False, "comments_monthly_limit": 0,
    }
    await db.set_entitlements("s", comments_enabled=True, comments_monthly_limit=5000)
    ent = await db.get_entitlements("s")
    assert ent["comments_enabled"] is True and ent["comments_monthly_limit"] == 5000
    # Upsert again (conflict path) flips it back off.
    await db.set_entitlements("s", comments_enabled=False)
    assert (await db.get_entitlements("s"))["comments_enabled"] is False


async def test_comment_rules_crud(clean_db):
    rid = await db.add_comment_rule(
        "s", match_type="keyword", pattern="سعر", action="reply_template",
        template="راسلناك بالأسعار", priority=10,
    )
    assert rid
    rules = await db.list_comment_rules("s")
    assert len(rules) == 1 and rules[0]["pattern"] == "سعر"
    assert await db.delete_comment_rule("s", rid) is True
    assert await db.list_comment_rules("s") == []
