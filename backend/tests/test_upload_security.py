"""
Security regression tests for file upload/serving (finding M-9).

The public /upload + /file endpoints used to:
  • serve uploads INLINE (DB path defaulted to inline; disk path was a bare
    FileResponse) — so an uploaded .svg with <script> executed on our origin
    (stored XSS → admin token theft), and
  • have no rate/volume cap — storage-exhaustion DoS.

The fix:
  • every /file response is Content-Disposition: attachment + a deny-all CSP,
  • /upload is rate-limited per IP and per session.

The guards run before any file I/O, so these tests need no real DB.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from routers import files


pytestmark = pytest.mark.unit


class _Client:
    host = "203.0.113.9"


class _Req:
    client = _Client()


class _DummyUpload:
    filename = "evil.svg"


# ── Serving: never inline ─────────────────────────────────────────────────────

def test_content_disposition_defaults_to_attachment():
    cd = files._content_disposition("evil.svg")
    assert cd.startswith("attachment")


def test_file_csp_denies_everything():
    assert "default-src 'none'" in files._FILE_CSP


async def test_disk_file_served_as_attachment_with_csp(monkeypatch):
    """A .svg fetched from the disk cache must download with a deny-all CSP,
    never render inline."""
    monkeypatch.setattr(files.db, "available", lambda: False)  # force disk path
    fid = "unittest-m9-fileid"
    p = files.UPLOAD_DIR / f"{fid}.svg"
    p.write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
    try:
        resp = await files.get_uploaded_file(fid)
        assert resp.headers["content-disposition"].startswith("attachment")
        assert "default-src 'none'" in resp.headers["content-security-policy"]
    finally:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# ── Upload: rate limited ──────────────────────────────────────────────────────

async def test_upload_rate_limited_per_ip(monkeypatch):
    async def _always_limited(key, *a, **k):
        return True
    monkeypatch.setattr(files, "is_rate_limited", _always_limited)
    with pytest.raises(HTTPException) as ei:
        await files.upload_file(file=_DummyUpload(), session_id="", store_id="s", request=_Req())
    assert ei.value.status_code == 429


async def test_upload_internal_session_rejected_before_ratelimit(monkeypatch):
    """The H-1 channel-session guard still fires first (no request needed)."""
    async def _boom(*a, **k):  # must NOT be reached
        raise AssertionError("rate-limit ran before the internal-session guard")
    monkeypatch.setattr(files, "is_rate_limited", _boom)
    with pytest.raises(HTTPException) as ei:
        await files.upload_file(file=_DummyUpload(), session_id="wa:966500000000", store_id="s")
    assert ei.value.status_code == 404
