"""File upload and download routes."""
import os
import uuid
from pathlib import Path
from urllib.parse import quote

import aiofiles
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, Response

import database as db
import conversation_store as cs
from routers.deps import (
    UPLOAD_DIR, MAX_FILE_MB, ALLOWED_EXTENSIONS, CONTENT_TYPES,
    is_internal_session_id, is_rate_limited, read_upload_bounded, _content_length,
)

router = APIRouter()

# Served-file CSP (M-9): uploads are attacker-supplied via the public widget.
# Force a download disposition + a deny-all CSP so an .svg / .html can never
# execute script on our origin (where admin tokens live). nosniff is already
# applied globally by the security-headers middleware.
_FILE_CSP = "default-src 'none'; sandbox"


def _content_disposition(filename: str, disposition: str = "attachment") -> str:
    name       = filename or "file"
    ascii_name = name.encode("ascii", "ignore").decode("ascii").strip() or "file"
    ascii_name = ascii_name.replace('"', "")
    utf8_name  = quote(name, safe="")
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


@router.post("/upload")
async def upload_file(
    file:       UploadFile = File(...),
    session_id: str        = Form(default=""),
    store_id:   str        = Form(default="default"),
    request:    Request    = None,
):
    # H-1: refuse to attach a file to a channel-owned conversation (wa:/msgr:/ig:)
    # — that would inject a forged "customer sent a file" message into a real
    # WhatsApp/Messenger/Instagram thread. Widget uploads use random-uuid ids.
    if is_internal_session_id(session_id):
        raise HTTPException(404, "الجلسة غير موجودة")

    # M-9: rate-limit the public, unauthenticated upload endpoint per IP and per
    # session so it can't be abused to exhaust disk/DB storage. (Per-file size is
    # capped below.) is_rate_limited is a no-op when the DB is unavailable.
    ip = request.client.host if (request and request.client) else "unknown"
    if await is_rate_limited(f"upload:i:{ip}", max_attempts=30, window=300):
        raise HTTPException(429, "محاولات رفع كثيرة جداً. انتظر قليلاً وحاول مجدداً.")
    if session_id and await is_rate_limited(f"upload:s:{session_id[:64]}", max_attempts=15, window=300):
        raise HTTPException(429, "محاولات رفع كثيرة جداً. انتظر قليلاً وحاول مجدداً.")

    if "{{" in store_id or "}}" in store_id:
        store_id = "default"

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"نوع الملف غير مدعوم. الأنواع المسموحة: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # M-4: stream with a hard cap instead of buffering the whole body into RAM.
    contents = await read_upload_bounded(
        file, MAX_FILE_MB * 1024 * 1024, content_length=_content_length(request),
    )

    file_id      = str(uuid.uuid4())
    content_type = CONTENT_TYPES.get(suffix, "application/octet-stream")
    filename     = file.filename or f"upload{suffix}"

    db_saved = False
    if db.available():
        db_saved = await db.save_upload(
            file_id=file_id, filename=filename, content_type=content_type,
            data=contents, store_id=store_id, session_id=session_id,
        )
        if not db_saved:
            print(f"[upload] ⚠️ DB save failed for {file_id!r} — falling back to disk only")

    try:
        save_path = UPLOAD_DIR / f"{file_id}{suffix}"
        async with aiofiles.open(save_path, "wb") as f:
            await f.write(contents)
    except Exception as exc:
        print(f"[upload] ⚠️ Disk cache save failed for {file_id!r}: {exc}")
        if not db_saved:
            raise HTTPException(500, f"تعذّر حفظ الملف: {exc}")

    base_url = os.getenv("BASE_URL", "").rstrip("/")
    file_url = f"{base_url}/file/{file_id}" if base_url else f"/file/{file_id}"

    if session_id:
        try:
            notification = f"📎 تم إرفاق ملف تصميم: [{filename}]({file_url})"
            await cs.add_message(session_id, "user", notification, store_id)
        except Exception as exc:
            print(f"[upload] ⚠️ Failed to log upload in conversation: {exc}")

    return {
        "message":  "تم رفع الملف بنجاح! سيتم مراجعته من فريق التصميم وسنتواصل معك قريباً.",
        "file_id":  file_id,
        "filename": filename,
        "url":      file_url,
    }


@router.get("/file/{file_id}")
async def get_uploaded_file(file_id: str):
    if db.available():
        record = await db.load_upload(file_id)
        if record:
            return Response(
                content=record["data"],
                media_type=record["content_type"],
                headers={
                    "Content-Disposition": _content_disposition(record["filename"]),
                    "Content-Security-Policy": _FILE_CSP,
                    "Cache-Control": "private, max-age=3600",
                },
            )

    try:
        if UPLOAD_DIR.exists():
            for path in UPLOAD_DIR.iterdir():
                if path.stem == file_id:
                    # Force download + deny-all CSP — a bare FileResponse would
                    # serve an .svg inline (image/svg+xml) → stored XSS on our
                    # origin. (<img> embedding still works regardless.)
                    return FileResponse(
                        path,
                        headers={
                            "Content-Disposition": "attachment",
                            "Content-Security-Policy": _FILE_CSP,
                            "Cache-Control": "private, max-age=3600",
                        },
                    )
    except Exception as e:
        print(f"[file] disk lookup failed for {file_id!r}: {e}")

    raise HTTPException(404, "الملف غير موجود أو تم حذفه")
