"""database.employees — split out of the original single-file database.py."""
import json
from database import _core
from database._core import _coerce_jsonb, _iso_z, _utcnow




# ── Employees ───────────────────────────────────────────────────────────────

async def list_employees(store_id: str) -> list[dict]:
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, store_id, name, email, role, active, created_at
                FROM employees
                WHERE store_id = $1
                ORDER BY created_at DESC
                """,
                store_id,
            )
        return [
            {
                "id":         int(r["id"]),
                "store_id":   r["store_id"],
                "name":       r["name"],
                "email":      r["email"],
                "role":       r["role"] or "agent",
                "active":     bool(r["active"]),
                "created_at": _iso_z(r["created_at"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] list_employees error: {e}")
        return []


async def add_employee(store_id: str, name: str, email: str,
                       password_hash: str, role: str = "agent",
                       active: bool = True) -> int | None:
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO employees (store_id, name, email, password_hash, role, active)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                store_id, name, email.lower(), password_hash,
                role or "agent", bool(active),
            )
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"[db] add_employee error: {e}")
        return None


async def get_employee(emp_id: int) -> dict | None:
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, store_id, name, email, password_hash, role, active, created_at
                FROM employees WHERE id = $1
                """,
                int(emp_id),
            )
        if not row:
            return None
        return {
            "id":            int(row["id"]),
            "store_id":      row["store_id"],
            "name":          row["name"],
            "email":         row["email"],
            "password_hash": row["password_hash"],
            "role":          row["role"] or "agent",
            "active":        bool(row["active"]),
            "created_at":    _iso_z(row["created_at"]),
        }
    except Exception as e:
        print(f"[db] get_employee error: {e}")
        return None


async def get_employee_by_email(store_id: str, email: str) -> dict | None:
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, store_id, name, email, password_hash, role, active, created_at
                FROM employees WHERE store_id = $1 AND email = $2
                """,
                store_id, email.lower(),
            )
        if not row:
            return None
        return {
            "id":            int(row["id"]),
            "store_id":      row["store_id"],
            "name":          row["name"],
            "email":         row["email"],
            "password_hash": row["password_hash"],
            "role":          row["role"] or "agent",
            "active":        bool(row["active"]),
            "created_at":    _iso_z(row["created_at"]),
        }
    except Exception as e:
        print(f"[db] get_employee_by_email error: {e}")
        return None


async def update_employee(emp_id: int, store_id: str, *, name: str | None = None,
                          email: str | None = None,
                          password_hash: str | None = None,
                          role: str | None = None,
                          active: bool | None = None) -> bool:
    if not _core._pool:
        return False
    sets: list[str] = []
    args: list = []
    if name is not None:
        sets.append(f"name = ${len(args)+1}"); args.append(name)
    if email is not None:
        sets.append(f"email = ${len(args)+1}"); args.append(email.lower())
    if password_hash is not None:
        sets.append(f"password_hash = ${len(args)+1}"); args.append(password_hash)
    if role is not None:
        sets.append(f"role = ${len(args)+1}"); args.append(role)
    if active is not None:
        sets.append(f"active = ${len(args)+1}"); args.append(bool(active))
    if not sets:
        return True
    args.append(int(emp_id))
    args.append(store_id)
    try:
        async with _core._pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE employees SET {', '.join(sets)} WHERE id = ${len(args)-1} AND store_id = ${len(args)}",
                *args,
            )
        return result != "UPDATE 0"
    except Exception as e:
        print(f"[db] update_employee error: {e}")
        return False


async def delete_employee(emp_id: int, store_id: str) -> bool:
    if not _core._pool:
        return False
    try:
        async with _core._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM employees WHERE id = $1 AND store_id = $2",
                int(emp_id), store_id,
            )
        return result != "DELETE 0"
    except Exception as e:
        print(f"[db] delete_employee error: {e}")
        return False


# ── Audit log (sensitive admin actions) ──────────────────────────────────
# Tiny API: write once per action, read for the audit viewer. Reads are
# paginated by created_at (newest first). Writes NEVER raise — losing an
# audit entry is better than failing the user's actual action because of
# a logging issue, but a missing entry is still loud in the server logs.

async def audit_record(
    actor: str,
    action: str,
    *,
    target_store: str = "",
    details: dict | None = None,
    ip: str = "",
    user_agent: str = "",
) -> None:
    """Insert one audit row. Trim user_agent to 500 chars to keep the row small."""
    if not _core._pool:
        return
    try:
        async with _core._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (actor, target_store, action, details, ip, user_agent)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                """,
                str(actor or "")[:200],
                str(target_store or "")[:200],
                str(action or "")[:100],
                json.dumps(details or {}, ensure_ascii=False, default=str),
                str(ip or "")[:64],
                str(user_agent or "")[:500],
            )
    except Exception as e:
        print(f"[db] audit_record({action!r}) error: {e}")


async def audit_list(
    *,
    store_id: str | None = None,
    action: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """
    Newest-first list of audit rows. `store_id=None` returns all stores
    (super-admin view); a store_id scopes to that store's own activity.
    `action` filter is exact-match on the action enum string.
    """
    if not _core._pool:
        return []
    limit  = max(1, min(int(limit  or 200), 1000))
    offset = max(0, int(offset or 0))
    where: list[str] = []
    params: list = []
    if store_id is not None:
        where.append(f"target_store = ${len(params) + 1}")
        params.append(store_id)
    if action:
        where.append(f"action = ${len(params) + 1}")
        params.append(action)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.extend([limit, offset])

    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, actor, target_store, action, details, ip, user_agent, created_at
                  FROM audit_log
                  {where_sql}
                 ORDER BY created_at DESC
                 LIMIT ${len(params) - 1}
                 OFFSET ${len(params)}
                """,
                *params,
            )
        return [
            {
                "id":           int(r["id"]),
                "actor":        r["actor"],
                "target_store": r["target_store"],
                "action":       r["action"],
                "details":      _coerce_jsonb(r["details"]),
                "ip":           r["ip"],
                "user_agent":   r["user_agent"],
                "created_at":   _iso_z(r["created_at"]),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[db] audit_list error: {e}")
        return []


# ── Support-access grants (JIT super access into a merchant's store) ────
#
# Tiny API. The auth middleware checks `support_access_active(store_id)`
# on every super-cross-store request, so the read is on the hot path.
# It's a single-row indexed lookup that returns the soonest expiring
# row for the store; cheap even at scale.

# Hard ceiling for grant duration. The owner picks (15m / 1h / 4h / 24h)
# from the UI but a malicious /direct POST shouldn't be able to set
# 365 days.
_MAX_GRANT_DURATION_MINUTES = 24 * 60


async def support_access_create(
    store_id: str,
    *,
    granted_by: str,
    duration_minutes: int,
    note: str = "",
) -> dict | None:
    """
    Create a new grant. Returns the new row dict, or None on failure /
    DB-down. duration_minutes is clamped to [1, _MAX_GRANT_DURATION_MINUTES].
    """
    if not _core._pool or not store_id:
        return None
    dur = max(1, min(int(duration_minutes or 60), _MAX_GRANT_DURATION_MINUTES))
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO support_access_grants
                    (store_id, granted_by, expires_at, note)
                VALUES ($1, $2, NOW() + ($3 || ' minutes')::interval, $4)
                RETURNING id, store_id, granted_by, granted_at, expires_at, note
                """,
                store_id, granted_by, str(dur), (note or "")[:500],
            )
        if not row:
            return None
        return {
            "id":           int(row["id"]),
            "store_id":     row["store_id"],
            "granted_by":   row["granted_by"],
            "granted_at":   _iso_z(row["granted_at"]),
            "expires_at":   _iso_z(row["expires_at"]),
            "note":         row["note"] or "",
            "revoked_at":   None,
        }
    except Exception as e:
        print(f"[db] support_access_create error: {e}")
        return None


async def support_access_revoke(grant_id: int, store_id: str) -> bool:
    """
    Revoke a grant. Scoped to store_id so an owner can't revoke another
    store's grant by guessing ids. Returns True on success.
    """
    if not _core._pool:
        return False
    try:
        async with _core._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE support_access_grants
                   SET revoked_at = NOW()
                 WHERE id = $1 AND store_id = $2 AND revoked_at IS NULL
                """,
                int(grant_id), store_id,
            )
        # asyncpg returns 'UPDATE <rowcount>'
        try:
            return int(result.split()[-1]) > 0
        except Exception:
            return False
    except Exception as e:
        print(f"[db] support_access_revoke error: {e}")
        return False


async def support_access_active(store_id: str) -> dict | None:
    """
    Hot path: is there an active grant for this store? Returns the
    earliest-expiring active grant (so the UI can show the right
    countdown), or None.
    """
    if not _core._pool or not store_id:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, store_id, granted_by, granted_at, expires_at, note
                  FROM support_access_grants
                 WHERE store_id   = $1
                   AND status     = 'active'
                   AND revoked_at IS NULL
                   AND expires_at > NOW()
                 ORDER BY expires_at ASC
                 LIMIT 1
                """,
                store_id,
            )
        if not row:
            return None
        return {
            "id":           int(row["id"]),
            "store_id":     row["store_id"],
            "granted_by":   row["granted_by"],
            "granted_at":   _iso_z(row["granted_at"]),
            "expires_at":   _iso_z(row["expires_at"]),
            "note":         row["note"] or "",
            "revoked_at":   None,
        }
    except Exception as e:
        print(f"[db] support_access_active error: {e}")
        return None


async def support_access_list(store_id: str, *, limit: int = 50) -> list[dict]:
    """
    All grants for a store, newest first. Owner UI uses it to show
    history (so the merchant sees who they granted to, when, and whether
    it was used). Includes revoked + expired rows so the trail is
    complete.
    """
    if not _core._pool:
        return []
    limit = max(1, min(int(limit or 50), 200))
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, store_id, granted_by, granted_at, expires_at, note,
                       revoked_at, status, requested_by, decided_by, decided_at
                  FROM support_access_grants
                 WHERE store_id = $1
                 ORDER BY granted_at DESC
                 LIMIT $2
                """,
                store_id, limit,
            )
        out = []
        for r in rows:
            now_active = (
                r["status"] == "active"
                and r["revoked_at"] is None
                and r["expires_at"] > _utcnow()
            )
            out.append({
                "id":           int(r["id"]),
                "store_id":     r["store_id"],
                "granted_by":   r["granted_by"],
                "granted_at":   _iso_z(r["granted_at"]),
                "expires_at":   _iso_z(r["expires_at"]),
                "note":         r["note"] or "",
                "revoked_at":   _iso_z(r["revoked_at"]) or None,
                "active":       now_active,
                "status":       r["status"],
                "requested_by": r["requested_by"],
                "decided_by":   r["decided_by"],
                "decided_at":   _iso_z(r["decided_at"]) or None,
            })
        return out
    except Exception as e:
        print(f"[db] support_access_list error: {e}")
        return []


def _sag_row(row) -> dict:
    """Shape a support_access_grants row into the API dict."""
    now_active = (
        row["status"] == "active"
        and row["revoked_at"] is None
        and row["expires_at"] > _utcnow()
    )
    return {
        "id":           int(row["id"]),
        "store_id":     row["store_id"],
        "granted_by":   row["granted_by"],
        "granted_at":   _iso_z(row["granted_at"]),
        "expires_at":   _iso_z(row["expires_at"]),
        "note":         row["note"] or "",
        "revoked_at":   _iso_z(row["revoked_at"]) or None,
        "active":       now_active,
        "status":       row["status"],
        "requested_by": row["requested_by"],
        "decided_by":   row["decided_by"],
        "decided_at":   _iso_z(row["decided_at"]) or None,
    }


async def support_access_request(
    store_id: str, *, requested_by: str, note: str = "",
) -> dict | None:
    """
    Create a PENDING access request (admin-initiated). It grants NO access
    until an owner/manager approves — `expires_at` is set in the past and
    `status='pending'` so support_access_active() never returns it.
    """
    if not _core._pool or not store_id:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO support_access_grants
                    (store_id, granted_by, expires_at, note, status, requested_by)
                VALUES ($1, '', NOW(), $2, 'pending', $3)
                RETURNING id, store_id, granted_by, granted_at, expires_at, note,
                          revoked_at, status, requested_by, decided_by, decided_at
                """,
                store_id, (note or "")[:500], (requested_by or "")[:200],
            )
        return _sag_row(row) if row else None
    except Exception as e:
        print(f"[db] support_access_request error: {e}")
        return None


async def support_access_pending(store_id: str) -> list[dict]:
    """Open (pending) access requests for a store — for the owner to act on."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, store_id, granted_by, granted_at, expires_at, note,
                       revoked_at, status, requested_by, decided_by, decided_at
                  FROM support_access_grants
                 WHERE store_id = $1 AND status = 'pending'
                 ORDER BY granted_at DESC
                """,
                store_id,
            )
        return [_sag_row(r) for r in rows]
    except Exception as e:
        print(f"[db] support_access_pending error: {e}")
        return []


async def support_access_approve(
    grant_id: int, store_id: str, *, decided_by: str, duration_minutes: int,
) -> dict | None:
    """
    Approve a pending request → active grant. The owner chooses the
    duration; the window starts NOW. Scoped to store_id + status='pending'
    so a stale/foreign id can't be approved. Returns the row or None.
    """
    if not _core._pool:
        return None
    dur = max(1, min(int(duration_minutes or 60), _MAX_GRANT_DURATION_MINUTES))
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE support_access_grants
                   SET status      = 'active',
                       granted_at  = NOW(),
                       expires_at  = NOW() + ($3 || ' minutes')::interval,
                       decided_by  = $4,
                       decided_at  = NOW()
                 WHERE id = $1 AND store_id = $2 AND status = 'pending'
                RETURNING id, store_id, granted_by, granted_at, expires_at, note,
                          revoked_at, status, requested_by, decided_by, decided_at
                """,
                int(grant_id), store_id, str(dur), (decided_by or "")[:200],
            )
        return _sag_row(row) if row else None
    except Exception as e:
        print(f"[db] support_access_approve error: {e}")
        return None


async def support_access_reject(
    grant_id: int, store_id: str, *, decided_by: str,
) -> bool:
    """Reject a pending request. Returns True if a pending row was updated."""
    if not _core._pool:
        return False
    try:
        async with _core._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE support_access_grants
                   SET status     = 'rejected',
                       revoked_at = NOW(),
                       decided_by = $3,
                       decided_at = NOW()
                 WHERE id = $1 AND store_id = $2 AND status = 'pending'
                """,
                int(grant_id), store_id, (decided_by or "")[:200],
            )
        try:
            return int(result.split()[-1]) > 0
        except Exception:
            return False
    except Exception as e:
        print(f"[db] support_access_reject error: {e}")
        return False
