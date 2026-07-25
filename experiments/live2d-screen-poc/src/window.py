"""Native frameless transparent Live2D window (PyQt6 + live2d-py v3)."""
from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QPoint, Qt, QTimer, QTimerEvent
from PyQt6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication, QMessageBox

from .win32_util import apply_exstyles, reassert_topmost

logger = logging.getLogger("live2d_poc")

# Prefer OpenGL RHI backend for QOpenGLWidget transparency on Windows.
import os as _os

_os.environ.setdefault("QSG_RHI_BACKEND", "opengl")


def _import_live2d():
    try:
        import live2d.v3 as live2d  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Failed to import live2d.v3 (live2d-py). "
            "Install POC deps: pip install -r requirements-poc.txt"
        ) from exc
    return live2d


class Live2DPocWindow(QOpenGLWidget):
    def __init__(
        self,
        *,
        model_path: Path,
        width: int = 480,
        height: int = 720,
        opacity: float = 1.0,
        scale: float = 1.0,
        fps: int = 60,
        click_through: bool = False,
        topmost: bool = True,
        auto_play_motion: bool = True,
        auto_play_expression: bool = True,
        cycle_expressions: float = 0.0,
        motion_group: str | None = None,
        motion_index: int = 0,
        expression_id: str | None = None,
        demo_seconds: float = 0.0,
    ) -> None:
        super().__init__()
        self._live2d = _import_live2d()
        self.model_path = Path(model_path)
        self.model: Any = None
        self._opacity = max(0.05, min(1.0, float(opacity)))
        self._scale = max(0.2, min(3.0, float(scale)))
        self._fps = max(15, min(120, int(fps)))
        self._click_through = bool(click_through)
        self._topmost = bool(topmost)
        self._auto_play_motion = bool(auto_play_motion)
        self._auto_play_expression = bool(auto_play_expression)
        self._cycle_expressions = max(0.0, float(cycle_expressions))
        self._motion_group = motion_group
        self._motion_index = int(motion_index)
        self._expression_id = expression_id
        self._demo_seconds = max(0.0, float(demo_seconds))
        self._drag_offset: QPoint | None = None
        self._gl_ready = False
        self._motion_triggered = False
        self._expression_triggered = False
        self._expression_cycle_index = 0
        self._available_motions: dict[str, int] = {}
        self._available_expressions: list[str] = []
        self._param_ids: list[str] = []
        self._frame = 0
        self._breath_phase = 0.0

        self.setWindowTitle("Live2D Screen POC")
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.resize(int(width), int(height))
        self.setWindowOpacity(self._opacity)

        self._bind_shortcuts()

        if self._demo_seconds > 0:
            QTimer.singleShot(int(self._demo_seconds * 1000), self.close)

        # Periodic topmost reassert without activating.
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(3000)
        self._topmost_timer.timeout.connect(self._reassert_topmost)
        if self._topmost:
            self._topmost_timer.start()

    def _bind_shortcuts(self) -> None:
        # Global-ish window shortcuts (work when window has focus).
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        QShortcut(QKeySequence("Esc"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self.toggle_click_through)
        QShortcut(QKeySequence("Ctrl+="), self, activated=lambda: self.adjust_scale(1.1))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self.adjust_scale(1 / 1.1))
        QShortcut(QKeySequence("Ctrl+]"), self, activated=lambda: self.adjust_opacity(0.05))
        QShortcut(QKeySequence("Ctrl+["), self, activated=lambda: self.adjust_opacity(-0.05))
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.trigger_motion)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self.trigger_expression)
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self._reset_view)

        # Recover from click-through: global hotkey via QShortcut only works with focus.
        # Use a polling timer + keyboard modifier edge when click-through is on.
        self._recover_timer = QTimer(self)
        self._recover_timer.setInterval(200)
        self._recover_timer.timeout.connect(self._poll_recover_hotkey)
        self._recover_timer.start()
        self._last_ctrl_shift_f8 = False

    def _poll_recover_hotkey(self) -> None:
        """Detect Ctrl+Shift+F8 even when click-through steals mouse (not keyboard)."""
        mods = QGuiApplication.queryKeyboardModifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        # F8 via GetAsyncKeyState
        f8_down = False
        if sys.platform == "win32":
            try:
                import ctypes

                f8_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x77) & 0x8000)
            except Exception:  # noqa: BLE001
                f8_down = False
        combo = ctrl and shift and f8_down
        if combo and not self._last_ctrl_shift_f8:
            logger.info("hotkey Ctrl+Shift+F8: toggle click-through")
            self.toggle_click_through()
        self._last_ctrl_shift_f8 = combo

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_win32_styles)

    def _apply_win32_styles(self) -> None:
        hwnd = int(self.winId())
        apply_exstyles(hwnd, click_through=self._click_through)
        if self._topmost:
            reassert_topmost(hwnd, topmost=True)

    def _reassert_topmost(self) -> None:
        if self._topmost and self.isVisible():
            reassert_topmost(int(self.winId()), topmost=True)

    def initializeGL(self) -> None:  # noqa: N802
        live2d = self._live2d
        live2d.glInit()
        self.model = live2d.LAppModel()
        path_str = str(self.model_path)
        logger.info("LoadModelJson: %s", path_str)
        try:
            self.model.LoadModelJson(path_str)
        except Exception as exc:  # noqa: BLE001
            logger.exception("model load failed")
            QMessageBox.critical(
                None,
                "Live2D POC",
                f"Failed to load model:\n{path_str}\n\n{exc}",
            )
            QTimer.singleShot(0, self.close)
            return

        try:
            self.model.Resize(self.width(), self.height())
            self.model.SetScale(self._scale)
        except Exception as exc:  # noqa: BLE001
            logger.warning("post-load resize/scale failed: %s", exc)

        self._discover_runtime_assets()
        self._gl_ready = True
        interval = max(1, int(1000 / self._fps))
        self.startTimer(interval)
        logger.info(
            "GL ready; motions=%s expressions=%s params=%d",
            self._available_motions,
            self._available_expressions[:20],
            len(self._param_ids),
        )
        # Auto-trigger after a short delay so first frames render.
        if self._auto_play_motion:
            QTimer.singleShot(500, self.trigger_motion)
        if self._auto_play_expression:
            QTimer.singleShot(900, self.trigger_expression)

        # Auto-cycle expressions every N seconds.
        if self._cycle_expressions > 0:
            self._cycle_timer = QTimer(self)
            self._cycle_timer.setInterval(int(self._cycle_expressions * 1000))
            self._cycle_timer.timeout.connect(self._cycle_next_expression)
            self._cycle_timer.start()
            logger.info(
                "expression cycle enabled: every %.1f s", self._cycle_expressions
            )

    def _discover_runtime_assets(self) -> None:
        if not self.model:
            return
        try:
            groups = self.model.GetMotionGroups()
            if isinstance(groups, dict):
                for name, count in groups.items():
                    self._available_motions[str(name)] = int(count)
            elif groups:
                for name in groups:
                    try:
                        motions = self.model.GetMotions(str(name))
                        n = len(motions) if motions is not None else 0
                    except Exception:  # noqa: BLE001
                        n = 1
                    self._available_motions[str(name)] = n
        except Exception as exc:  # noqa: BLE001
            logger.warning("GetMotionGroups failed: %s", exc)

        try:
            expr = self.model.GetExpressionIds()
            if expr:
                self._available_expressions = [str(x) for x in expr]
        except Exception as exc:  # noqa: BLE001
            logger.warning("GetExpressionIds failed: %s", exc)

        # Fallback: scan loose files when model3 declares nothing
        if not self._available_motions:
            self._scan_loose_motions()
        if not self._available_expressions:
            self._scan_loose_expressions()

        try:
            params = self.model.GetParamIds()
            if params:
                self._param_ids = [str(p) for p in params]
        except Exception as exc:  # noqa: BLE001
            logger.warning("GetParamIds failed: %s", exc)

    def _scan_loose_motions(self) -> None:
        model_dir = self.model_path.parent
        files = sorted(model_dir.rglob("*.motion3.json"))
        if not files:
            return
        # Use parent directory name as group label.
        self._available_motions[""] = len(files)
        logger.info(
            "loose motion scan: %d files (model3 declared none)",
            len(files),
        )
        for f in files[:8]:
            logger.info("  loose motion: %s", f.relative_to(model_dir))

    def _scan_loose_expressions(self) -> None:
        model_dir = self.model_path.parent
        files = sorted(model_dir.rglob("*.exp3.json"))
        if not files:
            return
        seen: list[str] = []
        self._loose_exp_data: dict[str, dict] = {}
        import json  # noqa: PLC0415
        for f in files:
            name = f.stem
            if name in seen:
                continue
            seen.append(name)
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                self._loose_exp_data[name] = data
            except Exception as exc:  # noqa: BLE001
                logger.warning("failed to parse loose exp %s: %s", f, exc)
        self._available_expressions = seen
        logger.info(
            "loose expression scan: %d files (model3 declared none)",
            len(seen),
        )
        for f in files[:10]:
            logger.info("  loose exp: %s", f.relative_to(model_dir))

    def resizeGL(self, w: int, h: int) -> None:  # noqa: N802
        if self.model:
            try:
                self.model.Resize(w, h)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Resize failed: %s", exc)

    def paintGL(self) -> None:  # noqa: N802
        live2d = self._live2d
        # Fully transparent clear (true alpha).
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        if not self.model or not self._gl_ready:
            return
        try:
            self._apply_soft_idle()
            self.model.Update()
            self.model.Draw()
        except Exception as exc:  # noqa: BLE001
            logger.exception("paint failed: %s", exc)

    def _apply_soft_idle(self) -> None:
        """When model has no motions, gently animate a few standard params."""
        if not self.model or self._available_motions:
            return
        self._breath_phase += 1.0 / max(self._fps, 1)
        breath = 0.5 + 0.5 * math.sin(self._breath_phase * 1.6)
        for pid, value in (
            ("ParamBreath", breath),
            ("ParamAngleX", 8.0 * math.sin(self._breath_phase * 0.7)),
            ("ParamAngleY", 4.0 * math.sin(self._breath_phase * 0.5)),
            ("ParamEyeLOpen", 1.0),
            ("ParamEyeROpen", 1.0),
        ):
            if pid in self._param_ids:
                try:
                    self.model.SetParameterValue(pid, float(value))
                except Exception:  # noqa: BLE001
                    pass

    def timerEvent(self, a0: QTimerEvent | None) -> None:  # noqa: N802
        if not self.isVisible():
            return
        self._frame += 1
        self.update()

    # --- interaction ---

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        if self.model and self._gl_ready:
            try:
                local = event.position()
                self.model.Drag(float(local.x()), float(local.y()))
            except Exception:  # noqa: BLE001
                pass

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.08 if delta > 0 else 1 / 1.08
        self.adjust_scale(factor)
        event.accept()

    def adjust_scale(self, factor: float) -> None:
        self._scale = max(0.2, min(3.0, self._scale * factor))
        if self.model:
            try:
                self.model.SetScale(self._scale)
            except Exception as exc:  # noqa: BLE001
                logger.warning("SetScale failed: %s", exc)
        logger.info("scale=%.3f", self._scale)

    def adjust_opacity(self, delta: float) -> None:
        self._opacity = max(0.05, min(1.0, self._opacity + delta))
        self.setWindowOpacity(self._opacity)
        logger.info("opacity=%.3f", self._opacity)

    def _reset_view(self) -> None:
        self._scale = 1.0
        self._opacity = 1.0
        self.setWindowOpacity(1.0)
        if self.model:
            try:
                self.model.SetScale(1.0)
                self.model.SetOffset(0.0, 0.0)
            except Exception:  # noqa: BLE001
                pass
        logger.info("view reset")

    def toggle_click_through(self) -> None:
        self._click_through = not self._click_through
        apply_exstyles(int(self.winId()), click_through=self._click_through)
        logger.info(
            "click_through=%s (recover: Ctrl+Shift+F8)",
            self._click_through,
        )

    def trigger_motion(self) -> None:
        if not self.model or not self._gl_ready:
            logger.warning("trigger_motion: model not ready")
            return
        live2d = self._live2d
        # None means "pick from model"; empty-string group is valid (some model3 use "").
        group = self._motion_group
        index = self._motion_index
        if group is None:
            if self._available_motions:
                group = next(iter(self._available_motions.keys()))
                index = 0
            else:
                # Fallback: StartRandomMotion may still no-op without groups.
                logger.warning(
                    "no motion groups in model; attempting StartRandomMotion / soft idle"
                )
                try:
                    self.model.StartRandomMotion(
                        priority=live2d.MotionPriority.FORCE
                    )
                    self._motion_triggered = True
                    logger.info("StartRandomMotion requested (no declared groups)")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("StartRandomMotion failed: %s", exc)
                    # Soft idle counts as visible motion substitute for models without motions.
                    self._motion_triggered = True
                    logger.info(
                        "soft-idle param animation active as motion substitute"
                    )
                return
        try:
            self.model.StartMotion(
                group,
                index,
                live2d.MotionPriority.FORCE,
            )
            self._motion_triggered = True
            logger.info("StartMotion group=%r index=%s", group, index)
        except Exception as exc:  # noqa: BLE001
            logger.exception("StartMotion failed: %s", exc)
            try:
                self.model.StartRandomMotion(priority=live2d.MotionPriority.FORCE)
                self._motion_triggered = True
                logger.info("StartRandomMotion fallback after StartMotion failure")
            except Exception as exc2:  # noqa: BLE001
                logger.warning("StartRandomMotion fallback failed: %s", exc2)

    def trigger_expression(self) -> None:
        if not self.model or not self._gl_ready:
            logger.warning("trigger_expression: model not ready")
            return
        expr_id = self._expression_id
        if not expr_id:
            if self._available_expressions:
                expr_id = self._available_expressions[0]
            else:
                # Fallback: try random or param-based "expression"
                try:
                    self.model.SetRandomExpression()
                    self._expression_triggered = True
                    logger.info("SetRandomExpression requested (no declared expressions)")
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("SetRandomExpression failed: %s", exc)
                # Param-based mouth open as visible expression substitute
                for pid in ("ParamMouthOpenY", "ParamMouthForm"):
                    if pid in self._param_ids:
                        try:
                            self.model.SetParameterValue(pid, 1.0)
                            self._expression_triggered = True
                            logger.info(
                                "expression substitute via param %s=1.0", pid
                            )
                            return
                        except Exception:  # noqa: BLE001
                            pass
                logger.warning("no expressions available on this model")
                return
        try:
            self.model.SetExpression(expr_id)
            self._expression_triggered = True
            logger.info("SetExpression id=%s", expr_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("SetExpression failed: %s", exc)

    def _cycle_next_expression(self) -> None:
        if not self._available_expressions:
            return
        idx = self._expression_cycle_index % len(self._available_expressions)
        self._expression_cycle_index = idx + 1
        expr_id = self._available_expressions[idx]

        # Always apply param overrides from the file directly.
        self._apply_loose_expression(idx)

        # Also tweak eye/mouth so changes are never entirely invisible.
        self._apply_visible_param_tweak(idx)

    def _apply_loose_expression(self, seed: int) -> None:
        """Parse loose .exp3.json and apply its parameter values directly."""
        if not self.model or not self._param_ids or not hasattr(self, "_loose_exp_data"):
            return
        keys = list(self._loose_exp_data.keys())
        if not keys:
            return
        name = keys[seed % len(keys)]
        data = self._loose_exp_data.get(name)
        if not data:
            return
        params = data.get("Parameters") or []
        if not params:
            return
        count = 0
        for entry in params:
            pid = entry.get("Id")
            val = entry.get("Value")
            if pid and val is not None and pid in self._param_ids:
                try:
                    self.model.SetParameterValue(pid, float(val))
                    count += 1
                except Exception:  # noqa: BLE001
                    pass
        if count:
            self._expression_triggered = True
            logger.info(
                "loose exp [%d/%d] id=%s applied %d params",
                seed + 1,
                len(keys),
                name,
                count,
            )

    def _apply_visible_param_tweak(self, seed: int) -> None:
        """Force eye/mouth params so changes are never entirely invisible."""
        if not self.model or not self._param_ids:
            return
        pairs = {
            "ParamMouthOpenY": 0.5,
            "ParamMouthForm": 0.8,
            "ParamEyeLOpen": 0.6 + 0.4 * (seed % 3 == 0),
            "ParamEyeROpen": 0.6 + 0.4 * (seed % 3 == 1),
            "ParamBrowLY": -0.2 * (seed % 5),
            "ParamBrowRY": -0.2 * (seed % 5),
        }
        for pid, val in pairs.items():
            if pid in self._param_ids:
                try:
                    self.model.SetParameterValue(pid, val)
                except Exception:  # noqa: BLE001
                    pass

    def closeEvent(self, event) -> None:  # noqa: N802
        logger.info(
            "closing; motion_triggered=%s expression_triggered=%s frames=%d",
            self._motion_triggered,
            self._expression_triggered,
            self._frame,
        )
        try:
            if hasattr(self, '_cycle_timer') and self._cycle_timer:
                self._cycle_timer.stop()
            self._topmost_timer.stop()
            self._recover_timer.stop()
            if self.model:
                try:
                    self.model.DestroyRenderer()
                except Exception:  # noqa: BLE001
                    pass
                self.model = None
        finally:
            super().closeEvent(event)
            app = QApplication.instance()
            if app is not None:
                app.quit()


def run_app(
    *,
    model_path: Path,
    width: int = 480,
    height: int = 720,
    opacity: float = 1.0,
    scale: float = 1.0,
    fps: int = 60,
    click_through: bool = False,
    topmost: bool = True,
    auto_play_motion: bool = True,
    auto_play_expression: bool = True,
    cycle_expressions: float = 0.0,
    motion_group: str | None = None,
    motion_index: int = 0,
    expression_id: str | None = None,
    demo_seconds: float = 0.0,
) -> int:
    live2d = _import_live2d()
    live2d.init()
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(True)
        win = Live2DPocWindow(
            model_path=model_path,
            width=width,
            height=height,
            opacity=opacity,
            scale=scale,
            fps=fps,
            click_through=click_through,
            topmost=topmost,
            auto_play_motion=auto_play_motion,
            auto_play_expression=auto_play_expression,
            cycle_expressions=cycle_expressions,
            motion_group=motion_group,
            motion_index=motion_index,
            expression_id=expression_id,
            demo_seconds=demo_seconds,
        )
        # Show without forcing activation when possible.
        win.show()
        win.raise_()
        # Do not call activateWindow() — avoid stealing focus by default.
        code = app.exec()
        return int(code)
    finally:
        try:
            live2d.dispose()
        except Exception as exc:  # noqa: BLE001
            logger.warning("live2d.dispose failed: %s", exc)
