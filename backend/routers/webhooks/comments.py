"""Facebook/Instagram comment & mention auto-reply pipeline.

Split out of the original single-file routers/webhooks.py."""
from __future__ import annotations
import database as db
import store_manager as sm



# ─────────────────────────────────────────────────────────────────────────
# Facebook / Instagram comment handler (called by the inbox drainer)
# ─────────────────────────────────────────────────────────────────────────

def _hits_forbidden(text: str, topics: list) -> bool:
    """Deterministic forbidden-topic guard. A substring hit on any configured
    topic means the comment must NEVER be auto-answered — escalate to a human.
    Cheap + reliable; complements the model's own judgement."""
    if not topics:
        return False
    low = (text or "").lower()
    return any(t and str(t).lower().strip() in low for t in topics)


async def handle_comment_event(comment: dict):
    """
    Process one inbound FB/IG comment → classify → (auto-reply | queue for
    approval | suggest). Channel sibling of handle_messenger_message. Never
    raises for non-transient cases; re-raises transient send/AI errors so the
    inbox drainer applies backoff.

    Pipeline (see plan Phase B): resolve store → gate (suspended / per-platform
    enable / entitlement / token) → persist (idempotent) → forbidden-topic gate
    → AI classify+reply → spam gate → mode/confidence gate → enqueue outbox.
    """
    import comments as cm
    import comment_ai
    try:
        platform     = comment.get("platform", "facebook")
        recipient_id = str(comment.get("recipient_id", "") or "")
        comment_id   = str(comment.get("comment_id", "") or "")
        text         = comment.get("text", "") or ""

        print(f"[{platform}_comment] 📨 recipient={recipient_id!r} comment={comment_id!r} chars={len(text)}")
        if not (recipient_id and comment_id):
            return

        store_id = sm.find_store_by_page_id(recipient_id)   # matches page_id + ig_id
        if not store_id:
            print(f"[{platform}_comment] ❌ no store for recipient_id={recipient_id!r}")
            return
        if sm.is_suspended(store_id):
            return

        # Entitlement is the hard feature gate (is the store on the comment plan).
        ent = await db.get_entitlements(store_id)
        if not ent.get("comments_enabled"):
            print(f"[{platform}_comment] ⛔ feature not entitled for store {store_id!r}")
            return

        cfg = sm.get_ai_config(store_id) or {}

        # Persist FIRST — the comment must appear in the Smart Inbox regardless of
        # whether AUTO-REPLY is enabled for this platform. Idempotent on
        # (store, platform, external id); a False means Meta retried a delivery
        # we already handled → stop.
        ins = await db.social_comment_upsert(store_id, platform, comment)
        if not ins["inserted"]:
            print(f"[{platform}_comment] duplicate {comment_id!r} — already processed")
            return
        pk = ins["id"]
        print(f"[{platform}_comment] 💾 stored pk={pk} store={store_id!r}")

        # Per-platform toggle gates AUTO-REPLY only — not ingest. When off, the
        # comment stays visible as 'new' for manual handling; we just skip the AI.
        enabled = bool(cfg.get("comments_ig_enabled") if platform == "instagram"
                       else cfg.get("comments_fb_enabled"))
        if not enabled:
            print(f"[{platform}_comment] ⏸ auto-reply off for platform — stored as new")
            return

        if not text.strip():
            return  # media-only comment, nothing to answer; left as 'new'

        token = (cfg.get("page_token") or "").strip()

        # Forbidden topics → never auto-answer; hand to a human.
        if _hits_forbidden(text, cfg.get("comment_forbidden_topics") or []):
            await db.update_social_comment(store_id, pk, status="pending_approval",
                                           intent="forbidden")
            print(f"[{platform}_comment] 🚫 forbidden topic — escalated {comment_id!r}")
            return

        result = await comment_ai.classify_and_reply(store_id, text, cfg)
        enrich = {
            "sentiment":     result["sentiment"],
            "intent":        result["intent"],
            "category":      result["category"],
            "is_spam":       result["is_spam"],
            "lead_score":    result["lead_score"],
            "lead_temp":     result["lead_temp"],
            "ai_confidence": result["confidence"],
            "suggested_reply": result["reply"],
        }

        # Spam gate — hide or just flag for review, never auto-reply to spam.
        if result["is_spam"]:
            if (cfg.get("comment_spam_action") or "flag") == "hide":
                await cm.hide_comment(token, comment_id, platform)
                await db.update_social_comment(store_id, pk, status="hidden", **enrich)
            else:
                await db.update_social_comment(store_id, pk, status="pending_approval", **enrich)
            return

        mode      = (cfg.get("comment_mode") or "approval").lower()
        threshold = _clamp_threshold(cfg.get("comment_confidence_threshold"))
        reply     = result["reply"]

        if mode == "auto" and reply and token and result["confidence"] >= threshold:
            await db.update_social_comment(store_id, pk, status="ai_replied", **enrich)
            await db.outbox_enqueue(
                "comment_reply",
                {"comment_pk": pk, "comment_id": comment_id,
                 "platform": platform, "text": reply},
                store_id=store_id,
            )
            print(f"[{platform}_comment] 🤖 auto-reply queued ({result['confidence']:.2f} ≥ {threshold:.2f})")
        else:
            await db.update_social_comment(store_id, pk, status="pending_approval", **enrich)
            print(f"[{platform}_comment] 📝 queued for approval (mode={mode}, conf={result['confidence']:.2f})")
    except Exception as exc:
        print(f"[comments] handle_comment_event error: {exc}")
        raise  # transient — let the inbox drainer retry with backoff


def _clamp_threshold(val) -> float:
    try:
        return max(0.0, min(1.0, float(val)))
    except (TypeError, ValueError):
        return 0.8   # safe default — only very confident replies auto-post
