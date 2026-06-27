"""database.comments — split out of the original single-file database.py."""
from database import _core
from database._core import _iso_z, _rows_affected




# ── Social comments (FB/IG comment automation) ──────────────────────────────
# Comments are PUBLIC, one-shot events (not threaded conversation sessions), so
# they live in their own tenant-scoped table rather than `conversations`. Every
# function here is store_id-scoped. See alembic 0014 + comments.py / comment_ai.

# Columns the API/pipeline may update post-insert. Whitelisted so column names
# can never come from caller input (the values are still parameterised).
_SOCIAL_COMMENT_UPDATABLE = {
    "sentiment", "intent", "category", "is_spam", "lead_score", "lead_temp",
    "ai_confidence", "status", "assigned_to", "suggested_reply", "final_reply",
    "replied_by", "replied_at",
}


def _social_comment_row(r) -> dict:
    return {
        "id":                  r["id"],
        "store_id":            r["store_id"],
        "platform":            r["platform"],
        "object_type":         r["object_type"],
        "external_comment_id": r["external_comment_id"],
        "parent_comment_id":   r["parent_comment_id"] or "",
        "post_id":             r["post_id"] or "",
        "recipient_id":        r["recipient_id"] or "",
        "author_id":           r["author_id"] or "",
        "author_name":         r["author_name"] or "",
        "message":             r["message"] or "",
        "permalink":           r["permalink"] or "",
        "sentiment":           r["sentiment"] or "",
        "intent":              r["intent"] or "",
        "category":            r["category"] or "",
        "is_spam":             bool(r["is_spam"]),
        "lead_score":          int(r["lead_score"] or 0),
        "lead_temp":           r["lead_temp"] or "",
        "ai_confidence":       float(r["ai_confidence"]) if r["ai_confidence"] is not None else None,
        "status":              r["status"],
        "assigned_to":         r["assigned_to"],
        "suggested_reply":     r["suggested_reply"] or "",
        "final_reply":         r["final_reply"] or "",
        "replied_by":          r["replied_by"] or "",
        "replied_at":          _iso_z(r["replied_at"]) if r["replied_at"] else "",
        "created_at":          _iso_z(r["created_at"]),
        "updated_at":          _iso_z(r["updated_at"]),
    }


async def social_comment_upsert(store_id: str, platform: str, comment: dict) -> dict:
    """
    Idempotent insert of one inbound comment, dedup on
    (store_id, platform, external_comment_id). Returns
    {"inserted": bool, "id": int|None}. inserted=False means Meta retried a
    delivery we already have — the caller should not re-run AI on it.

    `comment` is the dict produced by comments.extract_comments().
    """
    if not _core._pool:
        return {"inserted": False, "id": None}
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO social_comments
                    (store_id, platform, object_type, external_comment_id,
                     parent_comment_id, post_id, recipient_id, author_id,
                     author_name, message, permalink)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (store_id, platform, external_comment_id)
                DO NOTHING
                RETURNING id
                """,
                store_id, platform,
                comment.get("object_type", "comment"),
                str(comment.get("comment_id", "")),
                comment.get("parent_id", "") or None,
                comment.get("post_id", "") or None,
                comment.get("recipient_id", "") or None,
                comment.get("author_id", "") or None,
                comment.get("author_name", "") or "",
                comment.get("text", "") or "",
                comment.get("permalink", "") or None,
            )
        if row is None:
            return {"inserted": False, "id": None}
        return {"inserted": True, "id": int(row["id"])}
    except Exception as e:
        print(f"[db] social_comment_upsert error: {e}")
        return {"inserted": False, "id": None}


async def list_social_comments(store_id: str, *, status: str = "", platform: str = "",
                               lead_temp: str = "", limit: int = 100,
                               offset: int = 0) -> list[dict]:
    """Smart-Inbox listing, newest first. Optional status/platform/lead filters."""
    if not _core._pool:
        return []
    clauses = ["store_id = $1"]
    args: list = [store_id]
    if status:
        args.append(status);    clauses.append(f"status = ${len(args)}")
    if platform:
        args.append(platform);  clauses.append(f"platform = ${len(args)}")
    if lead_temp:
        args.append(lead_temp); clauses.append(f"lead_temp = ${len(args)}")
    args.append(max(1, min(int(limit or 100), 500)))
    lim = f"${len(args)}"
    args.append(max(0, int(offset or 0)))
    off = f"${len(args)}"
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM social_comments
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC
                LIMIT {lim} OFFSET {off}
                """,
                *args,
            )
        return [_social_comment_row(r) for r in rows]
    except Exception as e:
        print(f"[db] list_social_comments error: {e}")
        return []


async def get_social_comment(store_id: str, comment_pk: int) -> dict | None:
    """Fetch a single comment by primary key, tenant-scoped. None if not found."""
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT * FROM social_comments WHERE id = $1 AND store_id = $2",
                int(comment_pk), store_id,
            )
        return _social_comment_row(r) if r else None
    except Exception as e:
        print(f"[db] get_social_comment error: {e}")
        return None


async def update_social_comment(store_id: str, comment_pk: int, **fields) -> bool:
    """
    Patch whitelisted columns on a comment (tenant-scoped). Unknown keys are
    ignored. Always bumps updated_at. Returns True if a row was updated.
    """
    if not _core._pool:
        return False
    sets, args = [], []
    for k, v in fields.items():
        if k not in _SOCIAL_COMMENT_UPDATABLE:
            continue
        args.append(v)
        sets.append(f"{k} = ${len(args)}")
    if not sets:
        return False
    sets.append("updated_at = NOW()")
    args.append(int(comment_pk)); pk_ph = f"${len(args)}"
    args.append(store_id);        sid_ph = f"${len(args)}"
    try:
        async with _core._pool.acquire() as conn:
            res = await conn.execute(
                f"UPDATE social_comments SET {', '.join(sets)} "
                f"WHERE id = {pk_ph} AND store_id = {sid_ph}",
                *args,
            )
        return _rows_affected(res) > 0  # "UPDATE n"
    except Exception as e:
        print(f"[db] update_social_comment error: {e}")
        return False


# ── Comment rules (deterministic pre-LLM replies) ───────────────────────────

async def list_comment_rules(store_id: str) -> list[dict]:
    """Per-store reply rules, lowest priority value first (most specific)."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, priority, match_type, pattern, action, template, enabled
                FROM comment_rules WHERE store_id = $1
                ORDER BY priority ASC, id ASC
                """,
                store_id,
            )
        return [
            {
                "id":         r["id"],
                "priority":   int(r["priority"]),
                "match_type": r["match_type"],
                "pattern":    r["pattern"],
                "action":     r["action"],
                "template":   r["template"] or "",
                "enabled":    bool(r["enabled"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] list_comment_rules error: {e}")
        return []


async def add_comment_rule(store_id: str, *, match_type: str, pattern: str,
                           action: str, template: str = "", priority: int = 100,
                           enabled: bool = True) -> int | None:
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO comment_rules
                    (store_id, priority, match_type, pattern, action, template, enabled)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                RETURNING id
                """,
                store_id, int(priority), match_type, pattern, action,
                template or "", bool(enabled),
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] add_comment_rule error: {e}")
        return None


async def delete_comment_rule(store_id: str, rule_id: int) -> bool:
    if not _core._pool:
        return False
    try:
        async with _core._pool.acquire() as conn:
            res = await conn.execute(
                "DELETE FROM comment_rules WHERE id = $1 AND store_id = $2",
                int(rule_id), store_id,
            )
        return _rows_affected(res) > 0
    except Exception as e:
        print(f"[db] delete_comment_rule error: {e}")
        return False


# ── Store entitlements (minimal comment-feature gate) ───────────────────────

async def get_entitlements(store_id: str) -> dict:
    """Return {comments_enabled, comments_monthly_limit}. Defaults (disabled,
    0) when the store has no row yet."""
    default = {"comments_enabled": False, "comments_monthly_limit": 0}
    if not _core._pool:
        return default
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT comments_enabled, comments_monthly_limit "
                "FROM store_entitlements WHERE store_id = $1",
                store_id,
            )
        if not r:
            return default
        return {
            "comments_enabled":       bool(r["comments_enabled"]),
            "comments_monthly_limit": int(r["comments_monthly_limit"] or 0),
        }
    except Exception as e:
        print(f"[db] get_entitlements error: {e}")
        return default


async def get_entitlements_map() -> dict:
    """Return {store_id: comments_enabled} for every store that has a row.
    Used by the platform-ops snapshot to render the per-store toggle without
    an N+1 query. Stores absent from the map default to disabled."""
    if not _core._pool:
        return {}
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT store_id, comments_enabled FROM store_entitlements"
            )
        return {r["store_id"]: bool(r["comments_enabled"]) for r in rows}
    except Exception as e:
        print(f"[db] get_entitlements_map error: {e}")
        return {}


async def set_entitlements(store_id: str, *, comments_enabled: bool,
                           comments_monthly_limit: int = 0) -> None:
    """Upsert a store's comment-feature entitlement."""
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO store_entitlements
                    (store_id, comments_enabled, comments_monthly_limit, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (store_id) DO UPDATE
                   SET comments_enabled       = EXCLUDED.comments_enabled,
                       comments_monthly_limit = EXCLUDED.comments_monthly_limit,
                       updated_at             = NOW()
                """,
                store_id, bool(comments_enabled), int(comments_monthly_limit or 0),
            )
    except Exception as e:
        print(f"[db] set_entitlements error: {e}")


async def social_comment_analytics(store_id: str, days: int = 30) -> dict:
    """Aggregate comment metrics for the analytics dashboard (last `days`)."""
    empty = {
        "total": 0, "replied": 0, "ai_replied": 0, "response_rate": 0.0,
        "ai_response_rate": 0.0, "leads": 0, "avg_response_secs": 0,
        "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
    }
    if not _core._pool:
        return empty
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.fetchrow(
                """
                SELECT
                  COUNT(*)                                                          AS total,
                  COUNT(*) FILTER (WHERE status IN ('replied','ai_replied'))         AS replied,
                  COUNT(*) FILTER (WHERE status = 'replied' AND replied_by = 'ai')   AS ai_replied,
                  COUNT(*) FILTER (WHERE lead_temp IN ('hot','warm'))                AS leads,
                  COUNT(*) FILTER (WHERE sentiment = 'positive')                     AS positive,
                  COUNT(*) FILTER (WHERE sentiment = 'neutral')                      AS neutral,
                  COUNT(*) FILTER (WHERE sentiment = 'negative')                     AS negative,
                  AVG(EXTRACT(EPOCH FROM (replied_at - created_at)))
                      FILTER (WHERE replied_at IS NOT NULL)                          AS avg_secs
                FROM social_comments
                WHERE store_id = $1
                  AND created_at >= NOW() - make_interval(days => $2)
                """,
                store_id, int(days),
            )
        total   = int(r["total"] or 0)
        replied = int(r["replied"] or 0)
        ai_rep  = int(r["ai_replied"] or 0)
        return {
            "total":            total,
            "replied":          replied,
            "ai_replied":       ai_rep,
            "response_rate":    round(replied / total, 3) if total else 0.0,
            "ai_response_rate": round(ai_rep / replied, 3) if replied else 0.0,
            "leads":            int(r["leads"] or 0),
            "avg_response_secs": int(r["avg_secs"] or 0),
            "sentiment": {
                "positive": int(r["positive"] or 0),
                "neutral":  int(r["neutral"] or 0),
                "negative": int(r["negative"] or 0),
            },
        }
    except Exception as e:
        print(f"[db] social_comment_analytics error: {e}")
        return empty
