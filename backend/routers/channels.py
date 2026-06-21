"""
Channels router — connect/disconnect messaging channels the AI auto-replies on.

A "channel" is a conversational surface (Telegram, Messenger, Instagram, …) as
opposed to a commerce/payment "integration" (Salla, Shopify, Zid). Each channel
feeds the SAME channel-agnostic agent (agent.chat); see telegram.py / whatsapp.py
/ messenger.py for the per-channel pipes.

Currently wired end-to-end:
  • Telegram — connect via Bot API token (BotFather): we validate the token,
    register the webhook at /telegram/webhook/{store_id}, and store the send
    credential + a per-store webhook secret in ai_config.

Other channels (TikTok, Instagram/Messenger UI, X, Snapchat, Discord) are
surfaced by the dashboard as "coming soon" and are not handled here yet.
"""
from __future__ import annotations

import os
import re
import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import database as db
import store_manager as sm
import telegram as tg
from routers.deps import require_store_owner

router = APIRouter()

# Same BASE_URL contract as routers.integrations — the webhook URL we register
# with Telegram must exactly match a publicly reachable address (no trailing
# slash so we don't end up with a double slash in the path).
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

# A BotFather token is "<bot_id>:<auth_part>" — digits, a colon, then a run of
# url-safe characters. Anchored so a pasted URL/garbage is rejected before we
# ever call Telegram.
_TG_TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")


class TelegramConnectRequest(BaseModel):
    bot_token: str = Field(min_length=10, max_length=200)


class ChannelToggleRequest(BaseModel):
    enabled: bool


def _channels_status(cfg: dict) -> dict:
    """Build the (token-free) per-channel status the dashboard renders."""
    tg_token = (cfg.get("telegram_bot_token") or "").strip()
    page_tok = (cfg.get("page_token") or "").strip()
    return {
        "telegram": {
            "connected":    bool(tg_token),
            "enabled":      bool(cfg.get("telegram_enabled")),
            "bot_username": cfg.get("telegram_bot_username", ""),
        },
        "messenger": {
            "connected": bool(page_tok and cfg.get("messenger_enabled")),
            "enabled":   bool(cfg.get("messenger_enabled")),
        },
        "instagram": {
            "connected": bool(page_tok and cfg.get("instagram_enabled")),
            "enabled":   bool(cfg.get("instagram_enabled")),
        },
    }


@router.get("/admin/{store_id}/channels")
async def list_channels(store_id: str, request: Request):
    require_store_owner(request, store_id)
    cfg = sm.get_ai_config(store_id) or {}
    return {"channels": _channels_status(cfg)}


@router.post("/admin/{store_id}/channels/telegram/connect")
async def telegram_connect(store_id: str, req: TelegramConnectRequest, request: Request):
    require_store_owner(request, store_id)

    token = req.bot_token.strip()
    if not _TG_TOKEN_RE.match(token):
        raise HTTPException(400, "صيغة توكن بوت تيليجرام غير صحيحة (انسخه كاملاً من BotFather)")

    # Confirm the token is live and learn the bot's identity before we save it.
    me = await tg.get_me(token)
    if not me:
        raise HTTPException(400, "تعذّر التحقق من التوكن مع تيليجرام — تأكد أن البوت فعّال والتوكن صحيح")

    # Per-store webhook secret: Telegram echoes it in the
    # X-Telegram-Bot-Api-Secret-Token header so the receiver can prove an inbound
    # call really came from Telegram for THIS store.
    secret      = secrets.token_urlsafe(24)
    webhook_url = f"{BASE_URL}/telegram/webhook/{store_id}"
    ok, detail  = await tg.set_webhook(token, webhook_url, secret)
    if not ok:
        raise HTTPException(502, f"فشل ضبط الويبهوك مع تيليجرام: {detail}")

    existing = sm.get_ai_config(store_id)
    config = {
        **existing,
        "telegram_enabled":      True,
        "telegram_bot_token":    token,
        "telegram_bot_id":       tg.bot_id_from_token(token),
        "telegram_bot_username": me.get("username", ""),
        "telegram_secret":       secret,
    }
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)
    print(f"[channels] ✅ Telegram connected: store={store_id!r} bot=@{me.get('username','')}")

    return {
        "connected":    True,
        "bot_username": me.get("username", ""),
        "message":      "تم ربط بوت تيليجرام بنجاح",
    }


@router.post("/admin/{store_id}/channels/telegram/toggle")
async def telegram_toggle(store_id: str, req: ChannelToggleRequest, request: Request):
    """Pause / resume auto-replies without disconnecting (webhook stays set)."""
    require_store_owner(request, store_id)
    existing = sm.get_ai_config(store_id)
    if not (existing.get("telegram_bot_token") or "").strip():
        raise HTTPException(400, "لا يوجد بوت تيليجرام مربوط")
    config = {**existing, "telegram_enabled": bool(req.enabled)}
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)
    return {"enabled": bool(req.enabled)}


@router.delete("/admin/{store_id}/channels/telegram")
async def telegram_disconnect(store_id: str, request: Request):
    require_store_owner(request, store_id)
    existing = sm.get_ai_config(store_id)
    token = (existing.get("telegram_bot_token") or "").strip()

    # Best-effort: stop Telegram from delivering further updates.
    if token:
        await tg.delete_webhook(token)

    config = {
        **existing,
        "telegram_enabled":      False,
        "telegram_bot_token":    "",
        "telegram_bot_id":       "",
        "telegram_bot_username": "",
        "telegram_secret":       "",
    }
    await sm.set_ai_config(store_id, config)
    await db.save_ai_config(store_id, config)
    print(f"[channels] 🗑️ Telegram disconnected: store={store_id!r}")
    return {"message": "تم قطع الاتصال مع تيليجرام"}
