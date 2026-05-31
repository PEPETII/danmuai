"""Tests for QLocalServer single-instance guard."""

import pytest
from PyQt6.QtWidgets import QApplication

pytest.importorskip("PyQt6.QtNetwork", exc_type=ImportError)

from app.single_instance import SingleInstanceGuard


def test_single_instance_second_client_triggers_activate(qtbot):
    app = QApplication.instance() or QApplication([])

    primary = SingleInstanceGuard()
    assert primary.try_acquire() is True

    activated = []

    def on_activate():
        activated.append(True)

    primary.bind_activate(on_activate)

    secondary = SingleInstanceGuard()
    assert secondary.try_acquire() is False

    qtbot.waitUntil(lambda: activated == [True], timeout=3000)
    assert activated == [True]
