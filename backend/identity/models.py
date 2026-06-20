"""
Identity value model — the only types the rest of the code reads identity from.

Two orthogonal axes, both required by the design:

* ``IdentityLevel``  — the *authorization* axis (anonymous < verified_customer
  < employee < owner). Ordered so the single authorization rule can express
  ``identity_level >= verified_customer``. The names are descriptive (not
  Tier0/Tier1) so future levels slot in without renaming call sites.

* ``LifecycleState`` — the *operational* axis the session moves through
  (anonymous → claimed → verified → expired → revoked). A session is always in
  exactly one lifecycle state; it is derived deterministically from the signed
  token + clock and never set by a request field.

``SessionIdentity`` is a frozen value object: once resolved it cannot be mutated,
so a tool can't "promote itself" by writing to it.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


class IdentityLevel(enum.IntEnum):
    anonymous = 0
    verified_customer = 1
    employee = 2
    owner = 3

    @classmethod
    def parse(cls, value) -> "IdentityLevel":
        """Tolerant parse from a token claim (name string or int). Unknown →
        anonymous (fail closed)."""
        if isinstance(value, IdentityLevel):
            return value
        if isinstance(value, int):
            try:
                return cls(value)
            except ValueError:
                return cls.anonymous
        try:
            return cls[str(value)]
        except (KeyError, ValueError):
            return cls.anonymous


class LifecycleState(str, enum.Enum):
    anonymous = "anonymous"
    claimed = "claimed"
    verified = "verified"
    expired = "expired"
    revoked = "revoked"


@dataclass(frozen=True)
class SessionIdentity:
    """Immutable, backend-trusted identity for one chat session.

    ``verified_customer_id`` / ``verified_phone`` are populated ONLY by a
    verifier (never from a request body). For a channel session the phone is the
    Meta-authenticated sender; for a token/native verification it's the platform
    customer id.
    """
    session_id: str
    store_id: str
    identity_level: IdentityLevel = IdentityLevel.anonymous
    lifecycle_state: LifecycleState = LifecycleState.anonymous
    verified_customer_id: str | None = None
    verified_phone: str | None = None
    verification_method: str | None = None
    verified_at: int | None = None
    expires_at: int | None = None

    # ── Derived predicates (read-only) ──────────────────────────────────────
    @property
    def is_verified_customer(self) -> bool:
        return self.identity_level >= IdentityLevel.verified_customer

    @property
    def is_anonymous(self) -> bool:
        return self.identity_level == IdentityLevel.anonymous

    def with_verified_customer(
        self,
        *,
        customer_id: str | None,
        phone: str | None,
        method: str,
        verified_at: int,
        expires_at: int,
    ) -> "SessionIdentity":
        """Return a NEW verified identity (frozen → copy, never mutate)."""
        from dataclasses import replace
        return replace(
            self,
            identity_level=IdentityLevel.verified_customer,
            lifecycle_state=LifecycleState.verified,
            verified_customer_id=(str(customer_id).strip() if customer_id else None),
            verified_phone=(str(phone).strip() if phone else None),
            verification_method=method,
            verified_at=verified_at,
            expires_at=expires_at,
        )

    @classmethod
    def anonymous_for(cls, session_id: str, store_id: str,
                      *, expires_at: int | None = None,
                      claimed: bool = False) -> "SessionIdentity":
        return cls(
            session_id=session_id,
            store_id=store_id,
            identity_level=IdentityLevel.anonymous,
            lifecycle_state=(LifecycleState.claimed if claimed else LifecycleState.anonymous),
            expires_at=expires_at,
        )
