import os
import httpx
from typing import Optional


class SallaClient:
    BASE_URL = "https://api.salla.dev/admin/v2"

    def __init__(self, access_token: str):
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.request(method, f"{self.BASE_URL}{path}", headers=self.headers, **kwargs)
            if r.status_code == 401:
                # Try to refresh token
                from salla_oauth import refresh_access_token
                new_token = await refresh_access_token()
                self.headers["Authorization"] = f"Bearer {new_token}"
                r = await client.request(method, f"{self.BASE_URL}{path}", headers=self.headers, **kwargs)
            r.raise_for_status()
            return r.json()

    async def get_products(self, keyword: Optional[str] = None, per_page: int = 20) -> dict:
        params: dict = {"per_page": per_page}
        if keyword:
            params["keyword"] = keyword
        return await self._request("GET", "/products", params=params)

    async def get_product(self, product_id: str) -> dict:
        return await self._request("GET", f"/products/{product_id}")

    async def get_order(self, order_id: str) -> dict:
        return await self._request("GET", f"/orders/{order_id}")

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

        items:  [{"id": product_id, "quantity": qty}]
        customer_info: {"name": "...", "phone": "...", "email": "..."}
        """
        payload: dict = {"items": [{"id": str(i["product_id"]), "quantity": i["quantity"]} for i in items]}
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

    async def get_customer_by_phone(self, phone: str) -> dict:
        return await self._request("GET", "/customers", params={"keyword": phone})
