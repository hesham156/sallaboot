"""
Central conversation store.
Shared between the chat agent, admin endpoints, and widget polling.

Roles:
  user      — message from the store visitor
  assistant — auto reply from the AI bot
  admin     — manual reply from the store admin

Bot can be toggled:
  - Globally (affects all sessions)
  - Per-session (admin took over a specific chat)

Storage:
  - In-memory _conversations dict (primary read/write path)
  - PostgreSQL via database.py (write-through; loaded on startup)
"""

import datetime
import database as db

# ── Bot toggles ────────────────────────────────────────────────────────────────
# Global toggle: hot-cached in memory but the DB (app_settings table) is the
# source of truth. Loaded once at startup via load_globals_from_db().
_bot_globally_enabled: bool = True

# ── Conversations dict: session_id → conv dict ─────────────────────────────────
_conversations: dict[str, dict] = {}

# Sessions that have been mutated since the last periodic flush
# mark_dirty() must be at module level so mutation functions below can call it
_dirty_sessions: set[str] = set()


def mark_dirty(session_id: str):
    """Mark a session as needing a DB sync on the next periodic flush."""
    _dirty_sessions.add(session_id)


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Conversation CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create(session_id: str, store_id: str = "default") -> dict:
    if session_id not in _conversations:
        _conversations[session_id] = {
            "session_id": session_id,
            "store_id": store_id,
            "messages": [],
            "bot_enabled": True,
            "created_at": _now(),
            "last_activity": _now(),
            "pending_for_widget": [],
            "last_admin_read": "",
            # ── Shopping cart ──────────────────────────────────────────
            "cart": [],             # [{product_id, name, price, currency, image, url, quantity, notes}]
            "customer_info": {},    # {name, phone, email, city, country, avatar, gender}
            "salla_customer_id": "", # links the conversation to a logged-in Salla customer
            "last_component": None, # last structured component for the widget
            # ── Rating ────────────────────────────────────────────────
            "rating": None,         # 1-5 or None
            "rating_comment": "",
        }
    return _conversations[session_id]


# ─────────────────────────────────────────────────────────────────────────────
# Customer ↔ session lookup
# ─────────────────────────────────────────────────────────────────────────────

def find_session_by_customer(store_id: str, salla_customer_id: str | int) -> str | None:
    """
    Return the most-recent session_id for the given Salla customer in this
    store, or None. Used by the chat endpoint so a logged-in customer
    re-opening the widget on a different device picks up their thread
    instead of starting a new one.

    In-memory scan — fine up to ~10K conversations. Move to a DB index
    if/when we get past that.
    """
    cid = str(salla_customer_id or "").strip()
    if not cid:
        return None
    matches = [
        (sid, conv) for sid, conv in _conversations.items()
        if str(conv.get("salla_customer_id", "")) == cid
        and conv.get("store_id", "default") == store_id
    ]
    if not matches:
        return None
    matches.sort(key=lambda kv: kv[1].get("last_activity", ""), reverse=True)
    return matches[0][0]


async def find_session_by_customer_db(store_id: str, salla_customer_id: str | int) -> str | None:
    """
    Same as find_session_by_customer but falls back to the DB when memory
    misses (e.g. fresh process that hasn't loaded the conversation yet).
    Returns the newest matching session_id.
    """
    in_mem = find_session_by_customer(store_id, salla_customer_id)
    if in_mem:
        return in_mem
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
        # Warm into memory for next call
        await restore_to_memory(sid)
    return sid


def link_customer(session_id: str, salla_customer_id: str | int,
                  customer_data: dict | None = None) -> None:
    """
    Attach a Salla customer to a conversation. customer_data should be the
    /customers/{id} response normalised to:
      {name, phone, email, city, country, avatar, gender, mobile_code}
    Anything missing stays missing — never overwrites with empty strings.
    """
    conv = _conversations.get(session_id)
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
    mark_dirty(session_id)


# ─────────────────────────────────────────────────────────────────────────────
# Cart management
# ─────────────────────────────────────────────────────────────────────────────

def get_cart(session_id: str) -> list:
    return get_or_create(session_id).get("cart", [])


def cart_add(session_id: str, item: dict):
    """Add or update a product in the cart."""
    conv = get_or_create(session_id)
    pid  = str(item.get("product_id", ""))
    for existing in conv["cart"]:
        if str(existing.get("product_id", "")) == pid:
            existing["quantity"] = existing.get("quantity", 1) + item.get("quantity", 1)
            if item.get("notes"):
                existing["notes"] = item["notes"]
            mark_dirty(session_id)
            return
    conv["cart"].append(item)
    mark_dirty(session_id)


def cart_remove(session_id: str, product_id) -> bool:
    conv = _conversations.get(session_id)
    if not conv:
        return False
    before = len(conv["cart"])
    conv["cart"] = [i for i in conv["cart"] if str(i.get("product_id", "")) != str(product_id)]
    changed = len(conv["cart"]) < before
    if changed:
        mark_dirty(session_id)
    return changed


def cart_clear(session_id: str):
    conv = _conversations.get(session_id)
    if conv:
        conv["cart"] = []
        mark_dirty(session_id)


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


def set_customer_info(session_id: str, info: dict):
    conv = get_or_create(session_id)
    conv["customer_info"].update({k: v for k, v in info.items() if v})
    mark_dirty(session_id)


# ─────────────────────────────────────────────────────────────────────────────
# Last component (widget rich UI state)
# ─────────────────────────────────────────────────────────────────────────────

def set_last_component(session_id: str, component):
    conv = get_or_create(session_id)
    conv["last_component"] = component
    mark_dirty(session_id)


def pop_last_component(session_id: str):
    """Return and clear the last component."""
    conv = _conversations.get(session_id)
    if not conv:
        return None
    comp = conv.get("last_component")
    conv["last_component"] = None
    return comp


async def add_message(session_id: str, role: str, content: str, store_id: str = "default") -> dict:
    """
    Append a message to the conversation and AWAIT the DB persist.

    role: 'user' | 'assistant' | 'admin'

    store_id resolution: if a non-default store_id is passed and the existing
    conversation is still tagged with the placeholder "default", upgrade it so
    the conversation appears in the correct admin dashboard. Without this, a
    conversation that was first touched by a legacy caller (no store_id) would
    stay stuck under "default" forever — invisible to every real admin.

    Persistence: this function awaits the DB write so messages reliably
    survive deploys/restarts. Previously db.fire() (fire-and-forget) was
    used, which silently lost data when the write failed or the server
    restarted before the background task completed.
    """
    await restore_to_memory(session_id)
    conv = get_or_create(session_id, store_id)
    # Upgrade stale "default" tag to the real store_id passed by an explicit caller
    if store_id and store_id != "default" and conv.get("store_id", "default") == "default":
        conv["store_id"] = store_id

    msg = {"role": role, "content": content, "ts": _now()}
    conv["messages"].append(msg)
    conv["last_activity"] = _now()
    if role == "admin":
        # Queue for widget polling
        conv["pending_for_widget"].append({"content": content, "ts": msg["ts"]})

    # AWAIT the DB write — guarantees persistence before returning to caller
    try:
        await db.save_conversation(session_id, conv.get("store_id", store_id), conv)
    except Exception as exc:
        # Log loudly but don't break the chat flow if DB is temporarily down
        print(f"[conversation_store] ❌ Failed to persist message for {session_id!r}: {exc}")

    return msg


def get_groq_history(session_id: str) -> list:
    """
    Return message history in Groq/OpenAI format.
    Only user + assistant messages (admin messages are not sent to the AI).
    """
    conv = _conversations.get(session_id, {})
    return [
        {"role": m["role"], "content": m["content"]}
        for m in conv.get("messages", [])
        if m["role"] in ("user", "assistant")
    ]


def pop_pending_for_widget(session_id: str) -> list:
    """Return and clear pending admin messages for the widget."""
    conv = _conversations.get(session_id)
    if not conv:
        return []
    pending = list(conv["pending_for_widget"])
    conv["pending_for_widget"] = []
    return pending


# ─────────────────────────────────────────────────────────────────────────────
# Bot toggle
# ─────────────────────────────────────────────────────────────────────────────

def is_bot_enabled(session_id: str) -> bool:
    """Check if bot should respond for this session.
    Priority: per-session override → per-store toggle → global toggle.
    Reads from the persisted store tokens, not in-memory state.
    """
    import store_manager as sm
    conv = _conversations.get(session_id, {})
    # per-session override (human takeover)
    if not conv.get("bot_enabled", True):
        return False
    # per-store toggle (persisted in tokens.bot_enabled)
    store_id = conv.get("store_id", "default")
    if not sm.get_store_info(store_id).get("bot_enabled", True):
        return False
    # global toggle (persisted in app_settings)
    return _bot_globally_enabled


def set_session_bot(session_id: str, enabled: bool):
    get_or_create(session_id)["bot_enabled"] = enabled
    mark_dirty(session_id)


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
    Restore the global bot toggle from app_settings on startup. Called from
    main.py's startup_event after db.init() succeeds.
    """
    global _bot_globally_enabled
    try:
        val = await db.get_app_setting("bot_globally_enabled", True)
        _bot_globally_enabled = bool(val) if val is not None else True
        print(f"[conversation_store] global bot toggle loaded: {_bot_globally_enabled}")
    except Exception as exc:
        print(f"[conversation_store] ⚠️ Failed to load global bot toggle, defaulting to True: {exc}")


# ── Per-store bot toggle ───────────────────────────────────────────────────────

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

def mark_admin_read(session_id: str):
    conv = _conversations.get(session_id)
    if conv:
        conv["last_admin_read"] = _now()
        mark_dirty(session_id)


def has_unread_user_messages(session_id: str) -> bool:
    """True if user sent messages after admin last read."""
    conv = _conversations.get(session_id, {})
    last_read = conv.get("last_admin_read", "")
    for m in reversed(conv.get("messages", [])):
        if m["role"] == "user":
            return m["ts"] > last_read
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────────────────────

async def set_rating(session_id: str, rating: int, comment: str = ""):
    """
    Save a customer rating (1-5) for a conversation. Awaits the DB write.

    Important: pulls the session from DB into memory first if it's not
    already loaded. Without this, ratings submitted after a server restart
    (when the session hasn't been re-cached yet) would silently disappear
    because `_conversations.get(session_id)` would return None.
    """
    await restore_to_memory(session_id)
    conv = _conversations.get(session_id)
    if not conv:
        print(f"[conversation_store] ⚠️ set_rating: session {session_id!r} not found anywhere (DB + memory)")
        return
    conv["rating"]         = max(1, min(5, int(rating)))
    conv["rating_comment"] = comment
    try:
        await db.save_conversation(session_id, conv.get("store_id", "default"), conv)
    except Exception as exc:
        print(f"[conversation_store] ❌ Failed to persist rating for {session_id!r}: {exc}")


async def flush(session_id: str):
    """
    Persist any pending mutations (cart changes, customer info, last_component,
    bot_enabled toggles) to the DB. Call after a series of state changes that
    don't go through add_message — e.g. after a cart-only tool call.
    """
    conv = _conversations.get(session_id)
    if not conv:
        return
    try:
        await db.save_conversation(session_id, conv.get("store_id", "default"), conv)
    except Exception as exc:
        print(f"[conversation_store] ❌ Failed to flush {session_id!r}: {exc}")



async def flush_all() -> int:
    """
    Persist EVERY conversation in memory to the DB.
    Used on graceful shutdown to guarantee nothing is lost.
    Returns number of conversations saved.
    """
    saved = 0
    for sid, conv in list(_conversations.items()):
        try:
            await db.save_conversation(sid, conv.get("store_id", "default"), conv)
            saved += 1
        except Exception as exc:
            print(f"[conversation_store] ❌ flush_all failed for {sid!r}: {exc}")
    return saved



async def flush_dirty() -> int:
    """
    Persist only sessions that were mutated since the last flush_dirty() call.
    Called by the periodic background loop every 5 minutes as a safety net.
    Returns number of sessions flushed.
    """
    if not _dirty_sessions:
        return 0
    to_flush = list(_dirty_sessions)
    _dirty_sessions.clear()
    saved = 0
    for sid in to_flush:
        conv = _conversations.get(sid)
        if not conv:
            continue
        try:
            await db.save_conversation(sid, conv.get("store_id", "default"), conv)
            saved += 1
        except Exception as exc:
            # Re-mark dirty so next cycle retries it
            _dirty_sessions.add(sid)
            print(f"[conversation_store] ❌ flush_dirty failed for {sid!r}: {exc}")
    return saved


def all_conversations() -> dict:
    return _conversations


async def restore_to_memory(session_id: str) -> bool:
    """Restore a conversation from PostgreSQL to memory if it exists and is not already loaded."""
    if session_id in _conversations:
        return True
    if db.available():
        data = await db.load_conversation(session_id)
        if data:
            _conversations[session_id] = data
            return True
    return False


async def get_all_conversations_for_store(store_id: str) -> dict[str, dict]:
    """
    Get all conversations for a specific store, combining database records
    and active in-memory sessions (in-memory takes priority for active sessions).
    """
    if db.available():
        rows = await db.load_store_conversations(store_id, limit=2000)
        for r in rows:
            sid = r["session_id"]
            if sid not in _conversations:
                _conversations[sid] = r["data"]

    return {
        sid: conv
        for sid, conv in _conversations.items()
        if conv.get("store_id", "default") == store_id
    }


async def load_conversations_from_db():
    """
    Async — restore recent conversations from PostgreSQL on startup.
    Only called when DB is available; in-memory state takes precedence if
    the session already exists (shouldn't happen on a cold start).
    """
    rows = await db.load_conversations(limit=2000)
    if not rows:
        return
    loaded = 0
    for row in rows:
        sid = row["session_id"]
        if sid in _conversations:
            continue  # already loaded (shouldn't happen on cold start)
        data = row["data"]
        if not data.get("messages"):
            continue
        _conversations[sid] = data
        loaded += 1
    print(f"[conversation_store] Restored {loaded} conversation(s) from DB")


def summary_list(
    store_id: str = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """
    Conversation summaries for admin panel list view.
    Filter by store_id if provided; paginated via limit/offset.

    Returns:
        {
            "total":         int   — total conversations matching the filter,
            "conversations": list  — slice [offset : offset+limit] sorted newest-first,
        }
    """
    result = []
    for sid, conv in _conversations.items():
        if store_id and conv.get("store_id", "default") != store_id:
            continue
        msgs = conv["messages"]
        last = msgs[-1] if msgs else None
        user_count = sum(1 for m in msgs if m["role"] == "user")
        unread = has_unread_user_messages(sid)
        cust = conv.get("customer_info") or {}
        result.append({
            "session_id":         sid,
            "messages_count":     len(msgs),
            "user_messages_count": user_count,
            "last_message":       last,
            "bot_enabled":        conv["bot_enabled"],
            "last_activity":      conv["last_activity"],
            "created_at":         conv["created_at"],
            "unread":             unread,
            "rating":             conv.get("rating"),
            # ── Customer identity (for admin list view) ──
            "salla_customer_id":  conv.get("salla_customer_id", ""),
            "customer_name":      cust.get("name", ""),
            "customer_phone":     cust.get("phone", ""),
            "customer_email":     cust.get("email", ""),
            "customer_avatar":    cust.get("avatar", ""),
        })
    result.sort(key=lambda x: x["last_activity"], reverse=True)
    total = len(result)
    page  = result[offset : offset + limit] if limit > 0 else result
    return {"total": total, "conversations": page}
