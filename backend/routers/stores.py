"""
Store-level admin routes: sync, products, debug, register, diagnostics.
Super-admin platform-ops routes: registry-vs-db, reload-from-db, db-test.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Request

import auth as _auth
import database as db
import store_manager as sm
import store_brain as brain
from store_sync import sync_store
from models import ManualRegisterRequest

router = APIRouter()

# Lazy-bound at include time (set by main.py after lifecycle is wired)
_sync_task = None

def set_sync_task(fn):
    global _sync_task
    _sync_task = fn


# ── Sync ──────────────────────────────────────────────────────────────────────

@router.post("/admin/{store_id}/sync")
async def store_sync_endpoint(store_id: str):
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

    sm.register_store(
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


# ── Backward-compat aliases ───────────────────────────────────────────────────

@router.post("/admin/sync")
async def admin_sync_compat():
    stores = sm.list_stores()
    if not stores:
        raise HTTPException(400, "لا يوجد متاجر مسجّلة")
    return await store_sync_endpoint(stores[0]["store_id"])


@router.get("/admin/products")
async def admin_products_compat():
    stores = sm.list_stores()
    if not stores:
        return {"products": [], "total_products": 0}
    return await store_products(stores[0]["store_id"])


@router.get("/admin/debug")
async def admin_debug_compat():
    stores = sm.list_stores()
    if not stores:
        return {"error": "no stores registered"}
    return await store_debug(stores[0]["store_id"])


