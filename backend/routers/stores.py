"""
Store-level admin routes: sync, products, debug, register, diagnostics.
Super-admin platform-ops routes: registry-vs-db, reload-from-db, db-test.
"""
import asyncio
import datetime as _dt
import json
import os
import re
import tempfile
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

import auth as _auth
import database as db
import store_manager as sm
import store_brain as brain
from store_sync import sync_store
from models import ManualRegisterRequest
from routers.deps import audit, require_store_owner

router = APIRouter()


def _require_super(request: Request) -> dict:
    """Gate a route to the platform super-admin. Returns the claims."""
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(403, "مصرح للمدير العام فقط")
    return claims

# Lazy-bound at include time (set by main.py after lifecycle is wired)
_sync_task = None

def set_sync_task(fn):
    global _sync_task
    _sync_task = fn


# ── Sync ──────────────────────────────────────────────────────────────────────

@router.post("/admin/{store_id}/sync")
async def store_sync_endpoint(store_id: str):
    # ── Shopify store: delegate to Shopify sync ───────────────────────────────
    integrations_data = await db.get_integrations(store_id)
    shopify_data = integrations_data.get("shopify", {})
    if shopify_data.get("shop") and shopify_data.get("access_token"):
        from shopify_sync import sync_shopify_store
        try:
            result = await sync_shopify_store(
                store_id,
                shopify_data["shop"],
                shopify_data["access_token"],
            )
            return {
                "status":           "ok",
                "products_count":   result.get("products", 0),
                "categories_count": 0,
                "articles_count":   0,
                "last_sync":        None,
                "errors":           result.get("errors", []),
                "platform":         "shopify",
            }
        except Exception as e:
            raise HTTPException(500, f"{type(e).__name__}: {str(e)}")

    # ── Salla store ───────────────────────────────────────────────────────────
    token = sm.get_access_token(store_id)
    if not token:
        raise HTTPException(400, f"No access token for store '{store_id}'.")
    try:
        data = await sync_store(token, store_id)
        return {
            "status":           "ok",
            "products_count":   data.get("products_count", 0),
            "categories_count": len(data.get("categories", [])),
            "articles_count":   len(data.get("articles", [])),
            "last_sync":        data.get("last_sync"),
            "errors":           data.get("last_sync_errors", []),
            "platform":         "salla",
        }
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {str(e)}")


# ── Products ──────────────────────────────────────────────────────────────────

@router.get("/admin/{store_id}/products")
async def store_products(store_id: str, limit: int = 500, offset: int = 0):
    cache    = sm.get_cache(store_id)
    products = cache.get("products", [])
    total    = len(products)
    page     = products[offset : offset + limit] if limit > 0 else products
    return {
        "products":        page,
        "total_products":  total,
        "categories":      cache.get("categories", []),
        "articles":        cache.get("articles", []),
        "products_count":  cache.get("products_count", 0),
        "last_sync":       cache.get("last_sync", "never"),
        "errors":          cache.get("last_sync_errors", []),
    }


# ── Debug test-order ──────────────────────────────────────────────────────────

@router.post("/admin/{store_id}/debug/test-order")
async def debug_test_order(store_id: str, request: Request):
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    access = sm.get_access_token(store_id)
    if not access:
        return {"ok": False, "stage": "token", "error": "no access token for store"}

    from salla_client import SallaClient
    client = SallaClient(access, store_id=store_id)
    result: dict = {"ok": False, "store_id": store_id}

    try:
        presp = await client.create_product(
            name="🔧 منتج اختبار (تشخيص) — احذفه",
            price=1.0, product_type="service", unlimited_quantity=True,
            description="منتج تشخيص من لوحة التحكم", status="sale",
        )
        pid = (presp.get("data") or {}).get("id")
        result["product_created"] = bool(pid)
        result["product_id"] = pid
    except Exception as e:
        result["stage"] = "create_product"
        result["error"] = str(e)
        return result

    if not pid:
        result["stage"] = "create_product"
        result["error"] = "no product id returned"
        return result

    try:
        info = brain.get_store_info(store_id)
        img = (info.get("avatar") or "").strip() or \
              "https://cdn.assets.salla.network/prod/admin/cp/assets/images/placeholder.png"
        await client.attach_product_image_url(pid, img, alt="diagnostic")
        result["image_attached"] = True
    except Exception as e:
        result["image_attached"] = False
        result["image_error"] = str(e)

    test_customer = {"name": "عميل اختبار", "phone": "0500000000"}
    try:
        cresp = await client.create_customer(
            first_name="عميل", last_name="اختبار",
            mobile="500000000", mobile_code_country="+966",
        )
        tcid = (cresp.get("data") or {}).get("id")
        if tcid:
            test_customer = {"salla_customer_id": tcid}
            result["test_customer_id"] = tcid
    except Exception as e:
        try:
            fr = await client.get_customer_by_phone("500000000")
            fl = fr.get("data", [])
            fc = fl[0] if isinstance(fl, list) and fl else {}
            if fc.get("id"):
                test_customer = {"salla_customer_id": fc["id"]}
                result["test_customer_id"] = fc["id"]
            else:
                result["customer_note"] = str(e)
        except Exception as e2:
            result["customer_note"] = f"{e} | {e2}"

    try:
        oresp = await client.create_order(
            [{"product_id": pid, "quantity": 1}],
            test_customer,
            "طلب اختبار تشخيصي",
        )
        order = oresp.get("data") or {}
        result["order_created"] = bool(order.get("id"))
        result["order_id"]      = order.get("id")
        result["payment_url"]   = (order.get("urls") or {}).get("customer", "")
        result["ok"] = bool(order.get("id"))
    except Exception as e:
        result["stage"] = "create_order"
        result["error"] = str(e)

    return result


@router.get("/admin/{store_id}/debug")
async def store_debug(store_id: str):
    cache = sm.get_cache(store_id)
    cfg   = sm.get_ai_config(store_id) or {}
    info  = sm.get_store_info(store_id) or {}
    return {
        "store_id":       store_id,
        "registered":     sm.is_registered(store_id),
        "has_token":      bool(sm.get_access_token(store_id)),
        "products_count": cache.get("products_count", 0),
        "last_sync":      cache.get("last_sync", "never"),
        "store_name":     info.get("store_name", ""),
        "ai_model":       cfg.get("ai_model", ""),
        "provider":       "groq" if cfg.get("groq_api_key") else
                          "anthropic" if cfg.get("anthropic_api_key") else
                          "openai" if cfg.get("openai_api_key") else "env",
    }


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/admin/stores/register")
async def manual_register_store(req: ManualRegisterRequest, request: Request):
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(403, "مصرح للمدير العام فقط")

    store_id = req.store_id.strip()
    if not store_id or not req.access_token.strip():
        raise HTTPException(400, "store_id و access_token مطلوبان")

    await sm.register_store(
        store_id=store_id,
        access_token=req.access_token.strip(),
        refresh_token=req.refresh_token.strip(),
        store_info={"name": req.store_name.strip() or f"متجر {store_id}"},
    )

    persisted = False
    if db.available():
        try:
            tokens = sm.get_store_info(store_id)
            await db.save_store(store_id, tokens)
            persisted = True
            print(f"[admin] 💾 Store {store_id!r} persisted to DB synchronously")
        except Exception as exc:
            print(f"[admin] ❌ DB persist failed for {store_id!r}: {exc}")
            raise HTTPException(
                500,
                f"تم تسجيل المتجر في الذاكرة لكن فشل الحفظ في قاعدة البيانات: {exc}. "
                "المتجر سيُحذف عند أول إعادة تشغيل. راجع DATABASE_URL في Railway."
            )
    else:
        raise HTTPException(
            503,
            "قاعدة البيانات غير متصلة. المتاجر ستُحذف عند أول deploy. "
            "افتح Railway → أضف Postgres service → اربط DATABASE_URL."
        )

    if _sync_task:
        asyncio.create_task(_sync_task(store_id, req.access_token.strip()))
    return {
        "status":    "ok",
        "store_id":  store_id,
        "persisted": persisted,
        "message":   f"تم تسجيل المتجر {store_id!r} وحفظه في قاعدة البيانات ✅",
    }


# ── Platform diagnostics ──────────────────────────────────────────────────────

@router.get("/admin/registry-vs-db")
async def registry_vs_db(request: Request):
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    db_rows    = await db.list_raw_stores() if db.available() else []
    memory     = sm.list_stores()
    db_ids     = {r["store_id"] for r in db_rows}
    memory_ids = {s["store_id"] for s in memory}

    return {
        "db_connected":   db.available(),
        "in_db":          len(db_rows),
        "in_memory":      len(memory),
        "only_in_db":     sorted(db_ids - memory_ids),
        "only_in_memory": sorted(memory_ids - db_ids),
        "in_both":        sorted(db_ids & memory_ids),
        "db_rows":        db_rows,
        "memory_rows":    memory,
    }


@router.post("/admin/reload-from-db")
async def reload_from_db(request: Request):
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    before = len(sm.list_stores())
    await sm.load_from_db()
    after = len(sm.list_stores())
    return {
        "status":  "ok",
        "before":  before,
        "after":   after,
        "loaded":  after - before,
        "message": f"تم إعادة التحميل من DB — {before} → {after} متجر",
    }


@router.post("/admin/backfill-owner-emails")
async def backfill_owner_emails(request: Request):
    """
    Walk every registered store that doesn't have an owner_email yet,
    call Salla's /oauth2/user/info with the stored access_token, and
    save the returned email. Used to migrate stores installed BEFORE
    the unified email/password login shipped — without this they can't
    sign in through the new UI.

    Stores whose access_token is missing OR has expired without a
    working refresh path are reported under `failed`. The endpoint is
    safe to re-run: it skips stores that already have an email.
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    from salla_oauth import get_user_info, refresh_access_token
    from salla_client import SallaClient

    filled:  list[dict] = []
    skipped: list[dict] = []
    failed:  list[dict] = []

    async def _fetch_email_and_meta(tok: str) -> tuple[str, dict]:
        """Pull the owner email + store metadata (name/domain/avatar/url) in
        parallel: /oauth2/user/info → email; /store/info → metadata. Returns
        ('', {}) on per-call failure so the caller can decide whether one
        signal is enough."""
        email: str = ""
        meta:  dict = {}
        try:
            info = await get_user_info(tok)
            data = info.get("data") or {}
            email = (data.get("email") or "").strip().lower()
        except Exception as exc:
            print(f"[backfill] user_info failed: {exc}")
        try:
            cli = SallaClient(tok)
            si  = (await cli.get_store_info()).get("data") or {}
            meta = {
                "name":   (si.get("name")   or "").strip(),
                "domain": (si.get("domain") or "").strip(),
                "avatar": (si.get("avatar") or "").strip(),
                "url":    (si.get("url")    or "").strip(),
                "email":  (si.get("email")  or "").strip().lower(),
            }
            # Some merchants leave the OAuth user email blank but the store
            # email is populated — use it as a fallback.
            if not email and meta["email"]:
                email = meta["email"]
        except Exception as exc:
            print(f"[backfill] store_info failed: {exc}")
        return email, meta

    for s in sm.list_stores():
        store_id      = s["store_id"]
        existing_email = (s.get("owner_email")  or "").strip().lower()
        existing_domain = (s.get("store_domain") or "").strip()
        # Skip stores that already have BOTH — nothing to refresh
        if existing_email and existing_domain:
            skipped.append({
                "store_id": store_id,
                "reason":   "already_has_email_and_domain",
                "email":    existing_email,
                "domain":   existing_domain,
            })
            continue

        access_token = sm.get_access_token(store_id)
        if not access_token:
            failed.append({"store_id": store_id, "reason": "no_access_token"})
            continue

        # Try once with the current token; if both calls 401, refresh and
        # retry once. We swallow per-store errors so one broken token
        # doesn't abort the whole batch.
        email, meta = await _fetch_email_and_meta(access_token)
        if not email and not meta:
            try:
                new_token   = await refresh_access_token(store_id)
                email, meta = await _fetch_email_and_meta(new_token)
            except Exception as exc:
                failed.append({
                    "store_id": store_id,
                    "reason":   f"refresh_failed: {str(exc)[:120]}",
                })
                continue

        if not email and not meta:
            failed.append({"store_id": store_id, "reason": "salla_returned_nothing"})
            continue

        # Email goes through the dedicated owner_email setter (registry +
        # DB column). Metadata goes through update_store_info → save_store
        # which lands in the tokens JSONB blob.
        if email and not existing_email:
            await sm.set_owner_email(store_id, email)
        if meta:
            tokens = dict(sm.get_store_info(store_id) or {})
            updated = False
            if meta.get("name")   and tokens.get("store_name")   != meta["name"]:
                tokens["store_name"]   = meta["name"];   updated = True
            if meta.get("domain") and tokens.get("store_domain") != meta["domain"]:
                tokens["store_domain"] = meta["domain"]; updated = True
            if meta.get("avatar") and tokens.get("store_avatar") != meta["avatar"]:
                tokens["store_avatar"] = meta["avatar"]; updated = True
            if meta.get("url")    and tokens.get("store_url")    != meta["url"]:
                tokens["store_url"]    = meta["url"];    updated = True
            if updated:
                sm.update_store_info(store_id, tokens)
                if db.available():
                    db.fire(db.save_store(store_id, tokens))

        filled.append({
            "store_id": store_id,
            "email":    email or existing_email,
            "domain":   (meta.get("domain") if meta else "") or existing_domain,
        })

    return {
        "status":      "ok",
        "filled":      len(filled),
        "skipped":     len(skipped),
        "failed":      len(failed),
        "filled_rows": filled,
        "failed_rows": failed,
        "message":     f"تم تحديث {len(filled)} متجر، تخطّي {len(skipped)}، فشل {len(failed)}",
    }


@router.post("/admin/sallabot/reload-knowledge")
async def sallabot_reload_knowledge(request: Request):
    """
    Super-only: re-read backend/data/sallabot_knowledge.md and overwrite
    the demo store's custom_knowledge. Use this after editing the .md and
    redeploying — the regular bootstrap only seeds knowledge on first
    install so UI edits don't get clobbered, which means file changes
    need an explicit reload (or the SALLABOT_FORCE_RELOAD_KNOWLEDGE env).
    """
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    import bootstrap
    result = await bootstrap.reload_knowledge_from_file()
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "reload failed"))
    return {
        "status":  "ok",
        "loaded":  result["loaded_chars"],
        "file":    result["file"],
        "message": f"تم إعادة تحميل {result['loaded_chars']} حرف من الملف",
    }


@router.get("/admin/db-test")
async def db_diagnostic(request: Request):
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token)
    if not claims or not claims.get("su"):
        raise HTTPException(401, "يرجى تسجيل الدخول كمدير عام")

    import os
    result = await db.test_round_trip()
    result["env_database_url_set"] = bool(os.getenv("DATABASE_URL", "").strip())
    result["in_memory_stores"]     = len(sm.list_stores())
    return result


# ── Suspend / resume a store's subscription (super-admin) ─────────────────────

@router.post("/admin/stores/{store_id}/suspend")
async def suspend_store(store_id: str, request: Request):
    """Pause a store's subscription: data is kept but the bot stops serving
    customers on every channel. Reversible via /resume."""
    _require_super(request)
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    if not await sm.set_suspended(store_id, True):
        raise HTTPException(503, "تعذّر إيقاف المتجر")
    await audit(request, "store_suspended", target_store=store_id)
    return {"status": "ok", "store_id": store_id, "suspended": True}


@router.post("/admin/stores/{store_id}/resume")
async def resume_store(store_id: str, request: Request):
    """Re-activate a suspended store."""
    _require_super(request)
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")
    if not await sm.set_suspended(store_id, False):
        raise HTTPException(503, "تعذّر تفعيل المتجر")
    await audit(request, "store_resumed", target_store=store_id)
    return {"status": "ok", "store_id": store_id, "suspended": False}


# ── Delete a store entirely (super-admin) ─────────────────────────────────────

@router.delete("/admin/stores/{store_id}")
async def delete_store(store_id: str, request: Request):
    """Permanently delete a store and ALL its data (conversations, contacts,
    orders, employees, …) from the DB and the in-memory registry. Destructive
    and irreversible — super-admin only."""
    _require_super(request)
    if not sm.is_registered(store_id) and not db.available():
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    counts = await db.purge_store(store_id) if db.available() else {}
    sm.unregister_store(store_id)

    await audit(request, "store_deleted", target_store=store_id, details={
        "purged": counts,
    })
    return {"status": "ok", "store_id": store_id, "purged": counts}


# ── Export a store's data (owner / super) ─────────────────────────────────────

# Cap on the total upload bytes bundled into one export, so a store with
# huge attachments can't OOM the process. Files past the cap are listed in
# metadata.json under "uploads_skipped". Override via env if needed.
_EXPORT_MAX_UPLOAD_BYTES = int(os.getenv("EXPORT_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))

_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-؀-ۿ ]+")


def _safe_name(name: str) -> str:
    """Flatten a user-supplied filename to a single safe path segment
    (no separators, no traversal). Keeps Arabic letters readable."""
    base = (name or "file").replace("\\", "/").split("/")[-1]
    base = _UNSAFE_NAME_RE.sub("_", base).strip(". ") or "file"
    return base[:120]


@router.get("/admin/{store_id}/export")
async def export_store_data(store_id: str, request: Request):
    """
    Download EVERYTHING this store owns as a ZIP — the data-portability
    counterpart to the data-deletion flow (PDPL / GDPR Art. 20). Owner or
    super only; employees are blocked.

    Archive layout:
      • metadata.json — store_id, generated_at, record counts, skipped uploads
      • data.json     — every per-store table row (secrets/PII-hashes redacted)
      • uploads/<file_id>__<filename> — the actual uploaded files (up to the cap)
    """
    require_store_owner(request, store_id)   # owner or super; raises on employee
    if not db.available():
        raise HTTPException(503, "قاعدة البيانات غير متاحة — التصدير يتطلب اتصالاً بقاعدة البيانات")
    if not sm.is_registered(store_id):
        raise HTTPException(404, f"المتجر '{store_id}' غير مسجّل")

    data = await db.export_store(store_id)
    if not data:
        raise HTTPException(404, "لا توجد بيانات للتصدير")

    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    skipped: list[str] = []

    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            seen: dict[str, int] = {}
            async for file_id, filename, _ctype, blob in db.fetch_store_upload_blobs(
                store_id, _EXPORT_MAX_UPLOAD_BYTES, skipped
            ):
                arc = f"uploads/{file_id}__{_safe_name(filename)}"
                # Guard against the (unlikely) duplicate arcname.
                if arc in seen:
                    seen[arc] += 1
                    arc = f"uploads/{file_id}_{seen[arc]}__{_safe_name(filename)}"
                else:
                    seen[arc] = 0
                zf.writestr(arc, blob)

            meta = {
                "store_id":       store_id,
                "generated_at":   _dt.datetime.now(_dt.timezone.utc)
                                      .isoformat().replace("+00:00", "Z"),
                "schema_version": 1,
                "record_counts":  counts,
                "uploads_skipped": skipped,
                "note": ("Secrets are redacted: OAuth access/refresh tokens, "
                         "provider API keys, the store linking key, and employee "
                         "password hashes are NOT included."),
            }
            zf.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))
            zf.writestr("data.json", json.dumps(data, ensure_ascii=False, indent=2, default=str))
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    await audit(request, "store_data_exported", target_store=store_id, details={
        "record_counts":   counts,
        "uploads_skipped": len(skipped),
    })

    filename = f"export_{store_id}_{_dt.date.today().isoformat()}.zip"
    return FileResponse(
        tmp,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(os.remove, tmp),
    )


# ── Removed: unauthenticated backward-compat aliases ──────────────────────────
# The store-less /admin/sync (POST), /admin/products and /admin/debug aliases
# were deleted. Like the conversation aliases, they bypassed the admin auth
# middleware (single-segment paths) with no inline auth — /admin/sync let an
# anonymous caller trigger a catalogue sync, /admin/debug leaked store internals
# — and they targeted stores[0], which is arbitrary under multi-tenant. Use the
# authenticated /admin/{store_id}/{sync,products,debug} routes instead.


