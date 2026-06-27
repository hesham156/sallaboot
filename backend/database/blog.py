"""database.blog — split out of the original single-file database.py."""
from database import _core




# ── Blog posts ──────────────────────────────────────────────────────────────
# Dashboard-managed SEO articles. Public reads filter on published=TRUE and
# order by published_at DESC. Super-admin writes go through the /admin/blog
# endpoints — we trust the caller to have been authenticated by middleware.

async def blog_list_public() -> list[dict]:
    """Newest published posts first — what BlogList renders."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, slug, title, description, tags, author,
                       read_time, cover_image, published_at
                FROM blog_posts
                WHERE published = TRUE
                ORDER BY published_at DESC NULLS LAST, created_at DESC
            """)
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] blog_list_public error: {e}")
        return []


async def blog_list_all() -> list[dict]:
    """Every post incl. drafts — what the admin dashboard renders."""
    if not _core._pool:
        return []
    try:
        async with _core._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, slug, title, description, tags, author,
                       read_time, cover_image, published, published_at,
                       created_at, updated_at
                FROM blog_posts
                ORDER BY COALESCE(published_at, created_at) DESC
            """)
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[db] blog_list_all error: {e}")
        return []


async def blog_get_by_slug(slug: str, *, only_published: bool = True) -> dict | None:
    """Single post. Public callers must pass only_published=True so a
    draft slug can't be guessed and leaked before launch."""
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            if only_published:
                row = await conn.fetchrow("""
                    SELECT id, slug, title, description, content_md, tags,
                           author, read_time, cover_image, published, published_at
                    FROM blog_posts
                    WHERE slug = $1 AND published = TRUE
                """, slug)
            else:
                row = await conn.fetchrow("""
                    SELECT id, slug, title, description, content_md, tags,
                           author, read_time, cover_image, published, published_at,
                           created_at, updated_at
                    FROM blog_posts
                    WHERE slug = $1
                """, slug)
            return dict(row) if row else None
    except Exception as e:
        print(f"[db] blog_get_by_slug({slug!r}) error: {e}")
        return None


async def blog_get_by_id(post_id: int) -> dict | None:
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, slug, title, description, content_md, tags,
                       author, read_time, cover_image, published, published_at,
                       created_at, updated_at
                FROM blog_posts
                WHERE id = $1
            """, post_id)
            return dict(row) if row else None
    except Exception as e:
        print(f"[db] blog_get_by_id({post_id}) error: {e}")
        return None


async def blog_create(data: dict) -> dict | None:
    """Insert a new post. `data` keys: slug, title, description, content_md,
    tags (list), author, read_time, published. published_at auto-set when
    published is True. Returns the inserted row or None on failure."""
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO blog_posts
                    (slug, title, description, content_md, tags, author,
                     read_time, published, cover_image, published_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                        CASE WHEN $8 THEN NOW() ELSE NULL END)
                RETURNING id, slug, title, description, content_md, tags,
                          author, read_time, cover_image, published, published_at,
                          created_at, updated_at
            """,
                data["slug"], data["title"], data.get("description", ""),
                data.get("content_md", ""), data.get("tags", []) or [],
                data.get("author", "فريق حياك"),
                int(data.get("read_time", 5)), bool(data.get("published", False)),
                data.get("cover_image") or None,
            )
            return dict(row) if row else None
    except Exception as e:
        print(f"[db] blog_create error: {e}")
        return None


async def blog_update(post_id: int, data: dict) -> dict | None:
    """Update a post in place. Flipping published False→True sets
    published_at to NOW (first publication). Flipping True→False doesn't
    clear it — once published, the date stays for canonical reference."""
    if not _core._pool:
        return None
    try:
        async with _core._pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE blog_posts SET
                    slug         = COALESCE($2, slug),
                    title        = COALESCE($3, title),
                    description  = COALESCE($4, description),
                    content_md   = COALESCE($5, content_md),
                    tags         = COALESCE($6, tags),
                    author       = COALESCE($7, author),
                    read_time    = COALESCE($8, read_time),
                    published    = COALESCE($9, published),
                    cover_image  = COALESCE($10, cover_image),
                    published_at = CASE
                        WHEN $9 = TRUE AND published_at IS NULL THEN NOW()
                        ELSE published_at
                    END,
                    updated_at   = NOW()
                WHERE id = $1
                RETURNING id, slug, title, description, content_md, tags,
                          author, read_time, cover_image, published, published_at,
                          created_at, updated_at
            """,
                post_id,
                data.get("slug"),
                data.get("title"),
                data.get("description"),
                data.get("content_md"),
                data.get("tags"),
                data.get("author"),
                data.get("read_time"),
                data.get("published"),
                data.get("cover_image"),
            )
            return dict(row) if row else None
    except Exception as e:
        print(f"[db] blog_update({post_id}) error: {e}")
        return None


async def blog_delete(post_id: int) -> bool:
    if not _core._pool:
        return False
    try:
        async with _core._pool.acquire() as conn:
            r = await conn.execute("DELETE FROM blog_posts WHERE id = $1", post_id)
        # `r` looks like "DELETE 1" / "DELETE 0"
        return r.endswith("1")
    except Exception as e:
        print(f"[db] blog_delete({post_id}) error: {e}")
        return False
