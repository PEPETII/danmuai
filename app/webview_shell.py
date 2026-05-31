"""pywebview desktop shell for the local DanmuAI web console."""
from __future__ import annotations

import json
import multiprocessing
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, Literal

from app.bundle_paths import append_frozen_log, frozen_log_path, is_frozen
from app.startup_trace import log_startup

if TYPE_CHECKING:
    from app.web_console import WebConsoleServer
_START_TIMEOUT_SEC = 20.0
_CREATED_TIMEOUT_SEC = 5.0
_LOAD_TIMEOUT_SEC = 12.0
_FROZEN_LOAD_TIMEOUT_SEC = 25.0
_SERVER_POLL_SEC = 12.0
_FROZEN_SERVER_POLL_SEC = 5.0
_NAV_POLL_SEC = 0.25
_BROWSER_PROBE_SEC = 3.0
_HANDSHAKE_POLL_MS = 50
_SIGNAL_CREATED = "created"
_SIGNAL_LOADED = "loaded"
_PHASE_SIGNALS = frozenset({_SIGNAL_CREATED, _SIGNAL_LOADED})
HandshakeResult = Literal["pending", "success", "failure"]
def _load_timeout_sec() -> float:
    return _FROZEN_LOAD_TIMEOUT_SEC if is_frozen() else _LOAD_TIMEOUT_SEC
def preferred_webview_gui() -> str | None:
    if sys.platform == "win32":
        return "edgechromium"
    if sys.platform == "darwin":
        return "cocoa"
    return "gtk"
def wait_for_http_server(base_url: str, timeout: float = _SERVER_POLL_SEC) -> bool:
    deadline = time.monotonic() + timeout
    probe = f"{base_url.rstrip('/')}/api/session"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(probe, timeout=0.6) as resp:
                if resp.status != 200:
                    continue
                body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(body)
                if data.get("token"):
                    return True
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            time.sleep(0.15)
    return False
def notify_web_console_failure(danmu_app, reason_key: str, *, detail: str = "") -> None:
    """主线程弹窗 + 托盘气泡；HTTP 线程请经 QTimer.singleShot 调用本函数。"""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QMessageBox, QSystemTrayIcon

    from app.translations import tr
    server = getattr(danmu_app, "web_server", None)
    base_url = server.base_url if server else "http://127.0.0.1:18765"
    log_path = frozen_log_path()
    message = tr(reason_key).format(
        log_path=log_path,
        base_url=base_url,
        detail=detail,
    )
    def _show() -> None:
        tray = getattr(getattr(danmu_app, "tray", None), "tray", None)
        if tray is not None and QSystemTrayIcon.isSystemTrayAvailable():
            tray.showMessage(
                "DanmuAI",
                message[:240],
                QSystemTrayIcon.MessageIcon.Warning,
                5000,
            )
        QMessageBox.warning(None, tr("app.error_title"), message)
    QTimer.singleShot(0, _show)
def _ensure_server_ready(server: WebConsoleServer) -> bool:
    if getattr(server, "startup_ok", False):
        if wait_for_http_server(server.base_url, timeout=1.5):
            log_startup("webview.ensure_server_ready", ok=True, verified=True)
            return True
        log_startup("webview.ensure_server_ready", ok=False, startup_ok_stale=True)
    log_startup("webview.ensure_server_ready.begin")
    poll = _FROZEN_SERVER_POLL_SEC if is_frozen() else _SERVER_POLL_SEC
    if server.wait_ready(timeout=poll):
        log_startup("webview.ensure_server_ready.end", ok=True, via="wait_ready")
        return True
    if wait_for_http_server(server.base_url, timeout=poll):
        log_startup("webview.ensure_server_ready.end", ok=True, via="http_probe")
        return True
    danmu_app = server.bridge.danmu_app
    danmu_app.logger.error(
        f"Web 控制台未就绪: {server.base_url}（请查 startup.log 或端口占用）"
    )
    append_frozen_log(f"web console not ready: {server.base_url}")
    log_startup("webview.ensure_server_ready.end", ok=False)
    notify_web_console_failure(
        danmu_app,
        "web_console.not_ready",
        detail=server.base_url,
    )
    return False
def _fallback_to_system_browser(server: WebConsoleServer, path: str, reason: str) -> None:
    from app.web_console import open_web_console_browser
    server.bridge.danmu_app.logger.warning(
        f"pywebview 不可用，改用系统浏览器: {reason}"
    )
    append_frozen_log(f"fallback to system browser: {reason}")
    log_startup("webview.fallback_browser", reason=reason)
    open_web_console_browser(server, path)
def _nav_poll_loop(window: Any, nav_queue: Any, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            url = nav_queue.get(timeout=_NAV_POLL_SEC)
        except Exception:
            continue
        if url is None:
            break
        try:
            window.load_url(url)
            window.show()
            window.restore()
            append_frozen_log(f"pywebview navigate: {url}")
        except Exception as exc:
            append_frozen_log(f"pywebview navigate failed: {exc!r}")
def _webview_worker(
    url: str,
    title: str,
    gui: str | None,
    ready_queue: Any,
    nav_queue: Any,
) -> None:
    """Runs in child process; this process's main thread owns webview.start()."""
    multiprocessing.freeze_support()
    stop_nav = threading.Event()
    try:
        import webview
        def on_closing(*_args, **_kwargs):
            return True
        def on_loaded(window):
            window.show()
            append_frozen_log("pywebview window loaded")
            log_startup("pywebview.loaded")
            try:
                ready_queue.put(_SIGNAL_LOADED)
            except Exception:
                pass
        window = webview.create_window(
            title,
            url,
            width=1280,
            height=820,
            min_size=(960, 640),
            hidden=True,
            background_color="#FDFBF7",
        )
        window.events.closing += on_closing
        window.events.loaded += on_loaded
        # Signal "created" before webview.start(); do NOT call window.show() here — on Windows
        # show() before start() can block the child main thread (ISSUE-010).
        ready_queue.put(_SIGNAL_CREATED)
        append_frozen_log("pywebview created handshake sent")
        log_startup("pywebview.created_handshake")
        threading.Thread(
            target=_nav_poll_loop,
            args=(window, nav_queue, stop_nav),
            name="DanmuWebViewNav",
            daemon=True,
        ).start()
        if gui:
            webview.start(debug=False, gui=gui)
        else:
            webview.start(debug=False)
        stop_nav.set()
        try:
            nav_queue.put(None)
        except Exception:
            pass
    except Exception as exc:
        append_frozen_log(f"pywebview worker failed: {exc!r}")
        try:
            ready_queue.put(str(exc))
        except Exception:
            pass
def _webview_process_main(
    url: str,
    title: str,
    gui: str | None,
    ready_queue: Any,
    nav_queue: Any,
) -> None:
    _webview_worker(url, title, gui, ready_queue, nav_queue)
class WebViewShell:
    """Runs pywebview in a child process so Qt keeps the main GUI loop."""
    def __init__(self, server: WebConsoleServer, title: str = "DanmuAI"):
        self.server = server
        self.title = title
        self._process: multiprocessing.Process | None = None
        self._ready_queue: multiprocessing.Queue | None = None
        self._nav_queue: multiprocessing.Queue | None = None
        self._started = False
        self._handshake_deadline: float = 0.0
        self._got_created = False
        self._load_deadline: float = 0.0
        self._pending_path: str = ""
        self._handshake_failed: bool = False

    def is_running(self) -> bool:
        return self._started and self._process is not None and self._process.is_alive()

    def is_handshake_pending(self) -> bool:
        """Child process alive but loaded handshake not complete yet."""
        if self._started:
            return False
        proc = self._process
        return proc is not None and proc.is_alive()

    @property
    def handshake_failed(self) -> bool:
        return self._handshake_failed

    def _resolve_path(self, initial_path: str) -> str:
        pending = (self._pending_path or "").strip()
        return pending if pending else initial_path

    def request_navigate(self, path: str) -> None:
        """Update desired path; navigate immediately if the window already exists."""
        self._pending_path = path
        if self._got_created and self._nav_queue is not None:
            try:
                self._nav_queue.put(self._url(path))
            except Exception:
                pass
    def _url(self, path: str = "/") -> str:
        base = self.server.base_url.rstrip("/")
        if not path or path == "/":
            return f"{base}/"
        if path.startswith("#"):
            return f"{base}/{path}"
        if path.startswith("/"):
            return f"{base}{path}"
        return f"{base}/{path}"
    def begin_start(self, initial_path: str = "/") -> bool:
        """Start pywebview child process; complete handshake via poll_handshake()."""
        if self.is_running():
            self.open(initial_path)
            return True
        if not _ensure_server_ready(self.server):
            return False
        self._pending_path = initial_path
        url = self._url(initial_path)
        gui = preferred_webview_gui()
        ctx = multiprocessing.get_context("spawn")
        self._ready_queue = ctx.Queue()
        self._nav_queue = ctx.Queue()
        self._process = ctx.Process(
            target=_webview_process_main,
            args=(url, self.title, gui, self._ready_queue, self._nav_queue),
            name="DanmuWebView",
            daemon=True,
        )
        proc_started = time.perf_counter()
        self._process.start()
        log_startup(
            "webview.process.start",
            ms=(time.perf_counter() - proc_started) * 1000.0,
            url=url,
        )
        self._handshake_deadline = time.monotonic() + _START_TIMEOUT_SEC
        self._got_created = False
        self._load_deadline = 0.0
        self._handshake_failed = False
        return True
    def _drain_ready_queue(self, initial_path: str) -> HandshakeResult:
        queue_ref = self._ready_queue
        if queue_ref is None:
            return "failure"
        while True:
            try:
                signal = queue_ref.get_nowait()
            except queue.Empty:
                break
            log_startup("webview.ready_queue", signal=signal)
            if signal == _SIGNAL_CREATED:
                self._got_created = True
                self._load_deadline = time.monotonic() + _load_timeout_sec()
                continue
            if signal == _SIGNAL_LOADED:
                self._succeed_start(self._resolve_path(initial_path))
                return "success"
            if signal in _PHASE_SIGNALS:
                continue
            self._fail_start(str(signal), self._resolve_path(initial_path))
            return "failure"
        return "pending"
    def poll_handshake(self, initial_path: str) -> HandshakeResult:
        """Non-blocking handshake step; call from QTimer until not pending."""
        if self._started:
            return "success"
        proc = self._process
        if self._got_created and proc is not None and not proc.is_alive():
            self._fail_start("pywebview process exited early", self._resolve_path(initial_path))
            return "failure"
        now = time.monotonic()
        resolved = self._resolve_path(initial_path)
        if now > self._handshake_deadline:
            if not self._got_created:
                self._fail_start("timeout waiting for pywebview created", resolved)
            else:
                self._fail_start("timeout waiting for pywebview loaded", resolved)
            return "failure"
        if self._got_created and self._load_deadline > 0 and now > self._load_deadline:
            self._fail_start("timeout waiting for pywebview loaded", resolved)
            return "failure"
        result = self._drain_ready_queue(initial_path)
        if result != "pending":
            return result
        if not self._got_created and now + _CREATED_TIMEOUT_SEC > self._handshake_deadline:
            self._fail_start("timeout waiting for pywebview created", resolved)
            return "failure"
        return "pending"
    def start(self, initial_path: str = "/") -> bool:
        """Blocking start (tests / open() fallback); production uses begin_start + poll."""
        if not self.begin_start(initial_path):
            return False
        deadline = time.monotonic() + _START_TIMEOUT_SEC
        while time.monotonic() < deadline:
            result = self.poll_handshake(initial_path)
            if result == "success":
                return True
            if result == "failure":
                return False
            time.sleep(_HANDSHAKE_POLL_MS / 1000.0)
        if not self._got_created:
            return self._fail_start("timeout waiting for pywebview created", initial_path)
        return self._fail_start("timeout waiting for pywebview loaded", initial_path)
    def _fail_start(self, error: str, initial_path: str) -> bool:
        danmu_app = self.server.bridge.danmu_app
        danmu_app.logger.error(f"pywebview 启动失败: {error}")
        append_frozen_log(f"pywebview start failed: {error}")
        log_startup("webview.handshake.failed", error=error)
        self._handshake_failed = True
        self._terminate()
        _fallback_to_system_browser(self.server, initial_path, error)
        return False

    def _succeed_start(self, initial_path: str) -> bool:
        self._started = True
        self._handshake_failed = False
        append_frozen_log(f"pywebview window ready url={self._url(initial_path)}")
        log_startup("webview.handshake.ok", url=self._url(initial_path))
        if self._pending_path and self._pending_path != initial_path:
            self.request_navigate(self._pending_path)
        return True
    def open(self, path: str = "/") -> None:
        if not self.is_running():
            if not self.start(path):
                return
            return
        url = self._url(path)
        nav_queue = self._nav_queue
        if nav_queue is not None:
            try:
                nav_queue.put(url)
                return
            except Exception as exc:
                _fallback_to_system_browser(self.server, path, str(exc))
                return
        _fallback_to_system_browser(self.server, path, "nav queue unavailable")
    def _terminate(self) -> None:
        proc = self._process
        nav_queue = self._nav_queue
        self._process = None
        self._ready_queue = None
        self._nav_queue = None
        self._started = False
        self._handshake_deadline = 0.0
        self._got_created = False
        self._load_deadline = 0.0
        if nav_queue is not None:
            try:
                nav_queue.put(None)
            except Exception:
                pass
        if proc is None:
            return
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2.0)

    def destroy(self) -> None:
        self._terminate()
        self._handshake_failed = False
def attach_webview_shell(
    danmu_app,
    server: WebConsoleServer,
    *,
    initial_path: str = "/",
) -> WebViewShell:
    """Attach shell and start pywebview without blocking the Qt event loop."""
    from PyQt6.QtCore import QTimer

    existing = getattr(danmu_app, "webview_shell", None)
    if existing is not None:
        if existing.server is not server:
            existing.destroy()
        elif existing.is_running():
            existing.open(initial_path)
            log_startup("attach_webview_shell.reuse_running", path=initial_path)
            return existing
        elif existing.is_handshake_pending():
            existing.request_navigate(initial_path)
            log_startup("attach_webview_shell.reuse_pending", path=initial_path)
            return existing
        else:
            existing.destroy()

    shell = WebViewShell(server)
    danmu_app.webview_shell = shell
    log_startup("attach_webview_shell.begin", path=initial_path)
    def _poll() -> None:
        result = shell.poll_handshake(initial_path)
        if result == "pending":
            QTimer.singleShot(_HANDSHAKE_POLL_MS, _poll)
            return
        log_startup("attach_webview_shell.end", ok=(result == "success"))
    def _begin() -> None:
        if shell.begin_start(initial_path):
            QTimer.singleShot(_HANDSHAKE_POLL_MS, _poll)
        else:
            log_startup("attach_webview_shell.end", ok=False)
    QTimer.singleShot(0, _begin)
    return shell
