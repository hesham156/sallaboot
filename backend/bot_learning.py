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


# ─────────────────────────────────────────────────────────────────────────────
# Automatic learning loop — mine conversations for pending suggestions
# ─────────────────────────────────────────────────────────────────────────────
# Driven by lifecycle.learning_loop() every few hours (leader-elected). It turns
# raw chat history into two things, WITHOUT any LLM call:
#   1. pending FAQ drafts   — questions customers ask repeatedly, paired with the
#      bot's best-performing answer (from the conversation with the best outcome).
#   2. pending weak-spot lessons — questions that preceded a negative reaction
#      (low CSAT, admin takeover, or angry wording) for the admin to answer right.
# Plus it refreshes a compact "customer insights" block cached on the store so the
# live prompt can preempt the top questions/objections cheaply.
#
# Everything it writes is DISABLED (enabled=False) → it only reaches the bot after
# the admin approves it on the "تدريب البوت" page. Same safety gate as corrections.

_FAQ_MIN_REPEATS   = 3     # a question must recur in ≥ this many chats to draft an FAQ
_MAX_NEW_PER_KIND  = 5     # cap new suggestions per kind per run (avoid flooding)
_MIN_CONVS_TO_MINE = 8     # need a meaningful sample before mining


def _conv_outcome_score(conv: dict) -> int:
    """Higher = better outcome. Used to pick which chat's answer to a recurring
    question becomes the suggested FAQ answer (prefer answers that sold/satisfied)."""
    score = 0
    rating = conv.get("rating")
    if isinstance(rating, (int, float)) and rating:
        score += int(rating)                      # 1..5
    comp = conv.get("last_component") or {}
    if isinstance(comp, dict) and comp.get("type") == "checkout":
        score += 5
    else:
        for m in conv.get("messages", []):
            if m.get("role") == "assistant" and "رابط الدفع" in (m.get("content") or ""):
                score += 5
                break
    return score


def _answer_after(messages: list[dict], q_norm: str) -> str:
    """First assistant reply that directly follows a user message matching q_norm."""
    for i, m in enumerate(messages):
        if m.get("role") == "user" and _normalize(m.get("content") or "") == q_norm:
            for nxt in messages[i + 1:]:
                if nxt.get("role") == "assistant":
                    a = (nxt.get("content") or "").strip()
                    return a if (a and not a.startswith("📎")) else ""
                if nxt.get("role") == "user":
                    break
    return ""


def _build_insights_block(insights: dict) -> str:
    """Compact Arabic prompt block from analyze_insights() output. Cached on the
    store and injected so the bot proactively handles the real top questions and
    objections — this is what makes it 'sell better' from learned data."""
    tq  = insights.get("top_questions") or []
    npr = insights.get("non_purchase") or []
    conv = insights.get("conversion") or {}
    if not tq and not npr:
        return ""
    lines = ["══ رؤى من محادثات العملاء (استثمرها لتبيع وتساعد أفضل) ══"]
    if tq:
        top = " / ".join(f"{t['label']} ({t['count']})" for t in tq[:5])
        lines.append(f"• أكثر ما يسأل عنه العملاء: {top} — كن جاهزاً بإجابات سريعة ومقنعة عنها.")
    if npr:
        objs = " / ".join(r["label"] for r in npr[:4])
        lines.append(
            f"• أبرز أسباب عدم إتمام الشراء: {objs} — عالِج هذه الاعتراضات استباقياً قبل "
            f"أن يذكرها العميل (أبرز القيمة، وخيارات الدفع بالتقسيط، والشحن المجاني إن توفّر)."
        )
    cr = conv.get("conversion_rate")
    if cr is not None:
        lines.append(
            f"• نسبة تحويل المحادثات إلى طلبات حالياً {cr}% — اسعَ لرفعها بإرشاد العميل "
            f"بلطف نحو إتمام الطلب دون إلحاح."
        )
    return "\n".join(lines)


async def mine_store(store_id: str) -> int:
    """
    Mine one store's conversations for auto-learning suggestions + refresh the
    cached insights block. Returns the number of NEW pending suggestions created.
    Best-effort and silent: never raises.
    """
    try:
        from collections import defaultdict
        import conversation_store as cs
        import conversation_analyzer as ca
        import store_manager as sm

        convs = await cs.get_all_conversations_for_store(store_id)
        if len(convs) < _MIN_CONVS_TO_MINE:
            return 0

        # ── Refresh cached insights block (cheap to inject later) ──────────────
        try:
            insights = ca.analyze_insights(convs)
            block = _build_insights_block(insights)
            cfg = sm.get_ai_config(store_id) or {}
            if (cfg.get("learned_insights_block") or "") != block:
                cfg["learned_insights_block"] = block
                await sm.set_ai_config(store_id, cfg)
                try:
                    await db.save_ai_config(store_id, cfg)
                except Exception:
                    pass
                sm.reset_agent(store_id)   # rebuild so new insights enter the prompt
        except Exception as exc:
            print(f"[learning] insights refresh skipped for {store_id!r}: {exc}")

        # ── Dedup set: don't recreate suggestions we already have ──────────────
        try:
            existing = await db.list_training(store_id)
        except Exception:
            existing = []
        existing_titles = {
            _normalize(e.get("title", ""))
            for e in existing if e.get("kind") in ("faq", "lesson")
        }

        # ── 1) Recurring questions → pending FAQ drafts ───────────────────────
        q_counts: dict[str, int] = defaultdict(int)
        q_display: dict[str, str] = {}
        for conv in convs.values():
            seen_here: set[str] = set()
            for m in conv.get("messages", []):
                if m.get("role") != "user":
                    continue
                raw = (m.get("content") or "").strip()
                if len(raw) < 8 or raw.startswith("📎") or "تم إرفاق ملف" in raw:
                    continue
                qn = _normalize(raw)
                if len(qn) < 6 or qn in _FILLER or qn in seen_here:
                    continue
                seen_here.add(qn)            # count a question once per conversation
                q_counts[qn] += 1
                q_display.setdefault(qn, raw[:180])

        created = 0
        faq_added = 0
        for qn, cnt in sorted(q_counts.items(), key=lambda kv: -kv[1]):
            if faq_added >= _MAX_NEW_PER_KIND or cnt < _FAQ_MIN_REPEATS:
                break                       # list is sorted desc → safe to stop
            if qn in existing_titles:
                continue
            best_a, best_score = "", -1
            for conv in convs.values():
                a = _answer_after(conv.get("messages", []), qn)
                if not a:
                    continue
                s = _conv_outcome_score(conv)
                if s > best_score:
                    best_score, best_a = s, a
            if best_a and len(best_a) >= _MIN_ADMIN_CHARS:
                nid = await db.add_training(
                    store_id, kind="faq", title=q_display[qn],
                    content=best_a, enabled=False,
                )
            else:
                nid = await db.add_training(
                    store_id, kind="lesson", title=q_display[qn],
                    content="❓ سؤال يتكرّر كثيراً بدون إجابة واضحة من البوت — "
                            "اكتب الرد الأمثل ليتعلّمه ويتوقف عن إحالة العملاء للدعم.",
                    enabled=False,
                )
            if nid:
                existing_titles.add(qn)
                faq_added += 1
                created += 1

        # ── 2) Negative reactions → pending weak-spot lessons ─────────────────
        weak_added = 0
        for conv in convs.values():
            if weak_added >= _MAX_NEW_PER_KIND:
                break
            msgs = conv.get("messages", [])
            rating = conv.get("rating")
            low_rating = isinstance(rating, (int, float)) and rating and rating <= 2
            checked_out = ca._had_checkout(conv)
            admin_takeover = (conv.get("bot_enabled", True) is False) and not checked_out
            user_text = " ".join(
                m.get("content", "") for m in msgs if m.get("role") == "user"
            )
            angry = bool(user_text) and ca._matches_any(user_text, ca.ANGRY_KEYWORDS)
            if not (low_rating or admin_takeover or angry):
                continue
            q = _last_customer_question(msgs)
            if not q or len(q) < 6:
                continue
            qn = _normalize(q)
            if qn in existing_titles:
                continue                    # already captured (e.g. admin correction)
            signal = ("تقييم منخفض" if low_rating
                      else "تدخّل الإدارة" if admin_takeover
                      else "عدم رضا العميل")
            nid = await db.add_training(
                store_id, kind="lesson", title=q[:180],
                content=f"⚠️ {signal} بعد هذا السؤال — راجع المحادثة واكتب الرد الأمثل "
                        f"ليتعلّمه البوت ولا يكرّر نفس الموقف.",
                enabled=False,
            )
            if nid:
                existing_titles.add(qn)
                weak_added += 1
                created += 1

        if created:
            print(f"[learning] 🧠 store {store_id!r}: {faq_added} FAQ + "
                  f"{weak_added} weak-spot suggestion(s) (pending approval)")
        return created
    except Exception as exc:
        print(f"[learning] mine_store skipped for {store_id!r}: {exc}")
        return 0
