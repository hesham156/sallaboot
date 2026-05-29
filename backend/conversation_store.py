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
"""

import datetime

# ── Bot toggles ────────────────────────────────────────────────────────────────
_bot_globally_enabled: bool = True          # legacy / single-store fallback
_store_bot_enabled:    dict[str, bool] = {} # per-store override {store_id: bool}

# ── Conversations dict: session_id → conv dict ─────────────────────────────────
_conversations: dict[str, dict] = {}


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
            "customer_info": {},    # {name, phone, email}
            "last_component": None, # last structured component for the widget
        }
    return _conversations[session_id]


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
            return
    conv["cart"].append(item)


def cart_remove(session_id: str, product_id) -> bool:
    conv = _conversations.get(session_id)
    if not conv:
        return False
    before = len(conv["cart"])
    conv["cart"] = [i for i in conv["cart"] if str(i.get("product_id", "")) != str(product_id)]
    return len(conv["cart"]) < before


def cart_clear(session_id: str):
    conv = _conversations.get(session_id)
    if conv:
        conv["cart"] = []


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


# ─────────────────────────────────────────────────────────────────────────────
# Last component (widget rich UI state)
# ─────────────────────────────────────────────────────────────────────────────

def set_last_component(session_id: str, component):
    conv = get_or_create(session_id)
    conv["last_component"] = component


def pop_last_component(session_id: str):
    """Return and clear the last component."""
    conv = _conversations.get(session_id)
    if not conv:
        return None
    comp = conv.get("last_component")
    conv["last_component"] = None
    return comp


def add_message(session_id: str, role: str, content: str, store_id: str = "default") -> dict:
    """
    Append a message to the conversation.
    role: 'user' | 'assistant' | 'admin'
    """
    conv = get_or_create(session_id, store_id)
    msg = {"role": role, "content": content, "ts": _now()}
    conv["messages"].append(msg)
    conv["last_activity"] = _now()
    if role == "admin":
        # Queue for widget polling
        conv["pending_for_widget"].append({"content": content, "ts": msg["ts"]})
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
    """
    conv = _conversations.get(session_id, {})
    # per-session override (human takeover)
    if not conv.get("bot_enabled", True):
        return False
    # per-store toggle
    store_id = conv.get("store_id", "default")
    if not _store_bot_enabled.get(store_id, True):
        return False
    # global toggle (legacy)
    return _bot_globally_enabled


def set_session_bot(session_id: str, enabled: bool):
    get_or_create(session_id)["bot_enabled"] = enabled


def get_bot_globally() -> bool:
    return _bot_globally_enabled


def set_bot_globally(enabled: bool):
    global _bot_globally_enabled
    _bot_globally_enabled = enabled


# ── Per-store bot toggle ───────────────────────────────────────────────────────

def get_store_bot(store_id: str) -> bool:
    """Return per-store bot enabled state (defaults to True)."""
    return _store_bot_enabled.get(store_id, True)


def set_store_bot(store_id: str, enabled: bool):
    """Enable/disable bot for a specific store only."""
    _store_bot_enabled[store_id] = enabled


# ─────────────────────────────────────────────────────────────────────────────
# Admin read tracking
# ─────────────────────────────────────────────────────────────────────────────

def mark_admin_read(session_id: str):
    conv = _conversations.get(session_id)
    if conv:
        conv["last_admin_read"] = _now()


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

def all_conversations() -> dict:
    return _conversations


def summary_list(store_id: str = None) -> list:
    """Conversation summaries for admin panel list view. Filter by store_id if provided."""
    result = []
    for sid, conv in _conversations.items():
        if store_id and conv.get("store_id", "default") != store_id:
            continue
        msgs = conv["messages"]
        last = msgs[-1] if msgs else None
        user_count = sum(1 for m in msgs if m["role"] == "user")
        unread = has_unread_user_messages(sid)
        result.append({
            "session_id": sid,
            "messages_count": len(msgs),
            "user_messages_count": user_count,
            "last_message": last,
            "bot_enabled": conv["bot_enabled"],
            "last_activity": conv["last_activity"],
            "created_at": conv["created_at"],
            "unread": unread,
        })
    result.sort(key=lambda x: x["last_activity"], reverse=True)
    return result
