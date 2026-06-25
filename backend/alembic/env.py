"""
Alembic environment — sync runner (psycopg2) over $DATABASE_URL.

We deliberately don't use SQLAlchemy ORM models here: migrations write
raw SQL with `op.execute(...)`. Reasons:
  • The runtime queries are hand-rolled asyncpg, not SQLAlchemy. Importing
    ORM models just for migrations would be dead weight.
  • Raw SQL keeps migrations identical to what the legacy
    database._create_tables() emits, so reviewing diffs is mechanical.

Online mode is the only one wired — we always need a real DB to run against.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Make the backend/ directory importable so future migrations can `import
# database` if they need to share helpers / table-name constants.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_database_url() -> str:
    """
    Resolve $DATABASE_URL to a psycopg2-compatible SQLAlchemy URL.

    Railway often hands out:
      • postgres://...       (legacy alias)
      • postgresql://...     (canonical, but no dialect hint)
      • postgresql+asyncpg://...  (runtime form — wrong driver for alembic)

    Alembic needs `postgresql+psycopg2://`. Normalising here keeps the
    deploy config simple — operators only set DATABASE_URL once.
    """
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        # Caller checks for "" first and skips migrations; never reached with
        # an unset URL. Kept defensive.
        raise RuntimeError("DATABASE_URL is not set.")
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]
    if raw.startswith("postgresql+asyncpg://"):
        raw = "postgresql+psycopg2://" + raw[len("postgresql+asyncpg://"):]
    elif raw.startswith("postgresql://"):
        raw = "postgresql+psycopg2://" + raw[len("postgresql://"):]
    return raw


def run_migrations_online() -> None:
    engine = create_engine(
        _resolve_database_url(),
        poolclass=pool.NullPool,
        future=True,
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            # Keep the SQL we generate identical to what's already in the
            # legacy _create_tables() block — no autogeneration here.
            target_metadata=None,
            transaction_per_migration=True,
            compare_type=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError(
        "Offline mode is not supported — migrations always run against a live DB."
    )

# Resilient deploy: the start command is `alembic upgrade head && uvicorn …`, so
# a hard error here takes the ENTIRE app down in a crash loop (landing page,
# storefront widget, everything). The app itself tolerates a missing DB at
# runtime (filesystem fallback) and self-creates the schema via
# database._create_tables() once a DB is present — so when DATABASE_URL is simply
# absent (mis-set env / DB-less role), SKIP migrations and let uvicorn boot
# instead of crash-looping. A migration that genuinely FAILS *with* a DB
# configured still raises and blocks the deploy, as it should.
if not (os.getenv("DATABASE_URL") or "").strip():
    print("=" * 60)
    print("⚠️  alembic: DATABASE_URL is not set — SKIPPING migrations so the")
    print("    app can still boot. It will run WITHOUT persistence until a")
    print("    database is configured. Fix: set DATABASE_URL on this Railway")
    print("    service (link the Postgres plugin / restore the reference).")
    print("=" * 60)
else:
    run_migrations_online()
