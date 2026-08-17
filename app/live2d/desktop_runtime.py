"""Real desktop Live2D window backed by the isolated screen POC runtime."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QMouseEvent, QSurfaceFormat
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication

if sys.platform == "win32":
    import ctypes

    _DWMWA_WINDOW_CORNER_PREFERENCE = 33
    _DWMWA_BORDER_COLOR = 34
    _DWMWCP_DONOTROUND = 1
    _DWMCOLOR_NONE = 0xFFFFFFFE


def _load_sdk() -> Any:
    try:
        import live2d.v3 as live2d
    except ImportError as exc:  # pragma: no cover - depends on installation
        raise RuntimeError("Live2D 桌面运行时缺少 live2d-py 依赖") from exc
    return live2d


def _safe_relative(value: object) -> str:
    normalized = str(value or "").replace("\\", "/").strip()
    parts = normalized.split("/")
    if not normalized or normalized.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        return ""
    return "/".join(parts)


def _model_entries(model_path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    try:
        document = json.loads(model_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [], []
    references = document.get("FileReferences", {}) if isinstance(document, dict) else {}
    if not isinstance(references, dict):
        return [], []

    motions: list[dict[str, object]] = []
    raw_motions = references.get("Motions")
    if isinstance(raw_motions, dict):
        motion_groups = raw_motions.items()
    elif isinstance(raw_motions, list):
        motion_groups = ((item.get("Group") or item.get("group") or "", [item]) for item in raw_motions if isinstance(item, dict))
    else:
        motion_groups = ()
    for group, values in motion_groups:
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            file_name = item.get("File") if isinstance(item, dict) else item
            relative = _safe_relative(file_name)
            if relative:
                motions.append({"group": str(group), "index": index, "file": relative})

    expressions: list[dict[str, object]] = []
    raw_expressions = references.get("Expressions")
    if isinstance(raw_expressions, list):
        for index, item in enumerate(raw_expressions):
            if not isinstance(item, dict):
                continue
            relative = _safe_relative(item.get("File") or item.get("file"))
            expression_id = str(item.get("Name") or item.get("name") or Path(relative).stem).strip()
            if relative and expression_id:
                expressions.append({"id": expression_id, "index": index, "file": relative})
    return motions, expressions


class Live2DDesktopWindow(QOpenGLWidget):
    """Transparent, topmost QOpenGLWidget that owns the native model object."""

    def __init__(self, model_path: Path, *, width: int = 480, height: int = 720) -> None:
        super().__init__()
        self.model_path = model_path
        self.model: Any | None = None
        self.sdk: Any | None = None
        self.load_error: Exception | None = None
        self._gl_initialized = False
        self._closing = False
        self._drag_origin = None
        self._window_origin = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(240, 320)
        self.resize(width, height)
        surface_format = QSurfaceFormat()
        surface_format.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
        surface_format.setAlphaBufferSize(8)
        surface_format.setDepthBufferSize(24)
        surface_format.setStencilBufferSize(8)
        self.setFormat(surface_format)
        self.render_timer = QTimer(self)
        self.render_timer.setInterval(16)
        self.render_timer.timeout.connect(self.update)

    def showEvent(self, event) -> None:  # noqa: ANN001 - Qt virtual method
        super().showEvent(event)
        self._apply_windows_surface()

    def _apply_windows_surface(self) -> None:
        """Remove Win11 DWM corner/border chrome after the native HWND exists."""

        if sys.platform != "win32" or not self.isVisible():
            return
        try:
            hwnd = int(self.winId())
            if not hwnd:
                return
            donotround = ctypes.c_int(_DWMWCP_DONOTROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                _DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(donotround),
                ctypes.sizeof(donotround),
            )
            no_border = ctypes.c_uint32(_DWMCOLOR_NONE)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                _DWMWA_BORDER_COLOR,
                ctypes.byref(no_border),
                ctypes.sizeof(no_border),
            )
        except (AttributeError, OSError, TypeError, ValueError):
            # Older Windows/DWM versions may not expose these attributes.
            pass

    def initializeGL(self) -> None:
        try:
            self.sdk = _load_sdk()
            self.sdk.glInit()
            self._gl_initialized = True
            self.model = self.sdk.LAppModel()
            self.model.LoadModelJson(str(self.model_path))
            self.model.Resize(self.width(), self.height())
            self.model.SetAutoBreathEnable(True)
            self.model.SetAutoBlinkEnable(True)
            self.render_timer.start()
        except Exception as exc:  # pragma: no cover - native SDK/GPU dependent
            self.load_error = exc
            QTimer.singleShot(0, self.close)

    def paintGL(self) -> None:
        if self.model is None or self.sdk is None or self.load_error is not None:
            return
        self.sdk.clearBuffer(0.0, 0.0, 0.0, 0.0)
        self.model.Update()
        self.model.Draw()

    def resizeGL(self, width: int, height: int) -> None:
        if self.model is not None:
            self.model.Resize(width, height)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.position().toPoint()
            self._window_origin = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and self._window_origin is not None:
            self.move(self._window_origin + event.position().toPoint() - self._drag_origin)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            self._window_origin = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:  # noqa: ANN001 - Qt virtual method
        self.cleanup_native_resources()
        super().closeEvent(event)

    def cleanup_native_resources(self) -> None:
        if self._closing and self.model is None:
            return
        self._closing = True
        self.render_timer.stop()
        if self.model is not None:
            self.makeCurrent()
            try:
                self.model.DestroyRenderer()
            finally:
                if self.sdk is not None and self._gl_initialized:
                    self.sdk.glRelease()
                    self._gl_initialized = False
                self.doneCurrent()
                self.model = None
        elif self.sdk is not None and self._gl_initialized:
            self.sdk.glRelease()
            self._gl_initialized = False

    def runtime_capabilities(self) -> dict[str, object]:
        if self.model is None:
            return {}
        parameters: list[dict[str, object]] = []
        for index in range(self.model.GetParameterCount()):
            parameter = self.model.GetParameter(index)
            parameters.append(
                {
                    "parameter_id": str(parameter.id),
                    "minimum": float(parameter.min),
                    "maximum": float(parameter.max),
                    "default": float(parameter.default),
                    "current": float(parameter.value),
                }
            )
        motions, expressions = _model_entries(self.model_path)
        return {
            "parameter_ids": [item["parameter_id"] for item in parameters],
            "parameter_specs": parameters,
            "parameter_count": len(parameters),
            "motion_groups": [str(value) for value in self.model.GetMotionGroups()],
            "expression_ids": [str(value) for value in self.model.GetExpressionIds()],
            "motion_entries": motions,
            "expression_entries": expressions,
            "parameter_source": "runtime",
        }

    def set_parameter(self, parameter_id: str, value: float) -> dict[str, object]:
        if self.model is None:
            raise RuntimeError("模型尚未加载")
        parameter_id = str(parameter_id or "").strip()
        if not parameter_id:
            raise ValueError("parameter_id_required")
        specs = {str(item["parameter_id"]): item for item in self.runtime_capabilities()["parameter_specs"]}
        spec = specs.get(parameter_id)
        if spec is None:
            raise ValueError("parameter_not_found")
        requested = float(value)
        bounded = min(float(spec["maximum"]), max(float(spec["minimum"]), requested))
        self.model.SetParameterValue(parameter_id, bounded, 1.0)
        return {"parameter_id": parameter_id, "value": bounded, "clamped": bounded != requested}

    def start_motion(self, file_name: str) -> dict[str, object]:
        if self.model is None:
            raise RuntimeError("模型尚未加载")
        motions, _ = _model_entries(self.model_path)
        entry = next((item for item in motions if item["file"] == _safe_relative(file_name)), None)
        if entry is None:
            raise ValueError("motion_not_found")
        started = self.model.StartMotion(str(entry["group"]), int(entry["index"]), 3)
        if started is False:
            raise RuntimeError("motion_start_failed")
        return {"group": entry["group"], "index": entry["index"], "file": entry["file"]}

    def set_expression(self, file_name: str) -> dict[str, object]:
        if self.model is None:
            raise RuntimeError("模型尚未加载")
        _, expressions = _model_entries(self.model_path)
        entry = next((item for item in expressions if item["file"] == _safe_relative(file_name)), None)
        if entry is None:
            raise ValueError("expression_not_found")
        changed = self.model.SetExpression(str(entry["id"]))
        if changed is False:
            raise RuntimeError("expression_set_failed")
        return {"id": entry["id"], "file": entry["file"]}

    def trigger_action(self, action: str) -> dict[str, object]:
        """Apply a short, model-aware parameter action and restore defaults."""

        aliases: dict[str, tuple[tuple[str, float], ...]] = {
            "点头": (("angle_y", 0.75),),
            "摇头": (("angle_x", 0.75),),
            "歪头": (("angle_z", 0.65),),
            "左右看": (("eye_ball_x", 0.8),),
            "自动眨眼": (("eye_open", 0.0),),
            "开心": (("mouth_form", 1.0),),
            "惊讶": (("mouth_open", 1.0), ("eye_open", 1.0)),
            "疑惑": (("brow_form", -0.7),),
            "思考": (("angle_z", 0.35),),
            "说话口型": (("mouth_open", 0.8),),
        }
        effects = aliases.get(str(action or "").strip())
        if not effects:
            raise ValueError("action_not_found")
        specs = {
            str(item["parameter_id"]): item
            for item in self.runtime_capabilities().get("parameter_specs", [])
        }
        aliases_by_name: dict[str, tuple[str, ...]] = {
            "mouth_open": ("ParamMouthOpenY", "MouthOpenY", "MouthOpen"),
            "mouth_form": ("ParamMouthForm", "MouthForm"),
            "angle_x": ("ParamAngleX", "AngleX"),
            "angle_y": ("ParamAngleY", "AngleY"),
            "angle_z": ("ParamAngleZ", "AngleZ"),
            "eye_open": ("ParamEyeLOpen", "ParamEyeROpen", "EyeOpen"),
            "eye_ball_x": ("ParamEyeBallX", "EyeBallX"),
            "brow_form": ("ParamBrowLY", "ParamBrowRY", "BrowForm"),
        }
        applied: list[dict[str, object]] = []
        for logical_name, target in effects:
            parameter_id = next(
                (candidate for candidate in aliases_by_name[logical_name] if candidate in specs),
                None,
            )
            if parameter_id is None:
                continue
            result = self.set_parameter(parameter_id, target)
            applied.append(result)
            default = float(specs[parameter_id]["default"])
            QTimer.singleShot(650, lambda pid=parameter_id, value=default: self._restore_parameter(pid, value))
        if not applied:
            raise ValueError("action_parameters_not_found")
        return {"action": str(action), "parameters": applied}

    def _restore_parameter(self, parameter_id: str, value: float) -> None:
        if self.model is not None:
            self.set_parameter(parameter_id, value)


class Live2DDesktopRuntime:
    """Main-thread owner for one desktop model window."""

    def __init__(self, *, window_factory: Callable[[Path], Live2DDesktopWindow] | None = None) -> None:
        self._window_factory = window_factory or (lambda path: Live2DDesktopWindow(path))
        self._window: Live2DDesktopWindow | None = None
        self._model_path: Path | None = None
        self._sdk: Any | None = None

    @property
    def running(self) -> bool:
        return self._window is not None and self._window.model is not None

    @property
    def visible(self) -> bool:
        return self._window is not None and self._window.isVisible()

    def start(self, model_path: str | Path) -> dict[str, object]:
        path = Path(model_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError("model_not_found")
        if self.running:
            return self.snapshot()
        self.stop()
        self._sdk = _load_sdk()
        self._sdk.init()
        window = self._window_factory(path)
        self._window = window
        self._model_path = path
        window.show()
        window.raise_()
        app = QApplication.instance()
        if app is not None:
            for _ in range(3):
                app.processEvents()
                if window.model is not None or window.load_error is not None:
                    break
        if window.load_error is not None or window.model is None:
            error = window.load_error or RuntimeError("桌面窗口未完成模型加载")
            self.stop()
            raise RuntimeError(str(error))
        return self.snapshot()

    def stop(self) -> dict[str, object]:
        window, self._window = self._window, None
        self._model_path = None
        if window is not None:
            window.close()
        sdk, self._sdk = self._sdk, None
        if sdk is not None:
            sdk.dispose()
        return {"runtime_status": "stopped", "desktop_visible": False}

    def snapshot(self) -> dict[str, object]:
        if self._window is None or not self.running:
            return {"runtime_status": "stopped", "desktop_visible": False}
        return {
            "runtime_status": "running",
            "desktop_visible": self.visible,
            "capabilities": self._window.runtime_capabilities(),
        }

    def set_parameter(self, parameter_id: str, value: float) -> dict[str, object]:
        if self._window is None or not self.running:
            raise RuntimeError("model_not_running")
        return self._window.set_parameter(parameter_id, value)

    def trigger_action(self, action: str) -> dict[str, object]:
        if self._window is None or not self.running:
            raise RuntimeError("model_not_running")
        return self._window.trigger_action(action)

    def start_motion(self, file_name: str) -> dict[str, object]:
        if self._window is None or not self.running:
            raise RuntimeError("model_not_running")
        return self._window.start_motion(file_name)

    def set_expression(self, file_name: str) -> dict[str, object]:
        if self._window is None or not self.running:
            raise RuntimeError("model_not_running")
        return self._window.set_expression(file_name)


__all__ = ["Live2DDesktopRuntime", "Live2DDesktopWindow"]
