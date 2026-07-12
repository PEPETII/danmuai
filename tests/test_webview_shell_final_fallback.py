from __future__ import annotations

from unittest.mock import MagicMock

from app.webview_shell import WebViewShell


def test_deferred_handshake_failure_finalizes_browser_fallback_once(monkeypatch):
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server._browser_launch_opened = False
    server.bridge.danmu_app.logger = MagicMock()
    shell = WebViewShell(server)
    shell._defer_browser_fallback = True

    browser_calls: list[str] = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda _server, path: browser_calls.append(path),
    )
    monkeypatch.setattr(shell, "_terminate", lambda: None)
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _message: None)

    assert shell._abort_handshake("retry later", "/", fallback_browser=False) is False
    assert shell.handshake_failed is True
    assert browser_calls == []

    assert shell.finalize_handshake_failure("retries exhausted", "/") is False
    assert browser_calls == ["/"]
    assert server._browser_launch_opened is True

    assert shell.finalize_handshake_failure("duplicate finalize", "/") is False
    assert browser_calls == ["/"]


def test_fail_start_remains_idempotent_before_browser_fallback(monkeypatch):
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server._browser_launch_opened = False
    server.bridge.danmu_app.logger = MagicMock()
    shell = WebViewShell(server)
    shell._handshake_failed = True

    browser_calls: list[str] = []
    monkeypatch.setattr(
        "app.webview_shell._fallback_to_system_browser",
        lambda _server, path, _reason: browser_calls.append(path),
    )
    monkeypatch.setattr(shell, "_terminate", lambda: None)
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _message: None)

    assert shell._fail_start("duplicate ordinary failure", "/") is False
    assert browser_calls == []
    assert server._browser_launch_opened is False
