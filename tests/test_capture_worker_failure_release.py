import threading
import time
from unittest.mock import Mock

from app.runnable import CaptureCoordinator, CaptureRunnable
from PyQt6.QtCore import QObject, pyqtSlot

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


class _FailureReceiver(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []
        self.epochs: list[int] = []
        self.thread_ids: list[int] = []

    @pyqtSlot(str, int)
    def on_failed(self, message: str, epoch: int) -> None:
        self.messages.append(message)
        self.epochs.append(epoch)
        self.thread_ids.append(threading.get_ident())


def test_capture_runnable_carries_safe_payload_without_capture_backend_call():
    coordinator = _CaptureCoordinatorStub()
    image_payload = object()

    runnable = CaptureRunnable(image_payload, coordinator, threading.Event(), session_epoch=7)
    runnable.run()

    assert coordinator.completed.calls == [(image_payload, 7)]
    assert coordinator.failed.calls == []


def test_capture_stopping_signal_is_delivered_on_main_thread(qapp):
    coordinator = CaptureCoordinator()
    receiver = _FailureReceiver()
    coordinator.failed.connect(receiver.on_failed)
    main_thread_id = threading.get_ident()
    stopping = threading.Event()
    stopping.set()
    runnable = CaptureRunnable(object(), coordinator, stopping, session_epoch=11)

    worker = threading.Thread(target=runnable.run)
    worker.start()
    worker.join(timeout=2.0)
    assert not worker.is_alive()

    deadline = time.monotonic() + 1.0
    while not receiver.messages and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert receiver.messages == ["capture_aborted_stopping"]
    assert receiver.epochs == [11]
    assert receiver.thread_ids == [main_thread_id]


def test_capture_completed_signal_carries_session_epoch():
    coordinator = _CaptureCoordinatorStub()
    image = object()

    runnable = CaptureRunnable(
        image,
        coordinator,
        threading.Event(),
        session_epoch=23,
    )
    runnable.run()

    assert coordinator.completed.calls == [(image, 23)]
    assert coordinator.failed.calls == []


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
    monkeypatch.setattr("main.pixmap_to_image_snapshot", lambda _pixmap: object())

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
    assert coordinator.failed.calls == [("capture_aborted_stopping", 0)]


def test_capture_runnable_stopping_emits_failed_without_payload_delivery():
    """The payload dispatcher observes stopping before it can emit completed."""
    coordinator = _CaptureCoordinatorStub()
    stopping = threading.Event()

    stopping.set()
    runnable = CaptureRunnable(object(), coordinator, stopping)
    runnable.run()

    assert coordinator.completed.calls == []
    assert coordinator.failed.calls == [("capture_aborted_stopping", 0)]


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
    initial_epoch = app._capture_session_epoch
    app._pool_topup_timer = FakeTimer()
    app._topmost_health_timer = FakeTimer()
    app._lifetime_flush_timer = FakeTimer()
    app._live_status_timer = FakeTimer()
    app._mic_poll_timer = FakeTimer()
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
    assert app._capture_session_epoch == initial_epoch + 1


def test_capture_failed_from_previous_session_does_not_release_current_slot():
    from main import DanmuApp

    app = make_minimal_danmu_app()
    app.engine.running = True
    app._capture_session_epoch = 2
    app._capture_in_flight = True
    app._note_capture_failure = Mock()
    app._on_capture_failed = DanmuApp._on_capture_failed.__get__(app, DanmuApp)

    app._on_capture_failed("late capture boom", session_epoch=1)

    assert app._capture_in_flight is True
    app._note_capture_failure.assert_not_called()
