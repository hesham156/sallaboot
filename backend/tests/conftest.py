"""
Pytest fixtures shared across the test suite.

Three layers:
  1. Pure unit fixtures (env stubs, frozen secrets) — always available.
  2. DB fixture — tries TEST_DATABASE_URL first, then testcontainers, then
     skip-markers the test gracefully. Per-session DB is shared so the
     ~1.5s container spin-up amortises across hundreds of tests.
  3. App fixture — FastAPI AsyncClient bound to the test DB. Per-test
     schema is reset via TRUNCATE so tests don't leak state.

Test DB strategy:
  • TEST_DATABASE_URL set → use it (CI provides a managed Postgres).
  • Docker available → start a testcontainers Postgres.
  • Neither → integration-marked tests skip with a clear reason.
"""
from __future__ import annotations

import asyncio
import os
import sys
import warnings
from pathlib import Path
from typing import AsyncIterator

# Silence pre-existing FastAPI deprecation warnings at import time. pytest.ini
# filterwarnings only kicks in at test execution, not during collection /
# module import — and `main.py` uses the deprecated @app.on_event decorators
# at module level. Phase 2's modularisation will replace them.
# The on_event deprecation message spans multiple lines (starts with \n),
# so a `.*` prefix in the pattern doesn't match without DOTALL. Use (?s).
warnings.filterwarnings(
    "ignore",
    message=r"(?s).*on_event is deprecated.*",
    category=DeprecationWarning,
)
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"fastapi\..*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"typing_extensions")

import pytest

# Make backend/ importable from tests/ without installing as a package.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# ── Frozen env for the whole test session ─────────────────────────────────
# Set BEFORE any application code is imported. Anything that reads env at
# module load time (auth.ADMIN_SECRET, main._WORKER_ID) must see these.
os.environ.setdefault("ADMIN_SECRET",            "test-admin-secret-32-bytes-of-hex")
os.environ.setdefault("SALLA_WEBHOOK_SECRET",    "test-webhook-secret")
os.environ.setdefault("SUPER_ADMIN_EMAIL",       "test@admin.example")
os.environ.setdefault("SUPER_ADMIN_PASSWORD",    "test-super-pw")
os.environ.setdefault("BASE_URL",                "https://test.sallabot.example")
os.environ.setdefault("ADMIN_ALLOWED_ORIGINS",   "https://admin.example,https://dash.example")
# Drainers OFF by default in tests — each test that needs them runs its
# drain step explicitly so timing is deterministic.
os.environ.setdefault("ENABLE_DRAINERS",         "false")
os.environ.setdefault("ENABLE_PERIODIC",         "false")


# ── Async event loop ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """
    Session-scoped event loop so the DB pool / testcontainer survive
    across tests. Default pytest-asyncio gives one loop per function which
    would force a pool re-create every time.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Database URL resolution ───────────────────────────────────────────────

def _maybe_start_testcontainer() -> tuple[str | None, object | None]:
    """
    Try to start a Postgres testcontainer. Returns (dsn, container) on
    success; (None, None) on failure (Docker missing, no image, etc).
    Failures are not test errors — the DB-dependent tests just skip.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        return None, None
    try:
        # postgres:16 alpine is small and matches Railway's default.
        container = PostgresContainer("postgres:16-alpine")
        container.start()
        dsn = container.get_connection_url()
        # testcontainers returns a SQLAlchemy URL with the psycopg2 driver
        # hint (postgresql+psycopg2://). asyncpg wants plain postgresql://.
        if "+psycopg2://" in dsn:
            dsn = dsn.replace("+psycopg2://", "://", 1)
        return dsn, container
    except Exception as exc:
        print(f"[conftest] Could not start Postgres container: {exc}")
        return None, None


@pytest.fixture(scope="session")
def db_dsn() -> str | None:
    """
    Session-scoped Postgres DSN. Priority:
      1. TEST_DATABASE_URL env var (CI / dev with existing DB)
      2. Spin up a testcontainer (local dev with Docker)
      3. Return None → integration tests skip
    """
    env_dsn = (os.getenv("TEST_DATABASE_URL") or "").strip()
    if env_dsn:
        # Normalise asyncpg-style: postgres:// → postgresql://
        if env_dsn.startswith("postgres://"):
            env_dsn = "postgresql://" + env_dsn[len("postgres://"):]
        return env_dsn

    dsn, container = _maybe_start_testcontainer()
    if dsn:
        # Stash the container on the fixture's request scope so teardown
        # is guaranteed — pytest doesn't yield it via this fixture because
        # callers only need the DSN.
        import atexit
        atexit.register(container.stop)
        return dsn
    return None


# ── DB schema + pool ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
async def db_pool(db_dsn):
    """
    Initialise database.py against the test DSN and yield. Re-uses the
    same connection pool across all tests in the session.
    """
    if not db_dsn:
        pytest.skip("No DB available (set TEST_DATABASE_URL or install Docker)")

    os.environ["DATABASE_URL"] = db_dsn
    import database as db
    ok = await db.init()
    assert ok, f"db.init() failed against {db_dsn}"
    yield db
    # Don't close the pool here — atexit on the testcontainer handles it.


@pytest.fixture
async def clean_db(db_pool):
    """
    Per-test schema reset. Truncates every table we care about between
    tests so test ordering doesn't matter. Much faster than recreating
    the DB or re-running migrations per test.
    """
    db = db_pool
    # TRUNCATE … RESTART IDENTITY CASCADE resets BIGSERIAL counters too,
    # so tests can assert on stable ids when they need to.
    tables = [
        "webhook_inbox", "outbox", "leader_locks",
        "webhook_log", "webhook_seen", "login_attempts",
        "conversations", "abandoned_carts", "uploads",
        "bot_training", "bot_orders", "employees",
        "app_settings", "stores", "llm_usage", "audit_log",
        "support_access_grants", "widget_outbox",
    ]
    async with db._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE TABLE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"
        )
    yield db


# ── FastAPI test client ───────────────────────────────────────────────────

@pytest.fixture
async def app_client(clean_db) -> AsyncIterator:
    """
    httpx.AsyncClient bound to the in-process FastAPI app. The DB has
    already been initialised by clean_db (which depends on db_pool).
    No real HTTP server starts — ASGI-level transport.
    """
    from httpx import AsyncClient, ASGITransport
    # Import main lazily so it sees the test env vars and the initialised DB.
    import main
    transport = ASGITransport(app=main.app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=10.0,
    ) as client:
        yield client


# ── Cleanup of in-memory caches between tests ─────────────────────────────

@pytest.fixture(autouse=True)
def _reset_in_memory_state():
    """
    Reset module-level caches between tests. store_manager._registry
    is still a plain dict. conversation_store._conversations is now a
    ContextVar; it's task-scoped so it would already reset between
    tests, but we still explicitly clear it to be safe under any
    async-loop reuse patterns the runner introduces.
    """
    yield
    try:
        import store_manager as sm
        sm._registry.clear()
    except Exception:
        pass
    try:
        import conversation_store as cs
        # ContextVar reset — set to an empty dict so the next test
        # starts with a fresh, deterministic cache regardless of the
        # event-loop / context inheritance chain pytest sets up.
        cs._conversations.set({})
    except Exception:
        pass


# ── Helpers exposed to tests ──────────────────────────────────────────────

@pytest.fixture
def make_token():
    """
    Helper: build an admin or store-scoped token without going through
    the login endpoints. Tests that aren't exercising auth itself can
    use this as a one-liner.
    """
    import auth as _auth

    def _make(store_id: str = "test-store", *, is_super: bool = False,
              employee_id: int | None = None, role: str = "agent") -> str:
        return _auth.create_token(
            store_id,
            is_super=is_super,
            employee_id=employee_id,
            employee_name="Test Employee" if employee_id else "",
            employee_role=role if employee_id else "",
        )
    return _make


@pytest.fixture
def register_test_store(clean_db):
    """
    Helper: write a fully-formed store row directly to the DB so tests
    don't need to call the OAuth flow. Returns the store_id.
    """
    db = clean_db

    async def _register(store_id: str = "test-store",
                        access_token: str = "test-access-token",
                        **extra) -> str:
        tokens = {
            "access_token":        access_token,
            "refresh_token":       "test-refresh-token",
            "store_name":          extra.get("store_name", f"متجر {store_id}"),
            "bot_enabled":         extra.get("bot_enabled", True),
            "admin_password_hash": extra.get("admin_password_hash", ""),
            "ai_config":           extra.get("ai_config", {}),
        }
        await db.save_store(store_id, tokens)
        # Reload store_manager so endpoints see the new store
        import store_manager as sm
        await sm.load_from_db()
        return store_id
    return _register
