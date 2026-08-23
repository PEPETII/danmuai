"""QImage → JPEG Base64 data URI：主链路截图压缩（视觉 AI / 烂梗）。

隐私设计：内存压缩、不落盘。默认 max_width=1024 / quality=85。

与 image_compress.py 并存原因：
- GUI 线程将 QPixmap 复制为 QImage 快照；worker 只处理该线程安全快照，
  并用 Qt ``scaledToWidth`` + ``QImageWriter`` 编码。
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


def pixmap_to_image_snapshot(pixmap: QPixmap) -> QImage:
    """Copy a GUI-thread QPixmap into an independent, worker-safe QImage."""
    if pixmap.isNull():
        raise RuntimeError("invalid pixmap image")
    image = pixmap.toImage()
    if image.isNull():
        raise RuntimeError("invalid pixmap image")
    return image.copy()


def compress_screenshot(
    image: QImage | QPixmap,
    max_width: int = IMAGE_MAX_WIDTH,
    quality: int = IMAGE_JPEG_QUALITY,
) -> str:
    """Read-only encoder for a QImage snapshot.

    QPixmap input remains accepted for GUI-thread callers, but worker paths
    must provide the QImage snapshot created by ``pixmap_to_image_snapshot``.
    """
    qimage = (
        pixmap_to_image_snapshot(image)
        if isinstance(image, QPixmap)
        else image.copy()
    )
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
