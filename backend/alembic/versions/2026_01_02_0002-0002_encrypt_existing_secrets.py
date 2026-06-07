"""0002 encrypt existing secrets

Reads every row in `stores`, encrypts any plaintext secret field, writes
the row back. Idempotent: values already starting with `enc:v1:` are
skipped, so re-running the migration on an already-encrypted DB is a
no-op.

Why a data migration and not just "encrypt on next save":
  • Until every existing key is rotated through encrypt(), a DB leak
    still exposes plaintext.
  • Token refresh happens hourly — without this, the access_token on a
    busy store gets re-encrypted within a day, but the refresh_token
    might sit in plaintext for weeks.
  • Forces the operator to confirm ENCRYPTION_KEY is set before the
    deploy proceeds (the migration errors loudly if it isn't).

Environment requirement
───────────────────────
ENCRYPTION_KEY MUST be set. If unset, the migration errors with a clear
message rather than encrypting with a one-shot key that would render
every row unreadable on the next restart.

Rollback safety
───────────────
The downgrade() does the reverse — decrypts every field back to
plaintext, so a failed deploy can be rolled back. The same key must
be available for the rollback to work.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from alembic import op

# Make backend/ importable so we can use the same crypto helpers the
# runtime uses — guarantees the format on disk matches what the app
# reads back.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _require_encryption_key():
    if not (os.getenv("ENCRYPTION_KEY") or "").strip():
        raise RuntimeError(
            "Migration 0002 needs ENCRYPTION_KEY set. Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"\n"
            "Then add it to Railway env vars BEFORE re-running this deploy."
        )


def upgrade() -> None:
    _require_encryption_key()
    # Import after the key check so a missing env var fails with our
    # message, not with crypto's dev-key warning.
    import crypto  # noqa: E402

    conn = op.get_bind()
    rows = conn.exec_driver_sql(
        "SELECT store_id, tokens, ai_config FROM stores"
    ).fetchall()

    # asyncpg's JSONB codec doesn't apply here — alembic uses psycopg2
    # which returns JSONB as a Python dict already, OR as a string.
    # Coerce defensively.
    def _coerce(v):
        if isinstance(v, dict):
            return v
        if isinstance(v, (str, bytes)):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return {}

    encrypted_count = 0
    skipped_count   = 0
    for row in rows:
        store_id  = row[0]
        tokens    = _coerce(row[1])
        ai_config = _coerce(row[2])

        # Encrypt — helpers skip values already prefixed with enc:v1:
        # so re-running this migration is safe.
        enc_tokens    = crypto.encrypt_store_blob(tokens)
        enc_ai_config = crypto.encrypt_ai_config_blob(ai_config)

        # Skip the UPDATE entirely when nothing changed — keeps the
        # migration cheap on already-encrypted DBs.
        if enc_tokens == tokens and enc_ai_config == ai_config:
            skipped_count += 1
            continue

        conn.exec_driver_sql(
            "UPDATE stores SET tokens = %s::jsonb, ai_config = %s::jsonb, "
            "updated_at = NOW() WHERE store_id = %s",
            (
                json.dumps(enc_tokens,    ensure_ascii=False),
                json.dumps(enc_ai_config, ensure_ascii=False),
                store_id,
            ),
        )
        encrypted_count += 1

    print(
        f"[migration 0002] encrypted {encrypted_count} row(s), "
        f"skipped {skipped_count} already-encrypted"
    )


def downgrade() -> None:
    """Decrypt every row back to plaintext. Needs the same key(s)."""
    _require_encryption_key()
    import crypto  # noqa: E402

    conn = op.get_bind()
    rows = conn.exec_driver_sql(
        "SELECT store_id, tokens, ai_config FROM stores"
    ).fetchall()

    def _coerce(v):
        if isinstance(v, dict):
            return v
        if isinstance(v, (str, bytes)):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return {}

    decrypted_count = 0
    for row in rows:
        store_id  = row[0]
        tokens    = _coerce(row[1])
        ai_config = _coerce(row[2])
        dec_tokens    = crypto.decrypt_store_blob(tokens)
        dec_ai_config = crypto.decrypt_ai_config_blob(ai_config)
        if dec_tokens == tokens and dec_ai_config == ai_config:
            continue
        conn.exec_driver_sql(
            "UPDATE stores SET tokens = %s::jsonb, ai_config = %s::jsonb, "
            "updated_at = NOW() WHERE store_id = %s",
            (
                json.dumps(dec_tokens,    ensure_ascii=False),
                json.dumps(dec_ai_config, ensure_ascii=False),
                store_id,
            ),
        )
        decrypted_count += 1
    print(f"[migration 0002 down] decrypted {decrypted_count} row(s)")
