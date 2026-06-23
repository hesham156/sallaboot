"""
restore_backup.py — Download + decrypt a backup artifact, ready for restore.

This is the inverse of backup.py, kept as a STANDALONE CLI (never imported
by the app) so the running service can never accidentally clobber the live
database. It only ever reads from object storage and writes a local file —
the actual `pg_restore` is a deliberate, manual second step you run yourself.

Usage
─────
    # 1. List what's available off-site:
    python restore_backup.py --list

    # 2. Download + decrypt the newest (or a specific key) to a local file:
    python restore_backup.py --latest --out restore.dump
    python restore_backup.py --key backups/20260624T030000Z.dump.enc --out restore.dump

    # 3. Restore into a target database YOU control (NOT prod by reflex):
    pg_restore --clean --if-exists --no-owner --no-privileges \\
        --dbname "$TARGET_DATABASE_URL" restore.dump

Environment: same R2_* vars as backup.py, plus BACKUP_ENCRYPTION_KEY (or
ENCRYPTION_KEY fallback) — it MUST be the key the artifact was encrypted
with, or decryption fails. Keep an offline copy of this key; without it the
backups are unrecoverable.
"""
from __future__ import annotations

import argparse
import os
import sys

from cryptography.fernet import Fernet, InvalidToken


def _client():
    import boto3
    return boto3.session.Session().client(
        "s3",
        endpoint_url=(os.getenv("R2_ENDPOINT_URL") or "").strip(),
        aws_access_key_id=(os.getenv("R2_ACCESS_KEY_ID") or "").strip(),
        aws_secret_access_key=(os.getenv("R2_SECRET_ACCESS_KEY") or "").strip(),
        region_name="auto",
    )


def _bucket() -> str:
    b = (os.getenv("R2_BUCKET") or "").strip()
    if not b:
        sys.exit("R2_BUCKET not set")
    return b


def _prefix() -> str:
    return (os.getenv("R2_PREFIX") or "backups").strip().strip("/")


def _fernet() -> Fernet:
    raw = (os.getenv("BACKUP_ENCRYPTION_KEY")
           or os.getenv("ENCRYPTION_KEY") or "").strip()
    if not raw:
        sys.exit("BACKUP_ENCRYPTION_KEY (or ENCRYPTION_KEY) not set — cannot decrypt")
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError) as exc:
        sys.exit(f"Invalid backup key: {exc}")


def cmd_list() -> None:
    client = _client()
    resp = client.list_objects_v2(Bucket=_bucket(), Prefix=_prefix() + "/")
    rows = sorted(
        (o for o in resp.get("Contents", []) if o["Key"].endswith(".dump.enc")),
        key=lambda o: o["LastModified"], reverse=True,
    )
    if not rows:
        print("(no backups found)")
        return
    for o in rows:
        mb = o["Size"] / (1024 * 1024)
        print(f"{o['LastModified'].isoformat()}  {mb:8.2f} MB  {o['Key']}")


def _latest_key(client) -> str:
    resp = client.list_objects_v2(Bucket=_bucket(), Prefix=_prefix() + "/")
    rows = [o for o in resp.get("Contents", []) if o["Key"].endswith(".dump.enc")]
    if not rows:
        sys.exit("no backups found to restore")
    return max(rows, key=lambda o: o["LastModified"])["Key"]


def cmd_fetch(key: str | None, latest: bool, out: str) -> None:
    client = _client()
    if latest:
        key = _latest_key(client)
    if not key:
        sys.exit("provide --key <key> or --latest")
    print(f"Downloading {key} …")
    obj = client.get_object(Bucket=_bucket(), Key=key)
    ciphertext = obj["Body"].read()
    print(f"Decrypting {len(ciphertext):,} bytes …")
    try:
        plaintext = _fernet().decrypt(ciphertext)
    except InvalidToken:
        sys.exit("decryption failed — wrong BACKUP_ENCRYPTION_KEY for this artifact")
    with open(out, "wb") as fh:
        fh.write(plaintext)
    print(f"✅ Wrote {len(plaintext):,} bytes to {out}")
    print("Next: pg_restore --clean --if-exists --no-owner --no-privileges "
          f'--dbname "$TARGET_DATABASE_URL" {out}')


def main() -> None:
    ap = argparse.ArgumentParser(description="Download + decrypt a DB backup artifact.")
    ap.add_argument("--list", action="store_true", help="list available backups and exit")
    ap.add_argument("--key", help="exact object key to fetch")
    ap.add_argument("--latest", action="store_true", help="fetch the newest backup")
    ap.add_argument("--out", default="restore.dump", help="local output path (default: restore.dump)")
    args = ap.parse_args()

    if args.list:
        cmd_list()
        return
    if args.key or args.latest:
        cmd_fetch(args.key, args.latest, args.out)
        return
    ap.print_help()


if __name__ == "__main__":
    main()
