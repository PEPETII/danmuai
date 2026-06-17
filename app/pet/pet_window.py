"""Transparent desktop pet window: animation, drag, context menu, command box, bubble."""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PyQt6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QTextOption
from PyQt6.QtWidgets import QApplication, QLineEdit, QMenu, QWidget

from app.pet.pet_animation_mapper import resolve_pet_animation_hint
from app.pet.pet_assets import PET_FRAME_H, PET_FRAME_W, PetAssetPack, load_pet_assets, validate_pet_pack_dir
from app.pet.pet_state import PetSettings

if TYPE_CHECKING:
    from main import DanmuApp

from app.win32_overlay_zorder import (
    apply_overlay_exstyles,
    reassert_hwnd_topmost,
    stack_hwnd_above,
)

if sys.platform == "win32":
    import ctypes

    _DWMWA_WINDOW_CORNER_PREFERENCE = 33
    _DWMWCP_DONOTROUND = 1

_ANIM_INTERVAL_MS = 16
_DEFAULT_FRAME_INTERVAL_SEC = 1100 / 6 / 1000.0

# PetDex Desktop drag/momentum parity (packages/petdex-desktop/src/main.zig).
_DRAG_THRESHOLD_PX = 4
_MIN_VEL_PX_PER_SEC = 65.0
_MOMENTUM_FRICTION = 0.88
_MOMENTUM_MAX_DURATION_MS = 900
_POINTER_SAMPLE_WINDOW_SEC = 0.1
_WAVING_HOLD_SEC = 1.2
_MIN_SAMPLE_GAP_SEC = 0.016
_COMMAND_EDIT_HEIGHT = 32
_COMMAND_SPRITE_GAP = 4
_COMMAND_BAND_HEIGHT = _COMMAND_EDIT_HEIGHT + _COMMAND_SPRITE_GAP
_BUBBLE_MAX_WIDTH = 280
_BUBBLE_FADE_STEP = 0.14
_BUBBLE_MAX_ALPHA = 0.92


def command_band_height(command_visible: bool) -> int:
    """Extra window height reserved above the sprite when the command box is open."""
    return _COMMAND_BAND_HEIGHT if command_visible else 0


def sprite_y_offset(command_visible: bool) -> int:
    """Vertical offset for sprite paint/draw when the command box occupies the top band."""
    return _COMMAND_BAND_HEIGHT if command_visible else 0


@dataclass(frozen=True)
class PointerSample:
    x: float
    y: float
    t: float


def drag_run_state_for_dx(dx: float, *, threshold: float = _DRAG_THRESHOLD_PX) -> str | None:
    if dx >= threshold:
        return "running-right"
    if dx <= -threshold:
        return "running-left"
    return None


def momentum_run_state_for_vx(vx: float, *, min_vel: float = _MIN_VEL_PX_PER_SEC) -> str | None:
    if vx >= min_vel:
        return "running-right"
    if vx <= -min_vel:
        return "running-left"
    return None


def compute_pointer_velocity(
    samples: list[PointerSample],
    *,
    min_sample_gap_sec: float = _MIN_SAMPLE_GAP_SEC,
) -> tuple[float, float] | None:
    if len(samples) < 2:
        return None
    last = samples[-1]
    first = next((s for s in samples if last.t - s.t > min_sample_gap_sec), None)
    if first is None:
        return None
    dt = last.t - first.t
    if dt <= 0:
        return None
    return ((last.x - first.x) / dt, (last.y - first.y) / dt)


def resolve_interaction_animation(
    *,
    dragging: bool,
    momentum_active: bool,
    drag_anim_state: str,
    post_drag_waving_until: float,
    now: float,
    mapper_state: str,
) -> str:
    """Drag / throw / post-drag waving take precedence over agent mapper (PetDex parity)."""
    if dragging or momentum_active:
        return drag_anim_state
    if post_drag_waving_until > now:
        return "waving"
    return mapper_state


class PetWindow(QWidget):
    """Desktop pet floater; independent of danmu_render_mode / overlay."""

    def __init__(self, danmu_app: "DanmuApp", *, slot_id: int = 0):
        super().__init__()
        self._app = danmu_app
        self.slot_id = int(slot_id)
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
        self._dragging = False
        self._drag_anim_state = "jumping"
        self._momentum_active = False
        self._momentum_vx = 0.0
        self._momentum_vy = 0.0
        self._momentum_elapsed_ms = 0.0
        self._pointer_samples: list[PointerSample] = []
        self._post_drag_waving_until = 0.0
        self._last_painted_frame_index = -1
        self._last_painted_animation_state = ""
        self._slot_asset_source = self._settings.asset_source
        self._slot_asset_path = self._settings.asset_path
        self._slot_position_x = self._settings.position_x
        self._slot_position_y = self._settings.position_y
        self._bubble_text = ""
        self._bubble_alpha = 0.0
        self._bubble_target_alpha = 0.0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")

        self._command_edit = QLineEdit(self)
        self._command_edit.setPlaceholderText("输入弹幕指令，Enter 提交，Esc 关闭")
        self._command_edit.setFont(QFont("Microsoft YaHei", 10))
        self._command_edit.setAutoFillBackground(False)
        self._command_edit.setStyleSheet(
            "background: rgba(30, 30, 40, 200); color: white;"
            " border: 1px solid rgba(255, 255, 255, 0.3); border-radius: 4px;"
        )
        self._command_edit.hide()
        self._command_edit.returnPressed.connect(self._submit_command)
        self._command_edit.installEventFilter(self)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(_ANIM_INTERVAL_MS)
        self._anim_timer.timeout.connect(self._on_anim_tick)

        self._apply_window_geometry(reposition=True)

    def _ensure_assets_loaded(self) -> None:
        """S-003: defer spritesheet decode until first show_pet (cold-start perf)."""
        if self._spritesheet is None and self._load_error is None:
            self.reload_assets()

    def _load_slot_assets(self) -> PetAssetPack:
        if self.slot_id == 0 and self._slot_asset_source == self._settings.asset_source and self._slot_asset_path == self._settings.asset_path:
            return load_pet_assets(self._app.config)
        if self._slot_asset_source == "local" and self._slot_asset_path.strip():
            meta, sheet_path, grid_cols, grid_rows = validate_pet_pack_dir(Path(self._slot_asset_path.strip()))
            from app.pet.pet_assets import PetAssetPack, parse_spritesheet_layout

            return PetAssetPack(
                pet_id=str(meta.get("id", "")),
                display_name=str(meta.get("displayName", "")),
                description=str(meta.get("description", "")),
                root_dir=Path(self._slot_asset_path.strip()),
                spritesheet_path=sheet_path,
                grid_cols=grid_cols,
                grid_rows=grid_rows,
                spritesheet_layout=parse_spritesheet_layout(meta),
            )
        return load_pet_assets(self._app.config)

    def reload_assets(self) -> None:
        try:
            self._pack = self._load_slot_assets()
            self._spritesheet = QPixmap(str(self._pack.spritesheet_path))
            self._load_error = None
        except (ValueError, OSError) as exc:
            self._pack = None
            self._spritesheet = None
            self._load_error = str(exc)

    def apply_config(self) -> None:
        self._settings = PetSettings.from_config(self._app.config)
        if self.slot_id < len(self._settings.barrage.slots):
            slot = self._settings.barrage.slots[self.slot_id]
            self._slot_asset_source = slot.asset_source or self._settings.asset_source
            self._slot_asset_path = slot.asset_path or ""
            self._slot_position_x = slot.position_x
            self._slot_position_y = slot.position_y
        else:
            self._slot_asset_source = self._settings.asset_source
            self._slot_asset_path = self._settings.asset_path
            self._slot_position_x = self._settings.position_x
            self._slot_position_y = self._settings.position_y
        self.reload_assets()
        self._apply_window_geometry(reposition=True)
        if self.isVisible():
            self._sync_click_through()
            self.update()

    def apply_slot_config(self, slot_data: dict[str, object]) -> None:
        self._slot_asset_source = str(slot_data.get("asset_source", self._settings.asset_source) or self._settings.asset_source).strip().lower()
        if self._slot_asset_source not in ("builtin", "local"):
            self._slot_asset_source = "builtin"
        self._slot_asset_path = str(slot_data.get("asset_path", "") or "")
        try:
            self._slot_position_x = int(slot_data.get("position_x")) if slot_data.get("position_x") is not None else None
        except (TypeError, ValueError):
            self._slot_position_x = None
        try:
            self._slot_position_y = int(slot_data.get("position_y")) if slot_data.get("position_y") is not None else None
        except (TypeError, ValueError):
            self._slot_position_y = None
        self.reload_assets()
        self._apply_window_geometry(reposition=True)
        self.update()

    def supports_command_box(self) -> bool:
        return self.slot_id == 0 and self._settings.command_box_enabled

    def set_bubble_text(self, text: str) -> None:
        next_text = str(text or "").strip()
        self._bubble_text = next_text
        self._bubble_target_alpha = _BUBBLE_MAX_ALPHA if next_text else 0.0
        if next_text and self._bubble_alpha <= 0.05:
            self._bubble_alpha = 0.0
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
        self._ensure_assets_loaded()
        self._apply_window_geometry(reposition=True)
        self.show()
        self._sync_click_through()
        self.raise_()
        self._reassert_topmost()
        self.start_render_loop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_click_through()
        self._reassert_topmost()

    def hide_pet(self) -> None:
        self.stop_render_loop()
        self._hide_command_box()
        self.hide()

    def _pet_size(self) -> tuple[int, int]:
        scale = self._settings.scale
        return (int(PET_FRAME_W * scale), int(PET_FRAME_H * scale))

    def _command_box_open(self) -> bool:
        # isHidden() tracks user intent; isVisible() is false while the pet window itself is hidden.
        return not self._command_edit.isHidden()

    def _command_band_height(self) -> int:
        return command_band_height(self._command_box_open())

    def _sprite_y_offset(self) -> int:
        return sprite_y_offset(self._command_box_open())

    def _apply_window_geometry(self, *, reposition: bool = False) -> None:
        w, h = self._pet_size()
        band = self._command_band_height()
        pos_before = (self.x(), self.y())
        self.setFixedSize(w, h + band)
        self._command_edit.setGeometry(0, 0, w, _COMMAND_EDIT_HEIGHT)
        if not reposition:
            self.move(pos_before[0], pos_before[1])
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = self._slot_position_x
        y = self._slot_position_y
        if x is None:
            x = self._settings.position_x
        if y is None:
            y = self._settings.position_y
        if x is None or y is None:
            x = geo.right() - w - 40
            y = geo.bottom() - h - 80
        x = max(geo.left(), min(int(x), geo.right() - w))
        y = max(geo.top(), min(int(y), geo.bottom() - (h + band)))
        self.move(int(x), int(y))

    def _apply_win32_surface(self) -> None:
        """Win32: click-through layered style + disable Win11 DWM rounded corners on small pet HWND."""
        if sys.platform != "win32" or not self.isVisible():
            return
        hwnd = int(self.winId())
        if not hwnd:
            return
        try:
            donotround = ctypes.c_int(_DWMWCP_DONOTROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                _DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(donotround),
                ctypes.sizeof(donotround),
            )
        except OSError:
            pass
        apply_overlay_exstyles(hwnd, click_through=self._settings.click_through)
        self.update()

    def _sync_click_through(self) -> None:
        """Backward-compatible alias; surface attrs must be applied after show()."""
        self._apply_win32_surface()

    def _reassert_topmost(self) -> None:
        if not self._settings.always_on_top or sys.platform != "win32":
            return
        hwnd = int(self.winId())
        if not hwnd:
            return
        reassert_hwnd_topmost(hwnd)
        # Pet must stack above full-screen danmu / floating-panel overlays at the same screen point.
        for layer_key in ("overlay", "floating_panel_overlay"):
            layer = self._app.__dict__.get(layer_key)
            if layer is None or not layer.isVisible():
                continue
            try:
                layer_hwnd = int(layer.winId())
            except Exception:
                layer_hwnd = 0
            if layer_hwnd:
                stack_hwnd_above(hwnd, layer_hwnd)
        ctypes.windll.user32.BringWindowToTop(hwnd)

    def _mapper_animation(self) -> str:
        return resolve_pet_animation_hint(
            self._app,
            one_shot=self._one_shot,
            one_shot_until=self._one_shot_until,
        )

    def _current_animation(self) -> str:
        return resolve_interaction_animation(
            dragging=self._dragging,
            momentum_active=self._momentum_active,
            drag_anim_state=self._drag_anim_state,
            post_drag_waving_until=self._post_drag_waving_until,
            now=time.monotonic(),
            mapper_state=self._mapper_animation(),
        )

    def _set_drag_anim_state(self, state: str) -> None:
        if state == self._drag_anim_state:
            return
        self._drag_anim_state = state
        self._frame_index = 0
        self._frame_clock = 0.0

    def _cancel_momentum(self) -> None:
        self._momentum_active = False
        self._momentum_vx = 0.0
        self._momentum_vy = 0.0
        self._momentum_elapsed_ms = 0.0

    def _start_post_drag_waving(self) -> None:
        self._post_drag_waving_until = time.monotonic() + _WAVING_HOLD_SEC
        self._set_drag_anim_state("waving")

    def _push_pointer_sample(self, x: float, y: float) -> None:
        now = time.monotonic()
        self._pointer_samples.append(PointerSample(x=x, y=y, t=now))
        cutoff = now - _POINTER_SAMPLE_WINDOW_SEC
        self._pointer_samples = [s for s in self._pointer_samples if s.t >= cutoff]

    def _available_geometry(self):
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return None
        return screen.availableGeometry()

    def _move_window_clamped(self, dx: int, dy: int) -> tuple[bool, bool]:
        geo = self._available_geometry()
        if geo is None:
            self.move(self.x() + dx, self.y() + dy)
            return False, False
        x = self.x() + dx
        y = self.y() + dy
        hit_x = hit_y = False
        w, h = self.width(), self.height()
        if x < geo.left():
            x = geo.left()
            hit_x = True
        if y < geo.top():
            y = geo.top()
            hit_y = True
        if x + w > geo.right():
            x = geo.right() - w
            hit_x = True
        if y + h > geo.bottom():
            y = geo.bottom() - h
            hit_y = True
        self.move(x, y)
        return hit_x, hit_y

    def _tick_momentum(self) -> None:
        if not self._momentum_active:
            return
        self._momentum_elapsed_ms += _ANIM_INTERVAL_MS
        dt_sec = _ANIM_INTERVAL_MS / 1000.0
        hit_x, hit_y = self._move_window_clamped(
            int(self._momentum_vx * dt_sec),
            int(self._momentum_vy * dt_sec),
        )
        if hit_x:
            self._momentum_vx = 0.0
        if hit_y:
            self._momentum_vy = 0.0
        run_state = momentum_run_state_for_vx(self._momentum_vx)
        if run_state:
            self._set_drag_anim_state(run_state)
        self._momentum_vx *= _MOMENTUM_FRICTION
        self._momentum_vy *= _MOMENTUM_FRICTION
        speed = math.hypot(self._momentum_vx, self._momentum_vy)
        if self._momentum_elapsed_ms >= _MOMENTUM_MAX_DURATION_MS or speed < _MIN_VEL_PX_PER_SEC:
            self._cancel_momentum()
            self._start_post_drag_waving()
            self._persist_position()

    def _on_anim_tick(self) -> None:
        self._tick_momentum()
        if self._bubble_alpha < self._bubble_target_alpha:
            self._bubble_alpha = min(_BUBBLE_MAX_ALPHA, self._bubble_alpha + _BUBBLE_FADE_STEP)
        elif self._bubble_alpha > self._bubble_target_alpha:
            self._bubble_alpha = max(0.0, self._bubble_alpha - _BUBBLE_FADE_STEP)
        new_state = self._current_animation()
        frame_changed = False
        if new_state != self._animation_state:
            self._animation_state = new_state
            self._frame_index = 0
            self._frame_clock = 0.0
            frame_changed = True
        else:
            self._animation_state = new_state
        self._frame_clock += _ANIM_INTERVAL_MS / 1000.0
        interval = (
            self._pack.state_frame_interval_sec(self._animation_state)
            if self._pack
            else _DEFAULT_FRAME_INTERVAL_SEC
        )
        if self._frame_clock >= interval:
            self._frame_clock = 0.0
            frame_count = self._pack.state_frame_count(self._animation_state) if self._pack else 6
            self._frame_index = (self._frame_index + 1) % max(1, frame_count)
            frame_changed = True
        needs_repaint = (
            frame_changed
            or self._dragging
            or self._momentum_active
            or abs(self._bubble_alpha - self._bubble_target_alpha) > 0.001
            or self._frame_index != self._last_painted_frame_index
            or self._animation_state != self._last_painted_animation_state
        )
        if needs_repaint:
            self._last_painted_frame_index = self._frame_index
            self._last_painted_animation_state = self._animation_state
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self._pet_size()
        y_offset = self._sprite_y_offset()
        if self._load_error:
            painter.setPen(Qt.GlobalColor.red)
            painter.drawText(8, y_offset + 24, "宠物加载失败")
            return
        if self._pack is None or self._spritesheet is None or self._spritesheet.isNull():
            return
        opacity = max(0.2, min(self._settings.opacity, 1.0))
        painter.setOpacity(opacity)
        sx, sy, sw, sh = self._pack.frame_rect(self._animation_state, self._frame_index)
        painter.drawPixmap(0, y_offset, w, h, self._spritesheet, sx, sy, sw, sh)
        self._paint_bubble(painter, w, h, y_offset)

    def _paint_bubble(self, painter: QPainter, pet_w: int, _pet_h: int, y_offset: int) -> None:
        if not self._bubble_text or self._bubble_alpha <= 0.01:
            return
        geo = self._available_geometry()
        if geo is None:
            return
        painter.save()
        font = QFont("Microsoft YaHei", 10)
        painter.setFont(font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WordWrap)
        bubble_w = min(_BUBBLE_MAX_WIDTH, max(160, int(pet_w * 1.35)))
        measure = painter.boundingRect(
            QRectF(0, 0, bubble_w - 24, 180).toRect(),
            int(Qt.TextFlag.TextWordWrap),
            self._bubble_text,
        )
        bubble_h = min(180, max(44, measure.height() + 18))
        show_left = self.x() + pet_w > geo.center().x()
        bubble_x = pet_w - bubble_w if show_left else 0
        bubble_y = max(2, y_offset - bubble_h - 14)

        path = QPainterPath()
        rect = QRectF(bubble_x, bubble_y, bubble_w, bubble_h)
        path.addRoundedRect(rect, 14, 14)
        tail_base_x = bubble_x + (bubble_w * (0.28 if show_left else 0.72))
        path.moveTo(tail_base_x - 10, rect.bottom() - 2)
        path.lineTo(tail_base_x + 10, rect.bottom() - 2)
        path.lineTo((pet_w * 0.5), y_offset + 6)
        path.closeSubpath()

        bg = QColor(30, 30, 38, int(255 * self._bubble_alpha))
        border = QColor(255, 255, 255, int(120 * self._bubble_alpha))
        text_color = QColor(255, 255, 255, int(255 * self._bubble_alpha))
        painter.fillPath(path, bg)
        painter.setPen(QPen(border, 1))
        painter.drawPath(path)
        painter.setPen(text_color)
        painter.drawText(
            QRectF(bubble_x + 12, bubble_y + 9, bubble_w - 24, bubble_h - 16),
            self._bubble_text,
            option,
        )
        painter.restore()

    def mousePressEvent(self, event) -> None:
        if self._settings.click_through:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragging = True
            self._post_drag_waving_until = 0.0
            self._cancel_momentum()
            self._pointer_samples = []
            gx = event.globalPosition().x()
            gy = event.globalPosition().y()
            self._push_pointer_sample(gx, gy)
            self._set_drag_anim_state("jumping")
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._settings.click_through or self._drag_offset is None:
            return
        if event.buttons() & Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            target = global_pos - self._drag_offset
            dx = target.x() - self.x()
            dy = target.y() - self.y()
            prev_sample = self._pointer_samples[-1] if self._pointer_samples else None
            gx = event.globalPosition().x()
            gy = event.globalPosition().y()
            pointer_dx = gx - prev_sample.x if prev_sample else 0.0
            self._move_window_clamped(dx, dy)
            self._push_pointer_sample(gx, gy)
            run_state = drag_run_state_for_dx(pointer_dx)
            if run_state:
                self._set_drag_anim_state(run_state)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            global_pos = event.globalPosition().toPoint()
            offset = self._drag_offset
            target = global_pos - offset
            gap_x = target.x() - self.x()
            gap_y = target.y() - self.y()
            self._move_window_clamped(gap_x, gap_y)
            self._cancel_momentum()
            self._drag_offset = None
            self._dragging = False
            self._start_post_drag_waving()
            self._persist_position()
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._settings.click_through or not self.supports_command_box():
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._show_command_box()
            event.accept()

    def _build_context_menu(self) -> QMenu:
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

        # 与托盘「退出」同路径；分隔线与「关闭桌宠」区分语义（仅关桌宠 vs 退出进程）。
        menu.addSeparator()
        quit_action = QAction("退出应用", self)
        quit_action.triggered.connect(self._app.quit)
        menu.addAction(quit_action)
        return menu

    def contextMenuEvent(self, event) -> None:
        if self._settings.click_through:
            return
        self._build_context_menu().exec(event.globalPos())

    def _open_settings_page(self) -> None:
        opener: Callable[[str], None] | None = getattr(self._app, "_open_web_console", None)
        if opener:
            opener("/#pet")

    def _persist_position(self) -> None:
        pos = self.pos()
        if self.slot_id > 0 or self._settings.barrage.enabled:
            barrage = self._app.__dict__.get("pet_barrage_controller")
            if barrage is not None and hasattr(barrage, "persist_slot_position"):
                barrage.persist_slot_position(self.slot_id, pos.x(), pos.y())
            self._slot_position_x = pos.x()
            self._slot_position_y = pos.y()
            return
        self._app.config.set("pet_position_x", str(pos.x()))
        self._app.config.set("pet_position_y", str(pos.y()))
        self._settings = PetSettings.from_config(self._app.config)

    def _show_command_box(self) -> None:
        self._command_edit.clear()
        self._command_edit.show()
        self._command_edit.setFocus()
        self._apply_window_geometry()
        self.update()

    def _hide_command_box(self) -> None:
        self._command_edit.hide()
        self._apply_window_geometry()
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
