"""Transparent desktop pet window: animation, drag, context menu, command box."""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Callable

from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer
from PyQt6.QtGui import QAction, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QLineEdit, QMenu, QWidget

from app.pet.pet_assets import PET_FRAME_H, PET_FRAME_W, PetAssetPack, load_pet_assets
from app.pet.pet_animation_mapper import resolve_pet_animation_hint
from app.pet.pet_state import PetSettings

if TYPE_CHECKING:
    from main import DanmuApp

if sys.platform == "win32":
    import ctypes

    _GWL_EXSTYLE = -20
    _WS_EX_LAYERED = 0x00080000
    _WS_EX_TRANSPARENT = 0x00000020
    _HWND_TOPMOST = -1
    _SWP_NOMOVE = 0x0002
    _SWP_NOSIZE = 0x0001
    _SWP_NOACTIVATE = 0x0010
    _SWP_SHOWWINDOW = 0x0040
    try:
        _SetWindowLong = ctypes.windll.user32.SetWindowLongPtrW
        _GetWindowLong = ctypes.windll.user32.GetWindowLongPtrW
    except AttributeError:
        _SetWindowLong = ctypes.windll.user32.SetWindowLongW
        _GetWindowLong = ctypes.windll.user32.GetWindowLongW
    _SetWindowPos = ctypes.windll.user32.SetWindowPos

_ANIM_INTERVAL_MS = 16
_FRAME_DT = 1.0 / 9.0


class PetWindow(QWidget):
    """Desktop pet floater; independent of danmu_render_mode / overlay."""

    def __init__(self, danmu_app: "DanmuApp"):
        super().__init__()
        self._app = danmu_app
        self._settings = PetSettings.from_config(danmu_app.config)
        self._pack: PetAssetPack | None = None
        self._spritesheet: QPixmap | None = None
        self._frame_index = 0
        self._frame_clock = 0.0
        self._animation_state = "idle"
        self._one_shot: str | None = None
        self._one_shot_until = 0.0
        self._drag_offset: QPoint | None = None
        self._load_error: str | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("background: transparent;")

        self._command_edit = QLineEdit(self)
        self._command_edit.setPlaceholderText("输入弹幕指令，Enter 提交，Esc 关闭")
        self._command_edit.setFont(QFont("Microsoft YaHei", 10))
        self._command_edit.hide()
        self._command_edit.returnPressed.connect(self._submit_command)
        self._command_edit.installEventFilter(self)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(_ANIM_INTERVAL_MS)
        self._anim_timer.timeout.connect(self._on_anim_tick)

        self.reload_assets()
        self._apply_window_geometry()
        self._sync_click_through()

    def reload_assets(self) -> None:
        try:
            self._pack = load_pet_assets(self._app.config)
            self._spritesheet = QPixmap(str(self._pack.spritesheet_path))
            self._load_error = None
        except ValueError as exc:
            self._pack = None
            self._spritesheet = None
            self._load_error = str(exc)

    def apply_config(self) -> None:
        self._settings = PetSettings.from_config(self._app.config)
        self.reload_assets()
        self._apply_window_geometry()
        self._sync_click_through()
        if self.isVisible():
            self.update()

    def notify_command_submitted(self) -> None:
        self._trigger_one_shot("jump")

    def notify_reply_success(self) -> None:
        self._trigger_one_shot("wave")

    def notify_error(self) -> None:
        self._trigger_one_shot("failed")

    def _trigger_one_shot(self, state: str, duration: float = 1.5) -> None:
        self._one_shot = state
        self._one_shot_until = time.monotonic() + duration
        self._frame_index = 0

    def start_render_loop(self) -> None:
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def stop_render_loop(self) -> None:
        self._anim_timer.stop()

    def show_pet(self) -> None:
        self._apply_window_geometry()
        self.show()
        self.raise_()
        self._reassert_topmost()
        self.start_render_loop()

    def hide_pet(self) -> None:
        self.stop_render_loop()
        self._hide_command_box()
        self.hide()

    def _pet_size(self) -> tuple[int, int]:
        scale = self._settings.scale
        return (int(PET_FRAME_W * scale), int(PET_FRAME_H * scale))

    def _apply_window_geometry(self) -> None:
        w, h = self._pet_size()
        self.setFixedSize(w, h + 40)
        self._command_edit.setGeometry(0, 0, w, 32)
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = self._settings.position_x
        y = self._settings.position_y
        if x is None or y is None:
            x = geo.right() - w - 40
            y = geo.bottom() - h - 80
        self.move(int(x), int(y))

    def _sync_click_through(self) -> None:
        if sys.platform != "win32":
            return
        hwnd = int(self.winId())
        ex_style = _GetWindowLong(hwnd, _GWL_EXSTYLE)
        if self._settings.click_through:
            _SetWindowLong(hwnd, _GWL_EXSTYLE, ex_style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT)
        else:
            _SetWindowLong(hwnd, _GWL_EXSTYLE, (ex_style | _WS_EX_LAYERED) & ~_WS_EX_TRANSPARENT)

    def _reassert_topmost(self) -> None:
        if not self._settings.always_on_top or sys.platform != "win32":
            return
        hwnd = int(self.winId())
        _SetWindowPos(
            hwnd,
            _HWND_TOPMOST,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
        )

    def _current_animation(self) -> str:
        return resolve_pet_animation_hint(
            self._app,
            one_shot=self._one_shot,
            one_shot_until=self._one_shot_until,
        )

    def _on_anim_tick(self) -> None:
        self._animation_state = self._current_animation()
        self._frame_clock += _ANIM_INTERVAL_MS / 1000.0
        if self._frame_clock >= _FRAME_DT:
            self._frame_clock = 0.0
            frame_count = self._pack.frame_count if self._pack else 9
            self._frame_index = (self._frame_index + 1) % max(1, frame_count)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        opacity = max(0.2, min(self._settings.opacity, 1.0))
        painter.setOpacity(opacity)
        w, h = self._pet_size()
        y_offset = 36 if self._command_edit.isVisible() else 0
        if self._load_error:
            painter.setPen(Qt.GlobalColor.red)
            painter.drawText(8, y_offset + 24, "宠物加载失败")
            return
        if self._pack is None or self._spritesheet is None or self._spritesheet.isNull():
            return
        sx, sy, sw, sh = self._pack.frame_rect(self._animation_state, self._frame_index)
        painter.drawPixmap(0, y_offset, w, h, self._spritesheet, sx, sy, sw, sh)

    def mousePressEvent(self, event) -> None:
        if self._settings.click_through:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._settings.click_through or self._drag_offset is None:
            return
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self._persist_position()
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._settings.click_through or not self._settings.command_box_enabled:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._show_command_box()
            event.accept()

    def contextMenuEvent(self, event) -> None:
        if self._settings.click_through:
            return
        menu = QMenu(self)
        running = bool(getattr(self._app.engine, "running", False))
        toggle_action = QAction("停止弹幕" if running else "开始弹幕", self)
        toggle_action.triggered.connect(self._app.toggle)
        menu.addAction(toggle_action)

        if self.isVisible():
            hide_action = QAction("隐藏桌宠", self)
            hide_action.triggered.connect(lambda: self._app.hide_pet())
            menu.addAction(hide_action)
        else:
            show_action = QAction("显示桌宠", self)
            show_action.triggered.connect(lambda: self._app.show_pet())
            menu.addAction(show_action)

        settings_action = QAction("桌宠设置", self)
        settings_action.triggered.connect(self._open_settings_page)
        menu.addAction(settings_action)

        close_action = QAction("关闭桌宠", self)
        close_action.triggered.connect(lambda: self._app.close_pet())
        menu.addAction(close_action)
        menu.exec(event.globalPos())

    def _open_settings_page(self) -> None:
        opener: Callable[[str], None] | None = getattr(self._app, "_open_web_console", None)
        if opener:
            opener("/#pet")

    def _persist_position(self) -> None:
        pos = self.pos()
        self._app.config.set("pet_position_x", str(pos.x()))
        self._app.config.set("pet_position_y", str(pos.y()))

    def _show_command_box(self) -> None:
        self._command_edit.clear()
        self._command_edit.show()
        self._command_edit.setFocus()
        self.update()

    def _hide_command_box(self) -> None:
        self._command_edit.hide()
        self.update()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._command_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._hide_command_box()
                return True
        return super().eventFilter(obj, event)

    def _submit_command(self) -> None:
        text = self._command_edit.text()
        try:
            result = self._app.submit_pet_command(text, source="desktop_pet")
            self._hide_command_box()
            self.notify_command_submitted()
            bridge = getattr(self._app, "web_bridge", None)
            if bridge and hasattr(bridge, "publish_toast"):
                bridge.publish_toast("已加入下一次弹幕生成")
            elif result.get("ok"):
                pass
        except ValueError as exc:
            bridge = getattr(self._app, "web_bridge", None)
            if bridge and hasattr(bridge, "publish_toast"):
                bridge.publish_toast(str(exc), is_error=True)
