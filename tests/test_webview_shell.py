"""Tests for pywebview shell helpers."""

import sys
from unittest.mock import MagicMock, patch

from app.webview_shell import (
    WebViewShell,
    preferred_webview_gui,
    wait_for_http_server,
)


def test_preferred_webview_gui_windows():
    with patch.object(sys, "platform", "win32"):
        assert preferred_webview_gui() == "edgechromium"


def test_wait_for_http_server_success():
    class FakeResp:
        status = 200

        def read(self):
            return b'{"token":"abc","base_url":"http://127.0.0.1:18765"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        assert wait_for_http_server("http://127.0.0.1:18765", timeout=1.0) is True


def test_wait_for_http_server_rejects_missing_token():
    class FakeResp:
        status = 200

        def read(self):
            return b'{"base_url":"http://127.0.0.1:18765"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        assert wait_for_http_server("http://127.0.0.1:18765", timeout=0.5) is False


def test_webview_shell_url_hash_path():
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    shell = WebViewShell(server)
    assert shell._url("/#settings") == "http://127.0.0.1:18765/#settings"
    assert shell._url("#settings") == "http://127.0.0.1:18765/#settings"


def test_webview_shell_open_delegates_to_start_when_not_running(monkeypatch):
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.bridge.danmu_app.logger = MagicMock()
    shell = WebViewShell(server)
    shell._started = False
    shell._thread = None

    called = []

    def fake_start(path):
        called.append(path)
        return False

    monkeypatch.setattr(shell, "start", fake_start)

    shell.open("/#settings")
    assert called == ["/#settings"]
