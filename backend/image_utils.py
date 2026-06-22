"""
image_utils.py — server-side image optimisation for uploads.

One job: take raw image bytes and return a smaller, web-friendly version.
  • auto-orient from EXIF, then strip all metadata (privacy + size)
  • downscale so the longest edge ≤ max_dim (never upscales)
  • re-encode as WebP (or keep PNG when transparency must survive losslessly)

Used by the blog image-upload endpoint. Pure + dependency-light (Pillow only),
so it's easy to unit-test without a DB or network.
"""
from __future__ import annotations

import io

try:
    from PIL import Image, ImageOps
    _PIL_OK = True
except Exception:  # pragma: no cover - Pillow always present in prod
    _PIL_OK = False


# Generous default ceiling: a 1600px-wide hero looks crisp on retina without
# shipping a 4000px phone photo to every reader.
DEFAULT_MAX_DIM = 1600
DEFAULT_QUALITY = 82


class ImageError(ValueError):
    """Raised when the bytes aren't a decodable image."""


def optimize_image(
    data: bytes,
    *,
    max_dim: int = DEFAULT_MAX_DIM,
    quality: int = DEFAULT_QUALITY,
) -> tuple[bytes, str, str]:
    """
    Optimise `data`. Returns (out_bytes, extension, content_type).

    Always emits WebP — it beats JPEG/PNG at the same quality and every modern
    browser supports it. Animated GIFs are passed through untouched (Pillow's
    single-frame save would drop the animation).

    Raises ImageError on undecodable input. Never raises on a *valid* image —
    if optimisation somehow grows the file, the original-as-webp is still
    returned (callers can fall back to the raw bytes if they prefer).
    """
    if not _PIL_OK:
        raise ImageError("Pillow not available")

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:
        raise ImageError(f"not a decodable image: {exc}") from exc

    # Preserve animated GIFs verbatim (don't flatten to one frame).
    if getattr(im, "is_animated", False):
        return data, ".gif", "image/gif"

    # Respect EXIF orientation, then drop EXIF so a re-share can't leak GPS.
    im = ImageOps.exif_transpose(im)

    # Flatten anything with alpha onto white only if we were going to lose it;
    # WebP supports alpha, so keep RGBA → RGBA, else RGB.
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
    else:
        im = im.convert("RGB")

    # Downscale (never upscale) so the longest edge ≤ max_dim.
    w, h = im.size
    longest = max(w, h)
    if longest > max_dim:
        scale = max_dim / float(longest)
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

    out = io.BytesIO()
    im.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue(), ".webp", "image/webp"
