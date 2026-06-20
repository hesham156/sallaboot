"""
Authorization primitives — the ONLY place customer authorization is expressed.

Every customer-sensitive operation reduces to exactly one rule:

    identity_level >= verified_customer
        AND
    resource.owner_customer_id == session.verified_customer_id

``require_verified_customer`` enforces the first clause; ``authorize_resource``
the second. Both raise typed signals so callers (the agent) can translate them
into a verification prompt or a denial WITHOUT embedding authorization logic of
their own. No request parameter participates here.
"""
from __future__ import annotations

from .models import IdentityLevel, SessionIdentity


class VerificationRequired(Exception):
    """Raised when an operation needs a verified customer but the session isn't
    one yet. The agent turns this into an OTP / step-up prompt — it is NOT an
    error condition."""
    def __init__(self, message: str = "verification_required", *, phone_hint: str | None = None):
        super().__init__(message)
        self.phone_hint = phone_hint


class Forbidden(Exception):
    """Raised when a verified customer asks for a resource they don't own. The
    agent renders a neutral 'not found on your account' message — never an
    existence oracle."""


def require_verified_customer(identity: SessionIdentity) -> None:
    """First clause of the authorization rule. Raises VerificationRequired when
    the session has not reached verified_customer."""
    if identity is None or identity.identity_level < IdentityLevel.verified_customer:
        raise VerificationRequired(
            phone_hint=(identity.verified_phone if identity else None),
        )


def authorize_resource(identity: SessionIdentity, owner_customer_id) -> None:
    """Second clause: the resource's owner must equal the session's verified
    customer. Phone-verified channel sessions (no resolved customer id) are
    matched in the resolver instead, so this is only reached with an id present.
    """
    require_verified_customer(identity)
    owner = str(owner_customer_id or "").strip()
    mine = str(identity.verified_customer_id or "").strip()
    if not owner or not mine or owner != mine:
        raise Forbidden("resource_not_owned")
