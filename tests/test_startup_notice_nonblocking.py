"""BUG-018: startup notice must not block _start_web_console_stack / webview attach."""

from unittest.mock import MagicMock

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from tests.conftest import make_minimal_danmu_app
from tests.fakes import FakeLogger


def _mock_web_server() -> MagicMock:
    server = MagicMock()
    server.startup_ok = True
    server.base_url = "http://127.0.0.1:18765"
    server._startup_failure_user_notified = False
    return server


def test_startup_notice_deferred_during_web_console_stack(monkeypatch, qapp):
    del qapp
    app = make_minimal_danmu_app()
    notice = "未找到配置文件，已创建默认配置，请先检查 API Key 等基础设置。"
    config = MagicMock()
    config.get_startup_notice.return_value = notice
    object.__setattr__(app, "config", config)
    object.__setattr__(app, "logger", FakeLogger())
    object.__setattr__(app, "web_launch_mode", "webview")
    object.__setattr__(app, "config_changed", MagicMock())

    dialog_calls: list[tuple] = []
    scheduled: list[tuple] = []
    webview_scheduled: list[tuple] = []

    monkeypatch.setattr(
        "app.web_console.attach_web_console",
        lambda _app: _mock_web_server(),
    )
    monkeypatch.setattr(
        "app.font_registry.FontRegistry",
        lambda _cfg: MagicMock(load_all=lambda: 0),
    )
    monkeypatch.setattr(
        "app.ai_client_requests.visual_credentials_ready",
        lambda _cfg: True,
    )
    monkeypatch.setattr(
        "app.web_console.classify_web_console_startup",
        lambda _srv: "ok",
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: dialog_calls.append(args),
    )
    monkeypatch.setattr(
        QTimer,
        "singleShot",
        lambda ms, cb: scheduled.append((ms, cb)),
    )
    monkeypatch.setattr(
        app,
        "_schedule_webview_attach",
        lambda *args, **kw: webview_scheduled.append((args, kw)),
    )

    app._start_web_console_stack(lambda *args, **kw: None)

    assert dialog_calls == []
    assert len(webview_scheduled) == 1
    notice_callbacks = [cb for ms, cb in scheduled if ms == 0]
    assert len(notice_callbacks) == 1
    notice_callbacks[0]()
    assert len(dialog_calls) == 1
    assert dialog_calls[0][2] == notice


def test_startup_notice_deferred_in_browser_mode(monkeypatch, qapp):
    del qapp
    app = make_minimal_danmu_app()
    notice = "迁移提示"
    config = MagicMock()
    config.get_startup_notice.return_value = notice
    object.__setattr__(app, "config", config)
    object.__setattr__(app, "logger", FakeLogger())
    object.__setattr__(app, "web_launch_mode", "browser")
    object.__setattr__(app, "config_changed", MagicMock())

    dialog_calls: list[tuple] = []
    scheduled: list[tuple] = []
    browser_open_calls: list[tuple] = []

    monkeypatch.setattr(
        "app.web_console.attach_web_console",
        lambda _app: _mock_web_server(),
    )
    monkeypatch.setattr(
        "app.font_registry.FontRegistry",
        lambda _cfg: MagicMock(load_all=lambda: 0),
    )
    monkeypatch.setattr(
        "app.ai_client_requests.visual_credentials_ready",
        lambda _cfg: False,
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: dialog_calls.append(args),
    )
    monkeypatch.setattr(
        QTimer,
        "singleShot",
        lambda ms, cb: scheduled.append((ms, cb)),
    )
    monkeypatch.setattr(
        app,
        "_open_web_console_when_ready",
        lambda *args, **kw: browser_open_calls.append((args, kw)),
    )

    app._start_web_console_stack(lambda *args, **kw: None)

    assert dialog_calls == []
    assert browser_open_calls == []
    ms_values = [ms for ms, _cb in scheduled]
    assert 0 in ms_values
    assert 900 in ms_values
    notice_callbacks = [cb for ms, cb in scheduled if ms == 0]
    notice_callbacks[0]()
    assert len(dialog_calls) == 1
