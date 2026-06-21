"""
IdentityService — issue, resolve, and upgrade signed customer sessions.

This is the dependency-injected authority the chat endpoint and the agent use.
It is the ONLY place tokens are minted or read and the ONLY place a session is
upgraded to verified_customer.

Resolution order for a session's identity:

1. Channel sessions (``wa:`` / ``msgr:`` / ``ig:``) — the inbound Meta webhook
   already authenticated the sender, so these are verified *for free*. WhatsApp
   carries a phone we can match against Salla records; Messenger/Instagram have
   no Salla-resolvable identity, so they stay anonymous for *data reads* (they
   can still chat/shop and may OTP-verify).
2. A presented signed session token (widget) — verified + unexpired + bound to
   this store/session.
3. Otherwise anonymous (a ``customer_id`` hint in the body is a Claim, never a
   verification).
"""
from __future__ import annotations

import time

from . import tokens as _tokens
from .models import IdentityLevel, LifecycleState, SessionIdentity

# Channel sessions are platform-authenticated at the webhook boundary.
_WHATSAPP_PREFIX = "wa:"
_VERIFIED_CHANNEL_PREFIXES = ("wa:",)
# Messenger / Instagram / Telegram authenticate the sender at the webhook but
# carry no Salla-resolvable identity → anonymous for data reads (they can still
# chat/shop and may OTP-verify). Only WhatsApp carries a matchable phone.
_ALL_CHANNEL_PREFIXES = ("wa:", "msgr:", "ig:", "tg:")


def _now() -> int:
    return int(time.time())


class IdentityService:
    # ── issue ────────────────────────────────────────────────────────────────
    def issue_anonymous(self, store_id: str, session_id: str,
                        *, claimed: bool = False) -> str:
        identity = SessionIdentity.anonymous_for(
            session_id, store_id,
            expires_at=_now() + _tokens.ANON_TTL_SECONDS,
            claimed=claimed,
        )
        return _tokens.sign(identity)

    # ── resolve ──────────────────────────────────────────────────────────────
    def resolve(self, store_id: str, session_id: str,
                *, token: str | None = None) -> SessionIdentity:
        """The single entry point handlers/agent use to learn who a session is.

        Never raises: an invalid/expired token or unknown session resolves to an
        anonymous identity (fail closed for authority, open for availability)."""
        store_id = store_id or "default"
        session_id = session_id or ""

        # 1. Channel sessions — verified by the Meta-signed webhook.
        channel = self._channel_identity(store_id, session_id)
        if channel is not None:
            return channel

        # 2. Presented signed session token (widget).
        if token:
            ident = _tokens.verify(token, expected_store_id=store_id,
                                   expected_session_id=session_id)
            if ident is not None and ident.lifecycle_state != LifecycleState.expired:
                return ident
            # expired/invalid → fall through to anonymous

        # 3. Anonymous.
        return SessionIdentity.anonymous_for(session_id, store_id)

    def _channel_identity(self, store_id: str, session_id: str) -> SessionIdentity | None:
        sid = (session_id or "").strip()
        low = sid.lower()
        if not any(low.startswith(p) for p in _ALL_CHANNEL_PREFIXES):
            return None
        # WhatsApp → phone-verified; the phone is the authenticated sender.
        if low.startswith(_WHATSAPP_PREFIX):
            phone = sid[len(_WHATSAPP_PREFIX):].strip()
            return SessionIdentity(
                session_id=sid, store_id=store_id,
                identity_level=IdentityLevel.verified_customer,
                lifecycle_state=LifecycleState.verified,
                verified_phone=phone or None,
                verification_method="meta_webhook",
                verified_at=_now(),
            )
        # Messenger / Instagram: sender authenticated, but no Salla-resolvable
        # identity → anonymous for data reads (chat/shop still work; OTP can
        # upgrade if the store needs it).
        return SessionIdentity.anonymous_for(sid, store_id)

    # ── upgrade (verifiers only) ───────────────────────────────────────────────
    def upgrade_to_verified(
        self,
        identity: SessionIdentity,
        *,
        customer_id: str | None = None,
        phone: str | None = None,
        method: str,
    ) -> tuple[SessionIdentity, str]:
        """Promote a session to verified_customer and mint a fresh token.

        Called ONLY by verifiers (OTP / Shopify App Proxy / platform token).
        Returns (new_identity, new_token). Channel sessions don't need a token
        (their authority is re-derived from the session id each turn)."""
        now = _now()
        verified = identity.with_verified_customer(
            customer_id=customer_id,
            phone=phone,
            method=method,
            verified_at=now,
            expires_at=now + _tokens.VERIFIED_TTL_SECONDS,
        )
        return verified, _tokens.sign(verified)


# Module-level singleton for convenient DI.
identity_service = IdentityService()
