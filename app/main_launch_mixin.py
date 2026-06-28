"""DanmuApp 启动与控制台 attach Mixin（W-REFACTOR-MAIN-001）。

职责边界：
- Web 控制台打开/导航（_open_web_console、_open_web_console_when_ready）
- pywebview attach 重试与调度（_retry_webview_attach、_schedule_webview_attach）

与 DanmuApp 关系：通过 self 访问 webview_shell、web_server、web_launch_mode 等字段。
DanmuApp 通过多继承获得这些方法。

代码归属判断：Web 控制台/pywebview 的启动、attach、导航逻辑放这里。
"""

from __future__ import annotations


class DanmuAppLaunchMixin:
    """启动 Mixin：DanmuApp 通过多继承获得这些方法。

    通过 self 访问 DanmuApp 的 webview_shell、web_server、web_launch_mode 等字段。
    """

    def _open_web_console_when_ready(
        self,
        path: str = "/",
        *,
        use_browser: bool = False,
        attempt: int = 0,
        on_webview_handshake_failed=None,
    ) -> None:
        from app.webview_shell import open_web_console_when_ready

        open_web_console_when_ready(
            self,
            path,
            use_browser=use_browser,
            attempt=attempt,
            on_webview_handshake_failed=on_webview_handshake_failed,
        )

    def _retry_webview_attach(self, path: str, schedule_attempt: int) -> None:
        from app.webview_shell import retry_webview_attach

        retry_webview_attach(self, path, schedule_attempt)

    def _schedule_webview_attach(self, initial_path: str, *, attempt: int = 0) -> None:
        from app.webview_shell import schedule_webview_attach

        schedule_webview_attach(self, initial_path, attempt=attempt)

    def _open_web_console(self, path: str = "/") -> None:
        shell = getattr(self, "webview_shell", None)
        server = getattr(self, "web_server", None)
        if shell and shell.is_running():
            shell.open(path)
            return
        if shell and shell.is_handshake_pending():
            shell.request_navigate(path)
            return
        if shell and shell.handshake_failed and server:
            self._open_browser_fallback_after_webview_failure(server, path)
            return
        if server:
            from app.web_console import (
                classify_web_console_startup,
                open_web_console_browser,
                try_recover_web_console_for_user_action,
            )
            from app.webview_shell import notify_web_console_failure

            if classify_web_console_startup(server) == "failed":
                if try_recover_web_console_for_user_action(server):
                    pass
                else:
                    if not getattr(server, "_browser_launch_opened", False):
                        open_web_console_browser(server, path)
                        server._browser_launch_opened = True
                    if not getattr(server, "_startup_failure_user_notified", False):
                        notify_web_console_failure(self, "web_console.startup_failed")
                        server._startup_failure_user_notified = True
                    return
        if self.web_launch_mode == "webview" and self.web_server:
            self._open_web_console_when_ready(path, use_browser=False)
            return
        if self.web_launch_mode == "browser" and self.web_server:
            self._open_web_console_when_ready(path, use_browser=True)

    def _open_browser_fallback_after_webview_failure(
        self, server, path: str = "/"
    ) -> None:
        """Handshake 已失败时用户主动打开：自动改用系统浏览器（BUG-014 dedupe）。"""
        if getattr(server, "_browser_launch_opened", False):
            return
        from app.web_console import open_web_console_browser

        try:
            open_web_console_browser(server, path)
        except Exception as exc:
            self.logger.warning(
                f"failed to open system browser after webview fallback: {exc!r}"
            )
            return
        server._browser_launch_opened = True
        self.logger.info(
            f"tray fallback to system browser after webview handshake failed: {path}"
        )

    def restore_main_window(self) -> None:
        shell = getattr(self, "webview_shell", None)
        if shell is not None:
            shell.restore_window()

    def show_settings(self) -> None:
        self.restore_main_window()
        if self.web_server:
            self._open_web_console("/#settings")
