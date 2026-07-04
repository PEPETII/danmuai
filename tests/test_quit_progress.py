"""BUG-005: quit() shows progress dialog during teardown."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from tests.fakes import FakeTimer


def _patch_worker_pools(monkeypatch):
    fake_pool = MagicMock()
    fake_pool.waitForDone.return_value = True
    for name in (
        "capture_worker_pool",
        "ai_worker_pool",
        "meme_ai_pool",
        "meme_fetch_pool",
    ):
        monkeypatch.setattr(f"app.worker_pools.{name}", lambda _p=fake_pool: _p)

    import PyQt6.QtCore as qtcore

    monkeypatch.setattr(qtcore.QThreadPool, "globalInstance", staticmethod(lambda: fake_pool))
    return fake_pool


def test_quit_shows_and_closes_progress_dialog(qapp, monkeypatch):
    """quit() must show QProgressDialog before teardown and close it before QApplication.quit."""
    _patch_worker_pools(monkeypatch)

    progress_instances = []

    class _FakeProgressDialog:
        def __init__(self, *_args, **_kwargs):
            self.show = MagicMock()
            self.close = MagicMock()
            self.setWindowModality = MagicMock()
            self.setCancelButton = MagicMock()
            self.setMinimumDuration = MagicMock()
            self.setWindowTitle = MagicMock()
            progress_instances.append(self)

    monkeypatch.setattr("PyQt6.QtWidgets.QProgressDialog", _FakeProgressDialog)
    process_events = MagicMock()
    monkeypatch.setattr(
        "app.main_lifecycle_mixin.QApplication.processEvents", process_events
    )
    quit_mock = MagicMock()
    monkeypatch.setattr("app.main_lifecycle_mixin.QApplication.quit", quit_mock)

    pool_timer = FakeTimer()
    pool_timer.active = True
    pool_timer.started = 1

    app = SimpleNamespace(
        logger=MagicMock(),
        stop=MagicMock(),
        hotkey=MagicMock(),
        tray=MagicMock(),
        ai_worker=MagicMock(),
        history_writer=MagicMock(),
        config=MagicMock(),
        overlay=MagicMock(),
        webview_shell=None,
        web_server=MagicMock(),
        stop_web_status_timer=MagicMock(),
        _pool_topup_timer=pool_timer,
        _mic_service=MagicMock(),
    )

    from main import DanmuApp

    DanmuApp.quit(app)

    assert len(progress_instances) == 1
    progress = progress_instances[0]
    progress.show.assert_called_once()
    progress.close.assert_called_once()
    process_events.assert_called_once()
    app.stop.assert_called_once_with()
    quit_mock.assert_called_once_with()
