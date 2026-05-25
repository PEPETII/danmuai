"""In-memory JPEG compression for web preview (no disk writes)."""

from __future__ import annotations

import base64
import io
from typing import Any

from PIL import Image


def compress_image_bytes(
    data: bytes,
    max_width: int = 768,
    quality: int = 85,
) -> dict[str, Any]:
    pil_image = Image.open(io.BytesIO(data))
    pil_image = pil_image.convert("RGB")
    orig_width, orig_height = pil_image.size

    if orig_width > max_width:
        ratio = max_width / orig_width
        new_height = int(orig_height * ratio)
        pil_image = pil_image.resize((max_width, new_height), Image.Resampling.LANCZOS)

    final_width, final_height = pil_image.size
    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=quality)
    jpeg_bytes = buf.getvalue()
    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")

    return {
        "orig_w": orig_width,
        "orig_h": orig_height,
        "out_w": final_width,
        "out_h": final_height,
        "jpeg_bytes": len(jpeg_bytes),
        "base64_kb": len(b64) / 1024,
        "preview_data_url": f"data:image/jpeg;base64,{b64}",
    }
