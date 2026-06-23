"""
backup.py — Off-site, encrypted, automated database backups.

The app's only durable state lives in PostgreSQL (stores + tokens, all
conversations, contacts, orders, uploaded files as bytea, …). Railway's
managed Postgres takes its own snapshots, but those live on the SAME
provider — a billing lapse, an account compromise, or a region incident
takes the database AND its snapshots at once. This module adds an
independent, off-Railway copy.

Pipeline (run_backup):
    pg_dump -Fc  →  Fernet-encrypt the artifact  →  upload to object
    storage (Cloudflare R2 / any S3-compatible)  →  prune copies older
    than the retention window.

Design notes
────────────
• `pg_dump -Fc` (custom format) is already compressed and is the input
  pg_restore expects — the highest-fidelity logical backup. We run it as
  an async subprocess so the event loop isn't blocked.

• The artifact is encrypted with a DEDICATED key (BACKUP_ENCRYPTION_KEY),
  separate from the field-level ENCRYPTION_KEY, so:
    - rotating the field key doesn't make old backups unrestorable, and
    - leaking one key doesn't compromise the other.
  If BACKUP_ENCRYPTION_KEY is unset we fall back to ENCRYPTION_KEY (still
  better than a plaintext dump), and log a warning. NEVER store this key
  only inside Railway — keep an offline copy or a lost key = useless
  backups.

• Object storage is addressed via the S3 API (boto3). For Cloudflare R2
  set R2_ENDPOINT_URL to the account endpoint; everything else is the
  standard access-key / secret-key / bucket trio.

• Restore is the inverse and lives in restore_backup.py (a CLI tool), so
  this module stays write-only — it can never clobber the live DB.

Env vars
────────
R2_ENDPOINT_URL        — e.g. https://<account>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID       — R2 / S3 access key id
R2_SECRET_ACCESS_KEY   — R2 / S3 secret
R2_BUCKET              — bucket name (must already exist)
R2_PREFIX              — optional key prefix (default "backups")
BACKUP_ENCRYPTION_KEY  — Fernet key for the dump artifact (recommended)
BACKUP_RETENTION_DAYS  — delete copies older than this (default 30)
BACKUP_INTERVAL_HOURS  — daily by default (24); the loop reads this
DATABASE_URL           — taken as-is for pg_dump
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import tempfile
from typing import Optional

from cryptography.fernet import Fernet

import log as _logmod

log = _logmod.get_logger("backend.backup")

# Encrypted artifacts carry this suffix so it's obvious they are NOT a
# plain pg_restore input — they must be decrypted by restore_backup.py first.
_ENC_SUFFIX = ".dump.enc"

# Guard rail: warn (don't fail) once a dump crosses this size, so we notice
# before the whole-file in-memory encrypt becomes a memory problem.
_SIZE_WARN_BYTES = 500 * 1024 * 1024  # 500 MB


# ── Config ───────────────────────────────────────────────────────────────

def _prefix() -> str:
    return (os.getenv("R2_PREFIX") or "backups").strip().strip("/")


def _retention_days() -> int:
    try:
        return max(1, int(os.getenv("BACKUP_RETENTION_DAYS", "30")))
    except ValueError:
        return 30


def interval_hours() -> int:
    try:
        return max(1, int(os.getenv("BACKUP_INTERVAL_HOURS", "24")))
    except ValueError:
        return 24


def _storage_configured() -> bool:
    return all(
        (os.getenv(k) or "").strip()
        for k in ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID",
                  "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    )


def enabled() -> bool:
    """True when both a database and an object-storage destination exist."""
    return bool((os.getenv("DATABASE_URL") or "").strip()) and _storage_configured()


def get_status() -> dict:
    """Summary for /env-check and the admin UI. No secrets leak out."""
    return {
        "enabled":            enabled(),
        "storage_configured": _storage_configured(),
        "bucket":             (os.getenv("R2_BUCKET") or "").strip(),
        "prefix":             _prefix(),
        "retention_days":     _retention_days(),
        "interval_hours":     interval_hours(),
        # True when a DEDICATED backup key is set (vs. falling back to the
        # field-level ENCRYPTION_KEY).
        "dedicated_key":      bool((os.getenv("BACKUP_ENCRYPTION_KEY") or "").strip()),
    }


# ── Encryption (dedicated backup key) ──────────────────────────────────────

def _build_fernet() -> Optional[Fernet]:
    """
    Fernet from BACKUP_ENCRYPTION_KEY, else ENCRYPTION_KEY as a fallback.
    Returns None only when neither is set — callers then refuse to upload a
    plaintext dump (fail-closed: a leaked plaintext DB dump is worse than a
    missed backup).
    """
    raw = (os.getenv("BACKUP_ENCRYPTION_KEY")
           or os.getenv("ENCRYPTION_KEY") or "").strip()
    if not raw:
        return None
    try:
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"Invalid BACKUP_ENCRYPTION_KEY: {exc}. Generate with: python -c "
            "\"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        ) from exc


# ── pg_dump ─────────────────────────────────────────────────────────────

async def _pg_dump_to(path: str) -> None:
    """
    Run `pg_dump -Fc` into `path`. Raises RuntimeError on non-zero exit or
    when the pg_dump binary is missing (local Windows dev without the
    Postgres client tools).
    """
    dsn = (os.getenv("DATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError("DATABASE_URL not set — nothing to dump")

    # pg_dump accepts both postgres:// and postgresql://; pass through as-is.
    try:
        proc = await asyncio.create_subprocess_exec(
            "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
            "--file", path, "--dbname", dsn,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "pg_dump binary not found. It ships via the postgresql_16 nixpacks "
            "package in production; on local dev install the Postgres client tools."
        ) from exc

    _out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"pg_dump exited {proc.returncode}: "
            f"{(err or b'').decode('utf-8', 'replace')[:500]}"
        )


# ── S3 / R2 client (boto3 is sync → run in a thread) ────────────────────────

def _make_client():
    import boto3  # lazy: keeps boot working without boto3 / R2 configured
    return boto3.session.Session().client(
        "s3",
        endpoint_url=(os.getenv("R2_ENDPOINT_URL") or "").strip(),
        aws_access_key_id=(os.getenv("R2_ACCESS_KEY_ID") or "").strip(),
        aws_secret_access_key=(os.getenv("R2_SECRET_ACCESS_KEY") or "").strip(),
        region_name="auto",  # R2 ignores region but boto3 wants one
    )


def _upload_blocking(key: str, data: bytes) -> None:
    client = _make_client()
    client.put_object(
        Bucket=(os.getenv("R2_BUCKET") or "").strip(),
        Key=key,
        Body=data,
        ContentType="application/octet-stream",
    )


def _list_blocking() -> list[dict]:
    client = _make_client()
    bucket = (os.getenv("R2_BUCKET") or "").strip()
    prefix = _prefix() + "/"
    out: list[dict] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []) or []:
            out.append({
                "key":        obj["Key"],
                "size_bytes": int(obj.get("Size", 0)),
                "modified":   obj["LastModified"].astimezone(_dt.timezone.utc)
                                  .isoformat().replace("+00:00", "Z"),
            })
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    out.sort(key=lambda o: o["modified"], reverse=True)
    return out


def _delete_blocking(keys: list[str]) -> None:
    if not keys:
        return
    client = _make_client()
    bucket = (os.getenv("R2_BUCKET") or "").strip()
    # delete_objects caps at 1000 keys/call — chunk to be safe.
    for i in range(0, len(keys), 1000):
        client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]},
        )


# ── Retention ───────────────────────────────────────────────────────────

async def _prune_old() -> int:
    """Delete artifacts older than the retention window. Returns count deleted."""
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=_retention_days())
    objs = await asyncio.to_thread(_list_blocking)
    stale = [
        o["key"] for o in objs
        if o["key"].endswith(_ENC_SUFFIX)
        and _dt.datetime.fromisoformat(o["modified"].replace("Z", "+00:00")) < cutoff
    ]
    if stale:
        await asyncio.to_thread(_delete_blocking, stale)
        log.info("backup_pruned", extra={"count": len(stale)})
    return len(stale)


# ── Public API ────────────────────────────────────────────────────────────

async def list_backups(limit: int = 50) -> list[dict]:
    """Newest-first list of stored backup artifacts. [] when unconfigured."""
    if not _storage_configured():
        return []
    try:
        objs = await asyncio.to_thread(_list_blocking)
        return [o for o in objs if o["key"].endswith(_ENC_SUFFIX)][:limit]
    except Exception as exc:
        log.warning("backup_list_failed", extra={"err": str(exc)[:300]})
        return []


async def run_backup() -> dict:
    """
    Take one backup end-to-end. Returns a result dict:
        {ok, key, size_bytes, encrypted, pruned, error}
    Never raises — the periodic loop and the admin endpoint both rely on a
    structured result rather than an exception.
    """
    result = {"ok": False, "key": "", "size_bytes": 0,
              "encrypted": False, "pruned": 0, "error": ""}

    if not (os.getenv("DATABASE_URL") or "").strip():
        result["error"] = "DATABASE_URL not set"
        return result
    if not _storage_configured():
        result["error"] = "object storage not configured (R2_* env vars)"
        return result

    fernet = _build_fernet()
    if fernet is None:
        # Fail-closed: refuse to ship a plaintext DB dump off-site.
        result["error"] = (
            "no BACKUP_ENCRYPTION_KEY / ENCRYPTION_KEY set — refusing to "
            "upload an unencrypted dump"
        )
        log.error("backup_no_key")
        return result

    ts  = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"{_prefix()}/{ts}{_ENC_SUFFIX}"

    tmp = None
    try:
        # 1. Dump to a temp file (custom format is binary + compressed).
        fd, tmp = tempfile.mkstemp(suffix=".dump")
        os.close(fd)
        await _pg_dump_to(tmp)
        raw_size = os.path.getsize(tmp)
        if raw_size > _SIZE_WARN_BYTES:
            log.warning("backup_dump_large", extra={"bytes": raw_size})

        # 2. Encrypt the whole artifact.
        with open(tmp, "rb") as fh:
            plaintext = fh.read()
        ciphertext = fernet.encrypt(plaintext)
        result["encrypted"] = True

        # 3. Upload.
        await asyncio.to_thread(_upload_blocking, key, ciphertext)
        result["key"]        = key
        result["size_bytes"] = len(ciphertext)
        result["ok"]         = True
        log.info("backup_ok", extra={"key": key, "bytes": len(ciphertext),
                                     "raw_bytes": raw_size})

        # 4. Prune old copies (best-effort — a backup that uploaded fine
        #    must still count as success even if pruning hiccups).
        try:
            result["pruned"] = await _prune_old()
        except Exception as exc:
            log.warning("backup_prune_failed", extra={"err": str(exc)[:300]})

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:500]
        log.error("backup_failed", extra={"err": result["error"]})
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    return result
