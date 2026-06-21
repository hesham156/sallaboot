"""
Unit tests for analytics helpers added for the store-owner metrics expansion:
channel parity (telegram/messenger/instagram), deflection rate + peak hour,
and the operations endpoint helpers (first-response / span / knowledge gaps).

Pure-unit (no network, no DB) — exercises the helper functions directly.
"""
from __future__ import annotations

import datetime as _dt

import pytest

import routers.analytics as an

pytestmark = pytest.mark.unit


# ── _conv_channel ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sid,info,expected", [
    ("tg:111",   {},                       "telegram"),
    ("wa:966500", {},                      "whatsapp"),
    ("msgr:abc", {},                       "messenger"),
    ("ig:xyz",   {},                       "instagram"),
    ("sess-1",   {"channel": "telegram"},  "telegram"),
    ("sess-2",   {"channel": "whatsapp"},  "whatsapp"),
    ("sess-3",   {},                       "widget"),
    ("sess-4",   {"channel": "bogus"},     "widget"),
])
def test_conv_channel_detection(sid, info, expected):
    conv = {"customer_info": info}
    assert an._conv_channel(sid, conv) == expected


def test_prefix_wins_over_customer_info():
    # A tg: session tagged whatsapp in customer_info still resolves by prefix.
    assert an._conv_channel("tg:1", {"customer_info": {"channel": "whatsapp"}}) == "telegram"


# ── deflection rate + peak hour via _finalise_channel_stats ──────────────────

def test_deflection_rate_and_peak_hour():
    now = _dt.datetime(2026, 6, 21, 12, 0, 0)
    stats = an._empty_channel_stats(now)

    # 3 bot-handled, 1 admin-takeover → 75% deflection.
    base = {"created_at": now.isoformat(), "messages": []}
    an._accumulate_conv(stats, {**base, "bot_enabled": True},  now)
    an._accumulate_conv(stats, {**base, "bot_enabled": True},  now)
    an._accumulate_conv(stats, {**base, "bot_enabled": True},  now)
    an._accumulate_conv(stats, {**base, "bot_enabled": False}, now)

    out = an._finalise_channel_stats(stats)
    c = out["conversations"]
    assert c["total"] == 4
    assert c["bot_handled"] == 3
    assert c["admin_takeover"] == 1
    assert c["deflection_rate"] == 75.0
    # All four created at hour 12 → peak hour is 12.
    assert c["peak_hour"] == 12


def test_peak_hour_minus_one_when_empty():
    now = _dt.datetime(2026, 6, 21, 12, 0, 0)
    out = an._finalise_channel_stats(an._empty_channel_stats(now))
    assert out["conversations"]["peak_hour"] == -1
    assert out["conversations"]["deflection_rate"] == 0


# ── response-time helpers ────────────────────────────────────────────────────

def _msg(role, ts):
    return {"role": role, "content": "x", "ts": ts}


def test_first_response_seconds_basic():
    msgs = [
        _msg("user",      "2026-06-21T10:00:00"),
        _msg("assistant", "2026-06-21T10:00:30"),
        _msg("user",      "2026-06-21T10:01:00"),
    ]
    assert an._first_response_seconds(msgs) == 30.0


def test_first_response_admin_counts():
    msgs = [
        _msg("user",  "2026-06-21T10:00:00"),
        _msg("admin", "2026-06-21T10:02:00"),
    ]
    assert an._first_response_seconds(msgs) == 120.0


def test_first_response_none_without_reply():
    msgs = [_msg("user", "2026-06-21T10:00:00")]
    assert an._first_response_seconds(msgs) is None


def test_first_response_ignores_leading_assistant():
    # A greeting from the bot before any user message must not count.
    msgs = [
        _msg("assistant", "2026-06-21T10:00:00"),
        _msg("user",      "2026-06-21T10:00:10"),
        _msg("assistant", "2026-06-21T10:00:25"),
    ]
    assert an._first_response_seconds(msgs) == 15.0


def test_conversation_span_seconds():
    msgs = [
        _msg("user",      "2026-06-21T10:00:00"),
        _msg("assistant", "2026-06-21T10:00:30"),
        _msg("user",      "2026-06-21T10:05:00"),
    ]
    assert an._conversation_span_seconds(msgs) == 300.0


def test_conversation_span_none_single_message():
    assert an._conversation_span_seconds([_msg("user", "2026-06-21T10:00:00")]) is None
