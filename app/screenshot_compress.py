"""QPixmap → JPEG Base64 data URI：主链路截图压缩（视觉 AI / 烂梗）。

隐私设计：内存压缩、不落盘。默认 max_width=1024 / quality=85。

与 image_compress.py 并存原因：
- 输入已是 QPixmap（CaptureRunnable QThreadPool），Qt ``scaledToWidth`` +
  ``QImageWriter`` 避免 toImage→RGB888→Pillow 的额外拷贝。
- Web 预览走 bytes+PIL（``image_compress``），无法在 HTTP 线程引入 Qt。
- 两条管线共用 ``jpeg_resize.jpeg_bytes_to_data_uri``；PIL resize 仅在
  ``jpeg_resize.resize_rgb_to_jpeg_bytes``，本模块不走该函数。
"""

from __future__ import annotations

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QImageWriter, QPixmap

from app.config_defaults import DEFAULT_IMAGE_MAX_WIDTH
from app.jpeg_resize import jpeg_bytes_to_data_uri

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
    return jpeg_bytes_to_data_uri(jpeg_bytes)
