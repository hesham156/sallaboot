import os
import httpx
from typing import Optional


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

            r.raise_for_status()
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
        Create a draft order and return the customer-facing payment URL.

        items:  [{"product_id": ..., "quantity": ...}]
        customer_info: {"name": "...", "phone": "...", "email": "..."}
        """
        payload: dict = {
            "items": [
                {"id": str(i["product_id"]), "quantity": i["quantity"]}
                for i in items
            ]
        }
        if notes:
            payload["notes"] = notes
        if customer_info:
            name_parts = (customer_info.get("name") or "").split()
            payload["customer"] = {
                "first_name": name_parts[0] if name_parts else "",
                "last_name":  " ".join(name_parts[1:]) if len(name_parts) > 1 else "",
                "mobile":     customer_info.get("phone", ""),
                "email":      customer_info.get("email", ""),
            }
        return await self._request("POST", "/orders", json=payload)

    # ── Customer endpoints ────────────────────────────────────────────────────

    async def get_customer_by_phone(self, phone: str) -> dict:
        return await self._request("GET", "/customers", params={"keyword": phone})

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
