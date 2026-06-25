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


def test_extract_photo_surfaces_largest_file_id_and_caption():
    import telegram as tg
    update = {
        "update_id": 5,
        "message": {
            "message_id": 2, "from": {"id": 7, "first_name": "Noura"},
            "chat": {"id": 7},
            "photo": [
                {"file_id": "small", "width": 90},
                {"file_id": "big",   "width": 1280},   # largest = last
            ],
            "caption": "تصميمي",
        },
    }
    out = tg.extract_messages(update)
    assert len(out) == 1
    assert out[0]["media"]["kind"] == "image"
    assert out[0]["media"]["file_id"] == "big"         # picks the largest size
    assert out[0]["text"] == "تصميمي"                  # caption carried as text
    assert out[0]["chat_id"] == "7"


@pytest.mark.parametrize("key,field,expected_kind", [
    ("voice",    {"file_id": "v", "mime_type": "audio/ogg"}, "audio"),
    ("audio",    {"file_id": "a", "mime_type": "audio/mp3"}, "audio"),
    ("video",    {"file_id": "m", "mime_type": "video/mp4"}, "video"),
    ("video_note", {"file_id": "n"},                          "video"),
    ("animation",  {"file_id": "g"},                          "video"),
    ("sticker",  {"file_id": "s"},                            "image"),
    ("document", {"file_id": "d", "mime_type": "application/pdf",
                  "file_name": "spec.pdf"},                   "file"),
])
def test_extract_all_media_kinds_downloaded_not_dropped(key, field, expected_kind):
    import telegram as tg
    update = {"update_id": 1, "message": {
        "from": {"id": 3}, "chat": {"id": 3}, key: field}}
    out = tg.extract_messages(update)
    assert out, f"{key} was dropped"
    assert out[0]["media"]["kind"] == expected_kind
    assert out[0]["media"]["file_id"] == field["file_id"]


def test_extract_image_document_classified_as_image():
    import telegram as tg
    update = {"update_id": 1, "message": {
        "from": {"id": 3}, "chat": {"id": 3},
        "document": {"file_id": "d", "mime_type": "image/png", "file_name": "p.png"}}}
    out = tg.extract_messages(update)
    assert out[0]["media"]["kind"] == "image"          # documents classified by mime


async def test_fetch_media_returns_none_on_empty_inputs():
    import telegram as tg
    assert await tg.fetch_media("", "file") is None
    assert await tg.fetch_media("123:tok", "") is None


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
    # Split across the colon so the literal isn't a contiguous Telegram-token
    # shape in source — it's a synthetic fixture, not a real credential, but
    # GitHub secret scanning pattern-matches the full form and files a (false)
    # "public leak" alert. Same dodge as the concatenated case just below.
    ("123456789:" + "AAHk1Lp-abcDEFghijKLMNopqrstuvwx12", True),
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
