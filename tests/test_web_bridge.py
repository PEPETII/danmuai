"""Web console tests: bridge."""

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.application.web_runtime_state import WebRuntimeState
from app.web_console import (
    _SAVE_DONE_EVENT_KEY,
    _SAVE_RESULT_KEY,
    MainThreadInvokeTimeout,
    WebConsoleBridge,
    _write_config_save_result,
    save_config_via_bridge,
)
from main import DanmuApp

from tests.fakes import FakeTimer
from tests.web_console_helpers import make_status_app, pump_qt_until


def test_bridge_save_config_uses_public_app_entry():
    app = make_status_app()
    bridge = WebConsoleBridge(app)

    bridge._on_save_config({"api_endpoint": "https://new.example/v1"})

    app.apply_web_config_payload.assert_called_once_with({"api_endpoint": "https://new.example/v1"})
    assert app.build_status_snapshot.call_count >= 1


def test_save_config_via_bridge_returns_success_after_main_thread_ack():
    app = make_status_app()
    bridge = WebConsoleBridge(app)

    result = save_config_via_bridge(bridge, {"api_endpoint": "https://new.example/v1"})

    assert result == {"ok": True}
    app.apply_web_config_payload.assert_called_once_with(
        {"api_endpoint": "https://new.example/v1"}
    )


def test_save_config_via_bridge_returns_success_under_main_thread_load():
    import threading

    logger = MagicMock()

    def _emit(payload):
        def _ack():
            time.sleep(0.02)
            _write_config_save_result(payload[_SAVE_RESULT_KEY], ok=True)
            payload[_SAVE_DONE_EVENT_KEY].set()

        threading.Thread(target=_ack, daemon=True).start()

    bridge = SimpleNamespace(
        save_config_requested=SimpleNamespace(emit=_emit),
        danmu_app=SimpleNamespace(logger=logger),
    )

    result = save_config_via_bridge(
        bridge,
        {"api_endpoint": "https://loaded.example/v1"},
        timeout_sec=0.2,
    )

    assert result == {"ok": True}
    logger.error.assert_not_called()


def test_save_config_via_bridge_returns_timeout_when_main_thread_does_not_ack():
    bridge = SimpleNamespace(
        save_config_requested=SimpleNamespace(emit=lambda _payload: None),
        danmu_app=SimpleNamespace(logger=MagicMock()),
    )

    result = save_config_via_bridge(
        bridge,
        {"api_endpoint": "https://slow.example/v1"},
        timeout_sec=0.01,
    )

    assert result["ok"] is False
    assert result["error"] == "save_timeout"
    assert "超时" in result["detail"]
    bridge.danmu_app.logger.error.assert_called_once()


def test_save_config_via_bridge_returns_failure_when_main_thread_save_raises():
    app = make_status_app()
    app.apply_web_config_payload.side_effect = RuntimeError("db broken")
    bridge = WebConsoleBridge(app)

    result = save_config_via_bridge(bridge, {"api_endpoint": "https://broken.example/v1"})

    assert result["ok"] is False
    assert result["error"] == "save_failed"
    assert "db broken" in result["detail"]
    app.apply_web_config_payload.assert_called_once_with(
        {"api_endpoint": "https://broken.example/v1"}
    )


def test_save_config_via_bridge_returns_truncated_detail_on_error():
    app = make_status_app()
    secret = "sk-abc1234567890abcdef1234567890abcdef"
    app.apply_web_config_payload.side_effect = RuntimeError(
        "db broken "
        + secret
        + " "
        + ("x" * 400)
    )
    bridge = WebConsoleBridge(app)

    result = save_config_via_bridge(bridge, {"api_endpoint": "https://broken.example/v1"})

    assert result["ok"] is False
    assert result["error"] == "save_failed"
    assert secret not in result["detail"]
    assert "sk-****" in result["detail"]
    assert result["detail"].endswith("…")
    assert len(result["detail"]) <= 201
    app.set_web_error_status.assert_called_once()
    assert secret not in app.set_web_error_status.call_args.args[0]


def test_web_status_timer_lifecycle_public_api():
    first = MagicMock()
    second = MagicMock()
    app = SimpleNamespace()

    attached = DanmuApp.attach_web_status_timer(app, first)
    DanmuApp.attach_web_status_timer(app, second)
    DanmuApp.stop_web_status_timer(app)
    detached = DanmuApp.detach_web_status_timer(app)

    assert attached is first
    first.stop.assert_called_once_with()
    second.stop.assert_called_once_with()
    assert detached is second
    assert getattr(app, "_web_status_timer", None) is None


def test_resolve_request_credentials_public_wrapper():
    app = SimpleNamespace(ai_worker=MagicMock())
    app.ai_worker.resolve_request_credentials.return_value = ("https://x", "sk", "model", "doubao")

    resolved = DanmuApp.resolve_request_credentials(app)

    assert resolved == ("https://x", "sk", "model", "doubao")
    app.ai_worker.resolve_request_credentials.assert_called_once_with()


























def test_invoke_on_main_runs_on_bridge_thread():
    from app.web_console import WebConsoleBridge
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication

    qt_app = QApplication.instance() or QApplication([])
    bridge = WebConsoleBridge(MagicMock())
    observed: dict[str, object] = {}

    class InvokeWorker(QThread):
        def run(self) -> None:
            def capture() -> int:
                observed["thread"] = QThread.currentThread()
                return 42

            observed["result"] = bridge.invoke_on_main(capture)

    worker = InvokeWorker()
    worker.start()
    while worker.isRunning():
        qt_app.processEvents()
        worker.wait(50)
    assert observed["result"] == 42
    assert observed["thread"] is bridge.thread()


def test_invoke_on_main_fast_path_on_bridge_thread():
    from app.web_console import WebConsoleBridge
    from PyQt6.QtWidgets import QApplication

    _ = QApplication.instance() or QApplication([])
    bridge = WebConsoleBridge(MagicMock())
    assert bridge.invoke_on_main(lambda: 7) == 7


def test_invoke_on_main_raises_timeout_when_main_thread_slow():
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication

    qt_app = QApplication.instance() or QApplication([])
    bridge = WebConsoleBridge(MagicMock())
    observed: dict[str, object] = {}

    class InvokeWorker(QThread):
        def run(self) -> None:
            def slow_on_main() -> None:
                time.sleep(0.15)

            try:
                bridge.invoke_on_main(slow_on_main, timeout_sec=0.05)
            except MainThreadInvokeTimeout as exc:
                observed["exc"] = exc

    t0 = time.perf_counter()
    worker = InvokeWorker()
    worker.start()
    pump_qt_until(qt_app, invoke_worker=worker)
    elapsed = time.perf_counter() - t0

    assert isinstance(observed.get("exc"), MainThreadInvokeTimeout)
    assert observed["exc"].timeout_sec == pytest.approx(0.05)
    assert elapsed < 1.0


def test_invoke_on_main_timeout_increments_counter():
    """超时分支应自增 _invoke_timeout_count（W-INVOKE-OBSERV-001）。"""
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication

    qt_app = QApplication.instance() or QApplication([])
    bridge = WebConsoleBridge(MagicMock())
    assert bridge.invoke_timeout_count() == 0
    observed: dict[str, object] = {}

    class InvokeWorker(QThread):
        def run(self) -> None:
            def slow_on_main() -> None:
                time.sleep(0.15)

            try:
                bridge.invoke_on_main(slow_on_main, timeout_sec=0.05)
            except MainThreadInvokeTimeout:
                observed["timed_out"] = True

    worker = InvokeWorker()
    worker.start()
    pump_qt_until(qt_app, invoke_worker=worker)

    assert observed.get("timed_out") is True
    assert bridge.invoke_timeout_count() == 1


def test_invoke_on_main_timeout_under_main_thread_load():
    """BUG-072: sync invoke vs save_config on the same Qt thread must not deadlock."""
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication

    qt_app = QApplication.instance() or QApplication([])
    app = make_status_app()
    bridge = WebConsoleBridge(app)
    observed: dict[str, object] = {}
    save_holder: dict[str, object] = {}

    class InvokeWorker(QThread):
        def run(self) -> None:
            def slow_on_main() -> str:
                time.sleep(0.15)
                return "invoke_done"

            observed["result"] = bridge.invoke_on_main(slow_on_main)

    def run_save() -> None:
        save_holder["result"] = save_config_via_bridge(
            bridge,
            {"api_endpoint": "https://contention.example/v1"},
            timeout_sec=2.0,
        )

    t0 = time.perf_counter()
    invoke_worker = InvokeWorker()
    invoke_worker.start()
    save_thread = threading.Thread(target=run_save, daemon=True)
    save_thread.start()
    pump_qt_until(qt_app, invoke_worker=invoke_worker, extra_thread=save_thread)
    elapsed = time.perf_counter() - t0

    assert observed["result"] == "invoke_done"
    assert save_holder["result"] == {"ok": True}
    assert elapsed < 1.5
    app.apply_web_config_payload.assert_called_with(
        {"api_endpoint": "https://contention.example/v1"}
    )


def test_save_config_times_out_when_invoke_blocks_beyond_save_timeout():
    """BUG-072 / P0: save waits on main thread while invoke_on_main holds it past save timeout."""
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication

    qt_app = QApplication.instance() or QApplication([])
    app = make_status_app()
    bridge = WebConsoleBridge(app)
    save_holder: dict[str, object] = {}
    invoke_holding_main = threading.Event()

    class InvokeWorker(QThread):
        def run(self) -> None:
            def slow_on_main() -> None:
                invoke_holding_main.set()
                time.sleep(0.12)

            bridge.invoke_on_main(slow_on_main)

    def run_save() -> None:
        if not invoke_holding_main.wait(timeout=2.0):
            pytest.fail("invoke_on_main did not block main thread before save")
        # Snapshot return value: _on_save_config may later mutate the shared result dict.
        save_holder["result"] = dict(
            save_config_via_bridge(
                bridge,
                {"api_endpoint": "https://timeout.example/v1"},
                timeout_sec=0.05,
            )
        )

    invoke_worker = InvokeWorker()
    save_thread = threading.Thread(target=run_save, daemon=True)
    invoke_worker.start()
    save_thread.start()
    pump_qt_until(qt_app, invoke_worker=invoke_worker, extra_thread=save_thread)

    result = save_holder["result"]
    assert result["ok"] is False
    assert result["error"] == "save_timeout"
    assert "超时" in result["detail"]

def test_attach_status_timer_clears_error_when_server_becomes_ready():
    """attach_web_console status tick: slow → ready clears transient attach error."""
    import threading

    from app.web_console import (
        WebConsoleBridge,
        WebConsoleServer,
        classify_web_console_startup,
        clear_startup_attach_error_if_needed,
    )

    danmu_app = MagicMock()
    danmu_app.web_runtime_state = WebRuntimeState()
    danmu_app.set_web_error_status = lambda msg, *, is_error: danmu_app.web_runtime_state.set_error_status(
        msg, is_error=is_error
    )
    bridge = WebConsoleBridge(danmu_app)
    server = WebConsoleServer(bridge)
    server._thread = threading.Thread(target=time.sleep, args=(5.0,), daemon=True)
    server._thread.start()
    server._startup_error_from_attach = True
    danmu_app.web_runtime_state.set_error_status("未就绪", is_error=True)

    try:
        assert classify_web_console_startup(server) == "slow"

        server.startup_ok = True
        server._ready.set()
        if classify_web_console_startup(server) == "ready":
            clear_startup_attach_error_if_needed(server)

        assert classify_web_console_startup(server) == "ready"
        assert danmu_app.web_runtime_state.is_error is False
        assert server._startup_error_from_attach is False
    finally:
        server._bind_failed.set()
        server._thread.join(timeout=1.0)


def test_quit_stops_web_status_timer_before_server_shutdown(monkeypatch):
    order = []
    pool_results = {
        "capture": True,
        "ai": True,
        "meme_ai": True,
        "meme_fetch": True,
        "global": True,
    }
    wait_mock = MagicMock(
        side_effect=lambda timeout_ms: order.append(f"pool_wait:{timeout_ms}") or pool_results
    )
    monkeypatch.setattr("app.worker_pools.wait_all_worker_pools_done", wait_mock)
    quit_mock = MagicMock()
    monkeypatch.setattr("main.QApplication.quit", quit_mock)

    app = SimpleNamespace(
        logger=MagicMock(),
        stop=MagicMock(),
        _mic_service=MagicMock(),
        hotkey=MagicMock(),
        tray=MagicMock(),
        ai_worker=MagicMock(),
        history_writer=MagicMock(),
        config=MagicMock(),
        overlay=MagicMock(),
        webview_shell=None,
        web_server=MagicMock(
            wait_shutdown_complete=MagicMock(return_value=True),
            _thread=None,
        ),
        stop_web_status_timer=MagicMock(),
        _pool_topup_timer=FakeTimer(),
    )
    app.ai_worker.close.side_effect = lambda: order.append("close")
    app.history_writer.stop.side_effect = lambda: order.append("history_stop")
    app.config.close.side_effect = lambda: order.append("config_close")
    app.close_meme_barrage_client = lambda: order.append("close_meme_client")

    DanmuApp.quit(app)

    app.stop.assert_called_once_with()
    app.stop_web_status_timer.assert_called_once_with()
    app.web_server.stop.assert_called_once_with()
    app.web_server.wait_shutdown_complete.assert_called_once_with()
    wait_mock.assert_called_once_with(2000)
    assert order == [
        "pool_wait:2000",
        "close_meme_client",
        "history_stop",
        "close",
        "config_close",
    ]
    quit_mock.assert_called_once_with()


def test_quit_logs_warning_when_thread_pool_does_not_finish(monkeypatch):
    wait_mock = MagicMock(
        return_value={
            "capture": True,
            "ai": True,
            "meme_ai": True,
            "meme_fetch": True,
            "global": False,
        }
    )
    monkeypatch.setattr("app.worker_pools.wait_all_worker_pools_done", wait_mock)

    fake_pool = MagicMock()
    fake_pool.activeThreadCount.return_value = 1
    fake_pool.maxThreadCount.return_value = 4
    monkeypatch.setattr("app.worker_pools.worker_pool_for_label", lambda _label: fake_pool)
    monkeypatch.setattr("main.QApplication.quit", MagicMock())

    app = SimpleNamespace(
        logger=MagicMock(),
        stop=MagicMock(),
        _mic_service=MagicMock(),
        hotkey=MagicMock(),
        tray=MagicMock(),
        ai_worker=MagicMock(),
        history_writer=MagicMock(),
        config=MagicMock(),
        overlay=MagicMock(),
        webview_shell=None,
        web_server=MagicMock(
            wait_shutdown_complete=MagicMock(return_value=True),
            _thread=None,
        ),
        stop_web_status_timer=MagicMock(),
        _pool_topup_timer=FakeTimer(),
    )

    DanmuApp.quit(app)

    wait_mock.assert_called_once_with(2000)
    # global pool timeout — at least one warning
    assert app.logger.warning.call_count >= 1
    args = app.logger.warning.call_args[0]
    assert args[0].startswith("quit timed out waiting for AI worker thread pool")


def test_quit_warns_when_web_console_shutdown_does_not_finish(monkeypatch):
    import PyQt6.QtCore as qtcore

    fake_pool = MagicMock()
    fake_pool.waitForDone.return_value = True

    class _FakeQThreadPool:
        @staticmethod
        def globalInstance():
            return fake_pool

    monkeypatch.setattr(qtcore, "QThreadPool", _FakeQThreadPool)
    # W-TEARDOWN-RES-001：quit() 现在分别 waitForDone capture/ai/meme 三个独立池
    monkeypatch.setattr("app.worker_pools.capture_worker_pool", lambda: fake_pool)
    monkeypatch.setattr("app.worker_pools.ai_worker_pool", lambda: fake_pool)
    monkeypatch.setattr("app.worker_pools.meme_ai_pool", lambda: fake_pool)
    monkeypatch.setattr("app.worker_pools.meme_fetch_pool", lambda: fake_pool)
    monkeypatch.setattr("main.QApplication.quit", MagicMock())

    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = True
    shutdown_requested = threading.Event()
    shutdown_complete = threading.Event()
    shutdown_requested.set()

    web_server = MagicMock(
        wait_shutdown_complete=MagicMock(return_value=False),
        _thread=fake_thread,
        startup_ok=False,
    )
    web_server._bind_failed = threading.Event()
    web_server._shutdown_requested = shutdown_requested
    web_server._shutdown_complete = shutdown_complete

    app = SimpleNamespace(
        logger=MagicMock(),
        stop=MagicMock(),
        _mic_service=MagicMock(),
        hotkey=MagicMock(),
        tray=MagicMock(),
        ai_worker=MagicMock(),
        history_writer=MagicMock(),
        config=MagicMock(),
        overlay=MagicMock(),
        webview_shell=None,
        web_server=web_server,
        stop_web_status_timer=MagicMock(),
        _pool_topup_timer=FakeTimer(),
    )

    DanmuApp.quit(app)

    fake_thread.join.assert_called_once_with(timeout=0.5)
    warning_calls = app.logger.warning.call_args_list
    assert any(
        call.args[0].startswith("quit timed out waiting for Web console shutdown")
        for call in warning_calls
    )


