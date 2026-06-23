"""
Lightweight async Zid API client.

Two auth modes (both tokens come from the OAuth token exchange):
  Manager API (/v1/managers/*):
      Authorization: Bearer {authorization_jwt}
      X-Manager-Token: {access_token}

  Products API (/v1/products/):
      Access-Token: {access_token}
      Store-Id: {zid_store_id}
      Role: Manager

Tokens expire after ~1 year. Refresh via /oauth/token with grant_type=refresh_token.
"""
from __future__ import annotations

import asyncio

import httpx

_BASE = "https://api.zid.sa/v1"


class ZidClient:
    def __init__(
        self,
        access_token: str,
        authorization_jwt: str,
        zid_store_id: str | int = "",
        store_id: str = "",
    ):
        self.store_id      = store_id
        self.zid_store_id  = str(zid_store_id)
        self._access_token = access_token
        self._jwt          = authorization_jwt

        self._mgr_headers = {
            "Authorization":   f"Bearer {authorization_jwt}",
            "X-Manager-Token": access_token,
            "Accept-Language": "ar",
            "Content-Type":    "application/json",
        }
        self._prd_headers = {
            "Access-Token":    access_token,
            "Store-Id":        str(zid_store_id),
            "Role":            "Manager",
            "Accept-Language": "ar",
        }

    # ── Low-level ─────────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None, use_prd_auth: bool = False) -> dict:
        url = f"{_BASE}{path}"
        headers = self._prd_headers if use_prd_auth else self._mgr_headers
        async with httpx.AsyncClient(timeout=20) as client:
            for attempt in range(3):
                r = await client.get(url, headers=headers, params=params or {})
                if r.status_code == 429:
                    await asyncio.sleep(float(r.headers.get("Retry-After", "2")))
                    continue
                if r.status_code == 401 and attempt == 0:
                    try:
                        await self._refresh_tokens()
                        headers = self._prd_headers if use_prd_auth else self._mgr_headers
                        continue
                    except Exception as exc:
                        raise RuntimeError(
                            f"Zid token refresh failed for store {self.store_id!r}: {exc}"
                        ) from exc
                r.raise_for_status()
                return r.json()
        r.raise_for_status()
        return {}

    async def _refresh_tokens(self) -> None:
        """Exchange the stored refresh_token for new Zid credentials and persist them."""
        import os
        import database as _db

        integ    = await _db.get_integrations(self.store_id)
        zid_data = integ.get("zid") or {}
        rt       = zid_data.get("refresh_token", "")
        if not rt:
            raise RuntimeError(f"No Zid refresh_token for store {self.store_id!r}")

        async with httpx.AsyncClient(timeout=15) as rc:
            tr = await rc.post(
                "https://oauth.zid.sa/oauth/token",
                data={
                    "grant_type":    "refresh_token",
                    "client_id":     os.getenv("ZID_CLIENT_ID", ""),
                    "client_secret": os.getenv("ZID_CLIENT_SECRET", ""),
                    "refresh_token": rt,
                    "redirect_uri":  f"{os.getenv('BASE_URL', '')}/integrations/zid/callback",
                },
            )
            tr.raise_for_status()
            td = tr.json()

        new_access = td.get("access_token", "")
        new_jwt    = td.get("Authorization", "")
        new_rt     = td.get("refresh_token") or rt
        if not new_access or not new_jwt:
            raise RuntimeError("Zid token refresh response missing access_token/Authorization")

        self._access_token = new_access
        self._jwt          = new_jwt
        self._mgr_headers.update({
            "Authorization":   f"Bearer {new_jwt}",
            "X-Manager-Token": new_access,
        })
        self._prd_headers["Access-Token"] = new_access

        await _db.save_integration(self.store_id, "zid", {
            **zid_data,
            "access_token":      new_access,
            "authorization_jwt": new_jwt,
            "refresh_token":     new_rt,
        })

    # ── Store info ────────────────────────────────────────────────────────────

    async def get_store(self) -> dict:
        data = await self._get("/managers/account/store")
        return data.get("store", {})

    # ── Products (full paginated fetch) ──────────────────────────────────────

    async def get_all_products(self) -> list[dict]:
        products: list[dict] = []
        page = 1
        while True:
            data = await self._get(
                "/products/",
                params={"page": page, "page_size": 100, "extended": "true"},
                use_prd_auth=True,
            )
            batch = data.get("results", [])
            if not batch:
                break
            products.extend(batch)
            if not data.get("next"):
                break
            page += 1
            await asyncio.sleep(0.3)
        return products

    # ── Orders ────────────────────────────────────────────────────────────────

    async def get_orders(self, page: int = 1, per_page: int = 100) -> dict:
        return await self._get(
            "/managers/store/orders",
            params={"page": page, "per_page": per_page, "payload_type": "default"},
        )

    async def get_abandoned_carts(self, page: int = 1, per_page: int = 100) -> list[dict]:
        """
        List abandoned carts (Zid marks a cart abandoned after 10 min of
        inactivity). Each item carries id, url (recovery link), customer_name,
        customer_mobile, customer_email, cart_total, currency_code, products_count.
        """
        data = await self._get(
            "/managers/store/abandoned-carts",
            params={"page": page, "per_page": per_page},
        )
        return data.get("abandoned-carts", []) or []

    async def get_order(self, order_id: str | int) -> dict:
        data = await self._get(
            f"/managers/store/orders/{order_id}",
            params={"payload_type": "default"},
        )
        # Zid may wrap the order under "order" or return it directly.
        return data.get("order", data) if isinstance(data, dict) else {}

    # ── Customers ─────────────────────────────────────────────────────────────

    async def get_customers(self, page: int = 1, per_page: int = 100) -> dict:
        return await self._get(
            "/managers/store/customers",
            params={"page": page, "per_page": per_page},
        )

    # ── Webhooks ──────────────────────────────────────────────────────────────

    async def create_webhook(self, event: str, url: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{_BASE}/managers/store/webhooks",
                headers=self._mgr_headers,
                json={"event": event, "url": url, "is_active": True},
            )
            if r.status_code in (200, 201, 409):
                return r.json()
            r.raise_for_status()
            return r.json()

    async def list_webhooks(self) -> list[dict]:
        data = await self._get("/managers/store/webhooks")
        return data.get("webhooks", []) or []

    async def delete_webhook(self, webhook_id: str | int) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(
                f"{_BASE}/managers/store/webhooks/{webhook_id}",
                headers=self._mgr_headers,
            )
