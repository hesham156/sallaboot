"""
WhatsApp Campaign Sender

Resolves audience → list of {phone, name}, then sends the template
to each recipient with a small delay to respect Meta rate limits.

Audience types:
  chat_users       — unique phones extracted from conversations table
  salla_customers  — pulled from Salla API GET /customers
  abandoned_carts  — pulled from abandoned_carts table
  manual           — stored phone_list on the campaign row

Sending is done in the background via asyncio.create_task() so the
HTTP response is immediate. Progress is tracked per-recipient in
wa_campaign_recipients, and the campaign status in wa_campaigns is
updated on completion.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json as _json

import database as db
import store_manager as sm
import whatsapp as wa


# Meta recommends ≤ 80 messages/second per phone number on Cloud API.
# We use a conservative 5/s with jitter so normal stores don't trip
# the rate limiter, while high-volume stores can increase this later.
_SEND_DELAY = 0.22   # seconds between each send (~4.5 msg/s)
_MAX_BATCH  = 5000   # safety cap — prevent runaway campaigns


# ── Audience resolvers ─────────────────────────────────────────────────────────

async def _resolve_chat_users(store_id: str) -> list[dict]:
    """Unique phones from conversations that belong to this store."""
    if not db._pool:
        return []
    try:
        async with db._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT
                    data->>'customer_phone' AS phone,
                    data->>'customer_name'  AS name
                FROM conversations
                WHERE store_id = $1
                  AND data->>'customer_phone' IS NOT NULL
                  AND data->>'customer_phone' <> ''
                ORDER BY phone
                LIMIT $2
                """,
                store_id, _MAX_BATCH,
            )
        return [{"phone": r["phone"], "name": r["name"] or ""} for r in rows]
    except Exception as exc:
        print(f"[campaigns] _resolve_chat_users error: {exc}")
        return []


async def _resolve_salla_customers(store_id: str) -> list[dict]:
    """Pull customer list from Salla API (paginated, up to _MAX_BATCH)."""
    token = sm.get_access_token(store_id)
    if not token:
        return []
    from salla_client import SallaClient
    client = SallaClient(token, store_id=store_id)
    results: list[dict] = []
    page = 1
    while len(results) < _MAX_BATCH:
        try:
            resp = await client._request("GET", "/customers", params={"per_page": 50, "page": page})
        except Exception as exc:
            print(f"[campaigns] salla customers page {page} error: {exc}")
            break
        batch = resp.get("data") or []
        if not batch:
            break
        for c in batch:
            mobile = (c.get("mobile") or "").strip()
            if mobile:
                results.append({"phone": mobile, "name": c.get("name", "") or ""})
        if len(batch) < 50:
            break
        page += 1
    return results[:_MAX_BATCH]


async def _resolve_abandoned_carts(store_id: str) -> list[dict]:
    """Phones from abandoned_carts table."""
    if not db._pool:
        return []
    try:
        async with db._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT
                    cart_data->'customer'->>'mobile' AS phone,
                    cart_data->'customer'->>'name'   AS name
                FROM abandoned_carts
                WHERE store_id = $1
                  AND cart_data->'customer'->>'mobile' IS NOT NULL
                  AND cart_data->'customer'->>'mobile' <> ''
                  AND recovered = FALSE
                ORDER BY phone
                LIMIT $2
                """,
                store_id, _MAX_BATCH,
            )
        return [{"phone": r["phone"], "name": r["name"] or ""} for r in rows]
    except Exception as exc:
        print(f"[campaigns] _resolve_abandoned_carts error: {exc}")
        return []


async def resolve_audience(
    store_id: str, audience_type: str, phone_list: list
) -> list[dict]:
    """Return a deduplicated list of {phone, name} for the given audience type."""
    if audience_type == "chat_users":
        recipients = await _resolve_chat_users(store_id)
    elif audience_type == "salla_customers":
        recipients = await _resolve_salla_customers(store_id)
    elif audience_type == "abandoned_carts":
        recipients = await _resolve_abandoned_carts(store_id)
    elif audience_type == "manual":
        # phone_list is already stored as [{phone, name}, ...] or ["05xxx", ...]
        recipients = []
        for item in (phone_list or []):
            if isinstance(item, str):
                p = item.strip()
                if p:
                    recipients.append({"phone": p, "name": ""})
            elif isinstance(item, dict):
                p = (item.get("phone") or "").strip()
                if p:
                    recipients.append({"phone": p, "name": item.get("name", "")})
    else:
        recipients = []

    # Deduplicate by phone
    seen: set[str] = set()
    unique: list[dict] = []
    for r in recipients:
        p = r["phone"]
        if p not in seen:
            seen.add(p)
            unique.append(r)
    return unique


# ── Variable substitution ──────────────────────────────────────────────────────

def _fill_params(params: list[str], recipient: dict) -> list[str]:
    """Replace {{name}} / {{phone}} placeholders in template params."""
    filled = []
    for p in params:
        p = p.replace("{{name}}", recipient.get("name") or "عزيزي العميل")
        p = p.replace("{{phone}}", recipient.get("phone") or "")
        filled.append(p)
    return filled


# ── Core sender ────────────────────────────────────────────────────────────────

async def run_campaign(campaign_id: int) -> None:
    """
    Background task: resolve audience, send template to each recipient,
    update recipient rows and final campaign status.
    """
    campaign = await db.campaign_get(campaign_id)
    if not campaign:
        print(f"[campaigns] campaign {campaign_id} not found")
        return

    store_id = campaign["store_id"]
    cfg      = sm.get_ai_config(store_id) or {}
    token    = (cfg.get("whatsapp_token")    or "").strip()
    phone_id = (cfg.get("whatsapp_phone_id") or "").strip()

    if not token or not phone_id:
        await db.campaign_update_status(campaign_id, "failed")
        print(f"[campaigns] {campaign_id}: no WhatsApp credentials")
        return

    await db.campaign_update_status(campaign_id, "sending")

    # Resolve audience
    phone_list = campaign.get("phone_list") or []
    if isinstance(phone_list, str):
        try:
            phone_list = _json.loads(phone_list)
        except Exception:
            phone_list = []

    recipients = await resolve_audience(store_id, campaign["audience_type"], phone_list)
    if not recipients:
        await db.campaign_update_status(campaign_id, "failed", total=0, sent=0, failed=0)
        print(f"[campaigns] {campaign_id}: empty audience")
        return

    # Bulk-insert recipient rows
    await db.campaign_add_recipients(campaign_id, recipients)
    total = len(recipients)

    # Parse template params (stored as JSON arrays)
    h_params_raw = campaign.get("header_params") or []
    b_params_raw = campaign.get("body_params")   or []
    if isinstance(h_params_raw, str):
        try: h_params_raw = _json.loads(h_params_raw)
        except Exception: h_params_raw = []
    if isinstance(b_params_raw, str):
        try: b_params_raw = _json.loads(b_params_raw)
        except Exception: b_params_raw = []

    sent = failed = 0
    for recipient in recipients:
        h_params = _fill_params(h_params_raw, recipient)
        b_params = _fill_params(b_params_raw, recipient)
        ok = await wa.send_template(
            token            = token,
            phone_id         = phone_id,
            to               = recipient["phone"],
            template_name    = campaign["template_name"],
            language         = campaign.get("template_lang", "ar"),
            header_params    = h_params or None,
            body_params      = b_params or None,
        )
        if ok:
            sent += 1
        else:
            failed += 1
        await db.campaign_mark_recipient(campaign_id, recipient["phone"], ok=ok)
        await asyncio.sleep(_SEND_DELAY)

    await db.campaign_update_status(
        campaign_id, "sent",
        total=total, sent=sent, failed=failed,
        sent_at=_dt.datetime.now(_dt.timezone.utc),
    )
    print(f"[campaigns] {campaign_id} done — {sent}/{total} sent, {failed} failed")


async def maybe_fire_scheduled() -> None:
    """
    Called periodically by the lifecycle loop. Fires any campaigns whose
    scheduled_at has passed and are still in 'scheduled' status.
    """
    if not db._pool:
        return
    try:
        async with db._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id FROM wa_campaigns
                WHERE status = 'scheduled'
                  AND scheduled_at <= NOW()
                LIMIT 10
                """
            )
        for row in rows:
            asyncio.create_task(run_campaign(row["id"]))
    except Exception as exc:
        print(f"[campaigns] maybe_fire_scheduled error: {exc}")
