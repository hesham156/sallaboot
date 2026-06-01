import os
import httpx
from typing import Optional


def normalize_mobile_e164(phone: str, default_dial: str = "966") -> str:
    """
    Normalise a phone number to E.164 ("+<country><number>") which Salla's
    order API requires (mobile must be >= 10 chars and start with '+').

    Handles common Saudi formats:
      0531549560        → +966531549560
      531549560         → +966531549560
      966531549560      → +966531549560
      00966531549560    → +966531549560
      +966531549560     → +966531549560 (unchanged)
    Non-Saudi numbers already carrying a country code are preserved.
    """
    raw = (phone or "").strip()
    if not raw:
        return ""
    had_plus = raw.startswith("+")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""

    if had_plus:
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith(default_dial):
        return "+" + digits
    if digits.startswith("0"):
        return "+" + default_dial + digits[1:]
    # Bare local number (e.g. 5XXXXXXXX)
    return "+" + default_dial + digits


class SallaClient:
    BASE_URL = "https://api.salla.dev/admin/v2"

    def __init__(self, access_token: str, store_id: str = "default"):
        self.store_id     = store_id
        self.access_token = access_token
        self._set_headers(access_token)

    def _set_headers(self, token: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept":        "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.request(
                method, f"{self.BASE_URL}{path}", headers=self.headers, **kwargs
            )

            if r.status_code == 401:
                # Token expired — refresh once and retry.
                # The asyncio lock inside refresh_access_token() ensures that
                # concurrent 401s for the same store only trigger one refresh call.
                from salla_oauth import refresh_access_token
                try:
                    new_token = await refresh_access_token(self.store_id)
                    self.access_token = new_token
                    self._set_headers(new_token)
                    r = await client.request(
                        method, f"{self.BASE_URL}{path}", headers=self.headers, **kwargs
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"Token refresh failed for store {self.store_id!r}: {exc}"
                    ) from exc

            # Raise with Salla's actual error body so callers can log the real
            # reason (missing scope, validation fields, etc.) instead of a bare
            # "HTTP 422". raise_for_status() alone hides the response body.
            if r.status_code >= 400:
                body_preview = r.text[:600]
                raise RuntimeError(
                    f"Salla {method} {path} → HTTP {r.status_code}: {body_preview}"
                )
            return r.json()

    # ── Product endpoints ─────────────────────────────────────────────────────

    async def get_products(self, keyword: Optional[str] = None, per_page: int = 20) -> dict:
        params: dict = {"per_page": per_page}
        if keyword:
            params["keyword"] = keyword
        return await self._request("GET", "/products", params=params)

    async def get_product(self, product_id: str) -> dict:
        return await self._request("GET", f"/products/{product_id}")

    # ── Order endpoints ───────────────────────────────────────────────────────

    async def get_order(self, order_id: str) -> dict:
        return await self._request("GET", f"/orders/{order_id}")

    async def get_orders(
        self,
        per_page: int = 20,
        reference_id: Optional[str] = None,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
    ) -> dict:
        """
        List orders with optional filters.
        keyword — searches customer name, phone, email, reference.
        """
        params: dict = {"per_page": per_page, "page": page}
        if reference_id:
            params["reference_id"] = reference_id
        if keyword:
            params["keyword"] = keyword
        if status:
            params["status"] = status
        return await self._request("GET", "/orders", params=params)

    async def search_orders_by_reference(self, reference: str) -> dict:
        return await self._request("GET", "/orders", params={"reference_id": reference})

    async def create_order(
        self,
        items: list,
        customer_info: dict = None,
        notes: str = "",
    ) -> dict:
        """
        Create an order and return the customer-facing payment URL.

        items:  [{"product_id": ..., "quantity": ..., "options": [...]?}]
        customer_info: {
            "name": "...", "phone": "...", "email": "...",
            "salla_customer_id": int   # optional — if present, used directly
        }

        IMPORTANT: Salla's POST /orders expects a `products` array where each
        item is {identifier_type, identifier, quantity} — NOT an `items`
        array with {id, quantity}. Using the wrong key silently produced
        orders with no line items / failed checkouts. (Verified against the
        Salla Platform Docs OAS example.)
        """
        products = []
        for i in items:
            entry = {
                "identifier_type": i.get("identifier_type", "id"),
                "identifier":      int(i["product_id"]) if str(i["product_id"]).isdigit() else i["product_id"],
                "quantity":        i.get("quantity", 1),
            }
            if i.get("options"):
                entry["options"] = i["options"]
            products.append(entry)

        payload: dict = {"products": products}
        if notes:
            payload["notes"] = notes
        if customer_info:
            salla_cid = customer_info.get("salla_customer_id")
            if salla_cid:
                # Use existing Salla customer — API resolves name/phone/email
                payload["customer"] = {"id": int(salla_cid)}
            else:
                # Salla requires customer.mobile in E.164 (+966…). Sending a
                # raw local number ("0531549560") fails 422 validation.
                cust: dict = {
                    "name":   (customer_info.get("name") or "").strip() or "عميل",
                    "mobile": normalize_mobile_e164(customer_info.get("phone", "")),
                }
                email = (customer_info.get("email") or "").strip()
                if email:
                    cust["email"] = email
                payload["customer"] = cust
        return await self._request("POST", "/orders", json=payload)

    # ── Product creation (custom quotes) ───────────────────────────────────────

    async def create_product(
        self,
        name: str,
        price: float,
        *,
        product_type: str = "service",
        quantity: int = 0,
        unlimited_quantity: bool = True,
        description: str = "",
        status: str = "sale",
    ) -> dict:
        """
        Create a product in the store. Used to turn a custom printing quote
        into a real, orderable Salla product.

        POST /admin/v2/products  (scope: products.read_write)

        Defaults to a `service` type with unlimited quantity so a custom
        quote is immediately orderable — Salla normally forces status to
        'out' until a quantity is set and 'hidden' until an image is
        attached, so we pass quantity + unlimited_quantity to keep it
        sellable for checkout.
        """
        payload: dict = {
            "name":               name[:200],
            "price":              round(float(price), 2),
            "product_type":       product_type,
            "status":             status,
            "unlimited_quantity": unlimited_quantity,
        }
        if not unlimited_quantity:
            payload["quantity"] = max(1, int(quantity))
        if description:
            payload["description"] = description[:1000]
        return await self._request("POST", "/products", json=payload)

    async def attach_product_image_url(self, product_id, image_url: str, alt: str = "") -> dict:
        """
        Attach an image to a product BY URL (multipart form, `original` field).
        POST /admin/v2/products/{product}/images  (scope: products.read_write)

        Salla keeps a product `hidden` until it has at least one image, and a
        hidden product can't be ordered. So a custom-quote product needs an
        image attached before checkout. We pass a URL (the store logo or a
        placeholder) so no binary upload is needed.
        """
        # Force multipart/form-data even though all fields are text: httpx
        # encodes (None, value) tuples in `files=` as form fields, producing a
        # proper multipart body (which the endpoint requires).
        return await self._request(
            "POST", f"/products/{product_id}/images",
            files={
                "original": (None, image_url),
                "main":     (None, "true"),
                "alt":      (None, alt or "custom"),
            },
        )

    async def create_order_item(
        self,
        order_id: int,
        identifier: int,
        quantity: int = 1,
        identifier_type: str = "id",
        branch_id: Optional[int] = None,
        options: Optional[list] = None,
        name: Optional[str] = None,
        price: Optional[float] = None,
        cost_price: Optional[float] = None,
        weight: Optional[float] = None,
        weight_type: Optional[str] = None,
    ) -> dict:
        """
        Add a product item to an existing order using:
        POST /admin/v2/orders/items

        Docs: https://docs.salla.dev — Order Items → Create Order Item
        Scope required: orders.read_write

        Args:
            order_id        : The order ID to add the item to.
            identifier      : Product ID (or SKU if identifier_type='sku').
            quantity        : Number of units to add (default 1).
            identifier_type : 'id' (default) or 'sku'.
            branch_id       : Optional branch ID.
            options         : List of option dicts [{id, value:[...]}].
            name            : Optional custom product name override.
            price           : Optional unit price override.
            cost_price      : Optional cost price override.
            weight          : Optional weight value.
            weight_type     : Optional weight unit (e.g. 'g', 'kg').
        Returns:
            Full Salla API response dict with data[] list of created OrderItem objects.
        """
        payload: dict = {
            "order_id":       order_id,
            "identifier_type": identifier_type,
            "identifier":     identifier,
            "quantity":       quantity,
        }
        if branch_id is not None:
            payload["branch_id"] = branch_id
        if options:
            payload["options"] = options
        if name:
            payload["name"] = name
        if price is not None:
            payload["price"] = price
        if cost_price is not None:
            payload["cost_price"] = cost_price
        if weight is not None:
            payload["weight"] = weight
        if weight_type:
            payload["weight_type"] = weight_type

        return await self._request("POST", "/orders/items", json=payload)

    # ── Invoice endpoints ─────────────────────────────────────────────────────

    async def get_invoice(self, invoice_id: int) -> dict:
        """
        Fetch a specific invoice's full details.
        GET /admin/v2/orders/invoices/{invoice_id}

        Scope required: orders.read

        Returns InvoiceDetails object containing:
          id, invoice_number, uuid, order_id, type, date, qr_code,
          payment_method, subtotal, shipping_cost, cod_cost,
          discount, tax, total, items[]
        """
        return await self._request("GET", f"/orders/invoices/{invoice_id}")

    async def list_order_invoices(self, order_id: int) -> dict:
        """
        List invoices attached to a specific order.
        GET /admin/v2/orders/{order_id}/invoices

        Scope required: orders.read
        """
        return await self._request("GET", f"/orders/{order_id}/invoices")

    # ── Brands ─────────────────────────────────────────────────────────────────

    async def get_brands(self, per_page: int = 50, page: int = 1) -> dict:
        """GET /admin/v2/brands — list brands with logo & banner."""
        return await self._request("GET", "/brands", params={"per_page": per_page, "page": page})

    # ── Special Offers ─────────────────────────────────────────────────────────

    async def get_special_offers(self, per_page: int = 50) -> dict:
        """
        GET /admin/v2/specialoffers — promotional offers and discounts.
        The bot uses this to answer "ايش العروض الحالية؟".
        Scope required: offers.read
        """
        return await self._request("GET", "/specialoffers", params={"per_page": per_page})

    # ── Branches (physical stores / warehouses) ────────────────────────────────

    async def get_branches(self, per_page: int = 50) -> dict:
        """
        GET /admin/v2/branches — physical branches and pickup locations.
        Scope required: branches.read
        """
        return await self._request("GET", "/branches", params={"per_page": per_page})

    # ── Payment methods ────────────────────────────────────────────────────────

    async def get_payment_methods(self) -> dict:
        """
        GET /admin/v2/payment/methods — available payment methods.
        Scope required: payments.read
        """
        return await self._request("GET", "/payment/methods")

    # ── Shipping zones ─────────────────────────────────────────────────────────

    async def get_shipping_zones(self, per_page: int = 50) -> dict:
        """GET /admin/v2/shipping/zones — list of zones the store ships to."""
        return await self._request("GET", "/shipping/zones", params={"per_page": per_page})

    # ── Shipping companies ─────────────────────────────────────────────────────

    async def get_shipping_companies(self) -> dict:
        """
        GET /admin/v2/shipping/companies — list active shipping carriers
        linked to the store. Each item has:
          id, name, app_id, activation_type ('manual'|'api'), slug

        Scope required: shipping.read
        """
        return await self._request("GET", "/shipping/companies/")

    async def get_shipping_company(self, company_id) -> dict:
        """GET /admin/v2/shipping/companies/{id} — single carrier detail."""
        return await self._request("GET", f"/shipping/companies/{company_id}")

    # ── Store info ─────────────────────────────────────────────────────────────

    async def get_store_info(self) -> dict:
        """
        GET /admin/v2/store/info — full store profile:
          id, name, entity, email, avatar, plan, type, status, verified,
          currency, domain, description, licenses{tax/commercial/freelance},
          social{telegram, twitter, facebook, maroof, youtube, snapchat,
                 whatsapp, appstore_link, googleplay_link}

        Returned to the agent's brain so the bot can answer "ايش رقم
        الواتساب؟" / "اشمعنى دمتم شركة موثقة؟" / "وين المتجر؟" etc.
        """
        return await self._request("GET", "/store/info")

    # ── Customer endpoints ────────────────────────────────────────────────────

    async def get_customer(self, customer_id: int, fields: list[str] = None) -> dict:
        """
        Fetch a specific customer's full details.
        GET /admin/v2/customers/{customer_id}

        Scope required: customers.read

        Args:
            customer_id : Salla customer ID.
            fields      : Optional extra fields to include in the response.
                          Allowed: is_blocked, is_whitelisted, block_reason,
                          is_inactive, orders_count, orders_amount,
                          orders_average, orders_complete_ratio,
                          orders_cancel_ratio, orders_cancel, latest_purchase,
                          abandoned_carts_items, wallet_balance, total_points,
                          country_id, custom_fields, current_store_customer,
                          is_orders_rated, is_notifications_enabled
        Returns:
            Full Salla API response with Customer object.
        """
        params: dict = {}
        if fields:
            # Salla expects: ?fields[]=is_blocked&fields[]=orders_count …
            params["fields[]"] = fields
        return await self._request("GET", f"/customers/{customer_id}", params=params)

    async def get_customer_by_phone(self, phone: str) -> dict:
        """Search customers by phone number (keyword search)."""
        return await self._request("GET", "/customers", params={"keyword": phone})

    async def create_customer(
        self,
        first_name: str,
        last_name: str = "",
        mobile: str = "",
        mobile_code_country: str = "+966",
        email: str = "",
        gender: str = "",
        birthday: str = "",
    ) -> dict:
        """
        Create a new customer in the store's customer base.
        POST /admin/v2/customers  (scope: customers.read_write)

        Per the Salla docs: email and mobile are UNIQUE — creating a
        duplicate returns 422. Callers should look up by phone first and
        only create when not found.

        Args:
            mobile              : phone WITHOUT the country code (e.g. 555123456)
            mobile_code_country : dial code with '+' (e.g. "+966")
        """
        payload: dict = {"first_name": first_name[:25] or "عميل"}
        if last_name:
            payload["last_name"] = last_name[:25]
        if mobile:
            payload["mobile"] = mobile
            payload["mobile_code_country"] = mobile_code_country
        if email:
            payload["email"] = email
        if gender in ("male", "female"):
            payload["gender"] = gender
        if birthday:
            payload["birthday"] = birthday
        return await self._request("POST", "/customers", json=payload)

    # ── Abandoned Carts endpoints ──────────────────────────────────────────────

    async def get_abandoned_carts(
        self,
        per_page: int = 20,
        keyword: Optional[str] = None,
    ) -> dict:
        """
        List abandoned carts.
        Requires scope: carts.read
        Returns: {data: [{id, total, subtotal, checkout_url, age_in_minutes,
                           customer: {name, mobile, email}, items: [...]}]}
        """
        params: dict = {"per_page": per_page}
        if keyword:
            params["keyword"] = keyword
        return await self._request("GET", "/carts/abandoned", params=params)

    async def get_abandoned_cart(self, cart_id: str) -> dict:
        """Get a single abandoned cart with status (active / purchased)."""
        return await self._request("GET", f"/carts/abandoned/{cart_id}")
