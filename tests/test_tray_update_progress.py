"""Tests for TrayManager update progress dialog lifecycle (W-BUG-003-TRAY-UPDATE-PROGRESS-GC).

Regression coverage for the GC-collected dialog/timer bug: the QProgressDialog
and QTimer must survive as TrayManager instance attributes across gc.collect(),
and must be cleaned up on download_ready / failure / cancel / retrigger.
"""

import gc

from app.update_service import UpdateStatus
from tests.conftest import make_minimal_danmu_app


class _FakeSignal:
    def connect(self, *_args, **_kwargs):
        return None


class _FakeTranslator:
    language_changed = _FakeSignal()


def _make_tray(monkeypatch):
    """Create a TrayManager with Translator mocked out (avoids real Qt signal)."""
    from app.tray import TrayManager

    monkeypatch.setattr("app.tray.Translator.instance", lambda: _FakeTranslator())
    app = make_minimal_danmu_app()
    return TrayManager(app)


def _patch_update_service(
    monkeypatch,
    *,
    check_status,
    download_status,
    get_status,
):
    """Patch app.update_service functions used by _on_check_update.

    app/tray.py does ``from app import update_service`` inside the handler, then
    looks up attributes on the module at call time, so patching the module
    attributes is sufficient.
    """
    monkeypatch.setattr("app.update_service.check_for_updates", lambda: check_status)
    monkeypatch.setattr(
        "app.update_service.download_updates", lambda *, wait=False: download_status
    )
    monkeypatch.setattr("app.update_service.get_status", lambda: get_status)
    monkeypatch.setattr("app.update_service.apply_updates_and_restart", lambda: None)


def _cleanup_tray(tray):
    """Stop timer and close dialog to avoid leaking into other tests."""
    if tray._update_poll_timer is not None:
        tray._update_poll_timer.stop()
    if tray._update_progress is not None:
        tray._update_progress.close()


def test_update_progress_survives_gc(qapp, monkeypatch):
    """CORE regression: dialog/timer must survive gc.collect() (W-BUG-003)."""
    from PyQt6.QtWidgets import QMessageBox

    tray = _make_tray(monkeypatch)
    _patch_update_service(
        monkeypatch,
        check_status=UpdateStatus(
            ok=True, frozen=True, update_available=True, latest_version="9.9.9"
        ),
        download_status=UpdateStatus(ok=True, frozen=True, downloading=True),
        get_status=UpdateStatus(
            ok=True,
            frozen=True,
            downloading=True,
            download_progress=50,
            download_ready=False,
        ),
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    try:
        tray._on_check_update()
        qapp.processEvents()

        # Pre-GC: dialog and timer exist and are active.
        assert tray._update_progress is not None
        assert tray._update_poll_timer is not None
        assert tray._update_poll_timer.isActive() is True
        # isVisible() may be flaky in headless test envs; the `is not None` +
        # `isActive()` checks above are the load-bearing liveness assertions.
        # We still try isVisible() (processEvents above lets show() take
        # effect) to catch real regressions.
        assert tray._update_progress.isVisible() is True

        # THE KEY ASSERTION: GC must not collect the dialog/timer. Before the
        # fix they were local variables held only by a closure cell + signal
        # slot (a cycle), so gc.collect() could reap them at arbitrary times.
        gc.collect()
        assert tray._update_poll_timer is not None
        assert tray._update_poll_timer.isActive() is True
        assert tray._update_progress is not None
        assert tray._update_progress.isVisible() is True
    finally:
        _cleanup_tray(tray)


def test_update_progress_download_ready_clears_state(qapp, monkeypatch):
    """download_ready tick must stop timer, close dialog, clear attrs."""
    from PyQt6.QtWidgets import QMessageBox

    tray = _make_tray(monkeypatch)
    _patch_update_service(
        monkeypatch,
        check_status=UpdateStatus(
            ok=True, frozen=True, update_available=True, latest_version="9.9.9"
        ),
        download_status=UpdateStatus(ok=True, frozen=True, downloading=True),
        get_status=UpdateStatus(
            ok=True,
            frozen=True,
            downloading=False,
            download_progress=100,
            download_ready=True,
        ),
    )
    # question is called twice: download? (Yes), restart? (No)
    answers = iter([QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
    question_calls = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: (question_calls.append(a), next(answers))[1],
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    try:
        tray._on_check_update()
        # Don't processEvents before emit — avoid timer tick racing the manual
        # emit. The timer interval is 200ms so it hasn't ticked yet.
        assert tray._update_poll_timer is not None
        # Trigger one poll tick synchronously (DirectConnection in same thread).
        tray._update_poll_timer.timeout.emit()
        qapp.processEvents()

        assert tray._update_progress is None
        assert tray._update_poll_timer is None
        assert len(question_calls) == 2
    finally:
        _cleanup_tray(tray)


def test_update_progress_failure_clears_state(qapp, monkeypatch):
    """Failure tick (ok=False, not downloading) must clear state and warn."""
    from PyQt6.QtWidgets import QMessageBox

    tray = _make_tray(monkeypatch)
    _patch_update_service(
        monkeypatch,
        check_status=UpdateStatus(
            ok=True, frozen=True, update_available=True, latest_version="9.9.9"
        ),
        download_status=UpdateStatus(ok=True, frozen=True, downloading=True),
        get_status=UpdateStatus(
            ok=False,
            frozen=True,
            downloading=False,
            download_ready=False,
            error="network",
            message="下载失败",
        ),
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    warning_calls = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warning_calls.append(a))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    try:
        tray._on_check_update()
        assert tray._update_poll_timer is not None
        tray._update_poll_timer.timeout.emit()
        qapp.processEvents()

        assert tray._update_progress is None
        assert tray._update_poll_timer is None
        assert len(warning_calls) == 1
    finally:
        _cleanup_tray(tray)


def test_update_progress_cancel_clears_state(qapp, monkeypatch):
    """Cancel signal must stop timer and clear attrs."""
    from PyQt6.QtWidgets import QMessageBox

    tray = _make_tray(monkeypatch)
    _patch_update_service(
        monkeypatch,
        check_status=UpdateStatus(
            ok=True, frozen=True, update_available=True, latest_version="9.9.9"
        ),
        download_status=UpdateStatus(ok=True, frozen=True, downloading=True),
        get_status=UpdateStatus(
            ok=True,
            frozen=True,
            downloading=True,
            download_progress=50,
            download_ready=False,
        ),
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    try:
        tray._on_check_update()
        dlg = tray._update_progress
        assert dlg is not None
        assert tray._update_poll_timer is not None

        # Emit canceled synchronously (DirectConnection in same thread). The
        # _on_canceled closure stops the timer and nulls both attrs.
        dlg.canceled.emit()
        qapp.processEvents()

        assert tray._update_progress is None
        assert tray._update_poll_timer is None
    finally:
        _cleanup_tray(tray)


def test_update_progress_retrigger_clears_old(qapp, monkeypatch):
    """Re-triggering _on_check_update must stop old timer and create new ones."""
    from PyQt6.QtWidgets import QMessageBox

    tray = _make_tray(monkeypatch)
    _patch_update_service(
        monkeypatch,
        check_status=UpdateStatus(
            ok=True, frozen=True, update_available=True, latest_version="9.9.9"
        ),
        download_status=UpdateStatus(ok=True, frozen=True, downloading=True),
        get_status=UpdateStatus(
            ok=True,
            frozen=True,
            downloading=True,
            download_progress=50,
            download_ready=False,
        ),
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    try:
        tray._on_check_update()
        first_timer = tray._update_poll_timer
        first_dlg = tray._update_progress
        assert first_timer is not None
        assert first_dlg is not None

        # Second trigger must pre-clean the old dialog/timer before creating
        # new ones (pre-creation cleanup branch in _on_check_update).
        tray._on_check_update()
        assert tray._update_poll_timer is not None
        assert tray._update_progress is not None
        assert tray._update_poll_timer is not first_timer
        assert tray._update_progress is not first_dlg
        assert first_timer.isActive() is False
    finally:
        _cleanup_tray(tray)
