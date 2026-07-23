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
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal, pyqtSlot

from app.application.config_service import WEB_CONFIG_KEYS
from app.bundle_paths import append_frozen_log, frozen_log_path, is_frozen, resource_path
from app.live_overlay_hub import LiveOverlayHub
from app.startup_trace import log_startup, web_console_ready_timeout
from app.translations import tr
from app.web_console_runtime import run_uvicorn_locked
from app.web_console_support import SAVE_DONE_EVENT_KEY as _SAVE_DONE_EVENT_KEY
from app.web_console_support import SAVE_RESULT_KEY as _SAVE_RESULT_KEY
from app.web_console_support import (
    WebStatusSnapshot,
    apply_config_patch,
    enumerate_screens,
    export_config,
    extract_config_payload,
    handle_save_config_request,
    save_config_via_bridge,
    schedule_screen_cache,
    status_payloads_semantically_equal,
)
from app.web_console_support import (
    write_config_save_result as _write_config_save_result,
)
from app.web_console_ws import (
    _WS_MAX_LOG_CONSUMERS,
    _WS_MAX_STATUS_CONSUMERS,
    _enqueue_ws,
    _ws_token_valid,
    should_log_broadcast,
)

WebConsoleStartupPhase = Literal["ready", "slow", "failed"]

__all__ = [
    "INVOKE_ON_MAIN_TIMEOUT_SEC",
    "MainThreadInvokeTimeout",
    "WEB_CONSOLE_SHUTDOWN_TIMEOUT_SEC",
    "WEB_CONSOLE_THREAD_JOIN_GRACE_SEC",
    "WEB_CONFIG_KEYS",
    "WebConsoleBridge",
    "WebConsoleServer",
    "WebStatusSnapshot",
    "apply_config_patch",
    "attach_web_console",
    "classify_web_console_startup",
    "clear_startup_attach_error_if_needed",
    "enumerate_screens",
    "export_config",
    "extract_config_payload",
    "open_web_console_browser",
    "try_recover_web_console_for_user_action",
    "save_config_via_bridge",
]

if TYPE_CHECKING:
    from main import DanmuApp

STATIC_DIR = resource_path("web", "static")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18765
INVOKE_ON_MAIN_TIMEOUT_SEC = 10.0
WEB_CONSOLE_SHUTDOWN_TIMEOUT_SEC = 3.0
WEB_CONSOLE_THREAD_JOIN_GRACE_SEC = 0.2
WEB_STATUS_POLL_INTERVAL_MS = 1000


class MainThreadInvokeTimeout(TimeoutError):
    """invoke_on_main 等待 Qt 主线程完成时超时。"""

    def __init__(self, timeout_sec: float) -> None:
        self.timeout_sec = float(timeout_sec)
        super().__init__(f"主线程操作超时（{self.timeout_sec:.1f}s）")


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


class WebConsoleBridge(QObject):
    """HTTP/WS 工作线程与 Qt 主线程之间的唯一写入口。

    模式：uvicorn 路由里只 bridge.xxx_requested.emit(...)；槽在主线程调 DanmuApp。
    需同步返回的写操作（人格/弹幕库/麦克风测试等）用 invoke_on_main（QueuedConnection + Event.wait）。
    勿在 uvicorn 线程对 invoke_on_main 使用 QTimer.singleShot（槽常不触发）。
    publish_status / _broadcast_* 从主线程经 call_soon_threadsafe 喂 asyncio 队列推 WS。
    日志环 _log_ring 供 /api/logs 与 /ws/logs 回放；状态 500ms 定时器在 attach 时挂到 danmu_app。
    """

    log_received = pyqtSignal(str, str)
    status_updated = pyqtSignal(object)
    status_refresh_requested = pyqtSignal()
    sync_invoke_requested = pyqtSignal(object)

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
        self._pending_log_items: list[dict[str, Any]] = []
        self._log_flush_scheduled: bool = False
        # W-INVOKE-OBSERV-001：invoke_on_main 超时累计计数（供 /api/diagnostics 读取）
        self._invoke_timeout_count: int = 0
        # pywebview 浮动面板 WS 桥（方案 A：WebConsoleBridge 薄委托 PanelBridge）
        from app.floating_panel_web.panel_bridge import PanelBridge

        self._panel_bridge = PanelBridge()

        self.status_refresh_requested.connect(self.publish_status)
        self.sync_invoke_requested.connect(
            self._on_sync_invoke,
            Qt.ConnectionType.QueuedConnection,
        )
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

        try:
            danmu_app.logger.log_emitted.disconnect(self._on_log)
        except (TypeError, RuntimeError):
            pass
        danmu_app.logger.log_emitted.connect(
            self._on_log,
            Qt.ConnectionType.UniqueConnection,
        )
        danmu_app.state_changed.connect(self._on_state_changed)

    def invoke_on_main(
        self,
        fn,
        /,
        *args,
        timeout_sec: float | None = None,
        **kwargs,
    ):
        """在 bridge 所在线程（Qt 主线程）同步执行 fn；从 uvicorn 线程调用时阻塞直至完成或超时。

        线程安全机制：sync_invoke_requested 经 QueuedConnection 排队到主线程；
        HTTP 线程用 threading.Event.wait 等待完成，超时抛出 MainThreadInvokeTimeout。
        超时后已排队但未执行的 runner 会检查 aborted 标记并跳过 fn；fn 已启动则无法中断。
        """
        if QThread.currentThread() is self.thread():
            return fn(*args, **kwargs)

        timeout = (
            INVOKE_ON_MAIN_TIMEOUT_SEC
            if timeout_sec is None
            else float(timeout_sec)
        )
        done = threading.Event()
        aborted = threading.Event()
        result_holder: dict[str, object] = {}
        error_holder: list[BaseException] = []

        def runner() -> None:
            if aborted.is_set():
                return
            try:
                result_holder["result"] = fn(*args, **kwargs)
            except BaseException as exc:
                error_holder.append(exc)
            finally:
                done.set()

        self.sync_invoke_requested.emit(runner)
        if not done.wait(timeout=timeout):
            aborted.set()
            # W-INVOKE-OBSERV-001：先计数再告警，便于 /api/diagnostics 读取累计超时次数
            self._invoke_timeout_count += 1
            self.danmu_app.logger.error(
                "invoke_on_main timeout: fn=%r timeout_sec=%.1f",
                fn,
                timeout,
            )
            raise MainThreadInvokeTimeout(timeout)
        if error_holder:
            raise error_holder[0]
        if "result" in result_holder:
            return result_holder["result"]
        return None

    def invoke_timeout_count(self) -> int:
        """返回 invoke_on_main 累计超时次数（供 /api/diagnostics 读取，W-INVOKE-OBSERV-001）。"""
        return self._invoke_timeout_count

    @pyqtSlot(object)
    def _on_sync_invoke(self, runner: object) -> None:
        if callable(runner):
            runner()

    def set_event_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop
        panel_bridge = getattr(self, "_panel_bridge", None)
        if panel_bridge is not None:
            panel_bridge.set_event_loop(loop)
        if loop is not None:
            self._ws_log_debug("asyncio event loop attached for WebSocket broadcast")
        else:
            self._ws_log_debug("asyncio event loop detached for WebSocket broadcast")

    @property
    def panel_bridge(self):
        return self._panel_bridge

    @property
    def _ws_panel_queues(self):
        return self._panel_bridge._ws_panel_queues

    @property
    def _panel_backfill_buffer(self):
        return self._panel_bridge._panel_backfill_buffer

    def register_panel_consumer(self, queue: asyncio.Queue) -> None:
        self._panel_bridge.register_panel_consumer(queue)
        self._ws_log_debug(
            f"register_panel_consumer consumers={len(self._ws_panel_queues)}"
        )

    def unregister_panel_consumer(self, queue: asyncio.Queue) -> None:
        self._panel_bridge.unregister_panel_consumer(queue)
        self._ws_log_debug(
            f"unregister_panel_consumer consumers={len(self._ws_panel_queues)}"
        )

    def _ws_loop_active(self) -> bool:
        loop = self._loop
        return loop is not None and not loop.is_closed()

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

    def publish_status(self, *, force: bool = False) -> None:
        status = self.refresh_status()
        payload = asdict(status)
        if not force and status_payloads_semantically_equal(payload, self._last_status_payload):
            return
        self._last_status_payload = payload
        self.status_updated.emit(status)
        self._broadcast_status(payload)


    def _maybe_log_broadcast(self, kind: str, count: int) -> None:
        should_log, new_last_at = should_log_broadcast(
            self._last_broadcast_log_at,
            consumer_count=count,
        )
        if not should_log:
            return
        self._last_broadcast_log_at = new_last_at
        self._ws_log_debug(f"_broadcast_{kind} consumers={count}")

    def _broadcast_status(self, payload: dict) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        queues = list(self._ws_status_queues)
        self._maybe_log_broadcast("status", len(queues))
        for queue in queues:
            _enqueue_ws(loop, queue, payload)

    def _broadcast_log(self, level: str, message: str, ts: float) -> None:
        if not self._ws_loop_active():
            return
        self._pending_log_items.append(
            {"level": level, "message": message, "ts": ts}
        )
        self._schedule_log_flush()

    def _schedule_log_flush(self) -> None:
        if self._log_flush_scheduled:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        self._log_flush_scheduled = True
        loop.call_soon_threadsafe(self._flush_pending_logs)

    def _flush_pending_logs(self) -> None:
        self._log_flush_scheduled = False
        pending = self._pending_log_items
        self._pending_log_items = []
        if not pending:
            return
        queues = list(self._ws_log_queues)
        self._maybe_log_broadcast("log", len(queues))
        for queue in queues:
            for item in pending:
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

    @pyqtSlot(str, str)
    def _on_log(self, level: str, message: str) -> None:
        ts = time.time()
        self._log_ring.append((level, message, ts))
        self.log_received.emit(level, message)
        self._broadcast_log(level, message, ts)

    @pyqtSlot(bool)
    def _on_state_changed(self, _running: bool) -> None:
        pass

    @pyqtSlot(object)
    def _on_save_config(self, payload: object) -> None:
        """配置保存信号槽（主线程）：先写回执再释放事件，避免 HTTP 线程读到旧超时结果。"""
        handle_save_config_request(self, payload)


class WebConsoleServer:
    """在独立线程运行 uvicorn。

    frozen 安装版保留 non-daemon 线程，避免 Qt / pywebview 尚未完成收尾时
    Web 控制台线程被解释器当作守护线程直接回收；源码运行仍可用 daemon。
    """

    def __init__(self, bridge: WebConsoleBridge, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.bridge = bridge
        self.host = host
        self.port = port
        self.static_dir = STATIC_DIR
        self.live_overlay_hub = LiveOverlayHub()
        self.token = secrets.token_urlsafe(24)
        self._thread: threading.Thread | None = None
        self._server = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._bind_failed = threading.Event()
        self._shutdown_requested = threading.Event()
        self._shutdown_complete = threading.Event()
        self.startup_ok = False
        self._startup_error_from_attach = False
        self._startup_failure_user_notified = False
        # S-006: capped auto-restart state (WebConsoleServer only, not DanmuApp runtime).
        self._restart_attempts = 0
        self._last_restart_at = 0.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        """启动 DanmuWebConsole 线程；就绪以 _on_uvicorn_started 置位（非 lifespan 开头）。"""
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._bind_failed.clear()
        self._shutdown_requested.clear()
        self._shutdown_complete.clear()
        self.startup_ok = False
        self._startup_error_from_attach = False
        self._startup_failure_user_notified = False
        # daemon=True 即使 frozen:quit() 已显式 wait_shutdown_complete(),
        # non-daemon 在 uvicorn 卡住时会阻止进程退出(S-QUIT-WEB-DAEMON)。
        self._thread = threading.Thread(
            target=self._run,
            name="DanmuWebConsole",
            daemon=True,
        )
        self._thread.start()

    def wait_shutdown_complete(self, timeout: float = WEB_CONSOLE_SHUTDOWN_TIMEOUT_SEC) -> bool:
        """等待 uvicorn 线程完成退出；这是 quit() 的主要收尾判据。"""
        if self._shutdown_complete.is_set():
            return True
        thread = self._thread
        if thread is None:
            return True
        if not thread.is_alive():
            return self._shutdown_complete.is_set()
        return self._shutdown_complete.wait(timeout=timeout)

    def wait_ready(self, timeout: float = 12.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if self._ready.is_set():
                return True
            if self._bind_failed.is_set():
                return False
            thread = self._thread
            if thread is not None and not thread.is_alive():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._ready.wait(timeout=min(0.05, remaining))

    def _on_uvicorn_started(self) -> None:
        """Called only after uvicorn has bound the listen socket (post-lifespan startup)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                self._loop = loop
                self.bridge.set_event_loop(loop)
        except RuntimeError:
            pass
        self.bridge.danmu_app.logger.info(
            f"Web 控制台 HTTP/WS 已监听 {self.base_url}"
        )
        log_startup("uvicorn.started", base_url=self.base_url)
        self._ready.set()
        self.startup_ok = True
        if self._shutdown_requested.is_set() and self._server is not None:
            self._server.should_exit = True
        clear_startup_attach_error_if_needed(self)

    def stop(self) -> None:
        """Request uvicorn shutdown; frozen builds use non-daemon thread — join in quit() (S-002)."""
        danmu_app = self.bridge.danmu_app
        danmu_app.stop_web_status_timer()
        danmu_app.detach_web_status_timer()
        self._shutdown_requested.set()
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
        except Exception as exc:  # boundary: uvicorn thread fatal exit
            import traceback

            self._bind_failed.set()
            detail = traceback.format_exc()
            bridge.danmu_app.logger.error(
                tr("webConsoleRuntime.threadCrashed").format(error=repr(exc))
            )
            append_frozen_log(f"Web console thread crashed (outer):\n{detail}")
        finally:
            self._shutdown_complete.set()
            self._loop = None

    def _run_uvicorn_locked(self) -> None:
        run_uvicorn_locked(self)


WEB_CONSOLE_MAX_RESTART_ATTEMPTS = 3
WEB_CONSOLE_RESTART_BACKOFF_SEC = (2.0, 5.0, 10.0)


def maybe_restart_web_console(server: WebConsoleServer) -> bool:
    """S-006: retry dead uvicorn from main-thread status tick only (never HTTP/asyncio)."""
    if classify_web_console_startup(server) != "failed":
        return False
    if server._restart_attempts >= WEB_CONSOLE_MAX_RESTART_ATTEMPTS:
        return False
    now = time.monotonic()
    backoff_idx = min(server._restart_attempts, len(WEB_CONSOLE_RESTART_BACKOFF_SEC) - 1)
    if now - server._last_restart_at < WEB_CONSOLE_RESTART_BACKOFF_SEC[backoff_idx]:
        return False
    server._restart_attempts += 1
    server._last_restart_at = now
    server.bridge.danmu_app.logger.warning(
        "Web console auto-restart attempt %s/%s reason=web_console_auto_restart",
        server._restart_attempts,
        WEB_CONSOLE_MAX_RESTART_ATTEMPTS,
    )
    server.start()
    return True


def classify_web_console_startup(server: WebConsoleServer) -> WebConsoleStartupPhase:
    """Classify attach-time Web console state for pywebview scheduling."""
    if server.startup_ok:
        return "ready"
    if server._bind_failed.is_set():
        return "failed"
    thread = server._thread
    if thread is None or not thread.is_alive():
        return "failed"
    return "slow"


def clear_startup_attach_error_if_needed(server: WebConsoleServer) -> None:
    """Clear transient startup error bar after uvicorn binds (BUG-004)."""
    if not getattr(server, "_startup_error_from_attach", False):
        return
    server._startup_error_from_attach = False
    danmu_app = server.bridge.danmu_app
    danmu_app.set_web_error_status("", is_error=False)


def _notify_wait_ready_timeout(server: WebConsoleServer, danmu_app: "DanmuApp") -> None:
    """Log wait_ready timeout; ERROR only when the console thread died or bind failed."""
    thread = server._thread
    thread_alive = bool(thread and thread.is_alive())
    bind_failed = server._bind_failed.is_set()
    append_frozen_log(
        "wait_ready timeout: "
        f"thread_alive={thread_alive} "
        f"bind_failed={bind_failed} "
        f"startup_ok={server.startup_ok}"
    )
    still_starting = thread_alive and not bind_failed
    if still_starting:
        msg = (
            f"Web 控制台启动较慢，仍在后台等待 {server.base_url} 就绪"
            "（就绪后将打开桌面壳）"
        )
        danmu_app.logger.warning(msg)
        append_frozen_log(msg)
        return
    msg = (
        f"Web 控制台未在 {server.base_url} 就绪（WebSocket 会报 1006）。"
        "请检查终端是否有端口占用或依赖缺失，并执行: "
        'pip install -r requirements.txt'
    )
    if is_frozen():
        msg += f" 诊断日志: {frozen_log_path()}"
    danmu_app.logger.error(msg)
    append_frozen_log(msg)
    server._startup_error_from_attach = True
    danmu_app.set_web_error_status(msg, is_error=True)


def attach_web_console(danmu_app: "DanmuApp", port: int = DEFAULT_PORT) -> WebConsoleServer:
    """构造 bridge + 启动 WebConsoleServer；主线程挂 500ms 状态刷新定时器。"""
    log_startup("attach_web_console.begin", port=port)
    bridge = WebConsoleBridge(danmu_app)
    danmu_app.web_bridge = bridge
    server = WebConsoleServer(bridge, port=port)
    danmu_app.web_server = server
    log_startup("web_server.start")
    server.start()

    # BUG-007: 不在 __init__ 同步阻塞 wait_ready（frozen 最多 1.5s，tray 已可见但
    # 事件循环未启动 → 无响应）。改为依靠 _tick_status 500ms 轮询检测就绪，并挂
    # 一个 one-shot deadline 定时器在 ready_timeout 到期时记录超时诊断。
    # QTimer.singleShot 在 app.exec() 启动后触发，不阻塞主线程。
    ready_timeout = web_console_ready_timeout()

    def _check_ready_deadline():
        ready = server.startup_ok
        log_startup(
            "web_server.wait_ready_deadline",
            ok=ready,
            timeout_s=ready_timeout,
            startup_ok=server.startup_ok,
        )
        if not ready:
            _notify_wait_ready_timeout(server, danmu_app)

    QTimer.singleShot(int(ready_timeout * 1000), _check_ready_deadline)

    def _tick_status():
        phase = classify_web_console_startup(server)
        if phase == "ready":
            server._restart_attempts = 0
            clear_startup_attach_error_if_needed(server)
        elif phase == "failed":
            maybe_restart_web_console(server)
        web_bridge = getattr(danmu_app, "web_bridge", None)
        if web_bridge:
            web_bridge.publish_status()

    web_status_timer = QTimer(danmu_app)
    web_status_timer.setInterval(WEB_STATUS_POLL_INTERVAL_MS)
    web_status_timer.timeout.connect(_tick_status)
    danmu_app.attach_web_status_timer(web_status_timer)
    web_status_timer.start()

    schedule_screen_cache(bridge)

    log_startup("attach_web_console.end", startup_ok=server.startup_ok)
    return server


def try_recover_web_console_for_user_action(
    server: WebConsoleServer,
    *,
    probe_timeout: float = 2.0,
) -> bool:
    """User-initiated: one maybe_restart + HTTP probe. Returns True if HTTP ready."""
    if classify_web_console_startup(server) != "failed":
        return True
    maybe_restart_web_console(server)
    from app.webview_shell import wait_for_http_server

    return wait_for_http_server(server.base_url, timeout=probe_timeout)


def open_web_console_browser(server: WebConsoleServer, path: str = "/") -> None:
    import webbrowser

    webbrowser.open(f"{server.base_url}{path}")
