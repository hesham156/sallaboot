"""
Unit tests for the structured logging module.

What we cover
─────────────
• Formatter shape — JSON output is valid JSON with the expected keys.
• Request-ID context propagation — including across asyncio task
  boundaries (contextvars copy by default).
• Level filtering via LOG_LEVEL.
• extra={} fields end up at the top level of the JSON record.
• No-secret-leak smoke check — passing a secret-looking value through
  the formatter doesn't accidentally split / unescape it.

These are pure unit tests — no DB, no network — so they run anywhere
without the testcontainer fixture.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
from contextvars import copy_context

import pytest

import log as logmod


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_logging_setup(monkeypatch):
    """Each test gets a fresh setup pass."""
    monkeypatch.setattr(logmod, "_setup_done", False)
    logmod.set_request_id("")
    yield
    logmod.set_request_id("")


def _capture_log_output(level_name: str = "INFO", fmt: str = "json") -> tuple[logging.Logger, io.StringIO]:
    """Build a logger that writes to a StringIO so tests can inspect output."""
    os.environ["LOG_LEVEL"]  = level_name
    os.environ["LOG_FORMAT"] = fmt
    logmod.setup_logging()
    # Replace the root handler's stream with our buffer.
    buf = io.StringIO()
    root = logging.getLogger()
    for h in root.handlers:
        h.stream = buf
    return logmod.get_logger("test.logging"), buf


# ── JSON formatter ────────────────────────────────────────────────────────

def test_json_format_basic_shape():
    log, buf = _capture_log_output(fmt="json")
    log.info("hello_world", extra={"store_id": "abc", "n": 7})

    line = buf.getvalue().strip()
    payload = json.loads(line)
    assert payload["msg"]      == "hello_world"
    assert payload["level"]    == "INFO"
    assert payload["logger"]   == "test.logging"
    assert payload["store_id"] == "abc"
    assert payload["n"]        == 7
    # Timestamp present + ISO-formatted with Z (UTC).
    assert "ts" in payload
    assert "T" in payload["ts"]


def test_json_format_includes_request_id_when_set():
    log, buf = _capture_log_output(fmt="json")
    logmod.set_request_id("req-12345")
    log.info("with_rid")

    payload = json.loads(buf.getvalue().strip())
    assert payload["request_id"] == "req-12345"


def test_json_format_omits_request_id_when_unset():
    log, buf = _capture_log_output(fmt="json")
    log.info("no_rid")
    payload = json.loads(buf.getvalue().strip())
    assert "request_id" not in payload   # default contextvar is ""


# ── Text formatter ────────────────────────────────────────────────────────

def test_text_format_appends_extras_as_kv():
    log, buf = _capture_log_output(fmt="text")
    log.info("budget_hit", extra={"store": "shop1", "used": 1000})

    line = buf.getvalue()
    assert "budget_hit" in line
    assert "store=shop1" in line
    assert "used=1000"   in line
    assert "INFO"        in line


def test_text_format_shows_request_id_prefix():
    log, buf = _capture_log_output(fmt="text")
    logmod.set_request_id("abc1234567890def")
    log.info("with_rid")
    # Short-form: only first 8 chars in text mode.
    assert "[req:abc12345]" in buf.getvalue()


# ── Level filtering ──────────────────────────────────────────────────────

def test_level_filter_suppresses_debug_at_info():
    log, buf = _capture_log_output(level_name="INFO")
    log.debug("hidden_event")
    log.info("visible_event")
    out = buf.getvalue()
    assert "hidden_event"  not in out
    assert "visible_event" in out


def test_level_filter_warning_only():
    log, buf = _capture_log_output(level_name="WARNING")
    log.info("hidden")
    log.warning("shown")
    out = buf.getvalue()
    assert "hidden" not in out
    assert "shown"  in out


# ── Request-ID propagation across asyncio tasks ──────────────────────────

async def test_request_id_propagates_to_child_task():
    log, buf = _capture_log_output(fmt="json")
    logmod.set_request_id("parent-rid")

    async def child():
        # Child sees parent's context (contextvars copy at task creation).
        log.info("from_child")

    # gather creates a Task → context is captured at creation time.
    await asyncio.gather(child())

    lines = [json.loads(l) for l in buf.getvalue().splitlines() if l]
    child_line = next(l for l in lines if l["msg"] == "from_child")
    assert child_line["request_id"] == "parent-rid"


async def test_request_id_isolated_between_concurrent_tasks():
    """Two concurrent tasks each setting their own rid don't see each other."""
    log, buf = _capture_log_output(fmt="json")

    async def task(rid: str, marker: str):
        logmod.set_request_id(rid)
        # Yield once to interleave with the sibling.
        await asyncio.sleep(0)
        log.info(marker)

    # Run each task in its own contextvars copy so they're isolated.
    async def in_ctx(rid: str, marker: str):
        ctx = copy_context()
        await asyncio.create_task(task(rid, marker), context=ctx)

    await asyncio.gather(in_ctx("rid-A", "from_a"), in_ctx("rid-B", "from_b"))

    lines = [json.loads(l) for l in buf.getvalue().splitlines() if l]
    a_line = next(l for l in lines if l["msg"] == "from_a")
    b_line = next(l for l in lines if l["msg"] == "from_b")
    assert a_line["request_id"] == "rid-A"
    assert b_line["request_id"] == "rid-B"


# ── log_event convenience ─────────────────────────────────────────────────

def test_log_event_passes_fields_as_extra():
    log, buf = _capture_log_output(fmt="json")
    logmod.log_event(log, logging.WARNING, "test_event", a=1, b="x")
    payload = json.loads(buf.getvalue().strip())
    assert payload["msg"]   == "test_event"
    assert payload["level"] == "WARNING"
    assert payload["a"]     == 1
    assert payload["b"]     == "x"


# ── Exception logging ─────────────────────────────────────────────────────

def test_exception_includes_traceback_in_json():
    log, buf = _capture_log_output(fmt="json")
    try:
        raise ValueError("nope")
    except ValueError:
        log.exception("caught_it", extra={"where": "test"})

    payload = json.loads(buf.getvalue().strip())
    assert payload["msg"]   == "caught_it"
    assert payload["where"] == "test"
    assert "exc" in payload
    assert "ValueError"     in payload["exc"]
    assert "nope"           in payload["exc"]


# ── Stopwatch ─────────────────────────────────────────────────────────────

def test_stopwatch_measures_elapsed_ms():
    import time
    with logmod.Stopwatch() as sw:
        time.sleep(0.02)
    assert sw.ms >= 19   # 20ms ± clock jitter
    assert sw.ms <  200   # nothing pathological


# ── Redaction: secret-shaped values are masked in logs (M-17) ─────────────

def test_secret_value_is_redacted_in_json():
    """
    M-17: an api-key-shaped string in extras must be REDACTED before it hits
    the log sink (it used to pass through unchanged). The RedactingFilter runs
    on every record, so the secret never lands in the clear.
    """
    log, buf = _capture_log_output(fmt="json")
    fake_secret = "sk-abcdef0123456789-XYZ"
    log.warning("oddly_shaped_value", extra={"value": fake_secret})
    payload = json.loads(buf.getvalue().strip())
    assert "<redacted-token>" in payload["value"]
    assert "abcdef0123456789" not in payload["value"]
