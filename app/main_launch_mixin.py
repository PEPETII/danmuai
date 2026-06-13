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
            self._prompt_browser_fallback_after_webview_failure(server, path)
            return

        # BUG-XXX: 服务器线程已终止时尝试恢复或兜底打开浏览器
        if server:
            from app.web_console import classify_web_console_startup, open_web_console_browser

            phase = classify_web_console_startup(server)
            if phase == "failed":
                self.logger.warning(
                    "Web 控制台进程不可用（phase=failed），尝试重启或打开系统浏览器"
                )
                # 尝试重启一次
                server._startup_failure_user_notified = False
                server.start()
                from app.webview_shell import wait_for_http_server

                if wait_for_http_server(server.base_url, timeout=3.0):
                    server.startup_ok = True
                    self.web_server = server
                    self.logger.info("Web 控制台重启成功")
                else:
                    self.logger.warning(
                        "Web 控制台重启失败，已打开系统浏览器作为兜底"
                    )
                    open_web_console_browser(server, path)
                    return

        if self.web_launch_mode == "webview" and self.web_server:
            self._open_web_console_when_ready(path, use_browser=False)
            return
        if self.web_launch_mode == "browser" and self.web_server:
            self._open_web_console_when_ready(path, use_browser=True)

    def _prompt_browser_fallback_after_webview_failure(
        self, server, path: str = "/"
    ) -> None:
        """Handshake 已失败的兜底：弹窗询问用户是否在系统浏览器打开控制台。

        启动期已 fallback 过一次（``server._browser_launch_opened=True``）时不再弹窗，
        保留 BUG-014 dedupe。仅 web_launch_mode 与 web_server 状态由调用方判断。
        """
        if getattr(server, "_browser_launch_opened", False):
            return
        from PyQt6.QtWidgets import QMessageBox

        from app.translations import tr
        from app.web_console import open_web_console_browser

        base_url = getattr(server, "base_url", "http://127.0.0.1:18765")
        title = tr("webview.fallback_to_browser_title", "桌面窗口不可用")
        message = tr(
            "webview.fallback_to_browser_message",
            "pywebview 启动失败，是否在系统浏览器中打开本地网页端？\n地址：{base_url}",
        ).format(base_url=base_url)

        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(message)
        yes_btn = box.addButton(tr("common.yes"), QMessageBox.ButtonRole.YesRole)
        no_btn = box.addButton(tr("common.no"), QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(no_btn)
        box.exec()

        if box.clickedButton() == yes_btn:
            server._browser_launch_opened = True
            try:
                open_web_console_browser(server, path)
            except Exception as exc:
                self.logger.warning(
                    f"failed to open system browser after webview fallback: {exc!r}"
                )
                server._browser_launch_opened = False
                return
            self.logger.info(
                f"tray fallback to system browser after webview handshake failed: {path}"
            )
        else:
            self.logger.info(
                "tray fallback to system browser declined by user after webview handshake failed"
            )

    def show_settings(self) -> None:
        if self.web_server:
            self._open_web_console("/#settings")
