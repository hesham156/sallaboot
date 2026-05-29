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

# ── Global bot toggle ──────────────────────────────────────────────────────────
_bot_globally_enabled: bool = True

# ── Conversations dict: session_id → conv dict ─────────────────────────────────
_conversations: dict[str, dict] = {}


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Conversation CRUD
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create(session_id: str) -> dict:
    if session_id not in _conversations:
        _conversations[session_id] = {
            "session_id": session_id,
            "messages": [],            # full history (all roles)
            "bot_enabled": True,       # per-session flag
            "created_at": _now(),
            "last_activity": _now(),
            "pending_for_widget": [],  # admin msgs not yet polled by widget
            "last_admin_read": "",     # ISO ts — used for unread badge
        }
    return _conversations[session_id]


def add_message(session_id: str, role: str, content: str) -> dict:
    """
    Append a message to the conversation.
    role: 'user' | 'assistant' | 'admin'
    """
    conv = get_or_create(session_id)
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
    """Check if bot should respond for this session."""
    if not _bot_globally_enabled:
        return False
    return _conversations.get(session_id, {}).get("bot_enabled", True)


def set_session_bot(session_id: str, enabled: bool):
    get_or_create(session_id)["bot_enabled"] = enabled


def get_bot_globally() -> bool:
    return _bot_globally_enabled


def set_bot_globally(enabled: bool):
    global _bot_globally_enabled
    _bot_globally_enabled = enabled


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


def summary_list() -> list:
    """Conversation summaries for admin panel list view."""
    result = []
    for sid, conv in _conversations.items():
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
