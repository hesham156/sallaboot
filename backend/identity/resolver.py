"""
OwnedResourceResolver — the structural BOLA killer.

Customer-scoped AI tools do NOT receive the store's raw Salla client. They
receive a resolver bound to a verified ``SessionIdentity``. The ownership
comparison lives here, exactly once. A tool literally has no API to fetch
another customer's record, so the BOLA class cannot be reintroduced by a future
tool: anything that needs customer data must come through these methods and
inherit the check.

Ownership is satisfied when the record's owner matches the session's
``verified_customer_id`` (token / native verifier) OR the session's
``verified_phone`` (Meta-authenticated channel sender). Both are trusted —
neither is a request-body claim.
"""
from __future__ import annotations

from .guards import require_verified_customer
from .models import SessionIdentity


def order_owner_id(record: dict) -> str:
    """Owner customer id of an order/cart, robust to Salla's two shapes."""
    if not isinstance(record, dict):
        return ""
    cust = record.get("customer")
    if isinstance(cust, dict) and cust.get("id") is not None:
        return str(cust.get("id")).strip()
    if record.get("customer_id") is not None:
        return str(record.get("customer_id")).strip()
    return ""


def _record_phone(record: dict) -> str:
    cust = record.get("customer") if isinstance(record, dict) else None
    if isinstance(cust, dict):
        return str(cust.get("mobile") or cust.get("phone") or "")
    return ""


def _digits(s) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _phone_match(a: str, b: str) -> bool:
    """Conservative phone equivalence: compare the last 9 significant digits so a
    country-code prefix difference (9665… vs 05…) still matches the same line,
    without matching unrelated numbers."""
    da, db = _digits(a), _digits(b)
    if not da or not db:
        return False
    return da == db or da[-9:] == db[-9:]


class OwnedResourceResolver:
    """Identity-bound facade over the store's Salla client. Construct only for a
    verified session (anonymous → require_verified_customer raises upstream)."""

    def __init__(self, salla_client, identity: SessionIdentity):
        self._salla = salla_client
        self._identity = identity

    # ── ownership predicate ──────────────────────────────────────────────────
    def _owns(self, record: dict) -> bool:
        cid = (self._identity.verified_customer_id or "").strip()
        if cid and order_owner_id(record) == cid:
            return True
        ph = (self._identity.verified_phone or "").strip()
        if ph and _phone_match(ph, _record_phone(record)):
            return True
        return False

    # ── orders ───────────────────────────────────────────────────────────────
    async def get_order(self, locator: str) -> dict | None:
        """Resolve an order by id/reference and return it ONLY if owned. Never
        keyword/phone-searches (that would surface other customers' orders)."""
        require_verified_customer(self._identity)
        locator = (locator or "").strip()
        if not (locator and self._salla):
            return None
        order: dict = {}
        try:
            order = (await self._salla.get_order(locator)).get("data", {}) or {}
        except Exception:
            order = {}
        if not order:
            try:
                rows = (await self._salla.get_orders(reference_id=locator, per_page=5)).get("data", []) or []
                order = next((o for o in rows if self._owns(o)), {})
            except Exception:
                order = {}
        if not order:
            return None
        return order if self._owns(order) else None

    async def get_invoice(self, *, order_reference: str = "", invoice_id=None) -> dict | None:
        """Return the invoice for an OWNED order. An invoice_id alone is resolved
        back to its order to verify ownership before any disclosure."""
        require_verified_customer(self._identity)
        if not self._salla:
            return None

        # invoice_id alone → resolve its order and check ownership.
        if invoice_id and not order_reference:
            try:
                inv = (await self._salla.get_invoice(int(invoice_id))).get("data", {}) or {}
            except Exception:
                return None
            oid = inv.get("order_id")
            if oid and await self.get_order(str(oid)):
                return inv
            return None

        order = await self.get_order(order_reference)
        if not order:
            return None
        oid = order.get("id")
        if oid:
            try:
                inv_list = await self._salla.list_order_invoices(int(oid))
                data = inv_list.get("data", [])
                first = (data[0].get("id") if isinstance(data, list) and data
                         else data.get("id") if isinstance(data, dict) else None)
                if first:
                    return (await self._salla.get_invoice(int(first))).get("data", {}) or None
            except Exception:
                pass
        raw_inv = order.get("invoice") or order.get("invoices")
        try:
            if isinstance(raw_inv, dict) and raw_inv.get("id"):
                return (await self._salla.get_invoice(int(raw_inv["id"]))).get("data", {}) or None
            if isinstance(raw_inv, list) and raw_inv:
                return (await self._salla.get_invoice(int(raw_inv[0]["id"]))).get("data", {}) or None
        except Exception:
            pass
        return None

    # ── abandoned carts ────────────────────────────────────────────────────────
    async def get_my_abandoned_carts(self, *, limit: int = 10) -> list[dict]:
        """Only the verified customer's own abandoned carts — never the store's."""
        require_verified_customer(self._identity)
        if not self._salla:
            return []
        try:
            carts = (await self._salla.get_abandoned_carts(per_page=limit)).get("data", []) or []
        except Exception:
            return []
        return [c for c in carts if self._owns(c)]

    # ── profile ────────────────────────────────────────────────────────────────
    async def get_my_profile(self, *, include_stats: bool = False) -> dict | None:
        """The verified customer's OWN Salla record. No arbitrary lookup."""
        require_verified_customer(self._identity)
        if not self._salla:
            return None
        fields = ["orders_count", "orders_amount", "wallet_balance"] if include_stats else None
        cid = (self._identity.verified_customer_id or "").strip()
        if cid:
            try:
                return (await self._salla.get_customer(int(cid), fields=fields)).get("data", {}) or None
            except Exception:
                return None
        # Phone-verified channel session with no resolved id → match by phone.
        ph = (self._identity.verified_phone or "").strip()
        if ph:
            try:
                found = (await self._salla.get_customer_by_phone(ph)).get("data", [])
                rec = found[0] if isinstance(found, list) and found else (found if isinstance(found, dict) else {})
                if rec.get("id") and include_stats:
                    rec = (await self._salla.get_customer(int(rec["id"]), fields=fields)).get("data", rec)
                return rec or None
            except Exception:
                return None
        return None
