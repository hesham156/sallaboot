"""
Lifecycle & background loops.

Extracted from main.py during Phase 2 modularisation. This module owns:
  • App startup / shutdown handlers (DB init, store load, listener start,
    flush-on-stop)
  • Periodic loops: token refresh, dirty-conversation flush, DB cleanup
  • Inbox + outbox drainers (the long-running tasks that process the
    durable queues from Phase 1)
  • Worker identity (_WORKER_ID) and the ENABLE_DRAINERS / ENABLE_PERIODIC
    env-var gates

Two entry points:
  • register(app) — wires startup/shutdown handlers onto a FastAPI app.
    main.py calls this; the web process gets the full lifecycle.
  • The individual loop coroutines are imported by worker.py so the
    worker process runs the same loops without the FastAPI app.

Cross-module dispatchers (inbox row → Salla / WhatsApp handler) are
imported lazily inside the loop bodies. This avoids circular imports
between lifecycle.py and main.py (which holds the webhook handlers
until P2-6 moves them to routers/webhooks.py).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import socket as _socket

import store_manager as sm
import database as db
import conversation_store as cs
import realtime
from store_sync import sync_store
import log as _logmod

log = _logmod.get_logger("backend.lifecycle")


# ─────────────────────────────────────────────────────────────────────────
# Process identity & env gates
# ─────────────────────────────────────────────────────────────────────────

# Stable identifier for this process. Used as:
#   • the `claimed_by` value when draining webhook_inbox / outbox rows
#   • the `holder` value when acquiring leader_locks (so we see which
#     instance is currently running periodic jobs from
#     SELECT * FROM leader_locks)
# Format: <role>:<hostname>:<pid>
WORKER_ID = f"{os.getenv('WORKER_ROLE', 'web')}:{_socket.gethostname()}:{os.getpid()}"

_INBOX_BATCH_SIZE  = int(os.getenv("INBOX_BATCH_SIZE",  "20"))
_OUTBOX_BATCH_SIZE = int(os.getenv("OUTBOX_BATCH_SIZE", "20"))


def enable_drainers() -> bool:
    """True unless the deploy explicitly turned inbox/outbox drainers off."""
    return os.getenv("ENABLE_DRAINERS", "true").lower() != "false"


def enable_periodic() -> bool:
    """True unless the deploy explicitly turned periodic loops off."""
    return os.getenv("ENABLE_PERIODIC", "true").lower() != "false"


# ─────────────────────────────────────────────────────────────────────────
# Per-store boot helpers
# ─────────────────────────────────────────────────────────────────────────

async def sync_task(store_id: str, token: str) -> None:
    """
    Background catalogue sync for a single store. Called on startup for
    every registered store and again whenever a store re-authorises.
    Never raises — sync failures are logged and the bot still answers
    using whatever cache was last persisted.
    """
    try:
        await sync_store(token, store_id)
        print(f"✅ Store sync completed for {store_id!r}")
    except Exception as e:
        print(f"⚠️ Store sync failed for {store_id!r}: {e}")


# ─────────────────────────────────────────────────────────────────────────
# Proactive token refresh
# ─────────────────────────────────────────────────────────────────────────

async def check_expiring_tokens() -> None:
    """
    Refresh any store token that expires within 2 days. Salla tokens have
    a 2-week TTL — without this loop the reactive (401-triggered) refresh
    in salla_client.py would fire mid-customer-conversation, adding ~300ms
    latency to one out of every few thousand chats.
    """
    from salla_oauth import refresh_access_token

    now       = _dt.datetime.utcnow()
    threshold = now + _dt.timedelta(days=2)
    refreshed = 0

    for store in sm.list_stores():
        sid            = store["store_id"]
        expires_at_str = sm.get_token_expires_at(sid)
        if not expires_at_str:
            continue  # no expiry data yet — rely on reactive 401 refresh
        try:
            expires_at = _dt.datetime.fromisoformat(expires_at_str)
        except Exception:
            continue
        if expires_at <= threshold:
            days_left = max(0, (expires_at - now).days)
            print(f"[token_refresh] 🔄 Store {sid!r} expires in {days_left}d — proactive refresh …")
            try:
                await refresh_access_token(sid)
                print(f"[token_refresh] ✅ Proactive refresh OK for {sid!r}")
                refreshed += 1
            except Exception as exc:
                print(f"[token_refresh] ❌ Proactive refresh FAILED for {sid!r}: {exc}")

    if refreshed:
        print(f"[token_refresh] {refreshed} store(s) refreshed proactively")


# ─────────────────────────────────────────────────────────────────────────
# Periodic loops (leader-elected — safe to run on every instance)
# ─────────────────────────────────────────────────────────────────────────

async def token_refresh_loop() -> None:
    """
    Hourly: refresh tokens expiring within 2 days. Leader-elected so two
    instances don't race on the same merchant's refresh_token (refreshing
    an already-refreshed token returns 400 from Salla and burns the
    refresh window).
    """
    await asyncio.sleep(120)          # let startup settle
    while True:
        try:
            if await db.try_lead("token_refresh", WORKER_ID, ttl_seconds=7200):
                await check_expiring_tokens()
        except Exception as exc:
            print(f"[token_refresh] Unexpected loop error: {exc}")
        await asyncio.sleep(3_600)


async def periodic_flush_loop() -> None:
    """
    Every 5 min: persist any sessions marked dirty (cart changes, customer
    info, etc — anything that didn't go through add_message). Leader-elected;
    TTL=10min gives a buffer if the leader stalls briefly.
    """
    await asyncio.sleep(60)
    while True:
        try:
            if await db.try_lead("periodic_flush", WORKER_ID, ttl_seconds=600):
                saved = await cs.flush_dirty()
                if saved:
                    print(f"[periodic_flush] 💾 Flushed {saved} dirty session(s) (leader={WORKER_ID})")
        except Exception as exc:
            print(f"[periodic_flush] ❌ Error: {exc}")
        await asyncio.sleep(300)


async def learning_loop() -> None:
    """
    Every 6h (leader-elected): mine each store's conversations for auto-learning
    suggestions — pending FAQ drafts from repeated questions + weak-spot lessons
    from negative reactions — and refresh the cached customer-insights prompt
    block. Every suggestion is saved DISABLED; it only reaches the bot after the
    admin approves it on the "تدريب البوت" page (same safety gate as corrections).
    """
    await asyncio.sleep(300)          # let startup settle
    while True:
        try:
            if db.available() and await db.try_lead("learning_mine", WORKER_ID, ttl_seconds=6 * 3600):
                import bot_learning as bl
                stores = [s["store_id"] for s in sm.list_stores()]
                total = 0
                for sid in stores:
                    try:
                        total += await bl.mine_store(sid)
                    except Exception:
                        log.exception("learning_mine_store_failed", extra={"store_id": sid})
                if total:
                    print(f"[learning] 🧠 {total} new pending suggestion(s) across "
                          f"{len(stores)} store(s) (leader={WORKER_ID})")
        except Exception:
            log.exception("learning_loop_top_level_error")
        await asyncio.sleep(6 * 3600)


async def backup_loop() -> None:
    """
    Daily (BACKUP_INTERVAL_HOURS): take an encrypted off-site DB backup and
    prune copies past the retention window. Leader-elected so a multi-instance
    deploy takes exactly one backup per window, not one per replica. No-op
    when R2 isn't configured, so it's safe to leave running everywhere.
    """
    import backup as _bk
    if not _bk.enabled():
        log.info("backup_loop_disabled_unconfigured")
        return
    await asyncio.sleep(240)          # let startup settle
    interval = _bk.interval_hours() * 3600
    while True:
        try:
            # TTL covers a worst-case dump+upload; the next tick renews it.
            if await db.try_lead("backup", WORKER_ID, ttl_seconds=interval + 600):
                res = await _bk.run_backup()
                if res["ok"]:
                    log.info("backup_loop_ok", extra={
                        "key": res["key"], "bytes": res["size_bytes"],
                        "pruned": res["pruned"],
                    })
                else:
                    log.error("backup_loop_failed", extra={"error": res["error"]})
        except Exception:
            log.exception("backup_loop_top_level_error")
        await asyncio.sleep(interval)


async def periodic_cleanup_loop() -> None:
    """
    Every 6h: prune the small bookkeeping tables. Leader-elected with a
    long TTL covering worst-case DELETE on a large table.

    Tables pruned:
      • webhook_seen (legacy — webhook_inbox UNIQUE replaced it)  — 24h
      • login_attempts (rate-limit window is 5 min)               — 24h
      • webhook_log                                                — 30d
      • webhook_inbox status='done' (dead rows kept)              — 14d
      • outbox status='done'                                       —  7d
      • widget_outbox delivered                                    — 24h
    """
    await asyncio.sleep(300)
    while True:
        try:
            if await db.try_lead("periodic_cleanup", WORKER_ID, ttl_seconds=3600):
                seen   = await db.prune_webhook_seen(keep_last_hours=24)
                logins = await db.prune_login_attempts(keep_last_hours=24)
                wlog   = await db.prune_webhook_log(keep_last_days=30)
                inbox  = await db.prune_inbox_done(keep_last_days=14)
                obox   = await db.prune_outbox_sent(keep_last_days=7)
                widget = await db.prune_widget_outbox_delivered(keep_last_hours=24)
                if seen or logins or wlog or inbox or obox or widget:
                    print(
                        f"[periodic_cleanup] 🧹 Pruned: webhook_seen={seen}, "
                        f"login_attempts={logins}, webhook_log={wlog}, "
                        f"inbox_done={inbox}, outbox_sent={obox}, "
                        f"widget_outbox={widget}"
                    )
        except Exception as exc:
            print(f"[periodic_cleanup] ❌ Error: {exc}")
        await asyncio.sleep(6 * 3600)


async def abandoned_cart_loop() -> None:
    """
    Every 30 min: poll connected platforms that don't push abandoned carts
    (Shopify) and record newly-abandoned ones — dashboard row + owner email +
    customer WhatsApp recovery, parity with Salla's abandoned.cart webhook.
    Leader-elected so only one instance polls each store.
    """
    await asyncio.sleep(180)          # let startup settle
    while True:
        try:
            if await db.try_lead("abandoned_cart_poll", WORKER_ID, ttl_seconds=1800):
                import shopify_sync as _ss
                import zid_sync as _zs
                await _ss.poll_abandoned_checkouts()
                await _zs.poll_zid_abandoned_carts()
        except Exception as exc:
            print(f"[abandoned_cart] loop error: {exc}")
        await asyncio.sleep(1800)


async def campaign_scheduler_loop() -> None:
    """Every 60s: fire any scheduled campaigns whose time has come."""
    await asyncio.sleep(60)
    while True:
        try:
            from campaign_sender import maybe_fire_scheduled
            await maybe_fire_scheduled()
        except Exception as exc:
            print(f"[campaign_scheduler] ❌ {exc}")
        await asyncio.sleep(60)


async def followup_loop() -> None:
    """
    Every 30 min: send due WhatsApp follow-ups to classified customers.
    Leader-elected so only one instance fires per window.
    """
    await asyncio.sleep(180)   # let startup settle
    while True:
        try:
            if await db.try_lead("followup_loop", WORKER_ID, ttl_seconds=1800):
                from customer_followup import run_followup_pass
                sent = await run_followup_pass()
                if sent:
                    log.info("followup_loop_sent", extra={"sent": sent})
        except Exception as exc:
            log.error("followup_loop_error", extra={"error": str(exc)})
        await asyncio.sleep(1800)   # 30 minutes


# ─────────────────────────────────────────────────────────────────────────
# Inbox + outbox drainers
# ─────────────────────────────────────────────────────────────────────────
# Safe to run on every instance. SELECT FOR UPDATE SKIP LOCKED gives each
# worker a disjoint slice of rows; there's no coordination cost.
#
# The actual per-row handlers live in main.py (for now — moved to
# routers/webhooks.py in P2-6). We import them lazily inside the drainer
# bodies so this module doesn't create a circular import.


async def inbox_drain_loop() -> None:
    """
    Drain webhook_inbox: claim → process → mark done/failed.
    Sleeps 1s when there's backlog, 5s when idle.
    """
    # Late import: main.py defines _process_inbox_row and it references
    # _handle_whatsapp_message / _process_salla_event that live in main
    # until P2-6 moves them to routers/webhooks.py.
    await asyncio.sleep(15)
    log.info("inbox_drainer_started", extra={"worker_id": WORKER_ID})
    while True:
        try:
            if not db.available():
                await asyncio.sleep(10)
                continue
            rows = await db.inbox_claim_batch(WORKER_ID, _INBOX_BATCH_SIZE)
            if not rows:
                await asyncio.sleep(5)
                continue
            import main as _main  # late binding; safe — main is loaded first
            for row in rows:
                inbox_id = row["id"]
                try:
                    await _main._process_inbox_row(row)
                    await db.inbox_mark_done(inbox_id)
                except Exception as exc:
                    log.warning("inbox_row_failed", extra={
                        "inbox_id": inbox_id,
                        "attempts": row["attempts"],
                        "err":      f"{type(exc).__name__}: {exc}"[:300],
                    })
                    await db.inbox_mark_failed(inbox_id, f"{type(exc).__name__}: {exc}", row["attempts"])
            if len(rows) >= _INBOX_BATCH_SIZE:
                continue
            await asyncio.sleep(1)
        except Exception:
            log.exception("inbox_drainer_top_level_error")
            await asyncio.sleep(5)


async def outbox_drain_loop() -> None:
    """Same shape as the inbox drainer, scoped to outbound side-effects."""
    await asyncio.sleep(20)
    log.info("outbox_drainer_started", extra={"worker_id": WORKER_ID})
    while True:
        try:
            if not db.available():
                await asyncio.sleep(10)
                continue
            rows = await db.outbox_claim_batch(WORKER_ID, _OUTBOX_BATCH_SIZE)
            if not rows:
                await asyncio.sleep(5)
                continue
            import main as _main
            for row in rows:
                outbox_id = row["id"]
                try:
                    await _main._deliver_outbox_row(row)
                    await db.outbox_mark_sent(outbox_id)
                except Exception as exc:
                    log.warning("outbox_row_failed", extra={
                        "outbox_id": outbox_id,
                        "kind":      row["kind"],
                        "attempts":  row["attempts"],
                        "err":       f"{type(exc).__name__}: {exc}"[:300],
                    })
                    await db.outbox_mark_failed(outbox_id, f"{type(exc).__name__}: {exc}", row["attempts"])
            if len(rows) >= _OUTBOX_BATCH_SIZE:
                continue
            await asyncio.sleep(1)
        except Exception:
            log.exception("outbox_drainer_top_level_error")
            await asyncio.sleep(5)


# ─────────────────────────────────────────────────────────────────────────
# Startup / shutdown handlers
# ─────────────────────────────────────────────────────────────────────────

async def startup() -> None:
    """
    Boot sequence:
      1. Connect Postgres pool
      2. Load stores from JSON files (fallback) then DB (canonical)
      3. Restore recent conversations + global app settings
      4. Open the realtime pubsub listener
      5. Register env-var SALLA_ACCESS_TOKEN as 'default' store if needed
      6. Trigger background catalogue sync per store
      7. Start periodic loops + drainers (gated by env vars)
      8. Print warnings for unsafe defaults
    """
    # 1. Connect to PostgreSQL (no-op if DATABASE_URL not set)
    await db.init()

    # 2. Load stores: JSON files first (fallback), then DB overwrites
    sm.load_all_stores()
    await sm.load_from_db()

    # 2b. Ensure the marketing/demo store exists so the chat widget on
    #     the public landing page has something to talk to. Idempotent —
    #     re-running just refreshes the knowledge-file content.
    try:
        import bootstrap
        await bootstrap.ensure_sallabot_store()
    except Exception as exc:
        log.warning("bootstrap_demo_store_failed", extra={"err": str(exc)[:200]})

    # 3. Restore recent conversations from DB
    await cs.load_conversations_from_db()

    # 4. Restore global app-level settings (e.g. bot_globally_enabled)
    await cs.load_globals_from_db()

    # 5. Open the realtime pubsub listener. Failure is non-fatal — the
    #    app degrades to polling-only mode when the listener can't
    #    connect (and SSE endpoints return 503 cleanly).
    await realtime.start()

    # Always register env-var token as "default" store — survives Railway restarts
    env_token = os.getenv("SALLA_ACCESS_TOKEN", "")
    if env_token and not sm.is_registered("default"):
        await sm.register_store(
            "default", env_token,
            os.getenv("SALLA_REFRESH_TOKEN", ""),
            {"name": "المتجر الافتراضي"},
        )
        print("[startup] Registered 'default' store from SALLA_ACCESS_TOKEN env var")

    for store in sm.list_stores():
        token = sm.get_access_token(store["store_id"])
        if token:
            asyncio.create_task(sync_task(store["store_id"], token))

    # Periodic loops (leader-elected — safe on every instance)
    if enable_periodic():
        asyncio.create_task(token_refresh_loop())
        asyncio.create_task(periodic_flush_loop())
        asyncio.create_task(periodic_cleanup_loop())
        asyncio.create_task(followup_loop())
        asyncio.create_task(campaign_scheduler_loop())
        asyncio.create_task(abandoned_cart_loop())
        asyncio.create_task(learning_loop())
        asyncio.create_task(backup_loop())
        print("[startup] 🔄💾🧹 Periodic loops registered (leader-elected)")
    else:
        print("[startup] ⏸ Periodic loops disabled (ENABLE_PERIODIC=false)")

    if enable_drainers():
        asyncio.create_task(inbox_drain_loop())
        asyncio.create_task(outbox_drain_loop())
        print("[startup] 📥📤 Inbox + outbox drainers registered")
    else:
        print("[startup] ⏸ Inbox + outbox drainers disabled (ENABLE_DRAINERS=false)")

    # ── Critical warning if DB is not connected ──────────────────────
    db_st = db.get_status()
    if not db_st["connected"]:
        if not db_st["database_url"]:
            print("=" * 60)
            print("⛔  WARNING: DATABASE_URL is NOT set!")
            print("    Store data (tokens, AI config, passwords) will be")
            print("    DELETED on every Railway deploy / restart.")
            print("    Fix: Add a PostgreSQL service in Railway and link it.")
            print("=" * 60)
        else:
            print("=" * 60)
            print("⛔  WARNING: DATABASE_URL is set but connection FAILED!")
            print("    Store data will NOT be persisted between deploys.")
            print("=" * 60)
    else:
        print(f"[startup] 💾 DB connected — {len(sm.list_stores())} stores persisted")


async def shutdown() -> None:
    """
    SIGTERM-friendly cleanup. Railway sends SIGTERM and waits ~10s.
    Order matters:
      1. Close the realtime listener so open SSE clients get a clean
         shutdown sentinel (their browser EventSource reconnects to a
         new instance).
      2. Flush every in-memory conversation to PostgreSQL so cart items,
         customer info, and messages survive the restart.
    """
    try:
        await realtime.stop()
    except Exception as exc:
        print(f"[shutdown] realtime.stop error: {exc}")
    if not db.available():
        return
    print("[shutdown] 💾 Flushing all conversations to DB …")
    saved = await cs.flush_all()
    print(f"[shutdown] ✅ Flushed {saved} conversation(s) to PostgreSQL")


def register(app) -> None:
    """
    Wire startup + shutdown onto a FastAPI app. Uses the @on_event
    decorator form — FastAPI 0.115 removed add_event_handler in favour
    of lifespan handlers, but on_event still works (deprecation only).
    Phase 2.x can replace this with the lifespan async-context-manager
    pattern when we touch FastAPI's lifespan API again.
    """
    app.on_event("startup")(startup)
    app.on_event("shutdown")(shutdown)
