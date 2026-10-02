"""全屏鼠标拖拽选区覆盖层：仅 UI 交互，不负责截图或 AI。

由 DanmuApp 在主线程创建/销毁；坐标均为相对目标显示器左上角。

⚠ 坐标系统警告：
- ``region_w/h > 0`` 时按**屏内相对坐标**裁剪（**不是**绝对屏幕坐标）。
- 与 ``POST/GET /api/capture-region/*`` 配合：Web 端框选区域后写入 config，
  本模块读取并经 ``app.snipper.resolve_capture_rect`` 转为绝对屏幕坐标。
- 禁止把 ``region_*`` 字段写入 ``PUT /api/config`` 全量表单（会污染主配置）；
  区域选择须走 ``/api/capture-region/save`` 专用路由。
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

MIN_REGION_SIZE = 10


def rect_from_drag(x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int]:
    """Normalize drag corners to (x, y, width, height) with non-negative size."""
    left = min(x0, x1)
    top = min(y0, y1)
    return left, top, abs(x1 - x0), abs(y1 - y0)


def normalize_region_for_screen(
    x: int,
    y: int,
    width: int,
    height: int,
    screen_width: int,
    screen_height: int,
    *,
    min_size: int = MIN_REGION_SIZE,
) -> tuple[int, int, int, int] | None:
    """Clamp screen-relative region; return None if invalid or too small."""
    try:
        x = int(x)
        y = int(y)
        width = int(width)
        height = int(height)
        screen_width = int(screen_width)
        screen_height = int(screen_height)
        min_size = int(min_size)
    except (TypeError, ValueError):
        return None

    if width <= 0 or height <= 0:
        return None
    if width < min_size or height < min_size:
        return None

    left = max(0, x)
    top = max(0, y)
    right = min(screen_width, x + width)
    bottom = min(screen_height, y + height)
    if right <= left or bottom <= top:
        return None

    out_w = right - left
    out_h = bottom - top
    if out_w < min_size or out_h < min_size:
        return None
    return left, top, out_w, out_h


class RegionSelectorOverlay(QWidget):
    """Fullscreen semi-transparent overlay on one screen for rubber-band selection."""

    selection_finished = pyqtSignal(QRect)
    selection_cancelled = pyqtSignal()

    def __init__(self, screen, parent=None):
        super().__init__(parent)
        self._screen = screen
        self._origin = QPoint()
        self._current = QPoint()
        self._dragging = False
        self._selection = QRect()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        geo = screen.geometry()
        self.setGeometry(geo)

    def showEvent(self, event):
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._dragging = True
        self._origin = event.position().toPoint()
        self._current = self._origin
        self._selection = QRect(self._origin, self._current)
        self.update()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        self._current = event.position().toPoint()
        x, y, w, h = rect_from_drag(
            self._origin.x(),
            self._origin.y(),
            self._current.x(),
            self._current.y(),
        )
        self._selection = QRect(x, y, w, h)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            super().mouseReleaseEvent(event)
            return
        self._dragging = False
        self._current = event.position().toPoint()
        x, y, w, h = rect_from_drag(
            self._origin.x(),
            self._origin.y(),
            self._current.x(),
            self._current.y(),
        )
        self._selection = QRect(x, y, w, h)
        if w < MIN_REGION_SIZE or h < MIN_REGION_SIZE:
            self._cancel()
            return
        self.selection_finished.emit(QRect(x, y, w, h))
        self.close()

    def _cancel(self):
        self._dragging = False
        self.selection_cancelled.emit()
        self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        full = self.rect()
        dim = QColor(0, 0, 0, 120)
        sel = self._selection.normalized()

        if sel.width() > 0 and sel.height() > 0:
            painter.fillRect(0, 0, full.width(), sel.top(), dim)
            painter.fillRect(0, sel.bottom(), full.width(), full.height() - sel.bottom(), dim)
            painter.fillRect(0, sel.top(), sel.left(), sel.height(), dim)
            painter.fillRect(sel.right(), sel.top(), full.width() - sel.right(), sel.height(), dim)
            pen = QPen(QColor(255, 120, 150, 220), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(sel)
        else:
            painter.fillRect(full, dim)

        painter.end()
        super().paintEvent(event)


def screen_for_index(index: int):
    """Return QScreen for index, clamped to available screens."""
    screens = QApplication.screens()
    if not screens:
        return None
    idx = max(0, min(int(index), len(screens) - 1))
    return screens[idx]


def request_capture_region_selection(
    danmu_app,
    *,
    logger,
    resolve_screen_index_fn,
    screen_for_index_fn,
    close_region_selector_fn,
    on_finished_fn,
    on_cancelled_fn,
    on_destroyed_fn,
    publish_status_fn,
) -> None:
    """启动区域框选覆盖层（从 DanmuApp 迁移）。"""
    from app.web_api.capture_region import SELECTION_SELECTING

    if danmu_app._region_selection_state == SELECTION_SELECTING and danmu_app._region_selector is not None:
        logger.debug("capture region selection already in progress")
        return

    close_region_selector_fn()
    screen_index = resolve_screen_index_fn()
    danmu_app._region_selection_screen_index = screen_index
    screen = screen_for_index_fn(screen_index)
    if screen is None:
        danmu_app._region_selection_state = "invalid"
        logger.warning("capture region selection: no screen available")
        publish_status_fn()
        return

    danmu_app._region_selection_state = SELECTION_SELECTING
    overlay = RegionSelectorOverlay(screen)
    overlay.selection_finished.connect(on_finished_fn)
    overlay.selection_cancelled.connect(on_cancelled_fn)
    overlay.destroyed.connect(on_destroyed_fn)
    danmu_app._region_selector = overlay
    overlay.showFullScreen()
    publish_status_fn()


def close_region_selector(danmu_app, *, reassert_topmost_fn) -> None:
    """关闭区域选择器并清理信号连接（从 DanmuApp 迁移）。"""
    overlay = danmu_app._region_selector
    danmu_app._region_selector = None
    if overlay is None:
        return
    try:
        overlay.selection_finished.disconnect(danmu_app._on_region_selection_finished)
    except (TypeError, RuntimeError):
        pass
    try:
        overlay.selection_cancelled.disconnect(danmu_app._on_region_selection_cancelled)
    except (TypeError, RuntimeError):
        pass
    try:
        overlay.destroyed.disconnect(danmu_app._on_region_selector_destroyed)
    except (TypeError, RuntimeError):
        pass
    try:
        overlay.close()
    except RuntimeError:
        pass
    reassert_topmost_fn()


def on_region_selection_finished(
    danmu_app,
    rect,
    *,
    logger,
    publish_status_fn,
    config_changed_fn,
) -> None:
    """区域选择完成回调（从 DanmuApp 迁移）。"""
    from app.web_api.capture_region import (
        SELECTION_INVALID,
        SELECTION_SAVED,
        apply_capture_region,
    )

    danmu_app._region_selector = None
    screen_index = danmu_app._region_selection_screen_index
    if screen_index is None:
        screen_index = danmu_app.config.get_int("capture_screen_index", 0)
    screen = screen_for_index(screen_index)
    if screen is None:
        danmu_app._region_selection_state = SELECTION_INVALID
        publish_status_fn()
        return

    geo = screen.geometry()
    applied = apply_capture_region(
        danmu_app.config,
        rect.x(),
        rect.y(),
        rect.width(),
        rect.height(),
        screen_width=geo.width(),
        screen_height=geo.height(),
    )
    if applied is None:
        danmu_app._region_selection_state = SELECTION_INVALID
        logger.info("capture region selection rejected: invalid or too small")
    else:
        danmu_app._region_selection_state = SELECTION_SAVED
        logger.info(
            "capture region saved "
            f"x={applied[0]} y={applied[1]} w={applied[2]} h={applied[3]} "
            f"screen_index={screen_index}"
        )
        config_changed_fn()
    publish_status_fn()


def on_region_selection_cancelled(
    danmu_app,
    *,
    logger,
    publish_status_fn,
) -> None:
    """区域选择取消回调（从 DanmuApp 迁移）。"""
    from app.web_api.capture_region import SELECTION_CANCELLED

    danmu_app._region_selector = None
    danmu_app._region_selection_state = SELECTION_CANCELLED
    logger.debug("capture region selection cancelled")
    publish_status_fn()
