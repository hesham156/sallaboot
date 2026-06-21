"""
Unit tests for the Telegram channel pipe + connect validation.

Pure-unit (no network): update parsing, bot-id extraction, long-message
splitting, and the BotFather-token shape guard the connect endpoint applies
before it ever calls Telegram.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ── extract_messages ──────────────────────────────────────────────────────────

def test_extract_message_normalises_private_chat():
    import telegram as tg
    update = {
        "update_id": 42,
        "message": {
            "message_id": 7,
            "from": {"id": 111, "first_name": "Sara", "last_name": "A", "username": "sara"},
            "chat": {"id": 111, "type": "private"},
            "text": "  ابغى أتابع طلبي  ",
        },
    }
    out = tg.extract_messages(update)
    assert len(out) == 1
    m = out[0]
    assert m["msg_id"] == "42"                 # dedup keys on update_id
    assert m["chat_id"] == "111" and m["from"] == "111"
    assert m["text"] == "ابغى أتابع طلبي"       # trimmed
    assert m["name"] == "Sara A"


def test_extract_message_uses_caption_and_edited_message():
    import telegram as tg
    edited = {
        "update_id": 9,
        "edited_message": {
            "message_id": 3, "from": {"id": 5, "username": "ali"},
            "chat": {"id": 5}, "caption": "صورة المنتج",
        },
    }
    out = tg.extract_messages(edited)
    assert out and out[0]["text"] == "صورة المنتج" and out[0]["name"] == "ali"


@pytest.mark.parametrize("update", [
    {},                                                   # empty
    {"update_id": 1},                                     # no message
    {"update_id": 1, "message": {"chat": {"id": 5}}},     # no text
    {"update_id": 1, "message": {"text": "hi", "chat": {}}},   # no chat id
    {"update_id": 1, "callback_query": {"data": "x"}},    # not a message
])
def test_extract_message_ignores_non_text(update):
    import telegram as tg
    assert tg.extract_messages(update) == []


# ── bot id + split ────────────────────────────────────────────────────────────

def test_bot_id_from_token():
    import telegram as tg
    assert tg.bot_id_from_token("123456789:AAH-abcDEF") == "123456789"
    assert tg.bot_id_from_token("") == ""
    assert tg.bot_id_from_token("nocolon") == "nocolon"


def test_split_keeps_short_text_intact_and_chunks_long():
    import telegram as tg
    assert tg._split("short", tg._TG_TEXT_LIMIT) == ["short"]
    big = "\n".join(["x" * 1000] * 10)             # ~10k chars
    parts = tg._split(big, tg._TG_TEXT_LIMIT)
    assert len(parts) > 1
    assert all(len(p) <= tg._TG_TEXT_LIMIT for p in parts)


# ── connect token-shape guard (channels router) ───────────────────────────────

@pytest.mark.parametrize("token,valid", [
    ("123456789:AAHk1Lp-abcDEFghijKLMNopqrstuvwx12", True),
    ("8000000000:AAF" + "z" * 32, True),
    ("not-a-token", False),
    ("123:short", False),                          # auth part too short
    ("https://t.me/BotFather", False),             # pasted a URL
    ("", False),
    (":AAH" + "z" * 32, False),                    # no bot id
])
def test_telegram_token_shape_guard(token, valid):
    from routers.channels import _TG_TOKEN_RE
    assert bool(_TG_TOKEN_RE.match(token)) is valid
