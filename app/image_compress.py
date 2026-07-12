"""内存 JPEG 压缩：Web 预览专用 bytes 入口（不落盘）。

与 screenshot_compress.py 并存原因：
- 本模块处理任意 bytes 输入（POST /api/preview/compress），运行在 uvicorn HTTP
  线程，不能依赖 QApplication/QPixmap。
- screenshot_compress 专用于主链路 QPixmap 快照（QThreadPool），保留 Qt 原生
  resize/encode 以避免 RGB 缓冲拷贝与额外 PIL 开销。
- 两条管线共用 ``jpeg_resize.jpeg_bytes_to_data_uri`` 组装 data URI。
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image

from app.config_defaults import DEFAULT_IMAGE_MAX_WIDTH
from app.jpeg_resize import JPEG_DATA_URI_PREFIX, jpeg_bytes_to_data_uri, resize_rgb_to_jpeg_bytes


def compress_image_bytes(
    data: bytes,
    max_width: int = DEFAULT_IMAGE_MAX_WIDTH,
    quality: int = 85,
) -> dict[str, Any]:
    pil_image = Image.open(io.BytesIO(data))
    orig_width, orig_height = pil_image.size
    _, jpeg_bytes, final_width, final_height = resize_rgb_to_jpeg_bytes(
        pil_image,
        max_width=max_width,
        quality=quality,
    )
    preview_data_url = jpeg_bytes_to_data_uri(jpeg_bytes)
    b64_len = len(preview_data_url) - len(JPEG_DATA_URI_PREFIX)

    return {
        "orig_w": orig_width,
        "orig_h": orig_height,
        "out_w": final_width,
        "out_h": final_height,
        "jpeg_bytes": len(jpeg_bytes),
        "base64_kb": b64_len / 1024,
        "preview_data_url": preview_data_url,
    }
