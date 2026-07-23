"""pywebview 浮动面板子进程管理（spawn + ready queue + stop/restart）。"""

from __future__ import annotations

import logging
import multiprocessing
import sys
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

_SIGNAL_LOADED = "loaded"
_LOAD_TIMEOUT_SEC = 25.0
_STOP_JOIN_SEC = 3.0
_KILL_JOIN_SEC = 1.0
MAX_RESTARTS = 3


class PanelProcessError(RuntimeError):
    """Raised when panel subprocess cannot start (optional callers)."""


def _webview_worker(
    html_url: str,
    ready_queue: Any,
    *,
    width: int,
    height: int,
    x: int,
    y: int,
    click_through: bool,
) -> None:
    """Child process entry: webview.start() blocks until window closes."""
    multiprocessing.freeze_support()
    try:
        import webview
    except ImportError as exc:
        try:
            ready_queue.put(f"import-failed: {exc}")
        except (OSError, RuntimeError):
            pass
        return

    create_kwargs: dict[str, Any] = dict(
        title="DanmuAI Floating Panel",
        url=html_url,
        width=int(width),
        height=int(height),
        x=int(x),
        y=int(y),
        frameless=True,
        easy_drag=False,
        on_top=True,
        transparent=True,
        hidden=False,
    )
    try:
        window = webview.create_window(**create_kwargs)
    except (TypeError, ValueError):
        create_kwargs.pop("transparent", None)
        window = webview.create_window(**create_kwargs)

    hwnd_holder: dict[str, int] = {"hwnd": 0}

    def get_hwnd() -> int:
        try:
            from webview.platforms.winforms import BrowserView

            bv = BrowserView.instances.get(window.uid)
            if bv is not None:
                return int(bv.Handle.ToInt32())
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                import ctypes

                hwnd = ctypes.windll.user32.FindWindowW(None, "DanmuAI Floating Panel")
                if hwnd:
                    return int(hwnd)
            except Exception:
                pass
        return 0

    def on_loaded() -> None:
        hwnd = get_hwnd()
        hwnd_holder["hwnd"] = hwnd
        try:
            ready_queue.put(_SIGNAL_LOADED)
            ready_queue.put(f"hwnd:{hwnd}")
        except (OSError, RuntimeError):
            pass
        if hwnd and sys.platform == "win32":
            try:
                from app.win32_overlay_zorder import (
                    apply_overlay_exstyles,
                    reassert_hwnd_topmost,
                )

                apply_overlay_exstyles(hwnd, click_through=bool(click_through))
                reassert_hwnd_topmost(hwnd)
            except Exception as exc:
                try:
                    ready_queue.put(f"exstyle-failed: {exc}")
                except (OSError, RuntimeError):
                    pass

    def on_closing() -> bool:
        return True

    window.events.loaded += on_loaded
    window.events.closing += on_closing
    try:
        webview.start(gui="edgechromium")
    except Exception as exc:
        try:
            ready_queue.put(f"start-failed: {exc}")
        except (OSError, RuntimeError):
            pass


def _webview_process_main(
    html_url: str,
    ready_queue: Any,
    width: int,
    height: int,
    x: int,
    y: int,
    click_through: bool,
) -> None:
    _webview_worker(
        html_url,
        ready_queue,
        width=width,
        height=height,
        x=x,
        y=y,
        click_through=click_through,
    )


class PanelProcess:
    """Owns one pywebview child process for the floating panel."""

    def __init__(
        self,
        *,
        load_timeout_sec: float = _LOAD_TIMEOUT_SEC,
        webview2_checker: Callable[[], bool] | None = None,
        process_factory: Callable[..., Any] | None = None,
        logger_: logging.Logger | None = None,
    ) -> None:
        self._load_timeout_sec = float(load_timeout_sec)
        self._webview2_checker = webview2_checker
        self._process_factory = process_factory
        self._logger = logger_ or logger
        self._process: Any | None = None
        self._ready_queue: Any | None = None
        self._restart_count = 0
        self._fallback_to_qpainter_called = False
        self._last_html_url = ""
        self._last_geometry: tuple[int, int, int, int] = (360, 600, 20, 80)
        self._last_click_through = False
        self._hwnd = 0

    @property
    def restart_count(self) -> int:
        return self._restart_count

    @property
    def fallback_to_qpainter_called(self) -> bool:
        return self._fallback_to_qpainter_called

    def is_alive(self) -> bool:
        proc = self._process
        return proc is not None and bool(getattr(proc, "is_alive", lambda: False)())

    def start(
        self,
        html_url: str,
        width: int = 360,
        height: int = 600,
        x: int = 20,
        y: int = 80,
        *,
        click_through: bool = False,
    ) -> bool:
        """Spawn child and wait for loaded signal. Returns False on failure."""
        checker = self._webview2_checker
        if checker is None:
            from app.webview2_runtime import is_webview2_runtime_available

            checker = is_webview2_runtime_available
        if not checker():
            self._logger.warning("panel start skipped: WebView2 runtime unavailable")
            return False

        self.stop()
        self._last_html_url = str(html_url)
        self._last_geometry = (int(width), int(height), int(x), int(y))
        self._last_click_through = bool(click_through)
        self._hwnd = 0

        try:
            self._launch_child_process(
                self._last_html_url,
                *self._last_geometry,
                click_through=self._last_click_through,
            )
        except Exception as exc:
            self._logger.warning("panel launch failed: %r", exc)
            return False

        if not self._wait_loaded():
            self._logger.warning(
                "panel start timeout, falling back to QPainter timeout_sec=%.1f",
                self._load_timeout_sec,
            )
            self.stop()
            self._note_start_failure()
            return False
        self._restart_count = 0
        self._fallback_to_qpainter_called = False
        return True

    def stop(self) -> None:
        proc = self._process
        self._process = None
        self._ready_queue = None
        self._hwnd = 0
        if proc is None:
            return
        try:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=_STOP_JOIN_SEC)
        except Exception as exc:
            self._logger.debug("panel terminate: %r", exc)
        try:
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=_KILL_JOIN_SEC)
        except Exception as exc:
            self._logger.debug("panel kill: %r", exc)

    def restart(self) -> bool:
        """Stop and start with last parameters; resets restart_count on success."""
        ok = self.start(
            self._last_html_url,
            *self._last_geometry,
            click_through=self._last_click_through,
        )
        if ok:
            self._restart_count = 0
            self._fallback_to_qpainter_called = False
        return ok

    def note_child_died(self) -> bool:
        """Called by host when child exits unexpectedly. Returns True if restarting."""
        if self._restart_count >= MAX_RESTARTS:
            self._fallback_to_qpainter_called = True
            self._logger.error(
                "panel restart limit reached, falling back to QPainter count=%s",
                self._restart_count,
            )
            return False
        self._restart_count += 1
        self._logger.info(
            "restarting panel (%s/%s)",
            self._restart_count,
            MAX_RESTARTS,
        )
        ok = self.start(
            self._last_html_url,
            *self._last_geometry,
            click_through=self._last_click_through,
        )
        if not ok and self._restart_count >= MAX_RESTARTS:
            self._fallback_to_qpainter_called = True
        return ok

    def _note_start_failure(self) -> None:
        self._restart_count += 1
        if self._restart_count >= MAX_RESTARTS:
            self._fallback_to_qpainter_called = True

    def _launch_child_process(
        self,
        html_url: str,
        width: int,
        height: int,
        x: int,
        y: int,
        *,
        click_through: bool,
    ) -> None:
        if self._process_factory is not None:
            ready_queue, process = self._process_factory(
                html_url,
                width,
                height,
                x,
                y,
                click_through,
            )
            self._ready_queue = ready_queue
            self._process = process
            if hasattr(process, "start"):
                process.start()
            return

        ctx = multiprocessing.get_context("spawn")
        self._ready_queue = ctx.Queue()
        self._process = ctx.Process(
            target=_webview_process_main,
            args=(html_url, self._ready_queue, width, height, x, y, click_through),
            name="DanmuFloatingPanel",
            daemon=True,
        )
        self._process.start()

    def _wait_loaded(self) -> bool:
        queue = self._ready_queue
        if queue is None:
            return False
        deadline = time.monotonic() + self._load_timeout_sec
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            try:
                signal = queue.get(timeout=min(0.5, remaining))
            except Exception:
                proc = self._process
                if proc is not None and not proc.is_alive():
                    return False
                continue
            text = str(signal)
            if text == _SIGNAL_LOADED:
                # drain optional hwnd signal
                try:
                    while True:
                        extra = queue.get_nowait()
                        if isinstance(extra, str) and extra.startswith("hwnd:"):
                            try:
                                self._hwnd = int(extra.split(":", 1)[1])
                            except ValueError:
                                pass
                except Exception:
                    pass
                return True
            if text.startswith("import-failed") or text.startswith("start-failed"):
                self._logger.warning("panel child error: %s", text)
                return False
            if text.startswith("hwnd:"):
                try:
                    self._hwnd = int(text.split(":", 1)[1])
                except ValueError:
                    pass
                continue
        return False
