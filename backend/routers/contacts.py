"""
Contacts — unified CRM built from WhatsApp chat users + Salla customers.

GET  /admin/{store}/contacts              — paginated list with search
POST /admin/{store}/contacts/sync         — pull from conversations + Salla API
GET  /admin/{store}/contacts/export       — CSV download
"""
from __future__ import annotations

import csv
import io
import datetime as _dt

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse

import database as db
import store_manager as sm
from routers.deps import require_store_member

router = APIRouter()

_MAX_SALLA_CONTACTS = 10_000   # safety cap on Salla API pages during sync


def _require_store(store_id: str):
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")


# ── List ───────────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/contacts")
async def list_contacts(
    store_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    search: str = Query(""),
):
    await require_store_member(request, store_id)
    _require_store(store_id)
    total   = await db.contacts_count(store_id, search)
    records = await db.contacts_list(store_id, page, per_page, search)

    def _fmt(r: dict) -> dict:
        ls = r.get("last_seen")
        ca = r.get("created_at")
        return {
            "id":         r["id"],
            "phone":      r["phone"],
            "name":       r["name"] or "",
            "email":      r["email"] or "",
            "company":    r["company"] or "",
            "city":       r["city"] or "",
            "country":    r["country"] or "",
            "source":     r["source"] or "chat",
            "salla_id":   r.get("salla_id") or None,
            "last_seen":  ls.isoformat() if ls else None,
            "created_at": ca.isoformat() if ca else None,
        }

    return {
        "contacts":   [_fmt(r) for r in records],
        "total":      total,
        "page":       page,
        "per_page":   per_page,
        "pages":      max(1, (total + per_page - 1) // per_page),
    }


# ── Sync ───────────────────────────────────────────────────────────────────────

@router.post("/admin/{store_id}/contacts/sync")
async def sync_contacts(store_id: str, request: Request):
    await require_store_member(request, store_id)
    _require_store(store_id)

    chat_count   = 0
    salla_count  = 0
    upserted     = 0

    # ── 1. From conversations table ──────────────────────────────────────────
    if db._pool:
        try:
            async with db._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT
                        data->>'customer_phone' AS phone,
                        data->>'customer_name'  AS name,
                        MAX(updated_at)         AS last_seen
                    FROM conversations
                    WHERE store_id = $1
                      AND data->>'customer_phone' IS NOT NULL
                      AND data->>'customer_phone' <> ''
                    GROUP BY data->>'customer_phone', data->>'customer_name'
                    LIMIT 20000
                    """,
                    store_id,
                )
            chat_records = [
                {
                    "phone":     r["phone"].strip(),
                    "name":      r["name"] or "",
                    "source":    "chat",
                    "last_seen": r["last_seen"],
                }
                for r in rows if (r["phone"] or "").strip()
            ]
            upserted += await db.contacts_upsert_batch(store_id, chat_records)
            chat_count = len(chat_records)
        except Exception as exc:
            print(f"[contacts] chat sync error: {exc}")

    # ── 2. From Salla API ────────────────────────────────────────────────────
    token = sm.get_access_token(store_id)
    if token:
        try:
            from salla_client import SallaClient
            client = SallaClient(token, store_id=store_id)
            page = 1
            salla_records: list[dict] = []
            while len(salla_records) < _MAX_SALLA_CONTACTS:
                try:
                    resp = await client._request(
                        "GET", "/customers",
                        params={"per_page": 100, "page": page},
                    )
                except Exception:
                    break
                batch = resp.get("data") or []
                if not batch:
                    break
                for c in batch:
                    mobile = (c.get("mobile") or "").strip()
                    if not mobile:
                        continue
                    salla_records.append({
                        "phone":    mobile,
                        "name":     c.get("name") or "",
                        "email":    c.get("email") or "",
                        "company":  (c.get("company") or {}).get("name", "") if isinstance(c.get("company"), dict) else "",
                        "city":     (c.get("city") or {}).get("name", "") if isinstance(c.get("city"), dict) else "",
                        "country":  c.get("country") or "",
                        "source":   "salla",
                        "salla_id": str(c.get("id")) if c.get("id") else None,
                    })
                if len(batch) < 100:
                    break
                page += 1

            upserted += await db.contacts_upsert_batch(store_id, salla_records)
            salla_count = len(salla_records)
        except Exception as exc:
            print(f"[contacts] salla sync error: {exc}")

    # ── 3. From Shopify API ──────────────────────────────────────────────────
    shopify_count = 0
    try:
        integrations_data = await db.get_integrations(store_id)
        shopify_data      = integrations_data.get("shopify", {})
        sp_shop  = shopify_data.get("shop", "")
        sp_token = shopify_data.get("access_token", "")
        if sp_shop and sp_token:
            from shopify_client import ShopifyClient
            sp_client = ShopifyClient(sp_shop, sp_token, store_id=store_id)
            sp_customers = await sp_client.get_all_customers()
            shopify_records: list[dict] = []
            for c in sp_customers:
                phones = [
                    p.strip()
                    for p in [c.get("phone") or "", (c.get("default_address") or {}).get("phone", "")]
                    if p and p.strip()
                ]
                phone = phones[0] if phones else ""
                if not phone:
                    continue
                shopify_records.append({
                    "phone":   phone,
                    "name":    f"{c.get('first_name', '')} {c.get('last_name', '')}".strip(),
                    "email":   c.get("email", ""),
                    "city":    (c.get("default_address") or {}).get("city", ""),
                    "country": (c.get("default_address") or {}).get("country_code", ""),
                    "source":  "shopify",
                })
            if shopify_records:
                upserted += await db.contacts_upsert_batch(store_id, shopify_records)
            shopify_count = len(shopify_records)
    except Exception as exc:
        print(f"[contacts] shopify sync error: {exc}")

    total = await db.contacts_count(store_id)
    return {
        "message":        f"تمت المزامنة ✅ — {upserted} جهة اتصال جديدة/محدّثة",
        "chat_found":     chat_count,
        "salla_found":    salla_count,
        "shopify_found":  shopify_count,
        "total":          total,
    }


# ── Export CSV ─────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/contacts/export")
async def export_contacts(store_id: str, request: Request, search: str = Query("")):
    await require_store_member(request, store_id)
    _require_store(store_id)

    total   = await db.contacts_count(store_id, search)
    records = await db.contacts_list(store_id, 1, min(total, 50_000), search)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["الاسم", "رقم الهاتف", "البريد الإلكتروني", "الشركة", "المدينة", "الدولة", "المصدر", "آخر نشاط"])
    for r in records:
        ls = r.get("last_seen")
        writer.writerow([
            r.get("name") or "",
            r.get("phone") or "",
            r.get("email") or "",
            r.get("company") or "",
            r.get("city") or "",
            r.get("country") or "",
            r.get("source") or "",
            ls.strftime("%Y-%m-%d") if ls else "",
        ])

    output.seek(0)
    filename = f"contacts_{store_id}_{_dt.date.today()}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
