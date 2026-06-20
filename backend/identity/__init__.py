"""
Trusted customer-identity package.

This package is the single authority for *who a chat visitor is* and *what they
are allowed to read*. It exists to eliminate an entire bug class: AI tools and
chat endpoints authorizing customer-scoped data against a client-supplied
``customer_id`` (which is a forgeable claim, not an identity).

Security Invariant (SI-1)
-------------------------
Client-controlled identity claims MUST NEVER be an authorization source. Every
authorization decision relies exclusively on a backend-issued, signed
``SessionIdentity`` whose ``verified_customer_id`` was established by a trusted
verifier (Meta-signed webhook, Shopify App Proxy HMAC, platform customer token,
or OTP step-up).

Public API
----------
- SessionIdentity, IdentityLevel, LifecycleState        — the value model
- IdentityService                                       — issue / resolve / upgrade signed sessions
- require_verified_customer, authorize_resource         — the only authorization primitives
- VerificationRequired, Forbidden                       — typed authorization signals
- OwnedResourceResolver                                 — identity-bound facade over the store client
- order_owner_id                                        — robust owner extraction (shared)

The rest of the codebase reads identity ONLY through these names. No tool may
read identity from a request field.
"""
from __future__ import annotations

from .models import IdentityLevel, LifecycleState, SessionIdentity
from .guards import (
    Forbidden,
    VerificationRequired,
    authorize_resource,
    require_verified_customer,
)
from .resolver import OwnedResourceResolver, order_owner_id
from .service import IdentityService, identity_service

__all__ = [
    "IdentityLevel",
    "LifecycleState",
    "SessionIdentity",
    "IdentityService",
    "identity_service",
    "require_verified_customer",
    "authorize_resource",
    "VerificationRequired",
    "Forbidden",
    "OwnedResourceResolver",
    "order_owner_id",
]
