"""Regression for BUG-005: WebConsoleBridge._log_ring must stay at maxlen=500."""

from unittest.mock import MagicMock

import pytest

from app.web_console import WebConsoleBridge


@pytest.fixture
def stub_bridge(qapp):
    app = MagicMock()
    app.logger.log_emitted = MagicMock()
    app.state_changed = MagicMock()
    return WebConsoleBridge(app)


def test_log_ring_maxlen_not_reduced(stub_bridge):
    bridge = stub_bridge

    for i in range(1000):
        bridge._on_log("info", f"msg {i}")

    assert len(bridge._log_ring) == 500
    assert bridge._log_ring[0][1] == "msg 500"
    assert bridge._log_ring[-1][1] == "msg 999"
