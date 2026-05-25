"""Local web console for DanmuAI (warm Qwen prototype UI)."""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from app.bundle_paths import append_frozen_log, frozen_log_path, is_frozen, resource_path
from app.scene_fingerprint import DEFAULT_SCENE_PROBE_SIZE, clamp_scene_probe_size

if TYPE_CHECKING:
    from main import DanmuApp

STATIC_DIR = resource_path("web", "static")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18765


def _prepare_stdio_for_uvicorn() -> None:
    """PyInstaller windowed exe (console=False) has stderr=None; uvicorn logging breaks."""
    if sys.stderr is not None and sys.stdout is not None:
        return
    try:
        sink = open(os.devnull, "w", encoding="utf-8")
    except OSError:
        import io

        sink = io.StringIO()
    if sys.stderr is None:
        sys.stderr = sink
    if sys.stdout is None:
        sys.stdout = sys.stderr

_WS_BROADCAST_LOG_INTERVAL_SEC = 5.0


def _ws_token_valid(query_token: str | None, expected: str) -> bool:
    return bool(query_token and query_token.strip() == expected)


def _enqueue_ws(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    item: Any,
) -> None:
    """Thread-safe enqueue; drop oldest entry when the queue is full."""

    def _put() -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass

    loop.call_soon_threadsafe(_put)


# Keys exposed to the web settings form (subset of Qt settings panel).
WEB_CONFIG_KEYS = (
    "api_endpoint",
    "api_mode",
    "model",
    "temperature",
    "max_tokens",
    "screenshot_interval",
    "danmu_speed",
    "danmu_lines",
    "danmu_max_chars",
    "dedup_threshold",
    "screen_index",
    "layout_mode",
    "opacity",
    "font_size",
    "freq_mode",
    "capture_mode",
    "danmu_pool_enabled",
    "min_on_screen",
    "freshness",
    "drop_stale",
    "empty_accel",
    "eviction_mode",
    "image_max_width",
    "image_quality",
    "scene_probe_size",
    "hotkey",
    "memory_mode",
    "memory_window",
    "memory_clear_policy",
    "mic_mode_enabled",
    "mic_window_sec",
    "reply_scene_count",
    "reply_filler_count",
    "danmu_display_mode",
    "normal_recognition_interval_sec",
    "normal_reply_count",
)


def _clamp_choice(
    items: dict[str, str],
    key: str,
    allowed: tuple[str, ...],
    default: str,
) -> None:
    if key not in items:
        return
    value = str(items[key]).strip().lower()
    items[key] = value if value in allowed else default


def _clamp_int_key(
    items: dict[str, str],
    key: str,
    default: int,
    min_value: int,
    max_value: int,
) -> None:
    if key not in items:
        return
    try:
        v = int(items[key])
        items[key] = str(max(min_value, min(v, max_value)))
    except (TypeError, ValueError):
        items[key] = str(default)


def enumerate_screens() -> list[dict[str, Any]]:
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return [{"index": 0, "label": "显示器 1", "width": 0, "height": 0}]
    screens = app.screens() or []
    items = []
    for index, screen in enumerate(screens):
        geo = screen.geometry()
        dpr = screen.devicePixelRatio()
        phys_w = int(geo.width() * dpr)
        phys_h = int(geo.height() * dpr)
        items.append(
            {
                "index": index,
                "label": f"显示器 {index + 1} — {phys_w}×{phys_h}",
                "width": phys_w,
                "height": phys_h,
            }
        )
    return items or [{"index": 0, "label": "显示器 1", "width": 0, "height": 0}]


@dataclass
class WebStatusSnapshot:
    running: bool = False
    danmu_count: int = 0
    queue_count: int = 0
    display_count: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    runtime_sec: float = 0.0
    error_message: str = ""
    is_error: bool = False
    live_analyzing: bool = False
    live_local_fallback: bool = False
    live_delay_sec: float = 0.0
    live_stale_drops: int = 0
    live_message: str = ""
    persona_names: list[str] = field(default_factory=list)
    screen_index: int = 0
    has_api_key: bool = False
    dedup_profile: dict[str, Any] | None = None
    lifetime_danmu_count: int = 0
    lifetime_runtime_sec: float = 0.0
    lifetime_total_tokens: int = 0
    lifetime_input_tokens: int = 0
    lifetime_output_tokens: int = 0
    session_runs: list[dict] = field(default_factory=list)


def _mask_api_key(config) -> str:
    return "********" if config.get_api_key() else ""


def export_config(config) -> dict[str, Any]:
    from app.config_defaults import config_value_with_default
    from app.model_providers import model_likely_supports_mic_audio, resolve_active_model_id
    from app.web_api.custom_models import _mask_model

    data = {key: config_value_with_default(config, key) for key in WEB_CONFIG_KEYS}
    data["api_key"] = _mask_api_key(config)
    data["has_api_key"] = bool(config.get_api_key())
    active_model_id = resolve_active_model_id(config)
    data["default_model_id"] = config.get_default_model_id()
    data["active_model_id"] = active_model_id
    data["mic_audio_likely_supported"] = model_likely_supports_mic_audio(active_model_id)
    data["custom_models"] = [
        _mask_model(m) for m in config.get_custom_models() if isinstance(m, dict)
    ]
    from app.personae import (
        is_normal_display_mode,
        normal_reply_count_from_config,
        reply_counts_from_config,
    )

    if is_normal_display_mode(config):
        data["reply_batch_total"] = normal_reply_count_from_config(config)
    else:
        scene, filler = reply_counts_from_config(config)
        data["reply_batch_total"] = scene + filler
    return data


def extract_config_payload(body: Any) -> dict[str, Any]:
    """Accept `{data: {...}}` wrapper or a flat config patch dict."""
    if not isinstance(body, dict):
        raise ValueError("无效的配置数据")
    nested = body.get("data")
    if isinstance(nested, dict):
        return nested
    if body:
        return body
    raise ValueError("配置数据为空")


def apply_config_patch(danmu_app: "DanmuApp", payload: dict[str, Any]) -> None:
    config = danmu_app.config
    items: dict[str, str] = {}
    for key in WEB_CONFIG_KEYS:
        if key in payload and payload[key] is not None:
            items[key] = str(payload[key])

    if items:
        # Region crop removed from Web UI; always full-screen on the selected display.
        items["region_x"] = "0"
        items["region_y"] = "0"
        items["region_w"] = "0"
        items["region_h"] = "0"
        if "scene_probe_size" in items:
            try:
                items["scene_probe_size"] = str(
                    clamp_scene_probe_size(int(items["scene_probe_size"]))
                )
            except (TypeError, ValueError):
                items["scene_probe_size"] = str(DEFAULT_SCENE_PROBE_SIZE)
        if "mic_window_sec" in items:
            from app.mic_buffer import clamp_mic_window_sec

            try:
                items["mic_window_sec"] = str(clamp_mic_window_sec(int(items["mic_window_sec"])))
            except (TypeError, ValueError):
                items["mic_window_sec"] = "5"
        if "danmu_max_chars" in items:
            from app.danmu_engine import DANMU_MAX_CHARS_MAX, DANMU_MAX_CHARS_MIN

            try:
                v = int(items["danmu_max_chars"])
                items["danmu_max_chars"] = str(max(DANMU_MAX_CHARS_MIN, min(v, DANMU_MAX_CHARS_MAX)))
            except (TypeError, ValueError):
                items["danmu_max_chars"] = "15"
        if "danmu_lines" in items:
            from app.danmu_engine import DEFAULT_DANMU_LINES, clamp_danmu_lines

            try:
                items["danmu_lines"] = str(clamp_danmu_lines(int(items["danmu_lines"])))
            except (TypeError, ValueError):
                items["danmu_lines"] = str(DEFAULT_DANMU_LINES)
        if "layout_mode" in items:
            from app.danmu_engine import normalize_layout_mode

            items["layout_mode"] = normalize_layout_mode(items["layout_mode"])
        if "reply_scene_count" in items or "reply_filler_count" in items:
            from app.personae import (
                DEFAULT_REPLY_FILLER_COUNT,
                DEFAULT_REPLY_SCENE_COUNT,
                REPLY_COUNT_MAX,
                REPLY_COUNT_MIN,
            )

            def _clamp_reply_key(key: str, default: int) -> None:
                if key not in items:
                    return
                try:
                    v = int(items[key])
                    items[key] = str(max(REPLY_COUNT_MIN, min(v, REPLY_COUNT_MAX)))
                except (TypeError, ValueError):
                    items[key] = str(default)

            _clamp_reply_key("reply_scene_count", DEFAULT_REPLY_SCENE_COUNT)
            _clamp_reply_key("reply_filler_count", DEFAULT_REPLY_FILLER_COUNT)
        if (
            "danmu_display_mode" in items
            or "normal_recognition_interval_sec" in items
            or "normal_reply_count" in items
        ):
            from app.personae import DEFAULT_NORMAL_REPLY_COUNT

            _clamp_choice(items, "danmu_display_mode", ("realtime", "normal"), "normal")
            _clamp_int_key(items, "normal_recognition_interval_sec", 5, 1, 60)
            _clamp_int_key(
                items,
                "normal_reply_count",
                DEFAULT_NORMAL_REPLY_COUNT,
                1,
                20,
            )
        if (
            "memory_mode" in items
            or "memory_clear_policy" in items
            or "memory_window" in items
        ):
            _clamp_choice(
                items,
                "memory_mode",
                ("off", "dedup_only", "scene_card", "strong"),
                "off",
            )
            _clamp_choice(items, "memory_clear_policy", ("strict", "medium", "loose"), "medium")
            _clamp_int_key(items, "memory_window", 10, 1, 20)
        config.set_batch(items)
        model_id = (items.get("model") or "").strip()
        if model_id:
            config.set_default_model_id(model_id)

    api_key = payload.get("api_key", "")
    if api_key and api_key != "********":
        config.set_api_key(str(api_key).strip())

    if "default_model_id" in payload:
        model_id = str(payload.get("default_model_id", "")).strip()
        if model_id:
            config.set_default_model_id(model_id)
            config.set("model", model_id)

    if "custom_models" in payload and isinstance(payload["custom_models"], list):
        from app.web_api.custom_models import MASKED_KEY

        existing = list(config.get_custom_models())
        merged: list[dict] = []
        for i, inc in enumerate(payload["custom_models"]):
            if not isinstance(inc, dict):
                continue
            row = dict(inc)
            key = (row.get("apiKey") or row.get("api_key") or "").strip()
            prev = existing[i] if i < len(existing) else None
            if key == MASKED_KEY and prev:
                row["apiKey"] = prev.get("apiKey", "")
            elif key == MASKED_KEY:
                row["apiKey"] = ""
            merged.append(row)
        config.set_custom_models(merged)

    active = payload.get("active_personae")
    if isinstance(active, list) and active:
        danmu_app.personae.set_active([str(name) for name in active])

    danmu_app.config_changed.emit()


class WebConsoleBridge(QObject):
    """Thread-safe bridge: HTTP worker threads → Qt main thread."""

    log_received = pyqtSignal(str, str)
    status_updated = pyqtSignal(object)
    status_refresh_requested = pyqtSignal()

    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    toggle_requested = pyqtSignal()
    save_config_requested = pyqtSignal(object)

    def __init__(self, danmu_app: "DanmuApp"):
        super().__init__()
        self.danmu_app = danmu_app
        self.status = WebStatusSnapshot()
        self._log_ring: deque[tuple[str, str, float]] = deque(maxlen=500)
        self._ws_log_queues: list[asyncio.Queue] = []
        self._ws_status_queues: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_broadcast_log_at: float = 0.0
        self._last_status_payload: dict[str, Any] | None = None
        self.cached_screens: list[dict[str, Any]] = []

        self.status_refresh_requested.connect(self.publish_status)
        self.start_requested.connect(danmu_app.start)
        self.stop_requested.connect(danmu_app.stop)
        self.toggle_requested.connect(danmu_app.toggle)
        self.save_config_requested.connect(self._on_save_config)

        danmu_app.logger.log_emitted.connect(self._on_log)
        danmu_app.state_changed.connect(self._on_state_changed)

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._ws_log_debug("asyncio event loop attached for WebSocket broadcast")

    def _ws_log_debug(self, message: str) -> None:
        self.danmu_app.logger.debug(f"[WebConsole] {message}")

    def list_recent_logs(self, since_ts: float = 0.0) -> list[dict[str, Any]]:
        cutoff = float(since_ts or 0.0)
        return [
            {"level": level, "message": message, "ts": ts}
            for level, message, ts in self._log_ring
            if ts > cutoff
        ]

    def register_log_consumer(self, queue: asyncio.Queue) -> None:
        self._ws_log_queues.append(queue)
        for level, message, ts in self._log_ring:
            item = {"level": level, "message": message, "ts": ts}
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                break
        self._ws_log_debug(
            f"register_log_consumer consumers={len(self._ws_log_queues)}"
        )

    def unregister_log_consumer(self, queue: asyncio.Queue) -> None:
        if queue in self._ws_log_queues:
            self._ws_log_queues.remove(queue)
        self._ws_log_debug(
            f"unregister_log_consumer consumers={len(self._ws_log_queues)}"
        )

    def register_status_consumer(self, queue: asyncio.Queue) -> None:
        self._ws_status_queues.append(queue)
        self._ws_log_debug(
            f"register_status_consumer consumers={len(self._ws_status_queues)}"
        )

    def unregister_status_consumer(self, queue: asyncio.Queue) -> None:
        if queue in self._ws_status_queues:
            self._ws_status_queues.remove(queue)
        self._ws_log_debug(
            f"unregister_status_consumer consumers={len(self._ws_status_queues)}"
        )

    def refresh_status(self) -> WebStatusSnapshot:
        app = self.danmu_app
        running = app.engine.running
        queue_count = app.reply_buffer.size() if hasattr(app.reply_buffer, "size") else 0
        display_count = app._visible_display_count() if hasattr(app, "_visible_display_count") else 0
        input_tokens = int(getattr(app, "_total_input_tokens", 0) or 0)
        output_tokens = int(getattr(app, "_total_output_tokens", 0) or 0)
        total_tokens = input_tokens + output_tokens
        runtime = time.monotonic() - app._start_time if app._start_time > 0 else 0.0

        snapshot = app._build_live_status_snapshot() if running else None
        error_message = getattr(app, "_web_error_message", "") or ""
        is_error = bool(getattr(app, "_web_error_is_error", False))

        from app.danmu_engine import dedup_profile_enabled
        from app.personae import persona_display_name

        dedup_profile = None
        if dedup_profile_enabled():
            dedup_profile = app.engine.get_dedup_profile_snapshot()

        lifetime = {}
        lifetime_stats = getattr(app, "lifetime_stats", None)
        if lifetime_stats is not None:
            lifetime = lifetime_stats.snapshot(session_runtime_sec=runtime)

        session_runs: list[dict] = []
        session_log = getattr(app, "session_run_log", None)
        if session_log is not None:
            session_runs = session_log.list_dicts_newest_first()

        self.status = WebStatusSnapshot(
            running=running,
            danmu_count=app.danmu_count,
            queue_count=queue_count,
            display_count=display_count,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            runtime_sec=runtime,
            error_message=error_message or "",
            is_error=is_error,
            live_analyzing=bool(snapshot.analyzing) if snapshot else False,
            live_local_fallback=bool(snapshot.local_fallback) if snapshot else False,
            live_delay_sec=float(snapshot.delay_sec) if snapshot else 0.0,
            live_stale_drops=int(snapshot.stale_drops) if snapshot else 0,
            live_message=snapshot.primary_message() if snapshot else "",
            persona_names=[persona_display_name(n) for n in app.personae.get_active()],
            screen_index=app.config.get_int("screen_index", 0),
            has_api_key=bool(app.config.get_api_key()),
            dedup_profile=dedup_profile,
            lifetime_danmu_count=int(lifetime.get("lifetime_danmu_count", 0)),
            lifetime_runtime_sec=float(lifetime.get("lifetime_runtime_sec", 0.0)),
            lifetime_total_tokens=int(lifetime.get("lifetime_total_tokens", 0)),
            lifetime_input_tokens=int(lifetime.get("lifetime_input_tokens", 0)),
            lifetime_output_tokens=int(lifetime.get("lifetime_output_tokens", 0)),
            session_runs=session_runs,
        )
        return self.status

    def publish_status(self) -> None:
        status = self.refresh_status()
        payload = asdict(status)
        self._last_status_payload = payload
        self.status_updated.emit(status)
        self._broadcast_status(payload)

    def _maybe_log_broadcast(self, kind: str, count: int) -> None:
        if count <= 0:
            return
        now = time.monotonic()
        if now - self._last_broadcast_log_at < _WS_BROADCAST_LOG_INTERVAL_SEC:
            return
        self._last_broadcast_log_at = now
        self._ws_log_debug(f"_broadcast_{kind} consumers={count}")

    def _broadcast_status(self, payload: dict) -> None:
        loop = self._loop
        if not loop:
            return
        queues = list(self._ws_status_queues)
        self._maybe_log_broadcast("status", len(queues))
        for queue in queues:
            _enqueue_ws(loop, queue, payload)

    def _broadcast_log(self, level: str, message: str, ts: float) -> None:
        loop = self._loop
        if not loop:
            return
        item = {"level": level, "message": message, "ts": ts}
        queues = list(self._ws_log_queues)
        self._maybe_log_broadcast("log", len(queues))
        for queue in queues:
            _enqueue_ws(loop, queue, item)

    @pyqtSlot(str, str)
    def _on_log(self, level: str, message: str) -> None:
        ts = time.time()
        self._log_ring.append((level, message, ts))
        self.log_received.emit(level, message)
        self._broadcast_log(level, message, ts)

    @pyqtSlot(bool)
    def _on_state_changed(self, _running: bool) -> None:
        self.publish_status()

    @pyqtSlot(object)
    def _on_save_config(self, payload: object) -> None:
        if isinstance(payload, dict):
            apply_config_patch(self.danmu_app, payload)
        self.publish_status()


class WebConsoleServer:
    def __init__(self, bridge: WebConsoleBridge, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.bridge = bridge
        self.host = host
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self._thread: threading.Thread | None = None
        self._server = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._bind_failed = threading.Event()
        self.startup_ok = False

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._bind_failed.clear()
        self.startup_ok = False
        # Frozen exe: non-daemon thread so uvicorn is not torn down during Qt/pywebview init.
        self._thread = threading.Thread(
            target=self._run,
            name="DanmuWebConsole",
            daemon=not is_frozen(),
        )
        self._thread.start()

    def wait_ready(self, timeout: float = 12.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self._ready.wait(timeout=min(0.05, remaining)):
                return True
            if self._bind_failed.is_set():
                return False
            thread = self._thread
            if thread and not thread.is_alive() and not self._ready.is_set():
                return False

    def _on_uvicorn_started(self) -> None:
        """Called only after uvicorn has bound the listen socket (post-lifespan startup)."""
        self.bridge.danmu_app.logger.info(
            f"Web 控制台 HTTP/WS 已监听 {self.base_url}"
        )
        self._ready.set()
        self.startup_ok = True

    def stop(self) -> None:
        if self._loop and self._server:
            server = self._server

            def _request_shutdown() -> None:
                server.should_exit = True

            self._loop.call_soon_threadsafe(_request_shutdown)

    def _run(self) -> None:
        bridge = self.bridge
        append_frozen_log("DanmuWebConsole thread starting")
        try:
            self._run_uvicorn_locked()
        except Exception as exc:
            import traceback

            self._bind_failed.set()
            detail = traceback.format_exc()
            bridge.danmu_app.logger.error(f"Web 控制台线程异常退出: {exc!r}")
            append_frozen_log(f"Web console thread crashed (outer):\n{detail}")

    def _run_uvicorn_locked(self) -> None:
        bridge = self.bridge
        try:
            import uvicorn
            from fastapi import Body, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
            from fastapi.responses import FileResponse
            from fastapi.staticfiles import StaticFiles
        except ImportError as exc:
            msg = (
                f"Web console dependencies missing: {exc}. "
                "Install with: pip install fastapi \"uvicorn[standard]>=0.32.0\""
            )
            bridge.danmu_app.logger.error(msg)
            append_frozen_log(msg)
            return

        ws_impl = "websockets"
        try:
            import websockets  # noqa: F401 — required for uvicorn WebSocket upgrade
        except ImportError:
            ws_impl = "auto"
            bridge.danmu_app.logger.warning(
                "未安装 websockets，/ws/status、/ws/logs 可能无法连接；"
                "HTTP API 仍可用。请运行: pip install \"uvicorn[standard]>=0.32.0\""
            )
        token = self.token
        server_ref = self

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # uvicorn runs lifespan startup before socket bind; readiness is set in
            # _DanmuWebUvicornServer.startup() only after bind succeeds.
            server_ref._loop = asyncio.get_running_loop()
            bridge.set_event_loop(server_ref._loop)
            try:
                yield
            finally:
                server_ref._ready.clear()
                server_ref.startup_ok = False

        app = FastAPI(
            title="DanmuAI Web Console",
            docs_url=None,
            redoc_url=None,
            lifespan=lifespan,
        )

        def _check_token(authorization: str | None = Header(default=None)) -> None:
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="需要登录令牌")
            if authorization.removeprefix("Bearer ").strip() != token:
                raise HTTPException(status_code=403, detail="令牌无效")

        @app.get("/api/session")
        def read_console_session(host: str | None = Header(default=None)):
            # Header avoids Request in a nested scope (postponed annotations → query.request 422).
            host = (host or "").strip()
            base_url = f"http://{host}" if host else self.base_url
            return {"token": token, "base_url": base_url}

        @app.get("/api/status")
        def status():
            return asdict(bridge.refresh_status())

        @app.get("/api/logs/recent")
        def logs_recent(since_ts: float = 0.0):
            return {"items": bridge.list_recent_logs(since_ts)}

        @app.get("/api/config")
        def get_config():
            return export_config(bridge.danmu_app.config)

        @app.get("/api/personae")
        def list_personae():
            from app.personae import BUILTIN_PERSONAE, persona_display_name

            names = bridge.danmu_app.personae.list()
            active = set(bridge.danmu_app.personae.get_active())
            return {
                "items": [
                    {
                        "id": name,
                        "label": persona_display_name(name),
                        "active": name in active,
                        "builtin": name in BUILTIN_PERSONAE,
                    }
                    for name in names
                ],
                "active": bridge.danmu_app.personae.get_active(),
            }

        @app.get("/api/screens")
        def screens():
            if bridge.cached_screens:
                return bridge.cached_screens
            return enumerate_screens()

        @app.get("/api/meta")
        def meta():
            cfg = bridge.danmu_app.config
            return {
                "ui_mode": "web",
                "hotkey": cfg.get("hotkey", "Ctrl+Shift+B"),
                "language": cfg.get("language", ""),
                "screens": bridge.cached_screens or enumerate_screens(),
            }

        @app.get("/api/providers")
        def providers():
            from app.model_providers import PROVIDERS

            return [
                {
                    "id": p.id,
                    "label": p.label_zh,
                    "default_endpoint": p.default_endpoint,
                    "mode": p.mode,
                    "hint": p.model_id_hint_zh,
                }
                for p in PROVIDERS
            ]

        @app.get("/api/model-catalog")
        def model_catalog():
            from app.model_catalog import list_platform_catalogs

            return {"platforms": list_platform_catalogs()}

        @app.api_route("/api/config", methods=["PUT", "POST"])
        def save_config(
            body: dict[str, Any] = Body(...),
            authorization: str | None = Header(default=None),
        ):
            _check_token(authorization)
            try:
                data = extract_config_payload(body)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            # 与 /api/start 相同：跨线程直接 emit，由 Qt 排队到主线程槽。
            # 勿用 QTimer.singleShot（在 uvicorn 线程创建定时器常无法触发，导致“已保存”但未写入 DB）。
            bridge.save_config_requested.emit(data)
            return {"ok": True}

        @app.post("/api/start")
        def api_start(authorization: str | None = Header(default=None)):
            _check_token(authorization)
            bridge.start_requested.emit()
            return {"ok": True}

        @app.post("/api/stop")
        def api_stop(authorization: str | None = Header(default=None)):
            _check_token(authorization)
            bridge.stop_requested.emit()
            return {"ok": True}

        @app.post("/api/toggle")
        def api_toggle(authorization: str | None = Header(default=None)):
            _check_token(authorization)
            bridge.toggle_requested.emit()
            return {"ok": True}

        from app.web_api.routes import register_web_routes

        register_web_routes(app, bridge, _check_token)

        @app.get("/")
        def index():
            index_path = STATIC_DIR / "index.html"
            if not index_path.exists():
                raise HTTPException(status_code=404, detail="index.html missing")
            return FileResponse(index_path)

        if STATIC_DIR.is_dir():
            app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.websocket("/ws/logs")
        async def ws_logs(websocket: WebSocket, ws_token: str | None = None):
            if not _ws_token_valid(ws_token, token):
                await websocket.close(code=1008, reason="需要登录令牌")
                return
            client = websocket.client
            peer = f"{client.host}:{client.port}" if client else "unknown"
            await websocket.accept()
            bridge._ws_log_debug(f"WebSocket /ws/logs accepted peer={peer}")
            queue: asyncio.Queue = asyncio.Queue(maxsize=200)
            bridge.register_log_consumer(queue)
            try:
                while True:
                    item = await queue.get()
                    await websocket.send_json(item)
            except WebSocketDisconnect:
                bridge._ws_log_debug(f"WebSocket /ws/logs disconnected peer={peer}")
            except Exception as exc:
                bridge._ws_log_debug(
                    f"WebSocket /ws/logs closed peer={peer} error={exc!r}"
                )
            finally:
                bridge.unregister_log_consumer(queue)

        @app.websocket("/ws/status")
        async def ws_status(websocket: WebSocket, ws_token: str | None = None):
            if not _ws_token_valid(ws_token, token):
                await websocket.close(code=1008, reason="需要登录令牌")
                return
            client = websocket.client
            peer = f"{client.host}:{client.port}" if client else "unknown"
            await websocket.accept()
            bridge._ws_log_debug(f"WebSocket /ws/status accepted peer={peer}")
            queue: asyncio.Queue = asyncio.Queue(maxsize=64)
            bridge.register_status_consumer(queue)
            cached = bridge._last_status_payload
            if cached:
                await websocket.send_json(cached)
            bridge.status_refresh_requested.emit()
            try:
                while True:
                    item = await queue.get()
                    await websocket.send_json(item)
            except WebSocketDisconnect:
                bridge._ws_log_debug(f"WebSocket /ws/status disconnected peer={peer}")
            except Exception as exc:
                bridge._ws_log_debug(
                    f"WebSocket /ws/status closed peer={peer} error={exc!r}"
                )
            finally:
                bridge.unregister_status_consumer(queue)

        config_kwargs: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "log_level": "warning",
            "access_log": False,
            "ws": ws_impl,
        }
        if is_frozen():
            # PyInstaller: avoid httptools/uvloop auto-probes that can hang or fail silently.
            config_kwargs["loop"] = "asyncio"
            config_kwargs["http"] = "h11"
        if is_frozen() or sys.stderr is None:
            _prepare_stdio_for_uvicorn()
            # Default uvicorn log formatters call stream.isatty() on stderr.
            config_kwargs["log_config"] = None
        config = uvicorn.Config(app, **config_kwargs)
        append_frozen_log(
            f"uvicorn Config ready host={self.host} port={self.port} "
            f"frozen={is_frozen()} static={STATIC_DIR}"
        )

        class _DanmuWebUvicornServer(uvicorn.Server):
            def __init__(self, cfg, owner: WebConsoleServer):
                super().__init__(cfg)
                self._owner = owner

            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                if self.started:
                    self._owner._on_uvicorn_started()

        self._server = _DanmuWebUvicornServer(config, self)

        if is_frozen() and sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        try:
            append_frozen_log("uvicorn serve() starting")
            asyncio.run(self._server.serve())
            append_frozen_log("uvicorn serve() exited")
        except SystemExit:
            if not self._ready.is_set():
                self._bind_failed.set()
                msg = (
                    f"Web 控制台端口 {self.host}:{self.port} 绑定失败。"
                    "请关闭占用该端口的进程后重启 DanmuAI。"
                )
                bridge.danmu_app.logger.error(msg)
                append_frozen_log(msg)
        except OSError as exc:
            self._bind_failed.set()
            msg = (
                f"Web 控制台端口 {self.host}:{self.port} 绑定失败: {exc}。"
                "请关闭占用该端口的进程后重启 DanmuAI。"
            )
            bridge.danmu_app.logger.error(msg)
            append_frozen_log(msg)
        except Exception as exc:
            import traceback

            self._bind_failed.set()
            detail = traceback.format_exc()
            bridge.danmu_app.logger.error(f"Web 控制台线程异常退出: {exc!r}")
            append_frozen_log(f"Web console thread crashed (serve):\n{detail}")


def attach_web_console(danmu_app: "DanmuApp", port: int = DEFAULT_PORT) -> WebConsoleServer:
    bridge = WebConsoleBridge(danmu_app)
    danmu_app.web_bridge = bridge
    server = WebConsoleServer(bridge, port=port)
    danmu_app.web_server = server
    server.start()

    ready_timeout = 30.0 if is_frozen() else 12.0
    if not server.wait_ready(timeout=ready_timeout):
        thread = server._thread
        thread_alive = bool(thread and thread.is_alive())
        append_frozen_log(
            "wait_ready timeout: "
            f"thread_alive={thread_alive} "
            f"bind_failed={server._bind_failed.is_set()} "
            f"startup_ok={server.startup_ok}"
        )
        msg = (
            f"Web 控制台未在 {server.base_url} 就绪（WebSocket 会报 1006）。"
            "请检查终端是否有端口占用或依赖缺失，并执行: "
            'pip install -r requirements.txt'
        )
        if is_frozen():
            msg += f" 诊断日志: {frozen_log_path()}"
        danmu_app.logger.error(msg)
        append_frozen_log(msg)
        if hasattr(danmu_app, "_set_error_status_safe"):
            danmu_app._set_error_status_safe(msg, is_error=True)

    def _tick_status():
        if getattr(danmu_app, "web_bridge", None):
            danmu_app.web_bridge.publish_status()

    danmu_app._web_status_timer = QTimer(danmu_app)
    danmu_app._web_status_timer.setInterval(500)
    danmu_app._web_status_timer.timeout.connect(_tick_status)
    danmu_app._web_status_timer.start()

    def _cache_screens():
        bridge.cached_screens = enumerate_screens()

    QTimer.singleShot(0, _cache_screens)

    return server


def open_web_console_browser(server: WebConsoleServer, path: str = "/") -> None:
    import webbrowser

    webbrowser.open(f"{server.base_url}{path}")
