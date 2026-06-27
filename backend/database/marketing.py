"""database.marketing — split out of the original single-file database.py."""
import json
from database import _core
from database._core import _coerce_jsonb, _iso_z




# ── Broadcasts (omni-channel free-text bulk send) ───────────────────────────

async def broadcast_create(store_id: str, message: str, channels: list[str]) -> int | None:
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO broadcasts (store_id, message, channels)
                VALUES ($1, $2, $3::jsonb)
                RETURNING id
                """,
                store_id, message, json.dumps(channels, ensure_ascii=False),
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] broadcast_create error: {e}")
        return None


def _broadcast_row(r) -> dict:
    return {
        "id":           int(r["id"]),
        "store_id":     r["store_id"],
        "message":      r["message"],
        "channels":     _coerce_jsonb(r["channels"]) if not isinstance(r["channels"], list) else r["channels"],
        "status":       r["status"],
        "total_count":  int(r["total_count"] or 0),
        "sent_count":   int(r["sent_count"] or 0),
        "failed_count": int(r["failed_count"] or 0),
        "per_channel":  _coerce_jsonb(r["per_channel"]),
        "created_at":   _iso_z(r["created_at"]),
        "sent_at":      _iso_z(r["sent_at"]) if r["sent_at"] else "",
    }


async def broadcast_get(store_id: str, broadcast_id: int) -> dict | None:
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT * FROM broadcasts WHERE id = $1 AND store_id = $2",
                int(broadcast_id), store_id,
            )
        return _broadcast_row(r) if r else None
    except Exception as e:
        print(f"[db] broadcast_get error: {e}")
        return None


async def broadcast_list(store_id: str, limit: int = 50) -> list[dict]:
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM broadcasts WHERE store_id = $1 "
                "ORDER BY created_at DESC LIMIT $2",
                store_id, int(limit),
            )
        return [_broadcast_row(r) for r in rows]
    except Exception as e:
        print(f"[db] broadcast_list error: {e}")
        return []


async def broadcast_update(broadcast_id: int, *, status: str | None = None,
                           total: int | None = None, sent: int | None = None,
                           failed: int | None = None, per_channel: dict | None = None,
                           sent_at=None) -> None:
    if not _core._pool:
        return
    sets, args = [], []
    if status is not None:
        sets.append(f"status = ${len(args)+1}"); args.append(status)
    if total is not None:
        sets.append(f"total_count = ${len(args)+1}"); args.append(int(total))
    if sent is not None:
        sets.append(f"sent_count = ${len(args)+1}"); args.append(int(sent))
    if failed is not None:
        sets.append(f"failed_count = ${len(args)+1}"); args.append(int(failed))
    if per_channel is not None:
        sets.append(f"per_channel = ${len(args)+1}::jsonb")
        args.append(json.dumps(per_channel, ensure_ascii=False))
    if sent_at is not None:
        sets.append(f"sent_at = ${len(args)+1}"); args.append(sent_at)
    if not sets:
        return
    args.append(int(broadcast_id))
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE broadcasts SET {', '.join(sets)} WHERE id = ${len(args)}", *args,
            )
    except Exception as e:
        print(f"[db] broadcast_update error: {e}")


async def broadcast_channel_recipients(store_id: str, channel: str,
                                       within_hours: int | None = None,
                                       limit: int = 5000) -> list[dict]:
    """
    Resolve the recipients of a chat CHANNEL from the conversations table.
    Returns [{recipient, session_id, name}] where `recipient` is the
    channel-native id (phone / chat_id / psid) parsed from the session_id
    (`{wa|tg|msgr|ig}:{store_id}:{recipient}`). For the website widget the
    recipient IS the session_id (used to enqueue into widget_outbox).

    `within_hours` limits to conversations active in that window — required
    for WhatsApp / Messenger / Instagram free-text sends (Meta's 24h
    customer-care window). None = no time limit (telegram / widget).
    """
    if not _core._pool:
        return []
    args: list = [store_id]
    if channel in ("widget", "web"):
        # Website widget sessions don't carry an explicit channel tag (the
        # external channels do). Identify them as "no external channel" — i.e.
        # channel is NULL or web/widget — and their session_id is the random
        # widget id, used directly as the widget_outbox key.
        where = ["store_id = $1",
                 "(data->>'channel' IS NULL OR data->>'channel' IN ('web','widget'))"]
    else:
        where = ["store_id = $1", "data->>'channel' = $2"]
        args.append(channel)
    if within_hours is not None:
        where.append(f"updated_at >= NOW() - INTERVAL '{int(within_hours)} hours'")
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT session_id, data->>'customer_name' AS name
                FROM conversations
                WHERE {' AND '.join(where)}
                ORDER BY updated_at DESC
                LIMIT ${len(args)+1}
                """,
                *args, int(limit),
            )
        out = []
        for r in rows:
            sid = r["session_id"]
            recipient = sid if channel in ("widget", "web") else sid.rsplit(":", 1)[-1]
            if recipient:
                out.append({"recipient": recipient, "session_id": sid,
                            "name": r["name"] or ""})
        return out
    except Exception as e:
        print(f"[db] broadcast_channel_recipients({channel}) error: {e}")
        return []


async def broadcast_email_recipients(store_id: str, limit: int = 5000) -> list[dict]:
    """Distinct contact emails for the email broadcast channel."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT email, name FROM contacts
                WHERE store_id = $1 AND email <> ''
                ORDER BY email
                LIMIT $2
                """,
                store_id, int(limit),
            )
        return [{"recipient": r["email"], "name": r["name"] or ""} for r in rows]
    except Exception as e:
        print(f"[db] broadcast_email_recipients error: {e}")
        return []


# ── WhatsApp Templates ────────────────────────────────────────────────────────

async def wa_template_save(store_id: str, tpl: dict) -> dict:
    """Upsert a template definition. Returns the saved row."""
    if not _core._pool:
        return {}
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO whatsapp_templates
                    (store_id, name, language, category,
                     header_type, header_text, body_text, footer_text,
                     buttons, variables, status, notes, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,$12,NOW())
                ON CONFLICT (store_id, name) DO UPDATE SET
                    language    = EXCLUDED.language,
                    category    = EXCLUDED.category,
                    header_type = EXCLUDED.header_type,
                    header_text = EXCLUDED.header_text,
                    body_text   = EXCLUDED.body_text,
                    footer_text = EXCLUDED.footer_text,
                    buttons     = EXCLUDED.buttons,
                    variables   = EXCLUDED.variables,
                    status      = EXCLUDED.status,
                    notes       = EXCLUDED.notes,
                    updated_at  = NOW()
                RETURNING id, created_at, updated_at
                """,
                store_id,
                tpl["name"],
                tpl.get("language", "ar"),
                tpl.get("category", "MARKETING"),
                tpl.get("header_type") or None,
                tpl.get("header_text") or None,
                tpl.get("body_text", ""),
                tpl.get("footer_text") or None,
                json.dumps(tpl.get("buttons", []), ensure_ascii=False),
                json.dumps(tpl.get("variables", []), ensure_ascii=False),
                tpl.get("status", "approved"),
                tpl.get("notes") or None,
            )
        return {"id": int(row["id"]), **tpl}
    except Exception as e:
        print(f"[db] wa_template_save error: {e}")
        return {}


async def wa_template_list(store_id: str) -> list[dict]:
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM whatsapp_templates
                   WHERE store_id=$1 ORDER BY created_at DESC""",
                store_id,
            )
        result = []
        for r in rows:
            result.append({
                "id":          int(r["id"]),
                "name":        r["name"],
                "language":    r["language"],
                "category":    r["category"],
                "header_type": r["header_type"] or "",
                "header_text": r["header_text"] or "",
                "body_text":   r["body_text"],
                "footer_text": r["footer_text"] or "",
                "buttons":     r["buttons"] or [],
                "variables":   r["variables"] or [],
                "status":      r["status"],
                "notes":       r["notes"] or "",
                "created_at":  _iso_z(r["created_at"]),
                "updated_at":  _iso_z(r["updated_at"]),
            })
        return result
    except Exception as e:
        print(f"[db] wa_template_list error: {e}")
        return []


async def wa_template_delete(store_id: str, name: str) -> bool:
    if not _core._pool:
        return False
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.execute(
                "DELETE FROM whatsapp_templates WHERE store_id=$1 AND name=$2",
                store_id, name,
            )
        return r == "DELETE 1"
    except Exception as e:
        print(f"[db] wa_template_delete error: {e}")
        return False


# ── Customer Segments ─────────────────────────────────────────────────────────

async def seg_upsert(store_id: str, customer_id: str, data: dict) -> dict | None:
    """Insert or update a customer segment row. Returns the saved row."""
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO customer_segments
                    (store_id, customer_id, customer_name, phone, email,
                     segment, segment_reason, last_order_id, last_order_at,
                     last_conv_id, last_conv_at, next_followup_at, notes, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW())
                ON CONFLICT (store_id, customer_id) DO UPDATE SET
                    customer_name    = COALESCE(NULLIF(EXCLUDED.customer_name,''), customer_segments.customer_name),
                    phone            = COALESCE(NULLIF(EXCLUDED.phone,''),         customer_segments.phone),
                    email            = COALESCE(NULLIF(EXCLUDED.email,''),         customer_segments.email),
                    segment          = EXCLUDED.segment,
                    segment_reason   = EXCLUDED.segment_reason,
                    last_order_id    = COALESCE(EXCLUDED.last_order_id,   customer_segments.last_order_id),
                    last_order_at    = COALESCE(EXCLUDED.last_order_at,   customer_segments.last_order_at),
                    last_conv_id     = COALESCE(EXCLUDED.last_conv_id,    customer_segments.last_conv_id),
                    last_conv_at     = COALESCE(EXCLUDED.last_conv_at,    customer_segments.last_conv_at),
                    next_followup_at = EXCLUDED.next_followup_at,
                    notes            = COALESCE(NULLIF(EXCLUDED.notes,''), customer_segments.notes),
                    updated_at       = NOW()
                RETURNING *
            """,
            store_id, customer_id,
            data.get("customer_name", ""), data.get("phone", ""), data.get("email", ""),
            data.get("segment", "new"), data.get("segment_reason", ""),
            data.get("last_order_id"), data.get("last_order_at"),
            data.get("last_conv_id"), data.get("last_conv_at"),
            data.get("next_followup_at"), data.get("notes", ""))
            return dict(row) if row else None
    except Exception as e:
        print(f"[db] seg_upsert error: {e}")
        return None


async def seg_list(store_id: str, segment: str | None = None,
                   limit: int = 100, offset: int = 0) -> list[dict]:
    """List customer segments for a store, optionally filtered by segment type."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            if segment:
                rows = await conn.fetch("""
                    SELECT * FROM customer_segments
                    WHERE store_id=$1 AND segment=$2
                    ORDER BY updated_at DESC LIMIT $3 OFFSET $4
                """, store_id, segment, limit, offset)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM customer_segments
                    WHERE store_id=$1
                    ORDER BY updated_at DESC LIMIT $2 OFFSET $3
                """, store_id, limit, offset)
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] seg_list error: {e}")
        return []


async def seg_count_by_type(store_id: str) -> dict:
    """Return {segment: count} for all segments in a store."""
    if not _core._pool:
        return {}
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT segment, COUNT(*) as cnt
                FROM customer_segments WHERE store_id=$1
                GROUP BY segment
            """, store_id)
            return {r["segment"]: int(r["cnt"]) for r in rows}
    except Exception as e:
        print(f"[db] seg_count_by_type error: {e}")
        return {}


async def seg_get_due_followups(store_id: str, limit: int = 50) -> list[dict]:
    """Return customers whose next_followup_at <= now and not paused."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM customer_segments
                WHERE store_id=$1
                  AND next_followup_at <= NOW()
                  AND followup_paused = FALSE
                  AND phone <> ''
                ORDER BY next_followup_at ASC
                LIMIT $2
            """, store_id, limit)
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] seg_get_due_followups error: {e}")
        return []


async def seg_mark_followup_sent(store_id: str, customer_id: str,
                                 next_followup_at=None) -> None:
    """Increment followup_count and set last/next followup timestamps."""
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute("""
                UPDATE customer_segments
                SET followup_count   = followup_count + 1,
                    last_followup_at = NOW(),
                    next_followup_at = $3,
                    updated_at       = NOW()
                WHERE store_id=$1 AND customer_id=$2
            """, store_id, customer_id, next_followup_at)
    except Exception as e:
        print(f"[db] seg_mark_followup_sent error: {e}")


async def seg_pause(store_id: str, customer_id: str, paused: bool) -> None:
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute("""
                UPDATE customer_segments
                SET followup_paused=$3, updated_at=NOW()
                WHERE store_id=$1 AND customer_id=$2
            """, store_id, customer_id, paused)
    except Exception as e:
        print(f"[db] seg_pause error: {e}")


async def seg_get_all_stores_due() -> list[dict]:
    """Return all customers across all stores with due follow-ups."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM customer_segments
                WHERE next_followup_at <= NOW()
                  AND followup_paused = FALSE
                  AND phone <> ''
                ORDER BY next_followup_at ASC
                LIMIT 200
            """)
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] seg_get_all_stores_due error: {e}")
        return []


# ── WhatsApp Campaigns ─────────────────────────────────────────────────────────

async def campaign_create(store_id: str, data: dict) -> dict | None:
    if not _core._pool:
        return None
    import json as _j
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO wa_campaigns
                    (store_id, name, template_name, template_lang,
                     header_params, body_params, audience_type, phone_list,
                     status, scheduled_at)
                VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7,$8::jsonb,$9,$10)
                RETURNING *
                """,
                store_id,
                data["name"],
                data["template_name"],
                data.get("template_lang", "ar"),
                _j.dumps(data.get("header_params", [])),
                _j.dumps(data.get("body_params", [])),
                data.get("audience_type", "chat_users"),
                _j.dumps(data.get("phone_list", [])),
                data.get("status", "draft"),
                data.get("scheduled_at"),
            )
        return dict(row) if row else None
    except Exception as e:
        print(f"[db] campaign_create error: {e}")
        return None


async def campaign_list(store_id: str) -> list[dict]:
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name, template_name, template_lang,
                       audience_type, status, scheduled_at, sent_at,
                       total_count, sent_count, failed_count, created_at
                FROM wa_campaigns
                WHERE store_id = $1
                ORDER BY created_at DESC
                LIMIT 100
                """,
                store_id,
            )
        return [
            {
                "id":            r["id"],
                "name":          r["name"],
                "template_name": r["template_name"],
                "template_lang": r["template_lang"],
                "audience_type": r["audience_type"],
                "status":        r["status"],
                "scheduled_at":  _iso_z(r["scheduled_at"]),
                "sent_at":       _iso_z(r["sent_at"]),
                "total_count":   r["total_count"],
                "sent_count":    r["sent_count"],
                "failed_count":  r["failed_count"],
                "created_at":    _iso_z(r["created_at"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] campaign_list error: {e}")
        return []


async def campaign_get(campaign_id: int) -> dict | None:
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM wa_campaigns WHERE id = $1", campaign_id
            )
        return dict(row) if row else None
    except Exception as e:
        print(f"[db] campaign_get error: {e}")
        return None


async def campaign_update_status(
    campaign_id: int,
    status: str,
    *,
    total: int | None = None,
    sent: int | None = None,
    failed: int | None = None,
    sent_at=None,
) -> None:
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE wa_campaigns
                SET status       = $2,
                    total_count  = COALESCE($3, total_count),
                    sent_count   = COALESCE($4, sent_count),
                    failed_count = COALESCE($5, failed_count),
                    sent_at      = COALESCE($6, sent_at),
                    updated_at   = NOW()
                WHERE id = $1
                """,
                campaign_id, status, total, sent, failed, sent_at,
            )
    except Exception as e:
        print(f"[db] campaign_update_status error: {e}")


async def campaign_delete(store_id: str, campaign_id: int) -> bool:
    if not _core._pool:
        return False
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.execute(
                "DELETE FROM wa_campaigns WHERE id=$1 AND store_id=$2",
                campaign_id, store_id,
            )
        return r.endswith("1")
    except Exception as e:
        print(f"[db] campaign_delete error: {e}")
        return False


async def campaign_add_recipients(campaign_id: int, recipients: list[dict]) -> int:
    """Bulk-insert recipients. Returns inserted count."""
    if not _core._pool or not recipients:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO wa_campaign_recipients (campaign_id, phone, name)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                [(campaign_id, r["phone"], r.get("name", "")) for r in recipients],
            )
        return len(recipients)
    except Exception as e:
        print(f"[db] campaign_add_recipients error: {e}")
        return 0


async def campaign_mark_recipient(
    campaign_id: int, phone: str, *, ok: bool, error: str = ""
) -> None:
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE wa_campaign_recipients
                SET status = $3, error = $4, sent_at = CASE WHEN $3='sent' THEN NOW() ELSE NULL END
                WHERE campaign_id = $1 AND phone = $2
                """,
                campaign_id, phone,
                "sent" if ok else "failed",
                error,
            )
    except Exception as e:
        print(f"[db] campaign_mark_recipient error: {e}")


async def campaign_recipient_stats(campaign_id: int) -> dict:
    if not _core._pool:
        return {}
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)                                       AS total,
                    COUNT(*) FILTER (WHERE status='sent')         AS sent,
                    COUNT(*) FILTER (WHERE status='failed')       AS failed,
                    COUNT(*) FILTER (WHERE status='pending')      AS pending
                FROM wa_campaign_recipients
                WHERE campaign_id = $1
                """,
                campaign_id,
            )
        return dict(row) if row else {}
    except Exception as e:
        print(f"[db] campaign_recipient_stats error: {e}")
        return {}


# ── Contacts (unified CRM) ─────────────────────────────────────────────────────

async def contacts_count(store_id: str, search: str = "") -> int:
    if not _core._pool:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            if search:
                return await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM contacts
                    WHERE store_id = $1
                      AND (name ILIKE $2 OR phone ILIKE $2 OR email ILIKE $2)
                    """,
                    store_id, f"%{search}%",
                ) or 0
            return await conn.fetchval(
                "SELECT COUNT(*) FROM contacts WHERE store_id = $1", store_id,
            ) or 0
    except Exception as e:
        print(f"[db] contacts_count error: {e}")
        return 0


async def contacts_list(
    store_id: str, page: int = 1, per_page: int = 25, search: str = ""
) -> list[dict]:
    if not _core._pool:
        return []
    offset = (page - 1) * per_page
    try:
        async with _core._pool.acquire() as conn:
            if search:
                rows = await conn.fetch(
                    """
                    SELECT id, phone, name, email, company, city, country,
                           source, salla_id, last_seen, created_at, updated_at
                    FROM contacts
                    WHERE store_id = $1
                      AND (name ILIKE $2 OR phone ILIKE $2 OR email ILIKE $2)
                    ORDER BY updated_at DESC
                    LIMIT $3 OFFSET $4
                    """,
                    store_id, f"%{search}%", per_page, offset,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, phone, name, email, company, city, country,
                           source, salla_id, last_seen, created_at, updated_at
                    FROM contacts
                    WHERE store_id = $1
                    ORDER BY updated_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    store_id, per_page, offset,
                )
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] contacts_list error: {e}")
        return []


async def contacts_upsert_batch(store_id: str, records: list[dict]) -> int:
    """
    Upsert a batch of contacts. Records should have: phone, name, email,
    company, city, country, source, salla_id (all optional except phone).
    Returns number of rows upserted.
    """
    if not _core._pool or not records:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            count = 0
            for r in records:
                phone = (r.get("phone") or "").strip()
                if not phone:
                    continue
                source = r.get("source", "chat")
                await conn.execute(
                    """
                    INSERT INTO contacts
                        (store_id, phone, name, email, company, city, country,
                         source, salla_id, last_seen, updated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW())
                    ON CONFLICT (store_id, phone) DO UPDATE SET
                        name      = CASE WHEN contacts.source='salla' OR excluded.source='salla'
                                         THEN GREATEST(excluded.name, contacts.name)
                                         ELSE COALESCE(NULLIF(excluded.name,''), contacts.name) END,
                        email     = COALESCE(NULLIF(excluded.email,''), contacts.email),
                        company   = COALESCE(NULLIF(excluded.company,''), contacts.company),
                        city      = COALESCE(NULLIF(excluded.city,''), contacts.city),
                        country   = COALESCE(NULLIF(excluded.country,''), contacts.country),
                        source    = CASE WHEN excluded.source='salla' THEN 'salla' ELSE contacts.source END,
                        salla_id  = COALESCE(excluded.salla_id, contacts.salla_id),
                        last_seen = GREATEST(excluded.last_seen, contacts.last_seen),
                        updated_at = NOW()
                    """,
                    store_id,
                    phone,
                    (r.get("name") or "").strip(),
                    (r.get("email") or "").strip(),
                    (r.get("company") or "").strip(),
                    (r.get("city") or "").strip(),
                    (r.get("country") or "").strip(),
                    source,
                    r.get("salla_id") or None,
                    r.get("last_seen") or None,
                )
                count += 1
        return count
    except Exception as e:
        print(f"[db] contacts_upsert_batch error: {e}")
        return 0
