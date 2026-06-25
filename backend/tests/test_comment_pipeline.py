"""
Phase B — comment processing pipeline (gating logic), no DB / no live LLM.

Covers the safety-critical decisions in webhooks.handle_comment_event:
  • entitlement + per-platform enable gating
  • forbidden-topic escalation (AI never called)
  • spam hide vs flag
  • mode/confidence gate: auto-reply only when mode=auto AND confidence ≥ threshold
And comment_ai._parse_result tolerance, plus the outbox comment_reply sender.
"""
from __future__ import annotations

import pytest

import comment_ai
import comments as cm
from routers import webhooks as wh

pytestmark = pytest.mark.unit


# ── comment_ai._parse_result ────────────────────────────────────────────────

def test_parse_result_valid_json_clamps():
    raw = ('{"sentiment":"negative","intent":"complaint","category":"complaint",'
           '"is_spam":false,"lead_score":150,"lead_temp":"warm","confidence":2.0,'
           '"reply":"نأسف لذلك"}')
    r = comment_ai._parse_result(raw)
    assert r["sentiment"] == "negative"
    assert r["lead_score"] == 100        # clamped 150 → 100
    assert r["confidence"] == 1.0        # clamped 2.0 → 1.0
    assert r["reply"] == "نأسف لذلك"


def test_parse_result_extracts_json_from_prose():
    raw = 'Sure! Here is the result:\n```json\n{"confidence":0.9,"reply":"أهلاً"}\n```'
    r = comment_ai._parse_result(raw)
    assert r["confidence"] == 0.9 and r["reply"] == "أهلاً"


def test_parse_result_garbage_returns_default():
    assert comment_ai._parse_result("not json at all") == comment_ai.DEFAULT_RESULT
    assert comment_ai._parse_result("") == comment_ai.DEFAULT_RESULT


def test_hits_forbidden():
    assert wh._hits_forbidden("هل تعالج السكري؟", ["السكري", "كورونا"]) is True
    assert wh._hits_forbidden("كم السعر؟", ["السكري"]) is False
    assert wh._hits_forbidden("anything", []) is False


# ── handle_comment_event gating ─────────────────────────────────────────────

class _Spy:
    """Collects the side-effect calls handle_comment_event makes."""
    def __init__(self):
        self.updates = []      # list of (pk, kwargs)
        self.enqueued = []     # list of (kind, payload)
        self.hidden = []       # list of comment_ids
        self.classified = 0


@pytest.fixture
def wired(monkeypatch):
    """Wire handle_comment_event against in-memory fakes. Returns (spy, cfg)."""
    spy = _Spy()
    cfg = {
        "comments_fb_enabled": True,
        "page_token": "PAGE_TOKEN",
        "comment_mode": "auto",
        "comment_confidence_threshold": 0.8,
        "comment_forbidden_topics": ["قضية قانونية"],
        "comment_spam_action": "hide",
    }

    monkeypatch.setattr(wh.sm, "find_store_by_page_id", lambda rid: "store_a")
    monkeypatch.setattr(wh.sm, "is_suspended", lambda sid: False)
    monkeypatch.setattr(wh.sm, "get_ai_config", lambda sid: cfg)

    async def _ent(sid):              return {"comments_enabled": True}
    async def _upsert(sid, plat, c):  return {"inserted": True, "id": 1}
    async def _update(sid, pk, **kw): spy.updates.append((pk, kw)); return True
    async def _enq(kind, payload, *, store_id=""): spy.enqueued.append((kind, payload)); return 1
    async def _hide(token, cid, platform="facebook", hidden=True): spy.hidden.append(cid); return True

    monkeypatch.setattr(wh.db, "get_entitlements", _ent)
    monkeypatch.setattr(wh.db, "social_comment_upsert", _upsert)
    monkeypatch.setattr(wh.db, "update_social_comment", _update)
    monkeypatch.setattr(wh.db, "outbox_enqueue", _enq)
    monkeypatch.setattr(cm, "hide_comment", _hide)

    def _set_ai(result):
        async def _classify(store_id, text, settings=None):
            spy.classified += 1
            return result
        monkeypatch.setattr(comment_ai, "classify_and_reply", _classify)
    return spy, cfg, _set_ai


def _comment(text="كم السعر؟"):
    return {"platform": "facebook", "recipient_id": "PAGE_1",
            "comment_id": "c_1", "text": text}


def _result(confidence=0.95, is_spam=False, reply="أهلاً بك"):
    r = dict(comment_ai.DEFAULT_RESULT)
    r.update({"confidence": confidence, "is_spam": is_spam, "reply": reply,
              "sentiment": "positive", "intent": "pricing", "category": "sales"})
    return r


async def test_auto_high_confidence_enqueues_reply(wired):
    spy, cfg, set_ai = wired
    set_ai(_result(confidence=0.95, reply="السعر ٥٠ ريال"))
    await wh.handle_comment_event(_comment())
    assert spy.enqueued and spy.enqueued[0][0] == "comment_reply"
    assert spy.enqueued[0][1]["text"] == "السعر ٥٠ ريال"
    assert any(kw.get("status") == "ai_replied" for _, kw in spy.updates)


async def test_auto_low_confidence_goes_to_approval(wired):
    spy, cfg, set_ai = wired
    set_ai(_result(confidence=0.5))
    await wh.handle_comment_event(_comment())
    assert spy.enqueued == []     # below threshold → no auto-post
    assert any(kw.get("status") == "pending_approval" for _, kw in spy.updates)


async def test_approval_mode_never_auto_posts(wired):
    spy, cfg, set_ai = wired
    cfg["comment_mode"] = "approval"
    set_ai(_result(confidence=0.99))
    await wh.handle_comment_event(_comment())
    assert spy.enqueued == []
    assert any(kw.get("status") == "pending_approval" for _, kw in spy.updates)


async def test_forbidden_topic_escalates_without_calling_ai(wired):
    spy, cfg, set_ai = wired
    set_ai(_result(confidence=0.99))
    await wh.handle_comment_event(_comment(text="عندي قضية قانونية ضدكم"))
    assert spy.classified == 0     # AI never invoked on forbidden topics
    assert spy.enqueued == []
    assert any(kw.get("intent") == "forbidden" for _, kw in spy.updates)


async def test_spam_hide_action(wired):
    spy, cfg, set_ai = wired
    set_ai(_result(confidence=0.95, is_spam=True))
    await wh.handle_comment_event(_comment())
    assert spy.hidden == ["c_1"]
    assert spy.enqueued == []
    assert any(kw.get("status") == "hidden" for _, kw in spy.updates)


async def test_not_entitled_is_dropped(wired, monkeypatch):
    spy, cfg, set_ai = wired
    set_ai(_result())
    async def _no_ent(sid): return {"comments_enabled": False}
    monkeypatch.setattr(wh.db, "get_entitlements", _no_ent)
    await wh.handle_comment_event(_comment())
    assert spy.updates == [] and spy.enqueued == []


async def test_platform_disabled_is_dropped(wired):
    spy, cfg, set_ai = wired
    cfg["comments_fb_enabled"] = False
    set_ai(_result())
    await wh.handle_comment_event(_comment())
    assert spy.updates == [] and spy.enqueued == []
