import os
import asyncio
import random
import httpx
from typing import Optional

# Transient HTTP statuses worth retrying (rate-limit + server errors).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3

# Process-wide caches for Salla geo metadata (countries/cities). These IDs are
# global — identical for every store — so we resolve them once and reuse.
_COUNTRY_CACHE: dict = {}              # normalized name/code -> {"id", "name"}
_CITY_CACHE: dict = {}                 # country_id -> {normalized_city_name: id}
_CITY_PAGES_SCANNED: dict = {}         # country_id -> highest page already cached
_MAX_CITY_PAGES = 8                    # bound the lazy city scan (≈120 cities)


def _norm_geo(s: str) -> str:
    """Normalise a country/city name for fuzzy matching (Arabic alef variants,
    tatweel, case, surrounding whitespace)."""
    s = (s or "").strip().lower()
    if not s:
        return ""
    for a in ("أ", "إ", "آ"):
        s = s.replace(a, "ا")
    s = s.replace("ـ", "").replace("ة", "ه")
    return s


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

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Exponential backoff (0.5,1,2,4…) capped at 6s, with ±25% jitter."""
        base = min(0.5 * (2 ** attempt), 6.0)
        return base * (0.75 + 0.5 * random.random())

    @staticmethod
    def _retry_after(r: httpx.Response) -> Optional[float]:
        """Honour a sane Retry-After header (seconds, ≤30) if Salla sends one."""
        ra = r.headers.get("retry-after")
        if not ra:
            return None
        try:
            v = float(ra)
            return v if 0 < v <= 30 else None
        except ValueError:
            return None

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """
        Issue a Salla API request with resilience:
          • 401  → refresh the token once and retry.
          • 429 / 5xx → retry with exponential backoff (honours Retry-After).
          • network/timeout errors → retry, but ONLY for idempotent GET (so a
            POST whose response was lost doesn't create a duplicate order).
        Non-retryable 4xx still raise with Salla's real error body so callers
        can log the actual reason (missing scope, validation, …).
        """
        url        = f"{self.BASE_URL}{path}"
        idempotent = method.upper() == "GET"
        last_err: str = ""

        async with httpx.AsyncClient(timeout=20) as client:
            for attempt in range(_MAX_RETRIES + 1):
                # ── Send (retry transient network errors on GET only) ──────────
                try:
                    r = await client.request(method, url, headers=self.headers, **kwargs)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_err = f"network: {type(exc).__name__}: {exc}"
                    if idempotent and attempt < _MAX_RETRIES:
                        await asyncio.sleep(self._backoff(attempt))
                        continue
                    raise RuntimeError(f"Salla {method} {path} → {last_err}") from exc

                # ── 401 → refresh token once, then re-send this attempt ────────
                if r.status_code == 401:
                    from salla_oauth import refresh_access_token
                    try:
                        new_token = await refresh_access_token(self.store_id)
                        self.access_token = new_token
                        self._set_headers(new_token)
                        r = await client.request(method, url, headers=self.headers, **kwargs)
                    except Exception as exc:
                        raise RuntimeError(
                            f"Token refresh failed for store {self.store_id!r}: {exc}"
                        ) from exc

                # ── Transient rate-limit / server error → back off and retry ───
                if r.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                    delay = self._retry_after(r) or self._backoff(attempt)
                    last_err = f"HTTP {r.status_code}"
                    print(f"[salla] {method} {path} → {last_err}, retry "
                          f"{attempt + 1}/{_MAX_RETRIES} in {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue

                # ── Final outcome ─────────────────────────────────────────────
                if r.status_code >= 400:
                    raise RuntimeError(
                        f"Salla {method} {path} → HTTP {r.status_code}: {r.text[:600]}"
                    )
                return r.json()

        # Exhausted retries on a retryable status
        raise RuntimeError(f"Salla {method} {path} → failed after retries ({last_err})")

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

    async def add_order_note(self, order_id, note: str) -> dict:
        """
        Append a note to an order's history.
        POST /admin/v2/orders/{order_id}/histories  (scope: orders.read_write)
        Used to record custom-quote specs on the order (since POST /orders
        itself has no `notes` field).
        """
        return await self._request(
            "POST", f"/orders/{order_id}/histories", json={"note": note[:1000]},
        )

    async def create_order(
        self,
        items: list,
        customer_info: dict = None,
        notes: str = "",
        accepted_methods: Optional[list] = None,
    ) -> dict:
        """
        Create an order and return the customer-facing payment URL.

        items:  [{"product_id": ..., "quantity": ..., "options": [...]?}]
        customer_info: {
            "name": "...", "phone": "...", "email": "...",
            "salla_customer_id": int   # optional — if present, used directly
        }

        IMPORTANT (verified against the Salla Platform Docs OAS):
        - POST /orders expects a `products` array of
          {identifier_type, identifier, quantity} — NOT `items`.
        - `payment` is REQUIRED with `payment.status` ∈ {paid, pending_payment}.
          We use "pending_payment" + accepted_methods so the customer gets a
          payment link (urls.customer) and pays themselves.
        - customer.mobile must be E.164 (+966…).
        - delivery_method is only required for products that need shipping;
          custom-quote products are `service` type so we omit it.
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

        # Required payment block — pending_payment yields a payable order
        payload["payment"] = {
            "status":           "pending_payment",
            "accepted_methods": accepted_methods or ["mada", "credit_card", "bank", "cod"],
        }

        # NOTE: POST /orders has NO `notes` field in Salla's schema — sending it
        # 422s ("notes" validation). Order specs live in the product
        # name/description instead; a note can be added post-creation via
        # POST /orders/{id}/histories if needed. `notes` kept in the signature
        # for backward compat but intentionally NOT sent.
        _ = notes  # unused on purpose
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
        # Send ONLY `original` (the URL):
        #   • `main` over multipart arrives as "true" → rejected.
        #   • `alt` with long/Arabic values triggers a 422 on some stores.
        # The first attached image becomes main automatically.
        return await self._request(
            "POST", f"/products/{product_id}/images",
            files={"original": (None, image_url)},
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

    # ── Coupons ─────────────────────────────────────────────────────────────────

    async def create_coupon(
        self,
        code: str,
        amount: float,
        *,
        coupon_type: str = "percentage",       # "percentage" | "fixed"
        expiry_date: str = "",                  # "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
        maximum_amount: Optional[float] = None,  # cap on the discount value
        minimum_amount: Optional[float] = None,  # minimum order subtotal to qualify
        usage_limit: int = 1,
        usage_limit_per_user: int = 1,
        free_shipping: bool = False,
        exclude_sale_products: bool = True,
        status: str = "active",
    ) -> dict:
        """
        Create a SINGLE store coupon.
        POST /admin/v2/coupons  (scope: coupons.read_write)

        Verified against the Salla Platform Docs OAS
        (#/components/schemas/post_coupon_request_body):
          • Required for a single coupon: code, type, amount, free_shipping,
            expiry_date, exclude_sale_products.
          • `is_group` defaults to TRUE in Salla's schema — we MUST send
            `false` explicitly or Salla creates a *group* coupon instead.
          • `expiry_date` MUST be at least one day later than today.
          • `maximum_amount` is required when type is percentage (it caps the
            SAR value of the discount — our main guard against runaway
            discounts from an AI-issued coupon).
          • `type` accepts "percentage"/"fixed" (and single-letter aliases).
        """
        is_percentage = str(coupon_type).lower().startswith("p")
        payload: dict = {
            "code":                  code,
            "type":                  "percentage" if is_percentage else "fixed",
            "amount":                round(float(amount), 2),
            "free_shipping":         bool(free_shipping),
            "expiry_date":           expiry_date,
            "exclude_sale_products": bool(exclude_sale_products),
            "is_group":              False,   # ← critical: schema default is true
            "status":                status,
            "usage_limit":           int(usage_limit),
            "usage_limit_per_user":  int(usage_limit_per_user),
        }
        # maximum_amount is required for percentage; harmless to omit for fixed.
        if is_percentage and maximum_amount is not None:
            payload["maximum_amount"] = round(float(maximum_amount), 2)
        if minimum_amount:
            payload["minimum_amount"] = round(float(minimum_amount), 2)
        return await self._request("POST", "/coupons", json=payload)

    async def get_coupon_statistics(self, coupon_id) -> dict:
        """
        GET /admin/v2/coupons/statistics/{coupon} — usage + revenue stats for a
        coupon. Used by the dashboard to show the ROI of AI-issued coupons.
        Scope required: coupons.read
        """
        return await self._request("GET", f"/coupons/statistics/{coupon_id}")

    # ── Live inventory / variants ───────────────────────────────────────────────

    async def get_product_variants(self, product_id) -> dict:
        """
        GET /admin/v2/products/{product}/variants — live per-variant stock + price.
        Each item: {id, price{amount,currency}, stock_quantity, sku,
        related_option_values[], weight, weight_type}. Scope: products.read
        """
        return await self._request("GET", f"/products/{product_id}/variants")

    # ── Shipments / live tracking ───────────────────────────────────────────────

    async def get_shipments(self, order_id=None, per_page: int = 10) -> dict:
        """GET /admin/v2/shipments — optionally filtered by order_id. Scope: shipping.read"""
        params: dict = {"per_page": per_page}
        if order_id:
            params["order_id"] = order_id
        return await self._request("GET", "/shipments", params=params)

    async def get_shipment_tracking(self, shipment_id) -> dict:
        """
        GET /admin/v2/shipments/{id}/tracking — live status + history.
        Returns {status, courier_name, tracking_number, tracking_link,
        history[{status, note, create_at}]}. Scope: shipping.read
        """
        return await self._request("GET", f"/shipments/{shipment_id}/tracking")

    # ── Geo metadata + live shipping-rate estimate ──────────────────────────────

    async def list_countries(self, page: int = 1) -> dict:
        """GET /admin/v2/countries — paginated. Scope: metadata.read"""
        return await self._request("GET", "/countries", params={"page": page})

    async def list_cities(self, country_id, page: int = 1) -> dict:
        """GET /admin/v2/countries/{country}/cities — paginated. Scope: metadata.read"""
        return await self._request("GET", f"/countries/{country_id}/cities", params={"page": page})

    async def estimate_shipping_rates(self, city_id, country_id, order_id=None) -> dict:
        """
        GET /admin/v2/shipping/companies/estimate-rate — live carrier rates + ETA
        for a destination. Requires city_id + country_id (verified against the
        OAS: both are mandatory query params). Returns data[] of
        {title, total{amount,currency}, working_days, services[]}.
        """
        params: dict = {"city_id": city_id, "country_id": country_id}
        if order_id:
            params["order_id"] = order_id
        return await self._request("GET", "/shipping/companies/estimate-rate", params=params)

    # Geo metadata is GLOBAL (same IDs for every store), so resolution results are
    # cached process-wide. Cities have no search param and number in the hundreds
    # per country (≈900 for SA over ~61 pages) — but the major cities sit on the
    # first pages, so we lazily scan a bounded number of pages and cache as we go.
    async def resolve_country_id(self, country_name: str = "") -> Optional[int]:
        key = _norm_geo(country_name) or "sa"
        if key in _COUNTRY_CACHE:
            return _COUNTRY_CACHE[key]["id"]
        for page in range(1, 4):
            try:
                data = await self.list_countries(page=page)
            except Exception:
                break
            for c in data.get("data", []) or []:
                cid = c.get("id")
                for cand in (c.get("name"), c.get("name_en"), c.get("code")):
                    nc = _norm_geo(cand)
                    if nc:
                        _COUNTRY_CACHE[nc] = {"id": cid, "name": c.get("name")}
                if (c.get("code") or "").lower() == "sa":
                    _COUNTRY_CACHE["sa"] = {"id": cid, "name": c.get("name")}
            if key in _COUNTRY_CACHE:
                return _COUNTRY_CACHE[key]["id"]
            if not (data.get("pagination", {}).get("links") or {}).get("next"):
                break
        return _COUNTRY_CACHE.get("sa", {}).get("id")

    async def resolve_city_id(self, country_id, city_name: str) -> Optional[int]:
        target = _norm_geo(city_name)
        if not target or not country_id:
            return None
        cache = _CITY_CACHE.setdefault(country_id, {})
        if target in cache:
            return cache[target]
        page = _CITY_PAGES_SCANNED.get(country_id, 0) + 1
        while page <= _MAX_CITY_PAGES:
            try:
                data = await self.list_cities(country_id, page=page)
            except Exception:
                break
            rows = data.get("data", []) or []
            if not rows:
                break
            for ct in rows:
                cid = ct.get("id")
                for cand in (ct.get("name"), ct.get("name_en")):
                    nc = _norm_geo(cand)
                    if nc:
                        cache[nc] = cid
            _CITY_PAGES_SCANNED[country_id] = page
            if target in cache:
                return cache[target]
            if not (data.get("pagination", {}).get("links") or {}).get("next"):
                break
            page += 1
        # Loose fallback: substring match against whatever we've cached so far.
        for nc, cid in cache.items():
            if target in nc or nc in target:
                return cid
        return None

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

    # ── Invoice email ───────────────────────────────────────────────────────────

    async def send_order_invoice(self, order_id: int) -> dict:
        """
        Send the order invoice to the customer's email.
        POST /admin/v2/orders/{order_id}/send-invoice  (scope: orders.read_write)

        Requires the customer to have an email address on their Salla profile.
        Returns {"data": {"message": "تم ارسال رسالة الفاتورة بنجاح"}} on success.
        """
        return await self._request("POST", f"/orders/{order_id}/send-invoice")

    # ── Delivery promises ───────────────────────────────────────────────────────

    async def get_delivery_promises(self) -> dict:
        """
        GET /admin/v2/delivery-promises — delivery promise configs for the store.
        (scope: shipping.read)

        Returns data[] with: id, type (express/same_day/next_day/standard/international),
        status (bool), name, description, location{country, region, cities[]},
        delivery_time{from, to, type ("hours"|"days")}.
        """
        return await self._request("GET", "/delivery-promises")

    # ── Product reviews ─────────────────────────────────────────────────────────

    async def get_product_reviews(
        self,
        product_id=None,
        per_page: int = 10,
        stars: Optional[list] = None,
        review_type: str = "rating",
        publish: bool = True,
    ) -> dict:
        """
        GET /admin/v2/reviews — product ratings and store reviews.
        (scope: reviews.read)

        review_type: "rating" (product stars) | "ask" (customer questions) |
                     "shipping" (delivery rating) | "testimonial" (store review)
        stars: filter by star values e.g. ["4","5"] for ≥4 stars.
        publish: True → only published/approved reviews (default for bot display).
        """
        params: dict = {"per_page": per_page}
        if product_id:
            params["products[]"] = [str(product_id)]
        if stars:
            params["stars[]"] = [str(s) for s in stars]
        if review_type:
            params["type"] = review_type
        params["publish"] = "true" if publish else "false"
        return await self._request("GET", "/reviews", params=params)
