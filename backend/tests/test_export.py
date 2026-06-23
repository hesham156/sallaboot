"""
Tests for store data export (database.export_store + GET /admin/{id}/export).

Unit layer: the pure serialisation / redaction / filename helpers — the bits
that, if broken, leak secrets or produce invalid JSON. Always run.

Integration layer: the end-to-end ZIP endpoint against a real Postgres.
Skips when no DB is available.
"""
from __future__ import annotations

import datetime as _dt
import decimal as _decimal
import io
import json
import zipfile

import pytest

import database as db
from routers.stores import _safe_name


# ── Unit: serialisation ────────────────────────────────────────────────────

@pytest.mark.unit
def test_json_row_serialises_awkward_types():
    row = {
        "id":         5,
        "amount":     _decimal.Decimal("12.50"),
        "created_at": _dt.datetime(2026, 6, 24, 9, 30, tzinfo=_dt.timezone.utc),
        "day":        _dt.date(2026, 6, 24),
        "blob":       b"\x00\x01binary",       # must be dropped
        "meta":       {"k": "v"},               # jsonb already a dict
    }
    out = db._json_row(row)
    assert out["amount"] == 12.5
    assert out["created_at"] == "2026-06-24T09:30:00Z"
    assert out["day"] == "2026-06-24"
    assert "blob" not in out                    # binary never inlined
    assert out["meta"] == {"k": "v"}
    # The whole thing must be JSON-serialisable.
    json.dumps(out)


@pytest.mark.unit
def test_json_row_drops_named_columns():
    out = db._json_row({"email": "a@b.com", "password_hash": "secret"},
                       drop=("password_hash",))
    assert out == {"email": "a@b.com"}


@pytest.mark.unit
def test_redact_store_blob_strips_secrets():
    blob = {
        "access_token":  "TOP_SECRET",
        "refresh_token": "ALSO_SECRET",
        "store_name":    "متجر تجريبي",
        "ai_config": {
            "groq_api_key":      "gsk_secret",
            "anthropic_api_key": "sk-ant-secret",
            "model":             "claude-opus-4-8",
        },
    }
    red = db._redact_store_blob(blob)
    assert "access_token" not in red
    assert "refresh_token" not in red
    assert red["store_name"] == "متجر تجريبي"      # non-secret preserved
    assert "groq_api_key" not in red["ai_config"]
    assert "anthropic_api_key" not in red["ai_config"]
    assert red["ai_config"]["model"] == "claude-opus-4-8"
    # Original is untouched (we copy, not mutate the caller's dict).
    assert blob["access_token"] == "TOP_SECRET"


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected_no", [
    ("../../etc/passwd", "/"),
    ("a\\b\\c.png", "\\"),
])
def test_safe_name_blocks_traversal(raw, expected_no):
    safe = _safe_name(raw)
    assert expected_no not in safe
    assert ".." not in safe


@pytest.mark.unit
def test_safe_name_keeps_arabic():
    assert _safe_name("فاتورة.pdf").endswith(".pdf")


# ── Integration: full export endpoint ──────────────────────────────────────

@pytest.mark.integration
async def test_export_endpoint_bundles_and_redacts(app_client, register_test_store,
                                                   clean_db, make_token):
    store_id = await register_test_store(
        "exp-store",
        access_token="SECRET_ACCESS",
        ai_config={"groq_api_key": "gsk_secret", "model": "x"},
    )
    # Seed a couple of rows + one uploaded file.
    await db.record_bot_order(store_id, "sess-1", "ORD-1", 99.0, "SAR", "checkout")
    await db.save_upload("file-1", "فاتورة.pdf", "application/pdf",
                         b"%PDF-1.4 fake", store_id=store_id, session_id="sess-1")

    token = make_token(store_id)  # owner token
    resp = await app_client.get(
        f"/admin/{store_id}/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert "metadata.json" in names
    assert "data.json" in names
    assert any(n.startswith("uploads/file-1__") for n in names)

    data = json.loads(zf.read("data.json"))
    # Secret never leaves the building.
    blob = json.dumps(data, ensure_ascii=False)
    assert "SECRET_ACCESS" not in blob
    assert "gsk_secret" not in blob
    # Business data is present.
    assert len(data["bot_orders"]) == 1
    assert data["bot_orders"][0]["order_ref"] == "ORD-1"

    meta = json.loads(zf.read("metadata.json"))
    assert meta["store_id"] == store_id
    assert meta["record_counts"]["bot_orders"] == 1


@pytest.mark.integration
async def test_export_rejects_employee(app_client, register_test_store,
                                       clean_db, make_token):
    store_id = await register_test_store("exp-store-2")
    emp_token = make_token(store_id, employee_id=7, role="manager")
    resp = await app_client.get(
        f"/admin/{store_id}/export",
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    assert resp.status_code == 403
