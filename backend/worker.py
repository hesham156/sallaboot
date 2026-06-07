"""
Worker entrypoint — runs the durable inbox/outbox drainers and the
leader-elected periodic loops WITHOUT serving HTTP.

Why a separate process:
  • Drainer + periodic work doesn't share request-path latency; running
    them next to uvicorn means slow LLM tool calls or webhook spikes can
    interleave with periodic flushes.
  • Worker can be scaled independently (e.g. 1 worker, N web).
  • A misbehaving drainer can't OOM the HTTP servers.

How to deploy:
  • Same Docker image as the web service.
  • Start command: `python worker.py` (or `python -m worker`).
  • Set `ENABLE_DRAINERS=false` and `ENABLE_PERIODIC=false` on the WEB
    process so it stops running these loops in-process. The leader-lock
    layer makes leaving them on safe too — the env vars exist for
    efficiency, not correctness.

The worker reuses main.py's drainer + loop functions verbatim so there's
exactly one implementation of each piece of business logic. The
trade-off: importing main.py also imports FastAPI etc — a few MB of
unused code. Worth it to avoid two diverging code paths.
"""
from __future__ import annotations

import asyncio
import os
import signal

# Mark this process so leader_locks / claimed_by rows distinguish it from
# web instances. Must be set BEFORE importing main (the constant is built
# at module load).
os.environ.setdefault("WORKER_ROLE", "worker")

# Worker MUST run drainers + periodic (that's its job). Force-enable here
# even if the deploy env tried to disable them — a worker with both off
# would be a no-op and likely a misconfiguration.
os.environ["ENABLE_DRAINERS"] = "true"
os.environ["ENABLE_PERIODIC"] = "true"

import main  # noqa: E402  — env must be set first
import database as db  # noqa: E402
import conversation_store as cs  # noqa: E402
import store_manager as sm  # noqa: E402


async def _bootstrap() -> None:
    """
    Mirror the minimum init that main.startup_event does, minus the
    HTTP-only pieces (no FastAPI app, no sync of stores, no Salla product
    re-sync — that runs in the web process where users trigger it).
    """
    await db.init()
    sm.load_all_stores()
    await sm.load_from_db()
    await cs.load_conversations_from_db()
    await cs.load_globals_from_db()

    if not db.available():
        print("=" * 60)
        print("⛔  WORKER WARNING: DATABASE_URL not set or DB unreachable.")
        print("    Without a DB the inbox/outbox drainers have nothing to")
        print("    drain. The worker will idle until DB comes back.")
        print("=" * 60)
    else:
        print(f"[worker] 💾 DB connected — worker_id={main._WORKER_ID}")


async def _run() -> None:
    await _bootstrap()

    # Spawn the same coroutines the web process spawns. Wrapping them in
    # tasks so SIGTERM can cancel them cleanly.
    tasks = [
        asyncio.create_task(main._token_refresh_loop(),    name="token_refresh"),
        asyncio.create_task(main._periodic_flush_loop(),   name="periodic_flush"),
        asyncio.create_task(main._periodic_cleanup_loop(), name="periodic_cleanup"),
        asyncio.create_task(main._inbox_drain_loop(),      name="inbox_drain"),
        asyncio.create_task(main._outbox_drain_loop(),     name="outbox_drain"),
    ]
    print(f"[worker] 🚀 {len(tasks)} loops started — waiting for signals")

    # ── Graceful shutdown ────────────────────────────────────────────────
    # Railway sends SIGTERM and waits ~10s. On SIGTERM:
    #   • Stop the loops (they have their own try/except around iterations,
    #     so cancelling mid-sleep is harmless).
    #   • Flush any dirty conversations the in-memory cache still holds.
    #   • Release any leader_locks we own so the next worker picks them up
    #     immediately instead of waiting for TTL expiry.
    stop = asyncio.Event()

    def _handle_signal(sig_name: str):
        print(f"[worker] ⏸ received {sig_name} — shutting down")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig.name)
        except NotImplementedError:
            # Windows asyncio doesn't support add_signal_handler — fall back
            # to the default KeyboardInterrupt path on Ctrl+C.
            pass

    await stop.wait()

    # Cancel all background tasks and wait for them to finish their current
    # iteration. The drainer loops catch CancelledError implicitly via the
    # surrounding try/except.
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    # Flush dirty conversations one last time (in-process cache only — the
    # leader lock for periodic_flush is released so other workers can
    # cover ones we don't hold).
    if db.available():
        try:
            saved = await cs.flush_all()
            print(f"[worker] 💾 Flushed {saved} conversation(s) on shutdown")
        except Exception as exc:
            print(f"[worker] ⚠️ flush_all on shutdown failed: {exc}")

    # Release any leader locks we hold so the next worker picks up faster.
    # Safe even if we never won — release_leader is a no-op for non-holders.
    for lock_name in ("token_refresh", "periodic_flush", "periodic_cleanup"):
        try:
            await db.release_leader(lock_name, main._WORKER_ID)
        except Exception:
            pass

    print("[worker] 👋 exited cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("[worker] interrupted")
