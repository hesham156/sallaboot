"""database.ops — split out of the original single-file database.py."""
from database import _core
from database._core import _iso_z




# ── Bot training material ────────────────────────────────────────────────────

async def list_training(store_id: str) -> list[dict]:
    """Return all training entries for a store, newest first."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, kind, title, content, file_id, file_name,
                       size_chars, enabled, created_at
                FROM bot_training
                WHERE store_id = $1
                ORDER BY created_at DESC
                """,
                store_id,
            )
        return [
            {
                "id":         r["id"],
                "kind":       r["kind"],
                "title":      r["title"],
                "content":    r["content"] or "",
                "file_id":    r["file_id"] or "",
                "file_name":  r["file_name"] or "",
                "size_chars": int(r["size_chars"] or 0),
                "enabled":    bool(r["enabled"]),
                "created_at": _iso_z(r["created_at"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] list_training error: {e}")
        return []


async def add_training(store_id: str, kind: str, title: str, content: str,
                        file_id: str = "", file_name: str = "",
                        enabled: bool = True) -> int | None:
    """
    Insert one training row. Returns the new id, or None on failure.
    `enabled=False` is used for auto-learned lessons that wait for admin
    approval before they're injected into the bot's prompt.
    """
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO bot_training
                  (store_id, kind, title, content, file_id, file_name, size_chars, enabled)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                store_id, kind, title, content or "",
                file_id or None, file_name or None, len(content or ""), enabled,
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] add_training error: {e}")
        return None


async def update_training_enabled(training_id: int, enabled: bool, store_id: str) -> bool:
    """Toggle whether a training entry is included in the prompt.

    Scoped by store_id (finding M-1): the row is only updated when it belongs to
    the calling store, so a tenant can't toggle another tenant's training by
    guessing the global integer id. Returns True only when a row was affected.
    """
    if not _core._pool:
        return False
    try:
        async with _core._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE bot_training SET enabled = $1 WHERE id = $2 AND store_id = $3",
                enabled, int(training_id), store_id,
            )
        # asyncpg returns 'UPDATE <rowcount>'
        return int(result.split()[-1]) > 0
    except Exception as e:
        print(f"[db] update_training_enabled error: {e}")
        return False


async def delete_training(training_id: int, store_id: str) -> tuple[bool, str | None]:
    """Delete a training row. Returns (ok, deleted_file_id).

    Scoped by store_id (finding M-1): only deletes the row when it belongs to the
    calling store, so a tenant can't delete another tenant's training by guessing
    the global integer id. (ok=False, None) when no owned row matched.
    """
    if not _core._pool:
        return False, None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "DELETE FROM bot_training WHERE id = $1 AND store_id = $2 RETURNING file_id",
                int(training_id), store_id,
            )
        return (row is not None), (row["file_id"] if row else None)
    except Exception as e:
        print(f"[db] delete_training error: {e}")
        return False, None


# ── Webhook log (debugging + audit trail) ───────────────────────────────────

async def log_webhook(*, store_id: str = "", event: str = "", status: str = "ok",
                       detail: str = "", sig_status: str = "", body_head: str = "",
                       content_type: str = "", user_agent: str = "") -> None:
    """Append one webhook attempt row. Silent no-op when DB is unavailable."""
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO webhook_log
                  (store_id, event, status, detail, sig_status, body_head, content_type, user_agent)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                store_id or "", event or "", status or "", detail or "",
                sig_status or "", body_head or "", content_type or "", user_agent or "",
            )
    except Exception as e:
        print(f"[db] log_webhook error: {e}")


async def get_webhook_log(store_id: str | None = None, limit: int = 200) -> list[dict]:
    """Return the newest `limit` webhook rows, optionally filtered by store_id."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            if store_id:
                rows = await conn.fetch(
                    """
                    SELECT event, status, detail, sig_status, body_head,
                           content_type, user_agent, created_at
                    FROM webhook_log
                    WHERE store_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    store_id, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT store_id, event, status, detail, sig_status, body_head,
                           content_type, user_agent, created_at
                    FROM webhook_log
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
        return [
            {k: (_iso_z(v) if k == "created_at" and v else v) for k, v in dict(r).items()}
            for r in rows
        ]
    except Exception as e:
        print(f"[db] get_webhook_log error: {e}")
        return []


async def prune_webhook_log(keep_last_days: int = 30) -> int:
    """Delete webhook_log rows older than `keep_last_days`. Returns count deleted."""
    if not _core._pool:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.execute(
                f"DELETE FROM webhook_log WHERE created_at < NOW() - INTERVAL '{int(keep_last_days)} days'"
            )
        # asyncpg returns 'DELETE <n>' — parse the n
        try:
            return int(r.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_webhook_log error: {e}")
        return 0


# ── Webhook idempotency ─────────────────────────────────────────────────────

async def is_webhook_seen(dedup_key: str) -> bool:
    """True if this webhook key has already been processed. Atomic insert."""
    if not _core._pool or not dedup_key:
        return False
    try:
        async with _core._pool.acquire() as conn:
            # ON CONFLICT DO NOTHING + RETURNING tells us whether this was a new row
            row = await conn.fetchrow(
                """
                INSERT INTO webhook_seen (dedup_key) VALUES ($1)
                ON CONFLICT (dedup_key) DO NOTHING
                RETURNING dedup_key
                """,
                dedup_key,
            )
        # row is None when conflict happened → we've seen it before
        return row is None
    except Exception as e:
        print(f"[db] is_webhook_seen error: {e}")
        return False  # Fail-open: better to process duplicate than drop a real event


async def prune_webhook_seen(keep_last_hours: int = 24) -> int:
    """
    Drop dedup keys older than `keep_last_hours`. Salla retries up to 3× over
    15 min so 24h is plenty of safety margin.
    """
    if not _core._pool:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.execute(
                f"DELETE FROM webhook_seen WHERE created_at < NOW() - INTERVAL '{int(keep_last_hours)} hours'"
            )
        try:
            return int(r.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_webhook_seen error: {e}")
        return 0


# ── Login rate-limiting ─────────────────────────────────────────────────────

async def count_recent_login_attempts(attempt_key: str, window_secs: int) -> int:
    """Count attempts for this key in the last `window_secs` seconds."""
    if not _core._pool:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            n = await conn.fetchval(
                f"""
                SELECT COUNT(*) FROM login_attempts
                WHERE attempt_key = $1
                  AND created_at >= NOW() - INTERVAL '{int(window_secs)} seconds'
                """,
                attempt_key,
            )
        return int(n or 0)
    except Exception as e:
        print(f"[db] count_recent_login_attempts error: {e}")
        return 0


async def record_login_attempt(attempt_key: str) -> None:
    """Record a login attempt (success or failure)."""
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO login_attempts (attempt_key) VALUES ($1)",
                attempt_key,
            )
    except Exception as e:
        print(f"[db] record_login_attempt error: {e}")


async def prune_login_attempts(keep_last_hours: int = 24) -> int:
    """Delete old login attempts to keep the table small."""
    if not _core._pool:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.execute(
                f"DELETE FROM login_attempts WHERE created_at < NOW() - INTERVAL '{int(keep_last_hours)} hours'"
            )
        try:
            return int(r.split()[-1])
        except Exception:
            return 0
    except Exception as e:
        print(f"[db] prune_login_attempts error: {e}")
        return 0


# ── Uploads (persistent file storage in PostgreSQL) ──────────────────────────

async def save_upload(file_id: str, filename: str, content_type: str,
                       data: bytes, store_id: str = "", session_id: str = "") -> bool:
    """Persist an uploaded file to PostgreSQL. Returns True on success."""
    if not _core._pool:
        return False
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO uploads (file_id, filename, content_type, size_bytes, data, store_id, session_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                file_id, filename, content_type, len(data), data, store_id, session_id,
            )
        return True
    except Exception as e:
        print(f"[db] save_upload({file_id!r}) error: {e}")
        return False


async def load_upload(file_id: str) -> dict | None:
    """Read an uploaded file back from PostgreSQL. Returns None if missing."""
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT filename, content_type, data FROM uploads WHERE file_id = $1",
                file_id,
            )
        if not row:
            return None
        return {
            "filename":     row["filename"],
            "content_type": row["content_type"],
            "data":         bytes(row["data"]),
        }
    except Exception as e:
        print(f"[db] load_upload({file_id!r}) error: {e}")
        return None


# ── LLM token usage (daily circuit breaker) ─────────────────────────────────
# Three calls, all cheap:
#   • llm_usage_today(store_id)       — single-row indexed read; 0 if no row yet
#   • llm_usage_record(store_id, ti, to) — UPSERT on (store_id, today)
#   • llm_usage_report(store_id, days)  — 7- or 30-day chart for the admin UI
#
# The check happens BEFORE the LLM call and the record happens AFTER, so a
# burst of N concurrent /chat requests can race past the limit by up to N
# requests' worth of tokens. That's acceptable: the budget is a soft target
# anyway (real abuse comes from sustained traffic, not a 0.5s burst).

async def llm_usage_today(store_id: str) -> dict:
    """
    Tokens + request count consumed by `store_id` today (UTC).
    Returns zeros when the DB is down so the breaker fails open — refusing
    every chat because Postgres hiccupped would be worse than the abuse risk.
    """
    if not _core._pool:
        return {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "requests": 0}
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT tokens_in, tokens_out, requests
                  FROM llm_usage
                 WHERE store_id = $1 AND usage_date = (NOW() AT TIME ZONE 'UTC')::date
                """,
                store_id,
            )
        if not row:
            return {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "requests": 0}
        ti = int(row["tokens_in"])
        to = int(row["tokens_out"])
        return {
            "tokens_in":    ti,
            "tokens_out":   to,
            "tokens_total": ti + to,
            "requests":     int(row["requests"]),
        }
    except Exception as e:
        print(f"[db] llm_usage_today({store_id!r}) error: {e}")
        return {"tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "requests": 0}


async def llm_usage_record(store_id: str, tokens_in: int, tokens_out: int) -> dict:
    """
    UPSERT today's usage row and return the totals before/after the
    increment. Callers use the delta to check whether this request just
    crossed a budget threshold (80/90/100%) so they can fire an alert
    exactly once per crossing instead of on every subsequent request.

    Never raises — a failure here would lose a counter increment but
    should never block the user-facing reply that already succeeded.
    Returns zeros + delta=(ti+to) on failure so the caller's threshold
    math still works in the degraded path.
    """
    ti = max(0, int(tokens_in or 0))
    to = max(0, int(tokens_out or 0))
    if not _core._pool or not store_id:
        return {"before": 0, "after": ti + to, "delta": ti + to}
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO llm_usage (store_id, usage_date, tokens_in, tokens_out, requests, updated_at)
                VALUES ($1, (NOW() AT TIME ZONE 'UTC')::date, $2, $3, 1, NOW())
                ON CONFLICT (store_id, usage_date) DO UPDATE
                   SET tokens_in  = llm_usage.tokens_in  + EXCLUDED.tokens_in,
                       tokens_out = llm_usage.tokens_out + EXCLUDED.tokens_out,
                       requests   = llm_usage.requests   + 1,
                       updated_at = NOW()
                RETURNING (llm_usage.tokens_in + llm_usage.tokens_out) AS after_total
                """,
                store_id, ti, to,
            )
        after = int(row["after_total"]) if row else (ti + to)
        return {"before": after - (ti + to), "after": after, "delta": ti + to}
    except Exception as e:
        print(f"[db] llm_usage_record({store_id!r}) error: {e}")
        return {"before": 0, "after": ti + to, "delta": ti + to}


async def llm_usage_report(store_id: str, days: int = 7) -> list[dict]:
    """
    Last N days of usage for the admin dashboard, newest first. Includes
    zero-rows for missing days so the frontend can render a continuous bar
    chart without gap-filling logic.
    """
    if not _core._pool:
        return []
    days = max(1, min(int(days or 7), 90))
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH dates AS (
                    SELECT generate_series(
                        (NOW() AT TIME ZONE 'UTC')::date - ($1::int - 1),
                        (NOW() AT TIME ZONE 'UTC')::date,
                        '1 day'::interval
                    )::date AS d
                )
                SELECT d.d AS usage_date,
                       COALESCE(u.tokens_in,  0) AS tokens_in,
                       COALESCE(u.tokens_out, 0) AS tokens_out,
                       COALESCE(u.requests,   0) AS requests
                  FROM dates d
                  LEFT JOIN llm_usage u
                    ON u.store_id   = $2
                   AND u.usage_date = d.d
                 ORDER BY d.d DESC
                """,
                days, store_id,
            )
        return [
            {
                "date":         r["usage_date"].isoformat(),
                "tokens_in":    int(r["tokens_in"]),
                "tokens_out":   int(r["tokens_out"]),
                "tokens_total": int(r["tokens_in"]) + int(r["tokens_out"]),
                "requests":     int(r["requests"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] llm_usage_report({store_id!r}) error: {e}")
        return []


# ── Platform Operations aggregates (super-admin dashboard) ───────────────
# Surface read-only operational metrics so the platform owner can see the
# health of every store + queue at a glance. No customer data, no
# secrets — just counters, error counts, and top-N error lists.
#
# All queries are scoped to "today" (UTC) where time-based, so a single
# refresh of the dashboard shows current-day activity. Functions tolerate
# DB unavailability by returning empty/zero so the page still renders the
# operational layout instead of failing.

async def llm_tokens_today_all_stores() -> dict:
    """Platform-wide LLM totals + per-store breakdown for today."""
    if not _core._pool:
        return {"total_tokens": 0, "total_requests": 0, "per_store": []}
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT store_id,
                       (tokens_in + tokens_out) AS tokens_total,
                       tokens_in, tokens_out, requests
                  FROM llm_usage
                 WHERE usage_date = (NOW() AT TIME ZONE 'UTC')::date
                 ORDER BY (tokens_in + tokens_out) DESC
                """,
            )
        total_tok = sum(int(r["tokens_total"]) for r in rows)
        total_req = sum(int(r["requests"])     for r in rows)
        return {
            "total_tokens":   total_tok,
            "total_requests": total_req,
            "per_store": [
                {
                    "store_id":     r["store_id"],
                    "tokens_total": int(r["tokens_total"]),
                    "tokens_in":    int(r["tokens_in"]),
                    "tokens_out":   int(r["tokens_out"]),
                    "requests":     int(r["requests"]),
                }
                for r in rows
            ],
        }
    except Exception as e:
        print(f"[db] llm_tokens_today_all_stores error: {e}")
        return {"total_tokens": 0, "total_requests": 0, "per_store": []}


async def conversations_active_today() -> dict:
    """
    Active conversations + estimated message count today.

    "Active" = conversation row touched today (updated_at::date == today).
    "Messages today" is an approximation — we count rows where the
    last_activity in the JSONB blob falls on today. Accurate per-message
    timestamps would need a normalised messages table; we don't have one
    yet and adding it for a dashboard counter would be over-engineering.
    """
    if not _core._pool:
        return {"active_sessions": 0, "messages_today_estimate": 0}
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS active_sessions,
                    COALESCE(SUM(jsonb_array_length(data->'messages')), 0) AS msg_sum
                  FROM conversations
                 WHERE updated_at::date = (NOW() AT TIME ZONE 'UTC')::date
                """,
            )
        return {
            "active_sessions":         int(row["active_sessions"]) if row else 0,
            "messages_today_estimate": int(row["msg_sum"])         if row else 0,
        }
    except Exception as e:
        print(f"[db] conversations_active_today error: {e}")
        return {"active_sessions": 0, "messages_today_estimate": 0}


async def webhook_error_counts(window_hours: int = 24) -> dict:
    """
    Webhook errors in the last `window_hours`. Two slices: total count
    and a per-store top-N. Status 'rejected' covers signature failures.
    """
    if not _core._pool:
        return {"errors_24h": 0, "signature_failures_24h": 0, "top_stores": []}
    window_hours = max(1, min(int(window_hours or 24), 168))  # 1h–1w
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT
                    SUM(CASE WHEN status IN ('error', 'rejected') THEN 1 ELSE 0 END)::int AS errors,
                    SUM(CASE WHEN sig_status LIKE 'signature_%' AND status='rejected' THEN 1 ELSE 0 END)::int AS sig_fails
                  FROM webhook_log
                 WHERE created_at >= NOW() - INTERVAL '{window_hours} hours'
                """,
            )
            top = await conn.fetch(
                f"""
                SELECT store_id, COUNT(*) AS n
                  FROM webhook_log
                 WHERE status IN ('error', 'rejected')
                   AND created_at >= NOW() - INTERVAL '{window_hours} hours'
                   AND store_id <> ''
                 GROUP BY store_id
                 ORDER BY n DESC
                 LIMIT 5
                """,
            )
        return {
            "errors_24h":             int(row["errors"]    or 0) if row else 0,
            "signature_failures_24h": int(row["sig_fails"] or 0) if row else 0,
            "top_stores": [
                {"store_id": r["store_id"], "errors": int(r["n"])}
                for r in top
            ],
        }
    except Exception as e:
        print(f"[db] webhook_error_counts error: {e}")
        return {"errors_24h": 0, "signature_failures_24h": 0, "top_stores": []}


async def outbox_dead_top_stores(limit: int = 5) -> list[dict]:
    """Stores whose outbox has dead rows — they need operator attention."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT store_id, COUNT(*) AS n
                  FROM outbox
                 WHERE status = 'dead'
                   AND store_id IS NOT NULL AND store_id <> ''
                 GROUP BY store_id
                 ORDER BY n DESC
                 LIMIT $1
                """,
                int(limit),
            )
        return [{"store_id": r["store_id"], "dead": int(r["n"])} for r in rows]
    except Exception as e:
        print(f"[db] outbox_dead_top_stores error: {e}")
        return []


async def login_failures_24h() -> int:
    """Count failed login attempts in the last 24h (for the security card)."""
    if not _core._pool:
        return 0
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS n
                  FROM login_attempts
                 WHERE created_at >= NOW() - INTERVAL '24 hours'
                """,
            )
        return int(row["n"]) if row else 0
    except Exception as e:
        print(f"[db] login_failures_24h error: {e}")
        return 0
