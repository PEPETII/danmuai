"""DanmuAI Web 控制台：FastAPI + uvicorn 独立线程，静态页 web/static。

线程安全（核心约束）：
- HTTP/WebSocket 在 **uvicorn 线程**；DanmuApp / DanmuEngine / Overlay 在 **Qt 主线程**。
- **禁止**在路由处理器里直接调用 danmu_app.start()、改 config 触达 engine、操作 QWidget。
- 须经 **WebConsoleBridge** 的 pyqtSignal（如 save_config_requested、start_requested）：
  Qt 将槽排队到主线程执行；save_config 用 emit 而非 QTimer.singleShot（后者在 uvicorn 线程常不触发）。

鉴权：启动时生成随机 token；写操作 Header `Authorization: Bearer <token>`；WS 用 query ws_token。
默认 127.0.0.1:18765，仅本机访问。

调用：main.DanmuApp.__init__ → attach_web_console()。
"""

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

from app.application.config_service import (
    MASKED_API_KEY,
    WEB_CONFIG_KEYS,
    apply_web_config_patch,
)
from app.bundle_paths import append_frozen_log, frozen_log_path, is_frozen, resource_path
from app.live_overlay_hub import LiveOverlayHub

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
    """主线程 → asyncio 线程安全入队；队列满时丢最旧一条，保证 WS 推送不阻塞 UI。"""

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
    active_model_id: str = ""
    inferred_provider_id: str = ""
    model_display_name: str = ""
    uses_custom_credentials: bool = False
    model_source: str = "unknown"
    provider_model_mismatch: bool = False
    capture_mode: str = "screen"
    capture_window_hwnd: int = 0
    capture_region_mode: str = "full"
    region_x: int = 0
    region_y: int = 0
    region_w: int = 0
    region_h: int = 0
    region_selection_state: str = "idle"


def _mask_api_key(config) -> str:
    return MASKED_API_KEY if config.get_api_key() else ""


def export_config(config) -> dict[str, Any]:
    from app.config_defaults import config_value_with_default
    from app.model_providers import model_likely_supports_mic_audio, resolve_active_model_id
    from app.web_api.custom_models import _mask_model

    data = {key: config_value_with_default(config, key) for key in WEB_CONFIG_KEYS}
    data["api_key"] = _mask_api_key(config)
    data["has_api_key"] = bool(config.get_api_key())
    from app.model_selection import resolve_model_status

    active_model_id = resolve_active_model_id(config)
    model_status = resolve_model_status(config)
    data["default_model_id"] = config.get_default_model_id()
    data["active_model_id"] = active_model_id
    data.update(model_status)
    data["mic_audio_likely_supported"] = model_likely_supports_mic_audio(active_model_id)
    data["custom_models"] = [
        _mask_model(m) for m in config.get_custom_models() if isinstance(m, dict)
    ]
    from app.personae import normal_reply_count_from_config

    data["reply_batch_total"] = normal_reply_count_from_config(config)
    rx, ry, rw, rh = config.get_region()
    data["region_x"] = rx
    data["region_y"] = ry
    data["region_w"] = rw
    data["region_h"] = rh
    from app.web_api.capture_region import capture_region_mode

    data["capture_region_mode"] = capture_region_mode(config)
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
    """主线程执行：委托 ConfigService 统一处理 Web 配置 patch。"""
    apply_web_config_patch(danmu_app, payload)


class WebConsoleBridge(QObject):
    """HTTP/WS 工作线程与 Qt 主线程之间的唯一写入口。

    模式：uvicorn 路由里只 bridge.xxx_requested.emit(...)；槽在主线程调 DanmuApp。
    publish_status / _broadcast_* 从主线程经 call_soon_threadsafe 喂 asyncio 队列推 WS。
    日志环 _log_ring 供 /api/logs 与 /ws/logs 回放；状态 500ms 定时器在 attach 时挂到 danmu_app。
    """

    log_received = pyqtSignal(str, str)
    status_updated = pyqtSignal(object)
    status_refresh_requested = pyqtSignal()

    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    toggle_requested = pyqtSignal()
    save_config_requested = pyqtSignal(object)
    region_select_requested = pyqtSignal()
    region_reset_requested = pyqtSignal()

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
        region_select = getattr(danmu_app, "request_capture_region_selection", None)
        if callable(region_select):
            self.region_select_requested.connect(region_select)
        region_reset = getattr(danmu_app, "reset_capture_region", None)
        if callable(region_reset):
            self.region_reset_requested.connect(region_reset)

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
        # 唯一状态出口：禁止在此或路由内直接读取 danmu_app._xxx 再拼装 dict
        snapshot = self.danmu_app.build_status_snapshot()
        self.status = WebStatusSnapshot(**snapshot)
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
        if not isinstance(payload, dict):
            return
        done_event = payload.pop("__save_done_event", None)
        keys = sorted(payload.keys())
        cap_mode = payload.get("capture_mode", "<missing>")
        cap_hwnd = payload.get("capture_window_hwnd", "<missing>")
        try:
            self.danmu_app.apply_web_config_payload(payload)
        except Exception as exc:
            self.danmu_app.logger.error(
                "配置保存失败: keys=%s, error=%s",
                keys,
                exc,
                exc_info=True,
            )
            self.danmu_app.set_web_error_status(
                f"配置保存失败: {exc}",
                is_error=True,
            )
            self.publish_status()
            return
        finally:
            if done_event is not None:
                done_event.set()
        stored_mode = self.danmu_app.config.get("capture_mode", "screen")
        stored_hwnd = self.danmu_app.config.get("capture_window_hwnd", "0")
        self.danmu_app.logger.info(
            "配置保存成功: keys=%s capture_mode=%s→%s capture_window_hwnd=%s→%s",
            keys, cap_mode, stored_mode, cap_hwnd, stored_hwnd,
        )
        self.danmu_app.set_web_error_status("", is_error=False)
        self.publish_status()


class WebConsoleServer:
    """在独立线程运行 uvicorn；frozen 包用非 daemon 线程避免 Qt 初始化期间被回收。"""

    def __init__(self, bridge: WebConsoleBridge, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.bridge = bridge
        self.host = host
        self.port = port
        self.live_overlay_hub = LiveOverlayHub()
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
        """启动 DanmuWebConsole 线程；就绪以 _on_uvicorn_started 置位（非 lifespan 开头）。"""
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._bind_failed.clear()
        self.startup_ok = False
        # PyInstaller：非 daemon，避免 pywebview/Qt 尚未 enter 事件循环时守护线程被回收
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
        danmu_app = self.bridge.danmu_app
        danmu_app.stop_web_status_timer()
        danmu_app.detach_web_status_timer()
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
            from starlette.routing import WebSocketRoute
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
            server_ref.live_overlay_hub.set_loop(server_ref._loop)
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
                from app.model_selection import validate_web_config_patch

                validate_web_config_patch(bridge.danmu_app.config, data)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            # 跨线程 emit 给 Qt 主线程槽，用 Event 等待写入完成后再返回，
            # 避免前端立即 reload 读到旧配置。
            done = threading.Event()
            data["__save_done_event"] = done
            bridge.save_config_requested.emit(data)
            done.wait(timeout=5.0)
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

        from app.web_api.live_overlay import register_live_overlay_routes
        from app.web_api.routes import register_web_routes

        register_web_routes(app, bridge, _check_token)
        register_live_overlay_routes(
            app,
            server_ref.live_overlay_hub,
            self.base_url,
            _check_token,
        )

        async def _ws_status_endpoint(websocket: WebSocket):
            ws_token = websocket.query_params.get("ws_token")
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

        async def _ws_logs_endpoint(websocket: WebSocket):
            ws_token = websocket.query_params.get("ws_token")
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

        # FastAPI @app.websocket 在本项目路由规模下未进入 handler（升级直接 403）；
        # 改用 Starlette WebSocketRoute 注册，token 仍从 query ws_token 读取。
        app.router.routes.insert(0, WebSocketRoute("/ws/status", endpoint=_ws_status_endpoint))
        app.router.routes.insert(0, WebSocketRoute("/ws/logs", endpoint=_ws_logs_endpoint))

        @app.get("/")
        def index():
            index_path = STATIC_DIR / "index.html"
            if not index_path.exists():
                raise HTTPException(status_code=404, detail="index.html missing")
            return FileResponse(index_path)

        if STATIC_DIR.is_dir():
            app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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
            f"frozen={is_frozen()} static={STATIC_DIR} ws={ws_impl}"
        )

        class _DanmuWebUvicornServer(uvicorn.Server):
            """在 super().startup 绑定端口成功后再 _on_uvicorn_started，避免端口未监听就打开浏览器。"""

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
    """构造 bridge + 启动 WebConsoleServer；主线程挂 500ms 状态刷新定时器。"""
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
        danmu_app.set_web_error_status(msg, is_error=True)

    def _tick_status():
        if getattr(danmu_app, "web_bridge", None):
            danmu_app.web_bridge.publish_status()

    web_status_timer = QTimer(danmu_app)
    web_status_timer.setInterval(500)
    web_status_timer.timeout.connect(_tick_status)
    danmu_app.attach_web_status_timer(web_status_timer)
    web_status_timer.start()

    def _cache_screens():
        bridge.cached_screens = enumerate_screens()

    QTimer.singleShot(0, _cache_screens)

    return server


def open_web_console_browser(server: WebConsoleServer, path: str = "/") -> None:
    import webbrowser

    webbrowser.open(f"{server.base_url}{path}")
