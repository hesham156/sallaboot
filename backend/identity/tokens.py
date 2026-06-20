"""
Signed customer-session tokens — the cryptographic trust boundary.

Reuses the exact HMAC-SHA256 envelope the rest of the app already trusts
(``auth._sign_payload`` / ``auth._unsign_payload``, keyed by ADMIN_SECRET), so
there is ONE signing path and no new key material.

A customer-session token is namespaced (``typ="cust_sess"``, ``iss="7ayak-chat"``)
so it can never be mistaken for an admin token and an admin token can never be
read as a customer identity. Claims are intentionally short to keep the token
small; they mirror the design's session contract.
"""
from __future__ import annotations

import secrets
import time

import auth as _auth

from .models import IdentityLevel, LifecycleState, SessionIdentity

_TYP = "cust_sess"
_ISS = "7ayak-chat"

# Anonymous sessions live long (continuity) but carry NO authority. Verified
# sessions are short — re-verification is cheap and bounds the damage window.
ANON_TTL_SECONDS = 30 * 24 * 60 * 60      # 30 days
VERIFIED_TTL_SECONDS = 30 * 60            # 30 minutes


def _now() -> int:
    return int(time.time())


def sign(identity: SessionIdentity) -> str:
    """Serialise + HMAC-sign an identity into an opaque session token."""
    payload = {
        "typ": _TYP,
        "iss": _ISS,
        "sid": identity.session_id,
        "st":  identity.store_id,
        "il":  identity.identity_level.name,
        "ls":  identity.lifecycle_state.value,
        "exp": int(identity.expires_at or (_now() + ANON_TTL_SECONDS)),
        "n":   secrets.token_hex(4),
    }
    if identity.verified_customer_id:
        payload["cid"] = identity.verified_customer_id
    if identity.verified_phone:
        payload["ph"] = identity.verified_phone
    if identity.verification_method:
        payload["vm"] = identity.verification_method
    if identity.verified_at:
        payload["vat"] = int(identity.verified_at)
    return _auth._sign_payload(payload)


def verify(token: str, *, expected_store_id: str | None = None,
           expected_session_id: str | None = None) -> SessionIdentity | None:
    """Verify signature + expiry and rebuild a SessionIdentity, or None.

    An expired/invalid token is NOT an error — the caller simply treats the
    session as anonymous and may re-issue. Binding checks (store/session) make a
    token minted for one context unusable in another.
    """
    payload = _auth._unsign_payload(token)
    if not payload or payload.get("typ") != _TYP or payload.get("iss") != _ISS:
        return None

    session_id = str(payload.get("sid") or "")
    store_id   = str(payload.get("st") or "")
    if not session_id or not store_id:
        return None
    if expected_store_id is not None and store_id != expected_store_id:
        return None
    if expected_session_id is not None and session_id != expected_session_id:
        return None

    exp = int(payload.get("exp", 0))
    if exp < _now():
        # Expired → caller should treat as anonymous (lifecycle = expired).
        return SessionIdentity(
            session_id=session_id, store_id=store_id,
            identity_level=IdentityLevel.anonymous,
            lifecycle_state=LifecycleState.expired,
            expires_at=exp,
        )

    level = IdentityLevel.parse(payload.get("il"))
    # Defensive: a token claiming verified_customer MUST carry an identity.
    cid = payload.get("cid")
    ph  = payload.get("ph")
    if level >= IdentityLevel.verified_customer and not (cid or ph):
        level = IdentityLevel.anonymous

    return SessionIdentity(
        session_id=session_id,
        store_id=store_id,
        identity_level=level,
        lifecycle_state=LifecycleState(payload.get("ls", "anonymous"))
            if payload.get("ls") in {s.value for s in LifecycleState}
            else (LifecycleState.verified if level >= IdentityLevel.verified_customer
                  else LifecycleState.anonymous),
        verified_customer_id=(str(cid).strip() if cid else None),
        verified_phone=(str(ph).strip() if ph else None),
        verification_method=payload.get("vm"),
        verified_at=payload.get("vat"),
        expires_at=exp,
    )
