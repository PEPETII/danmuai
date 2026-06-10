"""Main flow tests: capture, backoff, and web launch."""

from unittest.mock import MagicMock, Mock

from app.reply_queue import QueuedReply
from app.runnable import AiRunnable
from main import compress_screenshot

from tests.conftest import make_minimal_danmu_app, start_app_timers
from tests.fakes import FakeCapturer, FakeConfig, FakePixmap


def test_normal_mode_start_uses_configured_capture_interval():
    app = make_minimal_danmu_app()
    app.config = FakeConfig(
        {
            "danmu_display_mode": "normal",
            "normal_recognition_interval_sec": "7",
            "api_key": "test-key",
        }
    )
    app._sync_reply_batch_config()
    start_app_timers(app)
    assert app.screenshot_timer._interval == 7000
    assert app.screenshot_timer.active


def test_normal_tick_skips_while_in_flight():
    app = make_minimal_danmu_app()
    app.config = FakeConfig({"danmu_display_mode": "normal"})
    app.engine.running = True
    grab_count = 0

    def grab():
        nonlocal grab_count
        grab_count += 1
        return FakePixmap(0)

    app.capturer = FakeCapturer(FakePixmap(0))
    app.capturer.grab = grab
    app.ai_in_flight = 1
    app._on_normal_capture_tick()
    assert grab_count == 0


def test_compress_screenshot_failure_path():
    """测试截图压缩失败时 in-flight 计数正确释放"""
    # 模拟一个会导致压缩失败的 pixmap
    mock_pixmap = Mock()
    mock_pixmap.toImage.side_effect = RuntimeError("has been deleted")

    # 创建 mock worker
    import threading

    mock_worker = Mock()
    mock_worker._stopping = threading.Event()

    # 创建 runnable 并执行
    runnable = AiRunnable(
        worker=mock_worker,
        pixmap=mock_pixmap,
        system_pt="system",
        user_pt="user",
        persona_id="test-persona",
        request_round=1,
        screenshot_id=1,
        captured_at=1.0,
        scene_generation=0,
        compress_fn=compress_screenshot
    )

    # 执行 run 方法（会捕获异常并发射错误信号）
    runnable.run()

    # 验证错误信号被发射
    mock_worker._emit_safe.assert_called_once()
    call_args = mock_worker._emit_safe.call_args
    assert call_args[0][0] == "error"
    assert "压缩失败" in call_args[0][1]










def test_capture_does_not_advance_scene_generation(monkeypatch):
    """普通模式截图不探测场景跳变，代际保持不变"""
    app = make_minimal_danmu_app()
    app.engine.running = True
    app.reply_buffer.push(QueuedReply("p", 0, 0, "old", scene_generation=0))
    app.capturer = FakeCapturer(FakePixmap(0b1))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app.reply_buffer.size() == 1
    assert app._latest_screenshot is not None


def test_capture_while_in_flight_still_updates_frame(monkeypatch):
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._latest_screenshot_id = 3
    app.ai_in_flight = 1
    app.capturer = FakeCapturer(FakePixmap((1 << 16) - 1))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app._latest_screenshot_id == 4
    assert app._latest_screenshot is not None


def test_repeated_capture_keeps_scene_generation(monkeypatch):
    app = make_minimal_danmu_app()
    app.engine.running = True
    app.capturer = FakeCapturer(FakePixmap(0b1))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app._latest_screenshot is not None


def test_invalid_pixmap_does_not_increment_screenshot_id():
    """无效 pixmap 不应递增 screenshot_id 或缓存帧"""
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._latest_screenshot_id = 5
    app.capturer = FakeCapturer(FakePixmap(0, is_null=True))

    app._capture_screenshot()

    assert app._latest_screenshot_id == 5
    assert app._latest_screenshot is None
    assert any("invalid_pixmap" in msg for msg in app.logger.warning_messages)


def test_repeated_capture_failure_sets_web_error_status():
    """S-009: third consecutive capture failure surfaces Web status bar error."""
    app = make_minimal_danmu_app()
    app.engine.running = True
    app.capturer = FakeCapturer(None)
    errors: list[tuple[str, bool]] = []
    app._set_error_status_safe = lambda msg, is_error: errors.append((msg, is_error))

    for _ in range(3):
        app._capture_screenshot()

    assert app._capture_fail_streak == 3
    assert errors
    assert errors[-1][1] is True


def test_capture_success_clears_capture_error_status():
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._capture_fail_streak = 3
    app._capture_error_active = True
    errors: list[tuple[str, bool]] = []
    app._set_error_status_safe = lambda msg, is_error: errors.append((msg, is_error))
    app.capturer = FakeCapturer(FakePixmap(0b1))

    app._capture_screenshot()

    assert app._capture_fail_streak == 0
    assert app._capture_error_active is False
    assert ("", False) in errors


def test_capture_failure_reschedules_next_screenshot():
    """测试截图失败不会让主循环卡死（普通模式由 screenshot_timer 驱动）"""
    app = make_minimal_danmu_app()
    app.engine.running = True

    app._capture_screenshot()

    assert app._latest_screenshot is None

def test_open_web_console_when_ready_skips_attach_on_terminal_failure(monkeypatch):

    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    object.__setattr__(app, "webview_shell", None)
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._bind_failed.set()
    object.__setattr__(app, "web_server", server)

    attach_calls = []
    notified = []
    monkeypatch.setattr(
        "app.webview_shell.attach_webview_shell",
        lambda *args, **kwargs: attach_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure",
        lambda danmu, key, **kw: notified.append(key),
    )
    monkeypatch.setattr(
        "app.webview_shell.wait_for_http_server",
        lambda url, timeout: False,
    )

    app._open_web_console_when_ready("/")
    assert attach_calls == []
    assert notified == ["web_console.startup_failed"]
    assert server._startup_failure_user_notified is True

    app._open_web_console_when_ready("/")
    assert notified == ["web_console.startup_failed"]


def _patch_fallback_message_box(monkeypatch, *, click_yes: bool, click_count: list | None = None):
    """Patch QMessageBox for tray fallback tests; return the fake_box for assertions."""
    yes_btn = MagicMock(name="yes_btn")
    no_btn = MagicMock(name="no_btn")
    fake_box = MagicMock()
    fake_box.addButton.side_effect = [yes_btn, no_btn]
    fake_box.clickedButton.return_value = yes_btn if click_yes else no_btn
    fake_box.exec.side_effect = (
        lambda: click_count.append(True) if click_count is not None else None
    )
    mock_cls = MagicMock(return_value=fake_box)
    mock_cls.Icon = MagicMock()
    mock_cls.Icon.Warning = 0
    mock_cls.ButtonRole = MagicMock()
    mock_cls.ButtonRole.YesRole = 0
    mock_cls.ButtonRole.NoRole = 1
    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox", mock_cls)
    return fake_box


def test_open_web_console_after_handshake_failed_prompts_browser_fallback(monkeypatch):
    """W-OPEN-CONSOLE-FALLBACK-001: tray click after handshake failure prompts user."""

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server._browser_launch_opened = False
    object.__setattr__(app, "web_server", server)

    shell = MagicMock()
    shell.is_running.return_value = False
    shell.is_handshake_pending.return_value = False
    shell.handshake_failed = True
    object.__setattr__(app, "webview_shell", shell)

    fake_box = _patch_fallback_message_box(monkeypatch, click_yes=True)
    browser_calls = []
    attach_calls = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )
    monkeypatch.setattr(
        "app.webview_shell.attach_webview_shell",
        lambda *args, **kwargs: attach_calls.append(1),
    )

    app._open_web_console("/#settings")
    assert fake_box.exec.call_count == 1
    assert browser_calls == ["/#settings"]
    assert server._browser_launch_opened is True
    assert attach_calls == []


def test_open_web_console_after_handshake_failed_no_prompt_when_browser_already_opened(
    monkeypatch,
):
    """W-OPEN-CONSOLE-FALLBACK-001: dedupe — skip prompt when already fallback once."""

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server._browser_launch_opened = True
    object.__setattr__(app, "web_server", server)

    shell = MagicMock()
    shell.is_running.return_value = False
    shell.is_handshake_pending.return_value = False
    shell.handshake_failed = True
    object.__setattr__(app, "webview_shell", shell)

    fake_box = _patch_fallback_message_box(monkeypatch, click_yes=True)
    browser_calls = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )

    app._open_web_console("/#settings")
    assert fake_box.exec.call_count == 0
    assert browser_calls == []


def test_open_web_console_after_handshake_failed_user_declines(monkeypatch):
    """W-OPEN-CONSOLE-FALLBACK-001: user picks No — no browser open, dedupe stays off."""

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server._browser_launch_opened = False
    object.__setattr__(app, "web_server", server)

    shell = MagicMock()
    shell.is_running.return_value = False
    shell.is_handshake_pending.return_value = False
    shell.handshake_failed = True
    object.__setattr__(app, "webview_shell", shell)

    fake_box = _patch_fallback_message_box(monkeypatch, click_yes=False)
    browser_calls = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )

    app._open_web_console("/#settings")
    assert fake_box.exec.call_count == 1
    assert browser_calls == []
    assert server._browser_launch_opened is False

