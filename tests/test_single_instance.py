"""Tests for QLocalServer single-instance guard."""

import importlib
import sys
from types import SimpleNamespace

import pytest

if sys.platform == "win32" and sys.version_info >= (3, 14):
    pytest.skip(
        "PyQt6.QtNetwork is not validated on Windows/Python 3.14 in this test environment",
        allow_module_level=True,
    )

pytest.importorskip("PyQt6.QtNetwork", exc_type=ImportError)
QApplication = pytest.importorskip("PyQt6.QtWidgets").QApplication
single_instance_module = importlib.import_module("app.single_instance")
SingleInstanceAcquireKind = single_instance_module.SingleInstanceAcquireKind
SingleInstanceAcquireResult = single_instance_module.SingleInstanceAcquireResult
SingleInstanceGuard = single_instance_module.SingleInstanceGuard


def test_single_instance_second_client_triggers_activate():
    app = QApplication.instance() or QApplication([])

    primary = SingleInstanceGuard()
    assert primary.try_acquire().kind is SingleInstanceAcquireKind.PRIMARY

    activated = []

    def on_activate():
        activated.append(True)

    primary.bind_activate(on_activate)

    secondary = SingleInstanceGuard()
    assert (
        secondary.try_acquire().kind
        is SingleInstanceAcquireKind.ACTIVATED_EXISTING
    )
    # try_acquire pumps events for in-process test; assert covers handler ran.
    assert activated == [True]


def test_single_instance_listen_failure_does_not_claim_primary(monkeypatch):
    remove_calls = []

    class FakeSignal:
        def connect(self, _handler):
            return None

    class FakeSocket:
        LocalSocketState = SimpleNamespace(UnconnectedState="unconnected")

        def connectToServer(self, _name):
            return None

        def waitForConnected(self, _timeout):
            return False

    class FakeServer:
        def __init__(self):
            self.newConnection = FakeSignal()

        def listen(self, _name):
            return False

        @staticmethod
        def removeServer(name):
            remove_calls.append(name)
            return False

    monkeypatch.setattr("app.single_instance.QLocalSocket", FakeSocket)
    monkeypatch.setattr("app.single_instance.QLocalServer", FakeServer)

    guard = SingleInstanceGuard()
    assert guard.try_acquire().kind is SingleInstanceAcquireKind.ACTIVATION_FAILED
    assert len(remove_calls) == 1


def test_single_instance_activation_failed_closes_server(monkeypatch):
    close_calls = []
    remove_calls = []

    class FakeSignal:
        def connect(self, _handler):
            return None

    class FakeSocket:
        LocalSocketState = SimpleNamespace(UnconnectedState="unconnected")

        def connectToServer(self, _name):
            return None

        def waitForConnected(self, _timeout):
            return False

    class FakeServer:
        def __init__(self):
            self.newConnection = FakeSignal()

        def listen(self, _name):
            return False

        def close(self):
            close_calls.append(True)

        @staticmethod
        def removeServer(name):
            remove_calls.append(name)
            return False

    monkeypatch.setattr("app.single_instance.QLocalSocket", FakeSocket)
    monkeypatch.setattr("app.single_instance.QLocalServer", FakeServer)

    guard = SingleInstanceGuard()
    assert guard.try_acquire().kind is SingleInstanceAcquireKind.ACTIVATION_FAILED
    assert close_calls == [True]

    guard.release()
    assert remove_calls == [guard._name, guard._name]


def test_single_instance_reclaims_stale_server_name(monkeypatch):
    listen_results = iter([False, True])
    remove_calls = []

    class FakeSignal:
        def __init__(self):
            self.handlers = []

        def connect(self, handler):
            self.handlers.append(handler)

    class FakeSocket:
        LocalSocketState = SimpleNamespace(UnconnectedState="unconnected")

        def connectToServer(self, _name):
            return None

        def waitForConnected(self, _timeout):
            return False

    class FakeServer:
        def __init__(self):
            self.newConnection = FakeSignal()

        def listen(self, _name):
            return next(listen_results)

        @staticmethod
        def removeServer(name):
            remove_calls.append(name)
            return True

    monkeypatch.setattr("app.single_instance.QLocalSocket", FakeSocket)
    monkeypatch.setattr("app.single_instance.QLocalServer", FakeServer)

    guard = SingleInstanceGuard()
    assert guard.try_acquire().kind is SingleInstanceAcquireKind.PRIMARY
    assert len(remove_calls) == 1


def test_single_instance_race_retry_activates_existing(monkeypatch):
    listen_results = iter([False])
    remove_calls = []
    connect_results = iter([False, True])
    writes = []

    class FakeSignal:
        def connect(self, _handler):
            return None

    class FakeSocket:
        LocalSocketState = SimpleNamespace(UnconnectedState="unconnected")

        def __init__(self):
            self._connected = False

        def connectToServer(self, _name):
            return None

        def waitForConnected(self, _timeout):
            self._connected = next(connect_results)
            return self._connected

        def write(self, payload):
            writes.append(payload)
            return len(payload)

        def flush(self):
            return True

        def waitForBytesWritten(self, _timeout):
            return True

        def waitForDisconnected(self, _timeout):
            self._connected = False
            return True

        def state(self):
            return (
                "connected" if self._connected else self.LocalSocketState.UnconnectedState
            )

        def disconnectFromServer(self):
            self._connected = False

    class FakeServer:
        def __init__(self):
            self.newConnection = FakeSignal()

        def listen(self, _name):
            return next(listen_results)

        @staticmethod
        def removeServer(name):
            remove_calls.append(name)
            return False

    monkeypatch.setattr("app.single_instance.QLocalSocket", FakeSocket)
    monkeypatch.setattr("app.single_instance.QLocalServer", FakeServer)

    guard = SingleInstanceGuard()
    result = guard.try_acquire()
    assert result.kind is SingleInstanceAcquireKind.ACTIVATED_EXISTING
    assert remove_calls == [guard._name]
    assert writes == [b"activate"]
