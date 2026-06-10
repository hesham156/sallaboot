"""
Self-demo store bootstrap — registers the special "sallabot" store_id
that powers the marketing chatbot embedded on the landing page.

The store has no Salla OAuth connection (it's not a real merchant). It
exists so the same chat infrastructure that serves real merchants can
also answer marketing questions about Sallabot itself: "what is it",
"how much does it cost", "how do I install it", etc.

Run from main.py startup. Idempotent: re-running just refreshes the
knowledge file content; existing tokens / passwords / agent state stay
intact.
"""
from __future__ import annotations

import os
from pathlib import Path

import store_brain as brain
import store_manager as sm

SALLABOT_STORE_ID = "sallabot"
SALLABOT_STORE_NAME = "سلّابوت"

_KNOWLEDGE_FILE = Path(__file__).parent / "data" / "sallabot_knowledge.md"


def _read_knowledge() -> str:
    """Load the markdown FAQ. Returns empty string if the file is missing —
    we still register the store so the widget renders, but the bot will be
    operating without any product-specific knowledge."""
    try:
        return _KNOWLEDGE_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        print(f"[bootstrap] ⚠️  knowledge file not found at {_KNOWLEDGE_FILE}")
        return ""
    except Exception as exc:
        print(f"[bootstrap] ⚠️  failed to read knowledge file: {exc}")
        return ""


def ensure_sallabot_store() -> None:
    """
    Register the marketing/demo store if it doesn't exist, and (always)
    sync the knowledge file content into its custom_knowledge.

    Why always sync the knowledge: deploying a new version of the
    knowledge file should take effect on the next boot without any
    manual admin action. The rest of the store state (password hash,
    AI config keys if any were customised) is preserved by
    register_store's existing merge logic.
    """
    knowledge = _read_knowledge()

    if not sm.is_registered(SALLABOT_STORE_ID):
        # No real access token — this is a no-Salla demo store. The agent
        # already guards every self.salla.* call behind `if not self.salla`,
        # so chat works fine using only custom_knowledge.
        sm.register_store(
            store_id      = SALLABOT_STORE_ID,
            access_token  = "",
            refresh_token = "",
            store_info    = {
                "name":   SALLABOT_STORE_NAME,
                "domain": os.getenv("BASE_URL", "").replace("https://", "").replace("http://", "") or "sallabot.com",
            },
        )
        print(f"[bootstrap] ✅ registered demo store {SALLABOT_STORE_ID!r}")

    # Always refresh the knowledge (covers code-deploy → new content)
    if knowledge:
        brain.set_custom_knowledge(SALLABOT_STORE_ID, knowledge)
        print(f"[bootstrap] 📚 loaded {len(knowledge)} chars of marketing knowledge")


# Reserved store_ids that real Salla merchants must never claim — exposed
# so the webhook handler (routers/webhooks.py) can keep its own set in sync.
RESERVED_FOR_DEMO = {SALLABOT_STORE_ID}
