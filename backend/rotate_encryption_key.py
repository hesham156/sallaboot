"""
rotate_encryption_key.py — Move every stored secret onto a new ENCRYPTION_KEY.

Standalone management CLI (never imported by the app). Re-encrypts the
secret-bearing fields of every `stores` row (Salla OAuth tokens + provider
API keys) from the previous key onto the current `ENCRYPTION_KEY`, so the
old key can finally be removed from `ENCRYPTION_KEYS_OLD`.

Why this is needed
──────────────────
`crypto.encrypt()` is idempotent on already-ciphertext — saving a row does
NOT move it to a new key. Without an explicit rewrite, an old key can never
be safely retired. This script performs that rewrite (decrypt with any
configured key → re-encrypt with the active key).

Rotation procedure
──────────────────
  1. Generate a new key:
       python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  2. On every service, set:
       ENCRYPTION_KEYS_OLD=<current-key>      # decrypt-only, fallback
       ENCRYPTION_KEY=<new-key>               # active, used for new writes
     Redeploy. The app now reads old ciphertext via the fallback and writes
     new ciphertext with the new key.
  3. Run this script (same env) to rewrite ALL existing rows:
       python rotate_encryption_key.py
  4. Verify it reports 0 errors and that a re-run rotates 0 rows.
  5. Remove ENCRYPTION_KEYS_OLD and redeploy.

Usage
─────
    python rotate_encryption_key.py            # rotate all rows, print report
    python rotate_encryption_key.py --dry-run  # report only (no writes)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys


async def _run(dry_run: bool) -> int:
    if not (os.getenv("DATABASE_URL") or "").strip():
        print("❌ DATABASE_URL not set — nothing to rotate.")
        return 1
    if not (os.getenv("ENCRYPTION_KEY") or "").strip():
        print("❌ ENCRYPTION_KEY not set. The active key is required to "
              "re-encrypt onto it.")
        return 1
    if not (os.getenv("ENCRYPTION_KEYS_OLD") or "").strip():
        print("⚠️  ENCRYPTION_KEYS_OLD is empty. If rows were encrypted with a "
              "previous key, they will appear as errors. Continuing anyway "
              "(harmless if the active key already encrypts everything).")

    import database as db

    ok = await db.init()
    if not ok:
        print("❌ Could not connect to the database.")
        return 1

    if dry_run:
        # Report how many rows WOULD change without writing.
        import crypto as _crypto
        async with db._pool.acquire() as conn:
            rows = await conn.fetch("SELECT store_id, tokens, ai_config FROM stores")
        would, errors = 0, 0
        for r in rows:
            tok = db._coerce_jsonb(r["tokens"])
            ai  = db._coerce_jsonb(r["ai_config"])
            try:
                if (_crypto.reencrypt_store_blob(tok) != tok
                        or _crypto.reencrypt_ai_config_blob(ai) != ai):
                    would += 1
            except ValueError:
                errors += 1
        print(f"[dry-run] {len(rows)} row(s): would rotate {would}, "
              f"{errors} unreadable (missing old key).")
        return 0

    print("🔐 Rotating encryption for all stores …")
    res = await db.rotate_encryption()
    print(f"   total={res['total']} rotated={res['rotated']} "
          f"unchanged={res['unchanged']} errors={len(res['errors'])}")
    for e in res["errors"]:
        print(f"   ⚠️  {e['store_id']}: {e['error']}")
    if res["errors"]:
        print("\n❗ Some rows could not be rotated — add the matching old key to "
              "ENCRYPTION_KEYS_OLD and re-run BEFORE removing any key.")
        return 2
    print("\n✅ Done. Re-run to confirm 0 rotated, then drop ENCRYPTION_KEYS_OLD.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Rotate the DB encryption key.")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing")
    args = ap.parse_args()
    sys.exit(asyncio.run(_run(args.dry_run)))


if __name__ == "__main__":
    main()
