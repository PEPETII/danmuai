"""QPixmap → JPEG Base64 data URI：视觉 AI 请求的截图压缩。

隐私设计：内存压缩、不落盘。默认 max_width=1024 / quality=85，返回 data:image/jpeg;base64,...。
"""

from __future__ import annotations

import base64

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QImageWriter, QPixmap

from app.config_defaults import DEFAULT_IMAGE_MAX_WIDTH

IMAGE_MAX_WIDTH = DEFAULT_IMAGE_MAX_WIDTH
IMAGE_JPEG_QUALITY = 85


def compress_screenshot(
    pixmap: QPixmap,
    max_width: int = IMAGE_MAX_WIDTH,
    quality: int = IMAGE_JPEG_QUALITY,
) -> str:
    """Read-only: does not mutate the input QPixmap."""
    qimage = pixmap.toImage()
    if qimage.isNull():
        raise RuntimeError("invalid pixmap image")

    if qimage.format() != QImage.Format.Format_RGB888:
        qimage = qimage.convertToFormat(QImage.Format.Format_RGB888)

    if qimage.width() > max_width:
        qimage = qimage.scaledToWidth(
            max_width,
            Qt.TransformationMode.SmoothTransformation,
        )

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QImageWriter()
    writer.setDevice(buffer)
    writer.setFormat(b"jpg")
    writer.setQuality(quality)
    if not writer.write(qimage):
        raise RuntimeError(writer.errorString())

    jpeg_bytes = bytes(buffer.data())
    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"
