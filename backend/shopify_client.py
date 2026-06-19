"""
Lightweight async Shopify Admin REST API client.

Auth: X-Shopify-Access-Token header (no token refresh — tokens don't expire).
Handles cursor-based pagination, basic rate-limiting, and retries on 429.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

_API_VERSION = "2024-01"


class ShopifyClient:
    def __init__(self, shop: str, access_token: str, store_id: str = ""):
        self.shop      = shop
        self.store_id  = store_id
        self._base     = f"https://{shop}/admin/api/{_API_VERSION}"
        self._headers  = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }

    # ── Low-level request ─────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=20) as client:
            for attempt in range(3):
                r = await client.get(url, headers=self._headers, params=params or {})
                if r.status_code == 429:
                    wait = float(r.headers.get("Retry-After", "2"))
                    await asyncio.sleep(min(wait, 10))
                    continue
                r.raise_for_status()
                return r.json()
        r.raise_for_status()
        return {}

    async def _get_with_link(self, path: str, params: dict | None = None) -> tuple[dict, str | None]:
        """Returns (body_json, next_page_info | None)."""
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=20) as client:
            for attempt in range(3):
                r = await client.get(url, headers=self._headers, params=params or {})
                if r.status_code == 429:
                    await asyncio.sleep(float(r.headers.get("Retry-After", "2")))
                    continue
                r.raise_for_status()
                # Extract next cursor from Link header
                next_pi = None
                for part in r.headers.get("Link", "").split(","):
                    if 'rel="next"' in part:
                        m = re.search(r'page_info=([^&>]+)', part)
                        if m:
                            next_pi = m.group(1)
                return r.json(), next_pi
        r.raise_for_status()
        return {}, None

    # ── Shop info ─────────────────────────────────────────────────────────────

    async def get_shop(self) -> dict:
        data = await self._get("/shop.json")
        return data.get("shop", {})

    # ── Products (full paginated fetch) ───────────────────────────────────────

    async def get_all_products(self) -> list[dict]:
        products: list[dict] = []
        since_id = 0
        while True:
            data = await self._get("/products.json", {
                "limit": 250,
                "since_id": since_id,
            })
            batch = data.get("products", [])
            if not batch:
                break
            products.extend(batch)
            if len(batch) < 250:
                break
            since_id = batch[-1]["id"]
            await asyncio.sleep(0.5)
        return products

    # ── Orders ────────────────────────────────────────────────────────────────

    async def get_orders(
        self,
        limit: int = 50,
        page_info: str | None = None,
        status: str = "any",
        financial_status: str | None = None,
    ) -> dict[str, Any]:
        params: dict = {"limit": limit, "status": status}
        if page_info:
            params["page_info"] = page_info
        else:
            # page_info and other params are mutually exclusive in Shopify
            if financial_status:
                params["financial_status"] = financial_status

        body, next_pi = await self._get_with_link("/orders.json", params)
        return {
            "orders":         body.get("orders", []),
            "next_page_info": next_pi,
        }

    async def get_order(self, order_id: int | str) -> dict:
        data = await self._get(f"/orders/{order_id}.json")
        return data.get("order", {})

    async def get_abandoned_checkouts(
        self, created_at_min: str | None = None, limit: int = 250
    ) -> list[dict]:
        """
        Fetch abandoned checkouts (the customer started checkout but never
        completed an order). Shopify has no 'abandoned' webhook — it marks a
        checkout abandoned server-side after a delay — so we poll this endpoint.
        Each item carries customer/email/phone, line_items, total_price, and
        abandoned_checkout_url.
        """
        params: dict = {"limit": min(int(limit or 250), 250), "status": "open"}
        if created_at_min:
            params["created_at_min"] = created_at_min
        data = await self._get("/checkouts.json", params)
        return data.get("checkouts", []) or []

    # ── Customers ─────────────────────────────────────────────────────────────

    async def get_all_customers(self) -> list[dict]:
        customers: list[dict] = []
        since_id = 0
        while True:
            data = await self._get("/customers.json", {
                "limit": 250,
                "since_id": since_id,
            })
            batch = data.get("customers", [])
            if not batch:
                break
            customers.extend(batch)
            if len(batch) < 250:
                break
            since_id = batch[-1]["id"]
            await asyncio.sleep(0.5)
        return customers

    # ── Webhooks ──────────────────────────────────────────────────────────────

    async def register_webhook(self, topic: str, address: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{self._base}/webhooks.json",
                headers=self._headers,
                json={"webhook": {"topic": topic, "address": address, "format": "json"}},
            )
            # 201 = created, 422 = already exists — both acceptable
            if r.status_code not in (201, 422):
                r.raise_for_status()
            return r.json()

    async def list_webhooks(self) -> list[dict]:
        data = await self._get("/webhooks.json")
        return data.get("webhooks", [])

    async def delete_webhook(self, webhook_id: int | str) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(
                f"{self._base}/webhooks/{webhook_id}.json",
                headers=self._headers,
            )
