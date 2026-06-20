"""
Structured logging — stdlib `logging` with a JSON formatter for prod and
a compact text formatter for dev.

Design choices
──────────────
• Stdlib only. Adding structlog would buy a few API niceties at the cost
  of a runtime dep and a configuration story to maintain — not worth it
  for the volume of logs we emit.

• Two formatters, one switch (LOG_FORMAT env var):
    - text (default): "12:34:56 INFO  [req:abc12345] backend.chat: refused store=ABC ip=1.2.3.4"
    - json:           "{\"ts\":\"...\",\"level\":\"INFO\",\"request_id\":\"...\",\"logger\":\"...\",\"msg\":\"...\",\"store_id\":\"ABC\",...}"
  Railway's log viewer is fine with either; json wins when you ship to
  Loki/Datadog/etc later.

• Request-ID propagation via contextvars. Any code path called during a
  request gets the id automatically — no need to thread it through every
  function. Async-safe (contextvars copy with task boundaries).

• Logger names follow the module hierarchy: get_logger(__name__) in each
  file produces names like "backend.lifecycle", "backend.routers.webhooks".
  Grep-able and groupable by subsystem.

• Structured fields are passed via `extra={...}` (stdlib convention):
      log.info("budget exhausted", extra={"store_id": sid, "used": n, "budget": b})
  The JSON formatter promotes them to top-level keys; the text formatter
  appends them as `key=value` pairs.

  Convenience: `log_event(log, "name", **fields)` does the boilerplate
  in one call, for code paths that log structured events constantly.

Env vars
────────
LOG_LEVEL   DEBUG|INFO|WARNING|ERROR  (default INFO)
LOG_FORMAT  text|json                 (default text)
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any


# ── Request-ID context ──────────────────────────────────────────────────

# Empty default so logs from background loops (no HTTP request in scope)
# omit the field entirely rather than show a placeholder.
_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Return the request_id active in this async/sync context, or ''."""
    return _REQUEST_ID.get()


def set_request_id(rid: str) -> None:
    """Set the request_id for downstream logs in this context."""
    _REQUEST_ID.set(rid or "")


def new_request_id() -> str:
    """Short UUID4-derived id — enough entropy to disambiguate at scale."""
    return uuid.uuid4().hex[:16]


# ── Formatters ──────────────────────────────────────────────────────────

# Standard LogRecord attribute names — everything else on the record is
# treated as a structured field. Mirrors logging.LogRecord.__init__.
_STANDARD_RECORD_FIELDS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
})


def _record_extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    """Extract caller-provided extras passed via extra={} to log calls."""
    return {
        k: v
        for k, v in record.__dict__.items()
        if k not in _STANDARD_RECORD_FIELDS and not k.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Keys ordered for human readability."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts":     datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":  record.levelname,
            "logger": record.name,
            "msg":    record.getMessage(),
        }
        rid = get_request_id()
        if rid:
            payload["request_id"] = rid
        # Extras go to the top level so log-search tools index them.
        payload.update(_record_extra_fields(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """
    Compact dev-friendly text format. Wraps standard fields, appends
    structured extras as key=value at the end. NOT for parsing — use json
    in production if you need machine-readable logs.
    """

    _LEVEL_FIXED = {
        "DEBUG":    "DEBUG",
        "INFO":     "INFO ",
        "WARNING":  "WARN ",
        "ERROR":    "ERROR",
        "CRITICAL": "CRIT ",
    }

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S")
        lvl = self._LEVEL_FIXED.get(record.levelname, record.levelname[:5].ljust(5))
        rid = get_request_id()
        rid_str = f" [req:{rid[:8]}]" if rid else ""
        extras = _record_extra_fields(record)
        extras_str = ""
        if extras:
            extras_str = " " + " ".join(
                f"{k}={_format_value(v)}" for k, v in extras.items()
            )
        line = f"{ts} {lvl}{rid_str} {record.name}: {record.getMessage()}{extras_str}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _format_value(v: Any) -> str:
    """Compact key=value rendering — quote strings only when they have spaces."""
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    if " " in s or "=" in s:
        return f"\"{s}\""
    return s


# ── PII / secret redaction (M-17) ────────────────────────────────────────
# Logs are a secondary data store: phone numbers, emails, and access tokens
# must not land in them in the clear (GDPR data-minimisation). redact() masks
# the common shapes, and is applied two ways:
#   • RedactingFilter — scrubs every structured log record before formatting.
#   • _RedactingStream — wraps stdout/stderr in production so plain print()
#     debug lines are covered too (skipped under pytest — see setup_logging).
# Free-form message *bodies* can't be detected by pattern; those call sites
# must avoid logging the content (e.g. log a length instead).

# Phones: 11+ digit runs (E.164 WhatsApp ids are ~12). The >=11 threshold
# deliberately spares 9-10 digit Salla store ids so logs stay greppable.
_PHONE_RE  = re.compile(r"\+?\d{11,}")
_EMAIL_RE  = re.compile(r"([A-Za-z0-9])[A-Za-z0-9._%+\-]*@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
_TOKEN_RE  = re.compile(r"\b(?:7yk_|gsk_|sk-ant-|sk-proj-|sk-|EAA|xoxb-)[A-Za-z0-9._\-]{6,}")
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")


def redact(s: str) -> str:
    """Mask emails, phone numbers, and access tokens. Best-effort + defensive —
    returns the input unchanged on any error or non-str input."""
    if not isinstance(s, str) or not s:
        return s
    try:
        s = _BEARER_RE.sub("Bearer <redacted>", s)
        s = _TOKEN_RE.sub("<redacted-token>", s)
        s = _EMAIL_RE.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", s)
        s = _PHONE_RE.sub(lambda m: "***" + re.sub(r"\D", "", m.group(0))[-4:], s)
        return s
    except Exception:
        return s


class RedactingFilter(logging.Filter):
    """Scrub PII/secrets from every log record before it is formatted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: (redact(v) if isinstance(v, str) else v)
                        for k, v in record.args.items()
                    }
                else:
                    record.args = tuple(
                        redact(a) if isinstance(a, str) else a for a in record.args
                    )
            for k, v in list(record.__dict__.items()):
                if k not in _STANDARD_RECORD_FIELDS and isinstance(v, str):
                    record.__dict__[k] = redact(v)
        except Exception:
            pass
        return True


class _RedactingStream:
    """Transparent stdout/stderr wrapper that redacts everything written — so
    plain print() is scrubbed as well as the logging handler. Delegates all
    other attributes to the wrapped stream."""

    _is_redacting = True

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def write(self, s):
        try:
            return self._wrapped.write(redact(s) if isinstance(s, str) else s)
        except Exception:
            return self._wrapped.write(s)

    def flush(self):
        return self._wrapped.flush()

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


def _install_stream_redaction() -> None:
    """Wrap sys.stdout / sys.stderr once so all output is redacted."""
    for attr in ("stdout", "stderr"):
        stream = getattr(sys, attr, None)
        if stream is not None and not getattr(stream, "_is_redacting", False):
            setattr(sys, attr, _RedactingStream(stream))


# ── Setup ───────────────────────────────────────────────────────────────

_setup_done = False


def setup_logging() -> None:
    """
    Initialise root logging once at process start. Re-entry is a no-op so
    test fixtures that re-import main don't double-add handlers.

    Reads env vars:
      LOG_LEVEL  — DEBUG|INFO|WARNING|ERROR (default INFO)
      LOG_FORMAT — text|json (default text)
    """
    global _setup_done
    if _setup_done:
        return

    level_name = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = (os.getenv("LOG_FORMAT", "text") or "text").strip().lower()
    formatter: logging.Formatter = JsonFormatter() if fmt == "json" else TextFormatter()

    # M-17: redact stdout/stderr in production so plain print() debug lines are
    # scrubbed too. Skipped under pytest — wrapping pytest's captured streams
    # interferes with capsys, and the RedactingFilter below still exercises the
    # redaction logic in tests.
    if "pytest" not in sys.modules:
        _install_stream_redaction()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    # Clear any handlers the application or a test fixture added at import
    # time so we own the output channel exclusively.
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Library loggers tend to log at DEBUG with way too much detail. Cap
    # them at WARNING unless someone explicitly wants the noise.
    for noisy in ("asyncio", "asyncpg", "httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _setup_done = True


def get_logger(name: str) -> logging.Logger:
    """
    Module-scoped logger. Use `log = get_logger(__name__)` at the top of
    each file. Idempotent — repeated calls return the same instance.
    """
    return logging.getLogger(name)


# ── Convenience: event-style logging ───────────────────────────────────

def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """
    Shorthand for an event-style log entry. Equivalent to:
        logger.log(level, event, extra=fields)
    but slightly more readable at call sites and easier to grep --
    `log_event\\(.*budget_exhausted` matches every place we emit that
    specific event regardless of how the log line is phrased.
    """
    logger.log(level, event, extra=fields)


# ── Timing helper for request-finished logs ────────────────────────────

class Stopwatch:
    """Cheap perf-counter wrapper — `with Stopwatch() as sw: ...; sw.ms`."""

    def __enter__(self) -> "Stopwatch":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = round((time.perf_counter() - self._start) * 1000, 1)
        return False
