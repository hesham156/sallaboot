"""Blog post API — public reads + super-admin CRUD.

Architecture:
  • Public reads (`/api/blog/*`) are unauthenticated and only return
    rows where published=TRUE.
  • Admin writes (`/admin/blog/*`) require a super-admin Bearer token,
    enforced inline (the middleware allowlist only checks "logged-in"
    for /admin/* so we double-check the .su claim here).

Why a separate router (not extending routers/public.py): keeps the
public.py file focused on SPA shell + health endpoints, and gives
us a clean place to add image uploads or richer post features later.
"""
from __future__ import annotations

import os
import re
import uuid

import aiofiles
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field

import auth as _auth
import database as db
import image_utils
from routers.deps import UPLOAD_DIR, MAX_FILE_MB, read_upload_bounded, _content_length

router = APIRouter()

# Images the blog editor accepts (validated by extension AND decoded by Pillow).
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


# ── Helpers ────────────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _require_super(request: Request) -> dict:
    """Inline super-admin check. Returns the JWT claims on success."""
    token  = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    claims = _auth.verify_token(token) or {}
    if not claims.get("su"):
        raise HTTPException(403, "مصرح للمدير العام فقط")
    return claims


def _serialize(row: dict, *, include_content: bool = True) -> dict:
    """Convert a DB row → JSON-safe dict. tags is a Postgres array;
    datetimes become ISO strings."""
    if not row:
        return row
    out = dict(row)
    for k in ("created_at", "updated_at", "published_at"):
        v = out.get(k)
        if v is not None and hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    out["tags"] = list(out.get("tags") or [])
    if not include_content:
        out.pop("content_md", None)
    return out


# ── Pydantic models ───────────────────────────────────────────────────────

class BlogPostCreate(BaseModel):
    slug:        str
    title:       str
    description: str  = ""
    content_md:  str  = ""
    tags:        list[str] = Field(default_factory=list)
    author:      str  = "فريق حياك"
    read_time:   int  = 5
    published:   bool = False
    cover_image: str  = ""


class BlogPostUpdate(BaseModel):
    # Every field optional → caller can patch one column without re-sending
    # the full post. None values are SQL NULLs that the COALESCE in
    # blog_update() falls back to the existing column value for.
    slug:        str  | None = None
    title:       str  | None = None
    description: str  | None = None
    content_md:  str  | None = None
    tags:        list[str] | None = None
    author:      str  | None = None
    read_time:   int  | None = None
    published:   bool | None = None
    cover_image: str  | None = None


# ── Public reads (no auth) ────────────────────────────────────────────────

@router.get("/api/blog/posts")
async def list_published_posts():
    """List of published posts for the public /blog page. Content body
    omitted — only metadata to keep the list response light."""
    rows = await db.blog_list_public()
    return {"posts": [_serialize(r, include_content=False) for r in rows]}


@router.get("/api/blog/posts/{slug}")
async def get_published_post(slug: str):
    row = await db.blog_get_by_slug(slug, only_published=True)
    if not row:
        raise HTTPException(404, "المقال غير موجود أو غير منشور")
    return _serialize(row)


# ── Admin CRUD (super-admin only) ─────────────────────────────────────────

@router.get("/admin/blog/posts")
async def admin_list_posts(request: Request):
    _require_super(request)
    rows = await db.blog_list_all()
    return {"posts": [_serialize(r, include_content=False) for r in rows]}


@router.get("/admin/blog/posts/{post_id}")
async def admin_get_post(post_id: int, request: Request):
    _require_super(request)
    row = await db.blog_get_by_id(post_id)
    if not row:
        raise HTTPException(404, "المقال غير موجود")
    return _serialize(row)


@router.post("/admin/blog/posts")
async def admin_create_post(req: BlogPostCreate, request: Request):
    _require_super(request)

    slug = (req.slug or "").strip().lower()
    if not _SLUG_RE.match(slug):
        raise HTTPException(400, "الـ slug لازم يكون حروف إنجليزية صغيرة وأرقام وشرطات فقط (مثل: my-first-post)")
    if not req.title.strip():
        raise HTTPException(400, "العنوان مطلوب")
    if len(slug) > 200:
        raise HTTPException(400, "الـ slug طويل جداً (200 حرف كحد أقصى)")

    # Reject slug collision early with a user-friendly message — the
    # UNIQUE constraint would also catch it, but as a 500-flavoured error.
    existing = await db.blog_get_by_slug(slug, only_published=False)
    if existing:
        raise HTTPException(409, f"مقال بهذا الـ slug موجود بالفعل: {slug!r}")

    row = await db.blog_create(req.model_dump())
    if not row:
        raise HTTPException(500, "فشل إنشاء المقال — راجع Railway logs")
    return _serialize(row)


@router.put("/admin/blog/posts/{post_id}")
async def admin_update_post(post_id: int, req: BlogPostUpdate, request: Request):
    _require_super(request)

    # Validate slug if the caller is changing it.
    if req.slug is not None:
        slug = req.slug.strip().lower()
        if not _SLUG_RE.match(slug):
            raise HTTPException(400, "الـ slug لازم يكون حروف إنجليزية صغيرة وأرقام وشرطات فقط")
        # Check collision against OTHER posts only (the current post can
        # keep its own slug).
        collision = await db.blog_get_by_slug(slug, only_published=False)
        if collision and collision["id"] != post_id:
            raise HTTPException(409, f"مقال بهذا الـ slug موجود بالفعل: {slug!r}")

    # model_dump(exclude_unset=True) → only the keys the caller actually
    # sent. None values for unsent fields stay out so blog_update's
    # COALESCE leaves them alone.
    patch = req.model_dump(exclude_unset=True)
    if not patch:
        # Empty PUT — return the row unchanged.
        row = await db.blog_get_by_id(post_id)
    else:
        row = await db.blog_update(post_id, patch)
    if not row:
        raise HTTPException(404, "المقال غير موجود")
    return _serialize(row)


@router.delete("/admin/blog/posts/{post_id}")
async def admin_delete_post(post_id: int, request: Request):
    _require_super(request)
    ok = await db.blog_delete(post_id)
    if not ok:
        raise HTTPException(404, "المقال غير موجود")
    return {"status": "ok", "deleted_id": post_id}


# ── Image upload (super-admin) ────────────────────────────────────────────────

@router.post("/admin/blog/upload-image")
async def admin_upload_blog_image(request: Request, file: UploadFile = File(...)):
    """Optimise + store an image for a blog cover or inline use. Returns a
    `/file/<id>` URL. The image is downscaled (≤1600px) and re-encoded as
    WebP server-side, so a 4 MB phone photo becomes a lean web asset."""
    _require_super(request)

    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in _IMAGE_EXTS:
        raise HTTPException(400, f"نوع الصورة غير مدعوم. المسموح: {', '.join(sorted(_IMAGE_EXTS))}")

    raw = await read_upload_bounded(
        file, MAX_FILE_MB * 1024 * 1024, content_length=_content_length(request),
    )

    try:
        data, ext, content_type = image_utils.optimize_image(raw)
    except image_utils.ImageError:
        raise HTTPException(400, "تعذّر قراءة الصورة — تأكد أنها ملف صورة صالح")

    file_id  = str(uuid.uuid4())
    filename = f"blog-{file_id}{ext}"

    if db.available():
        await db.save_upload(
            file_id=file_id, filename=filename, content_type=content_type,
            data=data, store_id="_blog", session_id="",
        )
    try:
        async with aiofiles.open(UPLOAD_DIR / f"{file_id}{ext}", "wb") as f:
            await f.write(data)
    except Exception as exc:
        print(f"[blog] image disk cache failed for {file_id!r}: {exc}")

    base_url = os.getenv("BASE_URL", "").rstrip("/")
    url = f"{base_url}/file/{file_id}" if base_url else f"/file/{file_id}"
    return {"url": url, "bytes": len(data), "content_type": content_type}
