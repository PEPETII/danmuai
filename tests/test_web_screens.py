"""Screen enumeration for web console."""

import pytest
from app.web_console import enumerate_screens
from PyQt6.QtWidgets import QApplication


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_enumerate_screens_returns_at_least_one(qapp):
    screens = enumerate_screens()
    assert len(screens) >= 1
    assert screens[0]["index"] == 0
    assert "label" in screens[0]
