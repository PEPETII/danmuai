import threading
import time
from unittest.mock import Mock

from PyQt6.QtCore import QObject, pyqtSlot

from app.runnable import CaptureCoordinator, CaptureRunnable
from tests.conftest import make_minimal_danmu_app
from tests.fakes import FakeCapturer, FakePixmap


class _SignalRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def emit(self, *args: object) -> None:
        self.calls.append(args)


class _CaptureCoordinatorStub:
    def __init__(self) -> None:
        self.completed = _SignalRecorder()
        self.failed = _SignalRecorder()


def _raise_capture_error(_plan: object) -> None:
    raise RuntimeError("capture boom")


class _FailureReceiver(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []
        self.thread_ids: list[int] = []

    @pyqtSlot(str)
    def on_failed(self, message: str) -> None:
        self.messages.append(message)
        self.thread_ids.append(threading.get_ident())


def test_capture_runnable_exception_emits_failed_without_completed(monkeypatch):
    coordinator = _CaptureCoordinatorStub()
    monkeypatch.setattr("app.runnable.execute_capture", _raise_capture_error)

    runnable = CaptureRunnable(object(), coordinator, threading.Event())
    runnable.run()

    assert coordinator.completed.calls == []
    assert coordinator.failed.calls == [("RuntimeError: capture boom",)]


def test_capture_failure_signal_is_delivered_on_main_thread(qapp, monkeypatch):
    coordinator = CaptureCoordinator()
    receiver = _FailureReceiver()
    coordinator.failed.connect(receiver.on_failed)
    monkeypatch.setattr("app.runnable.execute_capture", _raise_capture_error)
    main_thread_id = threading.get_ident()
    runnable = CaptureRunnable(object(), coordinator, threading.Event())

    worker = threading.Thread(target=runnable.run)
    worker.start()
    worker.join(timeout=2.0)
    assert not worker.is_alive()

    deadline = time.monotonic() + 1.0
    while not receiver.messages and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert receiver.messages == ["RuntimeError: capture boom"]
    assert receiver.thread_ids == [main_thread_id]


def test_capture_failed_releases_slot_and_allows_next_schedule(monkeypatch):
    from main import DanmuApp

    app = make_minimal_danmu_app()
    app.engine.running = True
    app._capture_in_flight = True
    app._note_capture_failure = Mock()
    app._trigger_api_call = Mock()
    app._on_capture_failed = DanmuApp._on_capture_failed.__get__(app, DanmuApp)

    app._on_capture_failed("RuntimeError: capture boom")

    assert app._capture_in_flight is False
    app._note_capture_failure.assert_called_once_with()
    app._trigger_api_call.assert_not_called()
    assert any("capture boom" in message for message in app.logger.warning_messages)

    app.capturer = FakeCapturer(FakePixmap(1))
    started = []

    class _FakePool:
        def start(self, runnable):
            started.append(runnable)

    monkeypatch.setattr("app.worker_pools.capture_worker_pool", lambda: _FakePool())

    app._schedule_capture()

    assert len(started) == 1
    assert app._capture_in_flight is True


def test_capture_failed_after_stop_only_releases_slot():
    from main import DanmuApp

    app = make_minimal_danmu_app()
    app.engine.running = False
    app.ai_worker._stopping.set()
    app._capture_in_flight = True
    app._note_capture_failure = Mock()
    app._trigger_api_call = Mock()
    app._on_capture_failed = DanmuApp._on_capture_failed.__get__(app, DanmuApp)

    app._on_capture_failed("RuntimeError: late capture boom")

    assert app._capture_in_flight is False
    app._note_capture_failure.assert_not_called()
    app._trigger_api_call.assert_not_called()


def test_capture_runnable_stopping_emits_failed_without_completed():
    """BUG-005: stopping 早退须 failed 结算，禁止静默 return。"""
    coordinator = _CaptureCoordinatorStub()
    stopping = threading.Event()
    stopping.set()
    runnable = CaptureRunnable(object(), coordinator, stopping)

    runnable.run()

    assert coordinator.completed.calls == []
    assert coordinator.failed.calls == [("capture_aborted_stopping",)]


def test_capture_runnable_stopping_after_grab_emits_failed(monkeypatch):
    """grab 完成后若已 stopping，不得 completed，须 failed 释放槽位。"""
    coordinator = _CaptureCoordinatorStub()
    stopping = threading.Event()

    def _grab_then_stop(_plan):
        stopping.set()
        return FakePixmap(1)

    monkeypatch.setattr("app.runnable.execute_capture", _grab_then_stop)
    runnable = CaptureRunnable(object(), coordinator, stopping)
    runnable.run()

    assert coordinator.completed.calls == []
    assert coordinator.failed.calls == [("capture_aborted_stopping",)]


def test_stopping_failed_releases_slot_without_failure_backoff():
    """stopping 的 failed 在主线程槽位清零，且不计入 capture 失败退避。"""
    from main import DanmuApp

    app = make_minimal_danmu_app()
    app.engine.running = False
    app.ai_worker._stopping.set()
    app._capture_in_flight = True
    app._note_capture_failure = Mock()
    app._trigger_api_call = Mock()
    app._on_capture_failed = DanmuApp._on_capture_failed.__get__(app, DanmuApp)

    app._on_capture_failed("capture_aborted_stopping")

    assert app._capture_in_flight is False
    app._note_capture_failure.assert_not_called()
    app._trigger_api_call.assert_not_called()


def test_stop_clears_capture_in_flight():
    """BUG-005: stop() 须显式清零 _capture_in_flight（不依赖 worker 迟到信号）。"""
    from main import DanmuApp
    from tests.fakes import FakeTimer

    app = make_minimal_danmu_app()
    app.engine.running = True
    app._capture_in_flight = True
    app.ai_in_flight = 1
    app._pool_topup_timer = FakeTimer()
    app._topmost_health_timer = FakeTimer()
    app._lifetime_flush_timer = FakeTimer()
    app._live_status_timer = FakeTimer()
    app.screenshot_timer = FakeTimer()
    app.reply_timer = FakeTimer()
    app._mic_orchestrator = Mock(stop_detector=Mock())
    app._sync_mic_service = Mock()
    app.overlay = Mock(stop_render_loop=Mock(), hide=Mock())
    app.tray = Mock(update_state=Mock())
    app.state_changed = Mock(emit=Mock())
    app._reset_scene_generation_baseline = Mock()
    # make_minimal_danmu_app 的 ai_worker 是 Mock；绑定真实 mark_stopping 副作用
    app.ai_worker.mark_stopping = lambda: app.ai_worker._stopping.set()
    app.stop = DanmuApp.stop.__get__(app, DanmuApp)

    app.stop()

    assert app._capture_in_flight is False
    assert app.ai_in_flight == 0
    assert app.ai_worker._stopping.is_set()
