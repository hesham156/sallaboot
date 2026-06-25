"""
Tests for the Facebook/Instagram comment transport (comments.py).

Pure-unit (no DB): webhook payload parsing for both platforms, the self-comment
loop guard, non-comment feed events being ignored, and the reply/hide/
private-reply Graph request shapes. Mirrors test_messenger.py.
"""
from __future__ import annotations

import pytest

import comments as cm

pytestmark = pytest.mark.unit


# ── extract_comments — Facebook ─────────────────────────────────────────────

def test_extract_facebook_feed_comment():
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE_1",
            "changes": [{
                "field": "feed",
                "value": {
                    "item": "comment", "verb": "add",
                    "comment_id": "c_1", "post_id": "PAGE_1_post",
                    "parent_id": "", "message": "كم السعر؟",
                    "from": {"id": "USER_9", "name": "Sara"},
                    "permalink_url": "https://fb.com/c_1",
                },
            }],
        }],
    }
    out = cm.extract_comments(payload)
    assert len(out) == 1
    c = out[0]
    assert c["platform"] == "facebook"
    assert c["object_type"] == "comment"
    assert c["recipient_id"] == "PAGE_1"
    assert c["comment_id"] == "c_1"
    assert c["post_id"] == "PAGE_1_post"
    assert c["author_id"] == "USER_9"
    assert c["author_name"] == "Sara"
    assert c["text"] == "كم السعر؟"
    assert c["permalink"] == "https://fb.com/c_1"


def test_extract_facebook_ignores_non_comment_feed_events():
    # Likes, reactions, status posts → not comments → ignored.
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE_1",
            "changes": [
                {"field": "feed", "value": {"item": "like", "verb": "add"}},
                {"field": "feed", "value": {"item": "status", "verb": "add",
                                            "from": {"id": "U"}}},
            ],
        }],
    }
    assert cm.extract_comments(payload) == []


def test_extract_facebook_skips_remove_verb():
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE_1",
            "changes": [{
                "field": "feed",
                "value": {"item": "comment", "verb": "remove",
                          "comment_id": "c_x", "from": {"id": "U"}},
            }],
        }],
    }
    assert cm.extract_comments(payload) == []


def test_extract_self_comment_is_filtered():
    # The Page's own comment (author id == page id) must never be surfaced —
    # otherwise the bot would reply to itself in a loop.
    payload = {
        "object": "page",
        "entry": [{
            "id": "PAGE_1",
            "changes": [{
                "field": "feed",
                "value": {"item": "comment", "verb": "add", "comment_id": "c_self",
                          "message": "our own reply", "from": {"id": "PAGE_1"}},
            }],
        }],
    }
    assert cm.extract_comments(payload) == []


# ── extract_comments — Instagram ────────────────────────────────────────────

def test_extract_instagram_comment():
    payload = {
        "object": "instagram",
        "entry": [{
            "id": "IG_1",
            "changes": [{
                "field": "comments",
                "value": {
                    "id": "ig_c_1", "text": "متوفر؟",
                    "from": {"id": "IGSID_3", "username": "noura"},
                    "media": {"id": "media_7"},
                },
            }],
        }],
    }
    out = cm.extract_comments(payload)
    assert len(out) == 1
    c = out[0]
    assert c["platform"] == "instagram"
    assert c["object_type"] == "comment"
    assert c["recipient_id"] == "IG_1"
    assert c["comment_id"] == "ig_c_1"
    assert c["post_id"] == "media_7"
    assert c["author_id"] == "IGSID_3"
    assert c["author_name"] == "noura"
    assert c["text"] == "متوفر؟"


def test_extract_instagram_mention_object_type():
    payload = {
        "object": "instagram",
        "entry": [{
            "id": "IG_1",
            "changes": [{
                "field": "mentions",
                "value": {"comment_id": "ig_m_1", "media_id": "media_2",
                          "from": {"id": "IGSID_5"}},
            }],
        }],
    }
    out = cm.extract_comments(payload)
    assert len(out) == 1
    assert out[0]["object_type"] == "mention"
    assert out[0]["comment_id"] == "ig_m_1"


# ── Reply / hide / private-reply request shapes ─────────────────────────────

class _Resp:
    status_code = 200
    text = ""


class _Capture:
    """Fake httpx.AsyncClient that records the last POST."""
    last: dict = {}

    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, headers=None, json=None, params=None):
        _Capture.last = {"url": url, "json": json, "params": params,
                         "auth": (headers or {}).get("Authorization")}
        return _Resp()


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    _Capture.last = {}
    monkeypatch.setattr(cm.httpx, "AsyncClient", _Capture)


async def test_facebook_reply_posts_to_comments_edge():
    ok = await cm.reply_to_comment("PAGE_TOKEN", "c_1", "أهلاً", platform="facebook")
    assert ok is True
    assert _Capture.last["url"].endswith("/c_1/comments")
    assert _Capture.last["json"] == {"message": "أهلاً"}
    assert _Capture.last["auth"] == "Bearer PAGE_TOKEN"


async def test_instagram_reply_posts_to_replies_edge():
    ok = await cm.reply_to_comment("PAGE_TOKEN", "ig_c_1", "تمام", platform="instagram")
    assert ok is True
    assert _Capture.last["url"].endswith("/ig_c_1/replies")
    assert _Capture.last["json"] == {"message": "تمام"}


async def test_hide_uses_platform_specific_field():
    await cm.hide_comment("T", "c_1", platform="facebook")
    assert _Capture.last["json"] == {"is_hidden": True}
    await cm.hide_comment("T", "ig_c_1", platform="instagram")
    assert _Capture.last["json"] == {"hide": True}


async def test_private_reply_posts_to_private_replies_edge():
    ok = await cm.private_reply("T", "c_1", "راسلناك بالخاص")
    assert ok is True
    assert _Capture.last["url"].endswith("/c_1/private_replies")
    assert _Capture.last["json"] == {"message": "راسلناك بالخاص"}


async def test_reply_is_noop_on_missing_args():
    assert await cm.reply_to_comment("", "c", "x") is False
    assert await cm.reply_to_comment("T", "", "x") is False
    assert await cm.reply_to_comment("T", "c", "") is False
