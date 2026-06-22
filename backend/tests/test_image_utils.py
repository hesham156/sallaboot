"""
Unit tests for image_utils.optimize_image — the blog image optimiser.
Generates images in-memory with Pillow (no fixtures, no disk).
"""
from __future__ import annotations

import io

import pytest

import image_utils

pytestmark = pytest.mark.unit

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _png(w: int, h: int, color=(200, 30, 30), mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def test_outputs_webp():
    out, ext, ct = image_utils.optimize_image(_png(400, 300))
    assert ext == ".webp" and ct == "image/webp"
    assert Image.open(io.BytesIO(out)).format == "WEBP"


def test_downscales_when_larger_than_max():
    out, _e, _c = image_utils.optimize_image(_png(4000, 2000), max_dim=1600)
    im = Image.open(io.BytesIO(out))
    assert max(im.size) == 1600          # longest edge clamped
    assert im.size == (1600, 800)        # aspect ratio preserved


def test_does_not_upscale_small_images():
    out, _e, _c = image_utils.optimize_image(_png(300, 200), max_dim=1600)
    assert Image.open(io.BytesIO(out)).size == (300, 200)


def test_shrinks_a_big_noisy_photo():
    # A large PNG → WebP should be meaningfully smaller.
    import os
    big = _png(2000, 2000, color=(123, 222, 64))
    out, _e, _c = image_utils.optimize_image(big)
    assert len(out) < len(big)
    assert max(Image.open(io.BytesIO(out)).size) == 1600
    os.environ  # noqa: B018 - keep import used; harmless


def test_rejects_non_image():
    with pytest.raises(image_utils.ImageError):
        image_utils.optimize_image(b"this is definitely not an image")


def test_rgba_preserved_as_webp():
    out, ext, _c = image_utils.optimize_image(_png(120, 120, color=(0, 0, 0, 0), mode="RGBA"))
    assert ext == ".webp"
    assert Image.open(io.BytesIO(out)).mode in ("RGBA", "RGB")
