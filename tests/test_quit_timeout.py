"""BUG-019: quit() parallel waitForDone for worker thread pools."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from tests.fakes import FakeTimer


def test_wait_all_worker_pools_done_runs_in_parallel(monkeypatch):
    """Each pool wait runs concurrently; total time ~max(delay), not sum."""
    import threading

    delay_sec = 0.3
    active = threading.Semaphore(5)
    active.acquire()

    def make_pool():
        pool = MagicMock()

        def wait_for_done(_ms):
            active.release()
            time.sleep(delay_sec)
            return True

        pool.waitForDone.side_effect = wait_for_done
        return pool

    pools = {
        "capture": make_pool(),
        "ai": make_pool(),
        "meme_ai": make_pool(),
        "meme_fetch": make_pool(),
        "global": make_pool(),
    }
    monkeypatch.setattr(
        "app.worker_pools.capture_worker_pool", lambda: pools["capture"]
    )
    monkeypatch.setattr("app.worker_pools.ai_worker_pool", lambda: pools["ai"])
    monkeypatch.setattr("app.worker_pools.meme_ai_pool", lambda: pools["meme_ai"])
    monkeypatch.setattr(
        "app.worker_pools.meme_fetch_pool", lambda: pools["meme_fetch"]
    )

    class _FakeQThreadPool:
        @staticmethod
        def globalInstance():
            return pools["global"]

    monkeypatch.setattr("app.worker_pools.QThreadPool", _FakeQThreadPool)

    from app.worker_pools import wait_all_worker_pools_done

    start = time.monotonic()
    results = wait_all_worker_pools_done(5000)
    elapsed = time.monotonic() - start

    assert results == {
        "capture": True,
        "ai": True,
        "meme_ai": True,
        "meme_fetch": True,
        "global": True,
    }
    assert elapsed < 0.8, f"expected parallel ~{delay_sec}s, got {elapsed:.2f}s"
    for pool in pools.values():
        pool.waitForDone.assert_called_once_with(5000)


def test_wait_all_worker_pools_done_reports_per_pool_timeouts(monkeypatch):
    outcomes = {
        "capture": True,
        "ai": False,
        "meme_ai": True,
        "meme_fetch": False,
        "global": True,
    }

    def make_pool(label):
        pool = MagicMock()
        pool.waitForDone.return_value = outcomes[label]
        return pool

    pools = {label: make_pool(label) for label in outcomes}
    monkeypatch.setattr(
        "app.worker_pools.capture_worker_pool", lambda: pools["capture"]
    )
    monkeypatch.setattr("app.worker_pools.ai_worker_pool", lambda: pools["ai"])
    monkeypatch.setattr("app.worker_pools.meme_ai_pool", lambda: pools["meme_ai"])
    monkeypatch.setattr(
        "app.worker_pools.meme_fetch_pool", lambda: pools["meme_fetch"]
    )

    class _FakeQThreadPool:
        @staticmethod
        def globalInstance():
            return pools["global"]

    monkeypatch.setattr("app.worker_pools.QThreadPool", _FakeQThreadPool)

    from app.worker_pools import wait_all_worker_pools_done

    results = wait_all_worker_pools_done(2000)

    assert set(results) == set(outcomes)
    assert results == outcomes


def test_quit_uses_parallel_pool_wait(qapp, monkeypatch):
    """DanmuApp.quit() calls wait_all_worker_pools_done once instead of 5 serial waits."""
    order = []
    wait_mock = MagicMock(
        return_value={
            "capture": True,
            "ai": True,
            "meme_ai": True,
            "meme_fetch": True,
            "global": True,
        }
    )
    wait_mock.side_effect = lambda timeout_ms: order.append(f"pool_wait:{timeout_ms}") or {
        "capture": True,
        "ai": True,
        "meme_ai": True,
        "meme_fetch": True,
        "global": True,
    }
    monkeypatch.setattr("app.worker_pools.wait_all_worker_pools_done", wait_mock)

    class _FakeProgressDialog:
        def __init__(self, *_args, **_kwargs):
            self.show = MagicMock()
            self.close = MagicMock()
            self.setWindowModality = MagicMock()
            self.setCancelButton = MagicMock()
            self.setMinimumDuration = MagicMock()
            self.setWindowTitle = MagicMock()

    monkeypatch.setattr("PyQt6.QtWidgets.QProgressDialog", _FakeProgressDialog)
    monkeypatch.setattr("app.main_lifecycle_mixin.QApplication.processEvents", MagicMock())
    monkeypatch.setattr("app.main_lifecycle_mixin.QApplication.quit", MagicMock())

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
    app.config.close.side_effect = lambda: order.append("config_close")
    app.close_meme_barrage_client = lambda: order.append("close_meme_client")

    from main import DanmuApp

    DanmuApp.quit(app)

    wait_mock.assert_called_once_with(2000)
    assert order.index("pool_wait:2000") < order.index("close_meme_client")
    assert order.index("close_meme_client") < order.index("config_close")
