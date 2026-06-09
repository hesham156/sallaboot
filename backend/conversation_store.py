"""
Central conversation store.

Phase 3 — task-scoped cache (no cross-replica state)
─────────────────────────────────────────────────────
Previously the module exposed a single process-wide `_conversations` dict.
That dict survived across requests, drainers, and any other asyncio task,
so two web replicas reading the same `session_id` saw *different*
snapshots until the periodic flusher reconciled them. Specifically:

  • `is_bot_enabled`, `get_cart`, `summary_list`, `pop_last_component`
    returned data from the writer-replica's memory, blind to a state
    change that happened on the other replica seconds ago.
  • Fire-and-forget `mark_dirty()` meant a mutation could sit unflushed
    in one process while another process answered a request from a
    stale read.

The fix: the cache is now a `contextvars.ContextVar`, populated per
asyncio task. Each FastAPI request runs in its own task, so each request
gets its own empty cache that's populated on demand via
`restore_to_memory()` and discarded when the task ends. The DB is the
*only* source of cross-task / cross-replica state.

Every mutation function (cart_*, set_customer_info, link_customer,
set_last_component, set_session_bot, mark_admin_read,
escalate_session, clear_escalation) is now `async` and **awaits** a full
`db.save_conversation` before returning. That makes the next request on
any replica see the committed write.

`mark_dirty()` remains as a deprecated no-op so legacy call sites don't
break during the migration window — mutations are persisted inline, so
the dirty_at column is effectively unused going forward. `flush_dirty()`
also stays as a safety net for any pre-Phase-3 row that still carries
a dirty_at value from before this deploy.

Reads (get_cart, get_customer_info, is_bot_enabled, get_groq_history,
pop_last_component, get_escalation, has_unread_user_messages) remain
synchronous. Their contract is: callers MUST have awaited
`restore_to_memory(session_id)` (or another function that does) earlier
in the same task. Without that prelude the cache is empty and the
function returns its zero value. Every endpoint that calls these
already follows the pattern.

Roles:
  user      — message from the store visitor
  assistant — auto reply from the AI bot
  admin     — manual reply from the store admin

Bot can be toggled:
  - Globally (affects all sessions; DB-persisted in app_settings)
  - Per-store (DB-persisted in stores.tokens.bot_enabled)
  - Per-session (DB-persisted in conversations.data.bot_enabled)
"""

from __future__ import annotations

import contextvars
import datetime

import database as db
import realtime as _rt


# ─────────────────────────────────────────────────────────────────────────────
# Global bot toggle (single value, DB is canonical)
# ─────────────────────────────────────────────────────────────────────────────
# Loaded once at startup via load_globals_from_db(). Read on the hot
# chat path so we keep a tiny in-process cache; writes go through
# set_bot_globally which persists.

_bot_globally_enabled: bool = True


# ─────────────────────────────────────────────────────────────────────────────
# Task-scoped conversations cache
# ─────────────────────────────────────────────────────────────────────────────
# ContextVar gives every asyncio task its own dict. asyncio.create_task
# copies the parent context, so a request handler and any background
# task it spawns share the cache — that's the right scope (they're
# operating on behalf of the same user action).
#
# Background loops spawned at startup (drainers, periodic) live in
# their own tasks → fresh cache each. The cache never accumulates
# data from "the wrong tenant" or "the wrong request".

_conversations: contextvars.ContextVar[dict[str, dict] | None] = contextvars.ContextVar(
    "_conversations", default=None
)


def _cache() -> dict[str, dict]:
    """
    Return the current task's conversations cache, lazily creating
    one if this is the first access in this task. The cache is a
    plain dict; mutations to its values are visible to subsequent
    reads inside the same task and invisible everywhere else.
    """
    c = _conversations.get()
    if c is None:
        c = {}
        _conversations.set(c)
    return c


def mark_dirty(session_id: str) -> None:  # noqa: ARG001
    """
    DEPRECATED — no-op since Phase 3.

    Mutations now await `db.save_conversation` immediately, so there's
    nothing to flag for later flushing. Kept as an importable name so
    legacy call sites compile during the migration window. Safe to
    delete once every caller has been audited.
    """
    return None


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


async def _persist(conv: dict) -> None:
    """
    Inline persist used by every mutation helper. Awaits the DB write,
    clears any leftover dirty_at flag from before Phase 3. Never raises:
    failures are logged so a flaky DB doesn't break the chat path. The
    caller has already mutated the cache copy; if the DB write fails,
    the cache and DB diverge until the next successful write — same
    failure mode as the legacy mark_dirty path, but loud.
    """
    if not db.available():
        return
    sid       = conv["session_id"]
    store_id  = conv.get("store_id", "default")
    try:
        await db.save_conversation(sid, store_id, conv)
        await db.clear_conversation_dirty([sid])
    except Exception as exc:
        print(f"[conversation_store] ❌ persist {sid!r} failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Conversation CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create(session_id: str, store_id: str = "default") -> dict:
    """
    Return the task-local cached conv dict for this session, creating
    a fresh one if absent. Synchronous because the cache is in-process.
    Callers that need the *DB* state must have already awaited
    `restore_to_memory(session_id)` earlier in this task.
    """
    cache = _cache()
    if session_id not in cache:
        cache[session_id] = {
            "session_id":         session_id,
            "store_id":           store_id,
            "messages":           [],
            "bot_enabled":        True,
            "created_at":         _now(),
            "last_activity":      _now(),
            # pending_for_widget moved to the widget_outbox DB table
            # in Phase 2. Old persisted rows that still have the key
            # are ignored on read; they age out naturally.
            "last_admin_read":    "",
            # ── Shopping cart ──────────────────────────────────────────
            "cart":               [],
            "customer_info":      {},
            "salla_customer_id":  "",
            "last_component":     None,
            # ── Rating ────────────────────────────────────────────────
            "rating":             None,
            "rating_comment":     "",
        }
    return cache[session_id]


# ─────────────────────────────────────────────────────────────────────────────
# Customer ↔ session lookup
# ─────────────────────────────────────────────────────────────────────────────

async def find_session_by_customer_db(store_id: str, salla_customer_id: str | int) -> str | None:
    """
    Return the newest session_id for the given Salla customer in this
    store, or None. DB-only since Phase 3 — the legacy in-memory scan
    only saw the current task's cache, which is almost always empty
    for this lookup case (it's called BEFORE the session is restored).
    """
    if not db.available():
        return None
    cid = str(salla_customer_id or "").strip()
    if not cid:
        return None
    try:
        sid = await db.find_session_by_salla_customer(store_id, cid)
    except Exception as exc:
        print(f"[conversation_store] find_session_by_customer_db error: {exc}")
        return None
    if sid:
        # Warm into the task-local cache so subsequent reads in this
        # request don't pay the DB roundtrip again.
        await restore_to_memory(sid)
    return sid


async def link_customer(session_id: str, salla_customer_id: str | int,
                        customer_data: dict | None = None) -> None:
    """
    Attach a Salla customer to a conversation. customer_data should be
    the /customers/{id} response normalised to
    `{name, phone, email, city, country, avatar, gender, mobile_code}`.
    Anything missing stays missing — never overwrites with empty strings.
    Persists immediately so the next read on any replica sees the link.
    """
    conv = _cache().get(session_id)
    if not conv:
        return
    cid = str(salla_customer_id or "").strip()
    if cid:
        conv["salla_customer_id"] = cid
    if customer_data:
        info = conv.get("customer_info") or {}
        for k, v in customer_data.items():
            if v:  # non-empty wins
                info[k] = v
        conv["customer_info"] = info
    await _persist(conv)


# ─────────────────────────────────────────────────────────────────────────────
# Cart management
# ─────────────────────────────────────────────────────────────────────────────

def get_cart(session_id: str) -> list:
    """Read-through from the task-local cache. Caller must have restored."""
    return get_or_create(session_id).get("cart", [])


async def cart_add(session_id: str, item: dict) -> None:
    """Add or update a product in the cart. Persists immediately."""
    conv = get_or_create(session_id)
    pid  = str(item.get("product_id", ""))
    for existing in conv["cart"]:
        if str(existing.get("product_id", "")) == pid:
            existing["quantity"] = existing.get("quantity", 1) + item.get("quantity", 1)
            if item.get("notes"):
                existing["notes"] = item["notes"]
            await _persist(conv)
            return
    conv["cart"].append(item)
    await _persist(conv)


async def cart_remove(session_id: str, product_id) -> bool:
    conv = _cache().get(session_id)
    if not conv:
        return False
    before = len(conv["cart"])
    conv["cart"] = [i for i in conv["cart"] if str(i.get("product_id", "")) != str(product_id)]
    changed = len(conv["cart"]) < before
    if changed:
        await _persist(conv)
    return changed


async def cart_clear(session_id: str) -> None:
    conv = _cache().get(session_id)
    if conv:
        conv["cart"] = []
        await _persist(conv)


def cart_total(session_id: str) -> float:
    total = 0.0
    for item in get_cart(session_id):
        try:
            total += float(item.get("price", 0)) * int(item.get("quantity", 1))
        except (ValueError, TypeError):
            pass
    return total


# ─────────────────────────────────────────────────────────────────────────────
# Customer info
# ─────────────────────────────────────────────────────────────────────────────

def get_customer_info(session_id: str) -> dict:
    return get_or_create(session_id).get("customer_info", {})


async def set_customer_info(session_id: str, info: dict) -> None:
    conv = get_or_create(session_id)
    conv["customer_info"].update({k: v for k, v in info.items() if v})
    await _persist(conv)


# ─────────────────────────────────────────────────────────────────────────────
# Last component (widget rich UI state)
# ─────────────────────────────────────────────────────────────────────────────

async def set_last_component(session_id: str, component) -> None:
    conv = get_or_create(session_id)
    conv["last_component"] = component
    await _persist(conv)


async def pop_last_component(session_id: str):
    """
    Return AND clear the last component. The clear is persisted so a
    second /chat reply on a different replica doesn't see the same
    component again.
    """
    conv = _cache().get(session_id)
    if not conv:
        return None
    comp = conv.get("last_component")
    if comp is not None:
        conv["last_component"] = None
        await _persist(conv)
    return comp


async def add_message(session_id: str, role: str, content: str, store_id: str = "default") -> dict:
    """
    Append a message to the conversation and AWAIT the DB persist.

    role: 'user' | 'assistant' | 'admin'

    store_id resolution: if a non-default store_id is passed and the
    existing conversation is still tagged with the placeholder
    'default', upgrade it so the conversation appears in the correct
    admin dashboard. Without this, a conversation that was first
    touched by a legacy caller (no store_id) would stay stuck under
    'default' forever — invisible to every real admin.

    Persistence: this function awaits the DB write so messages
    reliably survive deploys/restarts. Realtime NOTIFY fires *after*
    the commit so SSE subscribers can fetch the full message and find
    it.
    """
    await restore_to_memory(session_id)
    conv = get_or_create(session_id, store_id)
    # Upgrade stale "default" tag to the real store_id passed by an
    # explicit caller.
    if store_id and store_id != "default" and conv.get("store_id", "default") == "default":
        conv["store_id"] = store_id

    msg = {"role": role, "content": content, "ts": _now()}
    conv["messages"].append(msg)
    conv["last_activity"] = _now()
    if role == "admin":
        # Durable per-session queue. Replaces the legacy
        # conv["pending_for_widget"] list which only existed in the
        # writer replica's memory and disappeared on the way to any
        # other replica's SSE flush-on-connect. db.fire() — losing a
        # row here is acceptable in degraded DB mode because the
        # realtime NOTIFY below still delivers to live SSE consumers;
        # only the catch-up-on-reconnect path is affected.
        db.fire(db.widget_outbox_enqueue(session_id, {
            "role":    "admin",
            "content": content,
            "ts":      msg["ts"],
        }))

    # AWAIT the DB write — guarantees persistence before returning.
    await _persist(conv)

    # ── Realtime fanout ─────────────────────────────────────────────
    # Notify any live SSE clients (widget + admin dashboard) that this
    # session just gained a message. Best-effort: realtime.publish
    # never raises, just logs.
    sid_store = conv.get("store_id", store_id)
    payload = {
        "session_id": session_id,
        "store_id":   sid_store,
        "role":       role,
        "ts":         msg["ts"],
        # Trim the body — full text is queried by the SSE client via
        # the conversation detail endpoint. NOTIFY payload caps at 8KB
        # so passing the entire message would break on long ones.
        "preview":    (content or "")[:200],
    }
    await _rt.publish(f"session:{session_id}", f"{role}_message", payload)
    await _rt.publish(f"store:{sid_store}",    "new_message",        payload)

    return msg


# Sliding window of messages sent to the AI per request. 12 messages
# ≈ 6 full user/assistant turns — enough context for a sales
# conversation (current need, last suggestion, cart, customer info)
# without re-billing the whole transcript on every reply. Cart and
# customer state are stored separately (cs.get_cart / cs.get_customer_info),
# so trimming history does NOT lose them. Full transcript is still
# persisted in the DB for the admin inbox.
AI_HISTORY_TURNS = 12


def get_groq_history(session_id: str, limit: int = AI_HISTORY_TURNS) -> list:
    """
    Return message history in Groq/OpenAI/Anthropic format from the
    task-local cache. Caller must have restored.
    Only user + assistant messages (admin messages are not sent to AI).
    """
    conv = _cache().get(session_id, {})
    msgs = [
        {"role": m["role"], "content": m["content"]}
        for m in conv.get("messages", [])
        if m["role"] in ("user", "assistant")
    ]
    if limit and len(msgs) > limit:
        msgs = msgs[-limit:]
        # Anthropic + Groq tool-use both require the window to START
        # on a user turn (the model can't reply to its own prior
        # assistant turn without the user message that triggered it).
        # Drop a leading assistant message if the slice lands on one.
        if msgs and msgs[0]["role"] != "user":
            msgs = msgs[1:]
    return msgs


async def pop_pending_for_widget(session_id: str) -> list:
    """
    Return and atomically mark-delivered pending widget messages for
    this session. DB-backed so any web replica's SSE flush-on-connect
    sees the backlog produced by any other replica's admin reply.
    """
    if not db.available():
        return []
    return await db.widget_outbox_claim_pending(session_id, limit=100)


def enqueue_widget_message(session_id: str, payload: dict) -> None:
    """
    Direct enqueue for messages that DON'T flow through add_message
    but still need to land in the widget — e.g. the bot follow-up +
    CSAT survey emitted by /end. Fire-and-forget; same degraded-mode
    behaviour as add_message's admin branch.
    """
    db.fire(db.widget_outbox_enqueue(session_id, payload))


# ─────────────────────────────────────────────────────────────────────────────
# Bot toggle
# ─────────────────────────────────────────────────────────────────────────────

def is_bot_enabled(session_id: str) -> bool:
    """
    Resolution order: per-session override → per-store toggle → global.
    Per-session is read from the task-local cache (caller must have
    restored). Per-store reads `stores.tokens.bot_enabled` via
    store_manager. Global reads the module-cached toggle.
    """
    import store_manager as sm
    conv = _cache().get(session_id, {})
    if not conv.get("bot_enabled", True):
        return False
    store_id = conv.get("store_id", "default")
    if not sm.get_store_info(store_id).get("bot_enabled", True):
        return False
    return _bot_globally_enabled


async def set_session_bot(session_id: str, enabled: bool) -> None:
    conv = get_or_create(session_id)
    conv["bot_enabled"] = enabled
    await _persist(conv)


# ─────────────────────────────────────────────────────────────────────────────
# Admin escalation
# ─────────────────────────────────────────────────────────────────────────────
# A session is "escalated" when the bot decides the request needs a
# human (un-priced material, oversized design, custom box, etc.).
# Escalation:
#   1. Disables the bot for the session so the admin's reply is final.
#   2. Records WHY in conv["escalation"] so the admin dashboard can
#      surface the reason without re-reading the transcript.
# The admin dashboard already lists sessions where bot_enabled=False,
# so escalated chats appear in the queue automatically.

VALID_ESCALATION_REASONS = {
    "unpriced_material",     # خامة بلا سعر في الجدول
    "oversize_design",       # المقاس أكبر من عرض الرول/الشيت/المسطح
    "digital_over_500",      # ديجيتال > 500 حبة
    "offset_under_1000",     # أوفست < 1000 حبة
    "offset_paper_missing",  # سعر ورق الأوفست غير محمّل
    "box_oversize",          # علب بمقاس فرد أكبر من 99×69
    "custom_finishing",      # تشطيب/مواصفة غير مسعّرة
    "vip_or_complaint",      # عميل VIP أو شكوى
    "other",                 # غير ذلك
}


async def escalate_session(
    session_id: str,
    reason: str,
    details: str = "",
    customer_summary: str = "",
) -> dict:
    """
    Hand the session over to the admin.

    - `reason` must be one of VALID_ESCALATION_REASONS (else stored as "other").
    - `details` is what the bot would tell the admin (specs, size,
      qty, why it can't price). Free-form Arabic text.
    - `customer_summary` is an optional pre-built one-liner the admin
      sees in the inbox header.

    Returns the stored escalation dict for the caller to use.
    """
    conv = get_or_create(session_id)
    reason_clean = reason if reason in VALID_ESCALATION_REASONS else "other"
    escalation = {
        "reason":           reason_clean,
        "details":          (details or "").strip(),
        "customer_summary": (customer_summary or "").strip(),
        "at":               _now(),
        "resolved":         False,
    }
    conv["escalation"]   = escalation
    conv["bot_enabled"]  = False   # admin takeover
    await _persist(conv)
    return escalation


def get_escalation(session_id: str) -> dict | None:
    """Return the current escalation dict for the session, or None."""
    conv = _cache().get(session_id, {})
    esc = conv.get("escalation")
    if isinstance(esc, dict) and esc.get("reason"):
        return esc
    return None


async def clear_escalation(session_id: str) -> None:
    """Mark the escalation as resolved (admin handled the request)."""
    conv = _cache().get(session_id)
    if conv and isinstance(conv.get("escalation"), dict):
        conv["escalation"]["resolved"]    = True
        conv["escalation"]["resolved_at"] = _now()
        await _persist(conv)


def get_bot_globally() -> bool:
    return _bot_globally_enabled


async def set_bot_globally(enabled: bool):
    """Update the global bot toggle and persist to DB so it survives restarts."""
    global _bot_globally_enabled
    _bot_globally_enabled = bool(enabled)
    try:
        await db.set_app_setting("bot_globally_enabled", _bot_globally_enabled)
    except Exception as exc:
        print(f"[conversation_store] ❌ Failed to persist global bot toggle: {exc}")


async def load_globals_from_db():
    """
    Restore the global bot toggle from app_settings on startup. Called
    from lifecycle.startup after db.init() succeeds.
    """
    global _bot_globally_enabled
    try:
        val = await db.get_app_setting("bot_globally_enabled", True)
        _bot_globally_enabled = bool(val) if val is not None else True
        print(f"[conversation_store] global bot toggle loaded: {_bot_globally_enabled}")
    except Exception as exc:
        print(f"[conversation_store] ⚠️ Failed to load global bot toggle, defaulting to True: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Per-store bot toggle
# ─────────────────────────────────────────────────────────────────────────────

def get_store_bot(store_id: str) -> bool:
    """Return per-store bot enabled state (defaults to True). Reads from DB-backed tokens."""
    import store_manager as sm
    return sm.get_store_info(store_id).get("bot_enabled", True)


def set_store_bot(store_id: str, enabled: bool):
    """Enable/disable bot for a specific store only. Persisted via store_manager → DB."""
    import store_manager as sm
    if sm.is_registered(store_id):
        tokens = sm.get_store_info(store_id)
        tokens["bot_enabled"] = enabled
        sm.register_store(store_id, tokens.get("access_token", ""), tokens.get("refresh_token", ""), tokens)


# ─────────────────────────────────────────────────────────────────────────────
# Admin read tracking
# ─────────────────────────────────────────────────────────────────────────────

async def mark_admin_read(session_id: str) -> None:
    conv = _cache().get(session_id)
    if conv:
        conv["last_admin_read"] = _now()
        await _persist(conv)


def has_unread_user_messages(session_id: str) -> bool:
    """
    True if user sent messages after admin last read. Reads from the
    task-local cache.
    """
    conv = _cache().get(session_id, {})
    last_read = conv.get("last_admin_read", "")
    for m in reversed(conv.get("messages", [])):
        if m["role"] == "user":
            return m["ts"] > last_read
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Rating, flush, restore
# ─────────────────────────────────────────────────────────────────────────────

async def set_rating(session_id: str, rating: int, comment: str = ""):
    """Save a customer rating (1-5) for a conversation. Awaits the DB write."""
    await restore_to_memory(session_id)
    conv = _cache().get(session_id)
    if not conv:
        print(f"[conversation_store] ⚠️ set_rating: session {session_id!r} not found anywhere (DB + memory)")
        return
    conv["rating"]         = max(1, min(5, int(rating)))
    conv["rating_comment"] = comment
    await _persist(conv)


async def flush(session_id: str):
    """
    Force-save the task-local cached conv to DB. Phase-3 mutations
    persist inline, so this is mostly a no-op safety net for legacy
    callers and edge mutations done via direct dict access on the
    returned `get_or_create()` reference.
    """
    conv = _cache().get(session_id)
    if not conv:
        return
    await _persist(conv)


async def flush_all() -> int:
    """
    Persist EVERY conversation currently in this task's cache. Used on
    graceful shutdown to guarantee nothing is lost. Phase-3 mutations
    already persist inline, so on a fresh shutdown this is empty —
    kept for back-compat.

    Returns number of conversations saved.
    """
    saved = 0
    flushed_ids: list[str] = []
    for sid, conv in list(_cache().items()):
        try:
            await db.save_conversation(sid, conv.get("store_id", "default"), conv)
            saved += 1
            flushed_ids.append(sid)
        except Exception as exc:
            print(f"[conversation_store] ❌ flush_all failed for {sid!r}: {exc}")
    if flushed_ids:
        await db.clear_conversation_dirty(flushed_ids)
    return saved


async def flush_dirty() -> int:
    """
    Clear conversations.dirty_at for any pre-Phase-3 row still carrying
    the flag. Phase-3 mutations persist inline, so this loop has no
    real work to do on a freshly migrated DB — it just unflags rows so
    the periodic loop doesn't spin on them.

    Cross-instance safe; the dirty_at column is shared but mutations
    are now atomic per-write.
    """
    sids = await db.fetch_dirty_sessions(limit=200)
    if not sids:
        return 0
    # Phase 3: rows are already at their latest state in DB. Just clear
    # the flag so the periodic loop converges and stops finding work.
    await db.clear_conversation_dirty(sids)
    return len(sids)


def all_conversations() -> dict:
    """
    Return the task-local cache. WARNING: this only sees conversations
    that the current task has touched (via restore_to_memory,
    get_or_create, etc). For a cross-task / cross-replica view, use
    `summary_list()` or `get_all_conversations_for_store()` which read
    from the DB.

    Kept for back-compat with code that wants to scan recent items
    inside a single request. Do not use for admin-list / cross-store
    aggregation.
    """
    return _cache()


async def restore_to_memory(session_id: str) -> bool:
    """
    Load a conversation from PostgreSQL into the task-local cache if
    not already loaded in this task. Returns True if the conversation
    is now in cache (loaded or already present), False if it doesn't
    exist in the DB.

    Idempotent within a task; cheap on cache-hit. Every entry point
    that intends to read conv state via the sync helpers MUST await
    this once per session_id at the start of the request.
    """
    cache = _cache()
    if session_id in cache:
        return True
    if db.available():
        data = await db.load_conversation(session_id)
        if data:
            cache[session_id] = data
            return True
    return False


async def get_all_conversations_for_store(store_id: str) -> dict[str, dict]:
    """
    Return all conversations for a store, DB-backed. Does NOT touch
    the task-local cache (no warming) — callers are typically admin
    list views that don't need to mutate.
    """
    if not db.available():
        return {}
    rows = await db.load_store_conversations(store_id, limit=2000)
    return {r["session_id"]: r["data"] for r in rows}


async def load_conversations_from_db():
    """
    Phase 3 — no-op. Pre-Phase-3 this populated the process-wide
    cache at startup. With task-scoped caching, eager loading would
    just fill the startup task's cache (which dies immediately),
    achieving nothing.

    Kept as an importable name so lifecycle.startup() doesn't break.
    Sessions are now loaded lazily by `restore_to_memory()` on first
    access in each request.
    """
    return None


def _summarise_row(sid: str, store_id: str, conv: dict) -> dict:
    """Shape one DB row into the admin-list summary the SPA expects."""
    msgs = conv.get("messages") or []
    last = msgs[-1] if msgs else None
    user_count = sum(1 for m in msgs if m.get("role") == "user")

    last_read = conv.get("last_admin_read", "")
    unread = False
    for m in reversed(msgs):
        if m.get("role") == "user":
            unread = (m.get("ts", "") > last_read)
            break

    cust = conv.get("customer_info") or {}
    return {
        "session_id":          sid,
        # Prefer the conversations.store_id column (canonical), fall
        # back to data.store_id, fall back to 'default' (orphan).
        "store_id":            store_id or conv.get("store_id", "default"),
        "messages_count":      len(msgs),
        "user_messages_count": user_count,
        "last_message":        last,
        "bot_enabled":         conv.get("bot_enabled", True),
        "last_activity":       conv.get("last_activity", ""),
        "created_at":          conv.get("created_at", ""),
        "unread":              unread,
        "rating":              conv.get("rating"),
        # ── Customer identity ──
        "salla_customer_id":   conv.get("salla_customer_id", ""),
        "customer_name":       cust.get("name", ""),
        "customer_phone":      cust.get("phone", ""),
        "customer_email":      cust.get("email", ""),
        "customer_avatar":     cust.get("avatar", ""),
    }


async def summary_list(
    store_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """
    Conversation summaries for the admin list view — DB-backed since
    Phase 3.

    Filter by store_id when provided; paginate via limit/offset. The
    underlying DB query sorts newest-first via the existing
    `(store_id, updated_at DESC)` index.

    Returns:
        {
            "total":         int,
            "conversations": list,
        }
    """
    if not db.available():
        return {"total": 0, "conversations": []}

    if store_id:
        rows = await db.load_store_conversations(store_id, limit=2000)
    else:
        rows = await db.load_conversations(limit=2000)

    result = [
        _summarise_row(r["session_id"], r.get("store_id", ""), r["data"])
        for r in rows
    ]
    # load_store_conversations already orders newest-first;
    # load_conversations too. Re-sort defensively in case a future
    # caller changes the order.
    result.sort(key=lambda x: x["last_activity"], reverse=True)
    total = len(result)
    page  = result[offset: offset + limit] if limit > 0 else result
    return {"total": total, "conversations": page}
