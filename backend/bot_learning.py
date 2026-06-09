"""
bot_learning.py
─────────────────────────────────────────────────────────────────────────────
Continuous-improvement loop — "Lessons Learned".

The bot can't retrain its model weights live, but it CAN accumulate a growing
set of lessons that are injected into its prompt, so it gets smarter over time
and stops repeating mistakes.

The highest-signal, zero-extra-cost learning source is the ADMIN's own manual
replies: when a human takes over and answers a customer, that answer is the
correct response the bot should have given. We capture the
(customer question → admin answer) pair as a *pending lesson*.

Safety gate: lessons are saved DISABLED (enabled=False). They only enter the
bot's prompt after an admin reviews and approves them on the "تدريب البوت"
page — so the bot never auto-learns the wrong thing from a bad interaction.

Lessons reuse the existing bot_training table (kind='lesson') so they get the
same storage, prompt-injection (build_training_block) and admin UI for free.
"""
from __future__ import annotations
import re
import database as db

# Admin replies shorter/▼ vaguer than this aren't worth learning from.
_MIN_ADMIN_CHARS = 15
# Filler-only admin replies we never capture as lessons.
_FILLER = {
    "تمام", "اوكي", "أوكي", "ok", "اوك", "ثانية", "لحظة", "دقيقة",
    "حاضر", "تم", "اهلا", "أهلا", "مرحبا", "شكرا", "شكرًا", "عفوا",
}


def _normalize(text: str) -> str:
    t = re.sub(r"[ؗ-ًؚ-ْٰـ]", "", text or "")
    t = (t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
           .replace("ى", "ي").replace("ة", "ه"))
    t = re.sub(r"[^\w؀-ۿ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def _last_customer_question(messages: list[dict]) -> str:
    """The most recent customer (user) message — the thing the admin answered."""
    for m in reversed(messages):
        if m.get("role") == "user":
            q = (m.get("content") or "").strip()
            # Skip file-attachment system lines
            if q and not q.startswith("📎") and "تم إرفاق ملف" not in q:
                return q
    return ""


async def capture_admin_correction(store_id: str, session_id: str, admin_text: str) -> None:
    """
    Turn an admin's manual reply into a pending lesson.

    Best-effort and silent: never raises, never blocks the admin reply flow.
    Saves a disabled bot_training row (kind='lesson') awaiting approval.
    """
    try:
        import conversation_store as cs

        admin_text = (admin_text or "").strip()
        if len(admin_text) < _MIN_ADMIN_CHARS:
            return
        if _normalize(admin_text) in _FILLER:
            return

        # Phase-3: cs.all_conversations() is now task-scoped. Ensure
        # the session is loaded into THIS task's cache before reading.
        await cs.restore_to_memory(session_id)
        conv = cs.all_conversations().get(session_id) or {}
        messages = conv.get("messages", [])
        question = _last_customer_question(messages)
        if not question or len(question) < 4:
            return

        # ── Dedup: don't pile up near-identical lessons/FAQs for the same Q ──
        q_norm = _normalize(question)
        try:
            existing = await db.list_training(store_id)
        except Exception:
            existing = []
        for e in existing:
            if e.get("kind") in ("lesson", "faq"):
                if _normalize(e.get("title", "")) == q_norm:
                    return  # already captured / answered

        title = question[:180]
        new_id = await db.add_training(
            store_id,
            kind="lesson",
            title=title,
            content=admin_text,
            enabled=False,          # ← pending admin approval (safety gate)
        )
        if new_id:
            print(f"[learning] 📚 captured pending lesson #{new_id} for store "
                  f"{store_id!r}: {title[:60]!r}")
    except Exception as exc:
        print(f"[learning] capture_admin_correction skipped: {exc}")
