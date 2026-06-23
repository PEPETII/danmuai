"""Shared PIL JPEG resize for screenshot and web preview compression."""

from __future__ import annotations

import io

from PIL import Image

from app.config_defaults import DEFAULT_IMAGE_MAX_WIDTH


def resize_rgb_to_jpeg_bytes(
    pil_image: Image.Image,
    *,
    max_width: int = DEFAULT_IMAGE_MAX_WIDTH,
    quality: int = 85,
) -> tuple[Image.Image, bytes, int, int]:
    """Resize RGB image if wider than max_width; return (final PIL, jpeg bytes, out_w, out_h)."""
    pil_image = pil_image.convert("RGB")
    orig_width, orig_height = pil_image.size
    if orig_width > max_width:
        ratio = max_width / orig_width
        new_height = int(orig_height * ratio)
        pil_image = pil_image.resize((max_width, new_height), Image.Resampling.LANCZOS)
    final_width, final_height = pil_image.size
    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=quality)
    return pil_image, buf.getvalue(), final_width, final_height
