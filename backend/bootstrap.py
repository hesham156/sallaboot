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
    Register the marketing/demo store if it doesn't exist, and seed its
    custom_knowledge from the markdown file ONLY on first install.

    The UI is the source of truth — once the admin edits the knowledge
    from the Brain dashboard, those edits stick across deploys. To force
    a reload from the file (e.g. after editing the .md), call
    reload_knowledge_from_file() — exposed as a super-only endpoint.

    Setting SALLABOT_FORCE_RELOAD_KNOWLEDGE=true in the env also forces a
    reload at boot, useful for one-off deploys where the file content
    changed and you want it picked up without a manual API call.
    """
    knowledge = _read_knowledge()
    is_new    = not sm.is_registered(SALLABOT_STORE_ID)

    if is_new:
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

    # Seed only when there's nothing to overwrite (first install, or admin
    # explicitly cleared the knowledge). The opt-in env override exists
    # for the deploy-then-force-reload workflow.
    force = os.getenv("SALLABOT_FORCE_RELOAD_KNOWLEDGE", "").lower() == "true"
    existing = brain._get_custom_knowledge(SALLABOT_STORE_ID).strip()
    if knowledge and (not existing or force):
        brain.set_custom_knowledge(SALLABOT_STORE_ID, knowledge)
        why = "first install" if not existing else "FORCE env override"
        print(f"[bootstrap] 📚 seeded {len(knowledge)} chars of marketing knowledge ({why})")
    elif existing:
        print(f"[bootstrap] 📚 preserved existing knowledge ({len(existing)} chars) — "
              "UI edits stick. Set SALLABOT_FORCE_RELOAD_KNOWLEDGE=true to override.")


def reload_knowledge_from_file() -> dict:
    """
    Force a fresh read of the markdown file and overwrite custom_knowledge.
    Called by the super-admin /admin/sallabot/reload-knowledge endpoint —
    the explicit "reset to defaults" path so the no-overwrite startup
    behaviour above doesn't trap the admin if they want the file back.
    """
    if not sm.is_registered(SALLABOT_STORE_ID):
        return {"ok": False, "error": "sallabot store not registered yet"}
    knowledge = _read_knowledge()
    if not knowledge:
        return {"ok": False, "error": "knowledge file is empty or missing"}
    brain.set_custom_knowledge(SALLABOT_STORE_ID, knowledge)
    return {"ok": True, "loaded_chars": len(knowledge), "file": str(_KNOWLEDGE_FILE)}


# Reserved store_ids that real Salla merchants must never claim — exposed
# so the webhook handler (routers/webhooks.py) can keep its own set in sync.
RESERVED_FOR_DEMO = {SALLABOT_STORE_ID}
