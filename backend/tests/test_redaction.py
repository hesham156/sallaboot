"""
Tests for log redaction (finding M-17).

redact() masks emails, phone numbers, and access tokens so PII/secrets don't
land in logs in the clear. RedactingFilter applies it to structured records.
"""
from __future__ import annotations

import pytest

from log import redact, RedactingFilter, _RedactingStream


pytestmark = pytest.mark.unit


# ── redact() ──────────────────────────────────────────────────────────────────

def test_email_is_masked():
    out = redact("login for h456ad@gmail.com from 1.2.3.4")
    assert "h456ad@gmail.com" not in out
    assert "h***@gmail.com" in out          # first char + domain kept for triage


def test_whatsapp_phone_is_masked():
    out = redact("incoming from=966500000000")
    assert "966500000000" not in out
    assert "***0000" in out


def test_short_numeric_store_id_is_not_masked():
    """9-10 digit Salla store ids must stay readable (logs greppable by store)."""
    assert redact("/admin/1234567890/conversations") == "/admin/1234567890/conversations"


def test_bearer_header_is_masked():
    out = redact("Authorization: Bearer abc.def.ghi123")
    assert "abc.def.ghi123" not in out
    assert "Bearer <redacted>" in out


@pytest.mark.parametrize("secret", [
    "7yk_AbC123def456",
    "sk-ant-api03-xxxxxx",
    "sk-proj-abcdef123456",
    "gsk_livexxxxxxxxxx",
    "EAAGm0PX4ZCpsBA123456",
])
def test_token_prefixes_are_masked(secret):
    out = redact(f"key={secret} done")
    assert secret not in out
    assert "<redacted-token>" in out


def test_plain_text_unchanged():
    assert redact("store sync completed for shop1 (42 products)") == \
        "store sync completed for shop1 (42 products)"


def test_non_string_passthrough():
    assert redact(None) is None
    assert redact(12345) == 12345


# ── RedactingFilter ───────────────────────────────────────────────────────────

class _Rec:
    """Minimal LogRecord stand-in."""
    def __init__(self, msg, **extra):
        self.msg = msg
        self.args = ()
        self.__dict__.update(extra)


def test_filter_redacts_msg_and_extras():
    f = RedactingFilter()
    rec = _Rec("login a@b.com", value="7yk_secret123", store_id="1234567890")
    assert f.filter(rec) is True
    assert "a@b.com" not in rec.msg
    assert "<redacted-token>" in rec.value
    assert rec.store_id == "1234567890"   # short numeric id untouched


# ── _RedactingStream ──────────────────────────────────────────────────────────

def test_stream_wrapper_redacts_writes():
    import io
    buf = io.StringIO()
    stream = _RedactingStream(buf)
    stream.write("user h456ad@gmail.com phone 966500000000\n")
    stream.flush()
    out = buf.getvalue()
    assert "h456ad@gmail.com" not in out
    assert "966500000000" not in out
    assert getattr(stream, "_is_redacting", False) is True
