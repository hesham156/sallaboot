"""File upload and download routes."""
import os
import uuid
from pathlib import Path
from urllib.parse import quote

import aiofiles
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response

import database as db
import conversation_store as cs
from routers.deps import UPLOAD_DIR, MAX_FILE_MB, ALLOWED_EXTENSIONS, CONTENT_TYPES, is_internal_session_id

router = APIRouter()


def _content_disposition(filename: str, disposition: str = "inline") -> str:
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
):
    # H-1: refuse to attach a file to a channel-owned conversation (wa:/msgr:/ig:)
    # — that would inject a forged "customer sent a file" message into a real
    # WhatsApp/Messenger/Instagram thread. Widget uploads use random-uuid ids.
    if is_internal_session_id(session_id):
        raise HTTPException(404, "الجلسة غير موجودة")
    if "{{" in store_id or "}}" in store_id:
        store_id = "default"

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"نوع الملف غير مدعوم. الأنواع المسموحة: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(413, f"حجم الملف يتجاوز الحد المسموح ({MAX_FILE_MB} MB)")

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
                    "Cache-Control": "private, max-age=3600",
                },
            )

    try:
        if UPLOAD_DIR.exists():
            for path in UPLOAD_DIR.iterdir():
                if path.stem == file_id:
                    return FileResponse(path)
    except Exception as e:
        print(f"[file] disk lookup failed for {file_id!r}: {e}")

    raise HTTPException(404, "الملف غير موجود أو تم حذفه")
