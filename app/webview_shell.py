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
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from app.bundle_paths import append_frozen_log, frozen_log_path, is_frozen
from app.startup_trace import log_startup

if TYPE_CHECKING:
    from app.web_console import WebConsoleServer
_START_TIMEOUT_SEC = 20.0
_CREATED_TIMEOUT_SEC = 5.0
# Aligned with frozen: WebView2 cold start on Windows can exceed 12s.
_LOAD_TIMEOUT_SEC = 25.0
_FROZEN_LOAD_TIMEOUT_SEC = 25.0
# Short main-thread probe; slow bind is retried by open_web_console_when_ready (S-001).
_SERVER_POLL_SEC = 2.0
_FROZEN_SERVER_POLL_SEC = 1.5
_NAV_POLL_SEC = 0.25
_BROWSER_PROBE_SEC = 3.0
_HANDSHAKE_POLL_MS = 50
_SLOW_START_PROMPT_SEC = 5.0
_DISABLE_SLOW_START_PROMPT = True
_SPAWN_MAX_ATTEMPTS = 3
_WEBVIEW_ATTACH_MAX_ATTEMPTS = 2
_WEBVIEW_ATTACH_RETRY_MS = 1200
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
    """Probe public GET /api/status (W-SEC-001 locked down /api/session for curl)."""
    deadline = time.monotonic() + timeout
    probe = f"{base_url.rstrip('/')}/api/status"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(probe, timeout=0.6) as resp:
                if resp.status != 200:
                    continue
                body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(body)
                if isinstance(data, dict):
                    return True
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            time.sleep(0.15)
    return False


def _tray_icon_for_notify(danmu_app) -> object | None:
    """Return QSystemTrayIcon if available; tolerate partial DanmuApp (tests / early startup)."""
    try:
        tray_mgr = getattr(danmu_app, "tray", None)
    except RuntimeError:
        return None
    if tray_mgr is None:
        return None
    try:
        return getattr(tray_mgr, "tray", None)
    except RuntimeError:
        return None


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
        from PyQt6.QtWidgets import QApplication

        tray = _tray_icon_for_notify(danmu_app)
        if tray is not None and QSystemTrayIcon.isSystemTrayAvailable():
            tray.showMessage(
                "DanmuAI",
                message[:240],
                QSystemTrayIcon.MessageIcon.Warning,
                5000,
            )
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        QMessageBox.warning(None, tr("app.error_title"), message)
    QTimer.singleShot(0, _show)
def _server_ready_probe_sec() -> float:
    from app.startup_trace import web_console_ready_timeout

    return float(web_console_ready_timeout())


def _ensure_server_ready(server: WebConsoleServer) -> bool:
    """Short non-blocking probe for pywebview begin_start (S-001).

    Returns False while uvicorn is still starting; ``open_web_console_when_ready``
    retries on a QTimer instead of blocking the Qt main thread for 12s.
    """
    probe = _server_ready_probe_sec()
    # startup_ok can be set before HTTP answers; verify via GET /api/status (not /api/session).
    http_probe = 1.0 if getattr(server, "startup_ok", False) else min(probe, 1.0)
    if getattr(server, "startup_ok", False):
        if wait_for_http_server(server.base_url, timeout=http_probe):
            log_startup("webview.ensure_server_ready", ok=True, verified=True)
            return True
        log_startup("webview.ensure_server_ready", ok=False, startup_ok_stale=True)
    log_startup("webview.ensure_server_ready.begin", probe_sec=probe)
    if server.wait_ready(timeout=probe):
        if wait_for_http_server(server.base_url, timeout=http_probe):
            log_startup("webview.ensure_server_ready.end", ok=True, via="wait_ready")
            return True
    if wait_for_http_server(server.base_url, timeout=http_probe):
        log_startup("webview.ensure_server_ready.end", ok=True, via="http_probe")
        return True
    log_startup("webview.ensure_server_ready.end", ok=False, deferred=True)
    return False
def _fallback_to_system_browser(server: WebConsoleServer, path: str, reason: str) -> None:
    if getattr(server, "_browser_launch_opened", False):
        log_startup("webview.fallback_browser.skipped", reason=reason)
        return
    from app.web_console import open_web_console_browser

    server._browser_launch_opened = True
    server.bridge.danmu_app.logger.warning(
        f"pywebview 不可用，改用系统浏览器: {reason}"
    )
    append_frozen_log(f"fallback to system browser: {reason}")
    log_startup("webview.fallback_browser", reason=reason)
    open_web_console_browser(server, path)


def _maybe_prompt_slow_webview_start(shell: "WebViewShell", initial_path: str) -> None:
    """Offer system browser while pywebview loaded handshake is still pending.

    UX guard only — unlike ``_fallback_to_system_browser`` we do not terminate the
    child process so the desktop shell may still appear later. Called from ``poll_handshake`` on the Qt main thread (modal dialog blocks the 50 ms poll).
    """
    if _DISABLE_SLOW_START_PROMPT:
        return
    if shell._started:
        return
    if shell._attach_started_at <= 0:
        return
    if time.monotonic() - shell._attach_started_at < _SLOW_START_PROMPT_SEC:
        return
    server = shell.server
    if getattr(server, "_slow_webview_prompt_shown", False):
        return
    if getattr(server, "_browser_launch_opened", False):
        return
    proc = shell._process
    if proc is None or not proc.is_alive():
        return
    if not getattr(server, "startup_ok", False):
        if not wait_for_http_server(server.base_url, timeout=0.25):
            return

    from PyQt6.QtWidgets import QMessageBox

    from app.translations import tr
    from app.web_console import open_web_console_browser

    server._slow_webview_prompt_shown = True
    base_url = server.base_url
    title = tr("webview.slow_start_title", "DanmuAI 启动较慢")
    message = tr(
        "webview.slow_start_message",
        "桌面窗口启动较慢，是否改用系统浏览器打开本地网页端？\n地址：{base_url}",
    ).format(base_url=base_url)

    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(message)
    yes_btn = box.addButton(tr("common.yes"), QMessageBox.ButtonRole.YesRole)
    no_btn = box.addButton(tr("common.no"), QMessageBox.ButtonRole.NoRole)
    box.setDefaultButton(no_btn)
    box.exec()

    if box.clickedButton() == yes_btn:
        path = shell._resolve_path(initial_path)
        if not getattr(server, "_browser_launch_opened", False):
            server._browser_launch_opened = True
            open_web_console_browser(server, path)
            log_startup("webview.slow_start.browser_opened", path=path)
    else:
        log_startup("webview.slow_start.continue_waiting")


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
        def on_closing(window, *_args, **_kwargs):
            try:
                window.hide()
            except Exception:
                pass
            try:
                window.evaluate_js(
                    "try{"
                    "  var t=document.getElementById('toast');"
                    "  if(t){t.textContent='窗口已最小化到系统托盘，右键托盘图标可退出';"
                    "  t.className='toast show text-warmText';"
                    "  setTimeout(function(){t.classList.remove('show')},4000);}"
                    "}catch(e){}"
                )
            except Exception:
                pass
            return False
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
        self._spawn_attempt: int = 0
        self._last_launch_url: str = ""
        self._last_launch_gui: str | None = None
        self._defer_browser_fallback: bool = False
        self._attach_started_at: float = 0.0

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
    def _launch_child_process(self, url: str, gui: str | None) -> None:
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
        self._attach_started_at = time.monotonic()
        log_startup(
            "webview.process.start",
            ms=(time.perf_counter() - proc_started) * 1000.0,
            url=url,
            spawn_attempt=self._spawn_attempt,
        )

    def _retry_spawn(self, initial_path: str, reason: str) -> bool:
        """Relaunch child after early exit; returns True if another attempt was started."""
        if self._spawn_attempt >= _SPAWN_MAX_ATTEMPTS:
            return False
        self._spawn_attempt += 1
        log_startup(
            "webview.process.retry",
            attempt=self._spawn_attempt,
            reason=reason,
        )
        self._terminate()
        self._got_created = False
        self._load_deadline = 0.0
        self._handshake_deadline = time.monotonic() + _START_TIMEOUT_SEC
        try:
            self._launch_child_process(self._last_launch_url, self._last_launch_gui)
        except OSError as exc:
            if self._spawn_attempt >= _SPAWN_MAX_ATTEMPTS:
                self._fail_start(f"pywebview spawn failed: {exc}", self._resolve_path(initial_path))
                return False
            return self._retry_spawn(initial_path, f"spawn OSError: {exc}")
        return True

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
        self._last_launch_url = url
        self._last_launch_gui = gui
        self._spawn_attempt = 1
        self._got_created = False
        self._load_deadline = 0.0
        self._handshake_failed = False
        self._handshake_deadline = time.monotonic() + _START_TIMEOUT_SEC
        while self._spawn_attempt <= _SPAWN_MAX_ATTEMPTS:
            try:
                self._launch_child_process(url, gui)
                return True
            except OSError as exc:
                if self._spawn_attempt >= _SPAWN_MAX_ATTEMPTS:
                    self._fail_start(f"pywebview spawn failed: {exc}", initial_path)
                    return False
                log_startup(
                    "webview.process.retry",
                    attempt=self._spawn_attempt + 1,
                    reason=f"spawn OSError: {exc}",
                )
                self._spawn_attempt += 1
        return False
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
        if proc is not None and not proc.is_alive():
            resolved = self._resolve_path(initial_path)
            if not self._got_created:
                if self._retry_spawn(initial_path, "pywebview process exited early"):
                    return "pending"
                self._fail_start("pywebview process exited early", resolved)
                return "failure"
            self._fail_start("pywebview process exited early", resolved)
            return "failure"
        _maybe_prompt_slow_webview_start(self, initial_path)
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
    def _abort_handshake(
        self,
        error: str,
        initial_path: str,
        *,
        fallback_browser: bool = True,
    ) -> bool:
        if self._handshake_failed and not fallback_browser:
            return False
        if self._handshake_failed and fallback_browser:
            return False
        danmu_app = self.server.bridge.danmu_app
        if fallback_browser:
            danmu_app.logger.error(f"pywebview 启动失败: {error}")
        else:
            danmu_app.logger.warning(
                f"pywebview 握手未完成，将重试: {error}"
            )
        append_frozen_log(f"pywebview start failed: {error}")
        log_startup("webview.handshake.failed", error=error)
        self._handshake_failed = True
        self._terminate()
        use_browser = fallback_browser and not self._defer_browser_fallback
        if use_browser:
            _fallback_to_system_browser(self.server, initial_path, error)
        return False

    def _fail_start(self, error: str, initial_path: str) -> bool:
        fallback = not self._defer_browser_fallback
        return self._abort_handshake(error, initial_path, fallback_browser=fallback)

    def finalize_handshake_failure(self, error: str, initial_path: str) -> bool:
        """Final attach failure: always allow browser fallback (BUG-014 dedupe)."""
        self._defer_browser_fallback = False
        return self._abort_handshake(error, initial_path, fallback_browser=True)

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
        self._attach_started_at = 0.0
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
    on_handshake_failed: Callable[[], None] | None = None,
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
    shell._defer_browser_fallback = on_handshake_failed is not None
    danmu_app.webview_shell = shell
    log_startup("attach_webview_shell.begin", path=initial_path)
    def _poll() -> None:
        result = shell.poll_handshake(initial_path)
        if result == "pending":
            QTimer.singleShot(_HANDSHAKE_POLL_MS, _poll)
            return
        if result == "failure" and on_handshake_failed is not None:
            if not getattr(server, "_browser_launch_opened", False):
                server._webview_open_retry_active = False
                on_handshake_failed()
                log_startup("attach_webview_shell.end", ok=False, deferred_retry=True)
                return
            if not shell.handshake_failed:
                shell.finalize_handshake_failure(
                    "pywebview handshake failed after browser fallback skipped",
                    initial_path,
                )
            server._webview_open_retry_active = False
        log_startup("attach_webview_shell.end", ok=(result == "success"))
        if result == "success":
            server._webview_open_retry_active = False
    def _begin(defer_attempt: int = 0) -> None:
        if shell.begin_start(initial_path):
            QTimer.singleShot(_HANDSHAKE_POLL_MS, _poll)
            return
        from app.web_console import classify_web_console_startup

        if (
            defer_attempt < 40
            and classify_web_console_startup(server) != "failed"
            and not shell.handshake_failed
        ):
            QTimer.singleShot(500, lambda: _begin(defer_attempt + 1))
            return
        log_startup("attach_webview_shell.end", ok=False)
        server._webview_open_retry_active = False
    QTimer.singleShot(0, _begin)
    return shell


def retry_webview_attach(
    danmu_app,
    path: str,
    schedule_attempt: int,
) -> None:
    """重试 WebView attach（从 DanmuApp 迁移）。"""
    from PyQt6.QtCore import QTimer

    server = danmu_app.web_server
    if server is not None:
        server._webview_open_retry_active = False

    if schedule_attempt >= _WEBVIEW_ATTACH_MAX_ATTEMPTS:
        shell = getattr(danmu_app, "webview_shell", None)
        if shell is not None:
            shell.finalize_handshake_failure(
                "pywebview attach retries exhausted",
                path,
            )
        return
    shell = getattr(danmu_app, "webview_shell", None)
    if shell is not None:
        shell.destroy()
    danmu_app.webview_shell = None
    log_startup("webview_shell.attach_retry", attempt=schedule_attempt + 1)
    QTimer.singleShot(
        _WEBVIEW_ATTACH_RETRY_MS,
        lambda: schedule_webview_attach(
            danmu_app, path, attempt=schedule_attempt + 1
        ),
    )


def schedule_webview_attach(
    danmu_app,
    initial_path: str,
    *,
    attempt: int = 0,
) -> None:
    """等待 HTTP ready 后 attach pywebview（从 DanmuApp 迁移）。"""
    from PyQt6.QtCore import QTimer

    if danmu_app.web_launch_mode != "webview" or not danmu_app.web_server:
        return
    from app.web_console import classify_web_console_startup

    phase = classify_web_console_startup(danmu_app.web_server)
    if phase == "failed":
        return
    shell = getattr(danmu_app, "webview_shell", None)
    if shell and (shell.is_running() or shell.is_handshake_pending()):
        return
    if attempt == 0:
        from app.bundle_paths import is_frozen

        delay_ms = 400 if is_frozen() else 800
        log_startup("webview_shell.scheduled", delay_ms=delay_ms)
        QTimer.singleShot(
            delay_ms,
            lambda: schedule_webview_attach(danmu_app, initial_path, attempt=1),
        )
        return
    open_web_console_when_ready(
        danmu_app,
        initial_path,
        use_browser=False,
        attempt=0,
        on_webview_handshake_failed=lambda: retry_webview_attach(
            danmu_app, initial_path, attempt
        ),
    )


def open_web_console_when_ready(
    danmu_app,
    path: str = "/",
    *,
    use_browser: bool = False,
    attempt: int = 0,
    on_webview_handshake_failed=None,
) -> None:
    """等待 HTTP server ready 后打开 Web 控制台（从 DanmuApp 迁移）。"""
    from PyQt6.QtCore import QTimer

    server = danmu_app.web_server
    if not server:
        return
    from app.web_console import (
        classify_web_console_startup,
        clear_startup_attach_error_if_needed,
        open_web_console_browser,
    )

    if not use_browser and attempt == 0:
        if getattr(server, "_webview_open_retry_active", None) is True:
            shell = getattr(danmu_app, "webview_shell", None)
            if shell and shell.is_running():
                shell.open(path)
            elif shell and shell.is_handshake_pending():
                shell.request_navigate(path)
            return
        server._webview_open_retry_active = True

    phase = classify_web_console_startup(server)
    if phase == "failed":
        if not server._startup_failure_user_notified:
            notify_web_console_failure(danmu_app, "web_console.startup_failed")
            server._startup_failure_user_notified = True
        return

    if use_browser:
        if not getattr(server, "_browser_launch_opened", False):
            open_web_console_browser(server, path)
            server._browser_launch_opened = True
        http_ready = server.startup_ok or wait_for_http_server(
            server.base_url, timeout=0.25
        )
        if http_ready:
            clear_startup_attach_error_if_needed(server)
            return
        if attempt < 40:
            QTimer.singleShot(
                500,
                lambda: open_web_console_when_ready(
                    danmu_app,
                    path,
                    use_browser=True,
                    attempt=attempt + 1,
                ),
            )
            return
        if not server._startup_failure_user_notified:
            notify_web_console_failure(danmu_app, "web_console.startup_failed")
            server._startup_failure_user_notified = True
        return

    # Do not trust startup_ok alone — verify via GET /api/status (see _ensure_server_ready).
    http_ok = wait_for_http_server(server.base_url, timeout=1.0)
    if not http_ok and getattr(server, "startup_ok", False):
        http_ok = wait_for_http_server(server.base_url, timeout=2.0)
    if not http_ok:
        if attempt < 40:
            QTimer.singleShot(
                500,
                lambda: open_web_console_when_ready(
                    danmu_app,
                    path,
                    use_browser=use_browser,
                    attempt=attempt + 1,
                ),
            )
            return
        if not use_browser:
            server._webview_open_retry_active = False
        if not server._startup_failure_user_notified:
            notify_web_console_failure(danmu_app, "web_console.startup_failed")
            server._startup_failure_user_notified = True
        return
    clear_startup_attach_error_if_needed(server)

    shell = getattr(danmu_app, "webview_shell", None)
    if shell and shell.is_running():
        if not use_browser:
            server._webview_open_retry_active = False
        shell.open(path)
        return
    if shell and shell.is_handshake_pending():
        shell.request_navigate(path)
        return
    attach_webview_shell(
        danmu_app,
        server,
        initial_path=path,
        on_handshake_failed=on_webview_handshake_failed,
    )
