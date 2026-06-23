"""
Tests for backend/backup.py — off-site encrypted DB backups.

These never touch a real Postgres or R2: pg_dump and the S3 upload are
monkeypatched. What we assert is the stuff that, if broken, silently ships
a useless or insecure backup:
  • config detection (enabled / get_status)
  • fail-CLOSED when no encryption key (never upload a plaintext dump)
  • the uploaded artifact actually round-trips back to the dump bytes
  • retention deletes only old artifacts, keeps recent ones
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import importlib

import pytest
from cryptography.fernet import Fernet

pytestmark = pytest.mark.unit

_R2 = {
    "R2_ENDPOINT_URL": "https://acct.r2.cloudflarestorage.com",
    "R2_ACCESS_KEY_ID": "k",
    "R2_SECRET_ACCESS_KEY": "s",
    "R2_BUCKET": "bucket",
}


@pytest.fixture
def bk(monkeypatch):
    """Fresh backup module import with a clean env."""
    for k in ("DATABASE_URL", "BACKUP_ENCRYPTION_KEY", "ENCRYPTION_KEY",
              "R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
              "R2_BUCKET", "R2_PREFIX", "BACKUP_RETENTION_DAYS",
              "BACKUP_INTERVAL_HOURS"):
        monkeypatch.delenv(k, raising=False)
    import backup
    return importlib.reload(backup)


def _configure(monkeypatch, *, db=True, r2=True, key=True):
    if db:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    if r2:
        for k, v in _R2.items():
            monkeypatch.setenv(k, v)
    if key:
        monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())


def test_disabled_without_config(bk):
    assert bk.enabled() is False
    st = bk.get_status()
    assert st["enabled"] is False and st["storage_configured"] is False


def test_enabled_with_config(bk, monkeypatch):
    _configure(monkeypatch)
    assert bk.enabled() is True
    assert bk.get_status()["dedicated_key"] is True


def test_run_refuses_without_db(bk, monkeypatch):
    _configure(monkeypatch, db=False)
    res = asyncio.run(bk.run_backup())
    assert res["ok"] is False and "DATABASE_URL" in res["error"]


def test_run_fails_closed_without_key(bk, monkeypatch):
    """The single most important guarantee: never upload a plaintext dump."""
    _configure(monkeypatch, key=False)
    uploaded = []
    monkeypatch.setattr(bk, "_upload_blocking", lambda k, d: uploaded.append((k, d)))
    res = asyncio.run(bk.run_backup())
    assert res["ok"] is False
    assert "refusing" in res["error"].lower()
    assert uploaded == []  # nothing left the building


def test_run_uploads_encrypted_roundtrip(bk, monkeypatch):
    """The uploaded artifact must decrypt back to the exact dump bytes."""
    key = Fernet.generate_key().decode()
    _configure(monkeypatch, key=False)
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", key)

    dump_bytes = b"PGDMP-fake-custom-format-\x00\x01\x02 contents"

    async def fake_dump(path):
        with open(path, "wb") as fh:
            fh.write(dump_bytes)

    captured = {}
    monkeypatch.setattr(bk, "_pg_dump_to", fake_dump)
    monkeypatch.setattr(bk, "_upload_blocking",
                        lambda k, d: captured.update(key=k, data=d))
    monkeypatch.setattr(bk, "_prune_old", _async_return(0))

    res = asyncio.run(bk.run_backup())
    assert res["ok"] is True
    assert res["key"].endswith(".dump.enc")
    assert res["encrypted"] is True
    # The artifact decrypts back to the original dump.
    assert Fernet(key.encode()).decrypt(captured["data"]) == dump_bytes


def test_prune_deletes_only_old(bk, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("BACKUP_RETENTION_DAYS", "30")
    now = _dt.datetime.now(_dt.timezone.utc)
    old = (now - _dt.timedelta(days=40)).isoformat().replace("+00:00", "Z")
    new = (now - _dt.timedelta(days=2)).isoformat().replace("+00:00", "Z")

    monkeypatch.setattr(bk, "_list_blocking", lambda: [
        {"key": "backups/old.dump.enc", "size_bytes": 1, "modified": old},
        {"key": "backups/new.dump.enc", "size_bytes": 1, "modified": new},
    ])
    deleted = []
    monkeypatch.setattr(bk, "_delete_blocking", lambda keys: deleted.extend(keys))

    n = asyncio.run(bk._prune_old())
    assert n == 1
    assert deleted == ["backups/old.dump.enc"]


def _async_return(value):
    async def _f(*a, **k):
        return value
    return _f
