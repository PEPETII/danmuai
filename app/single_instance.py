"""Single-instance guard via QLocalServer (one DanmuAI per user profile)."""

from __future__ import annotations

import hashlib
import os
from typing import Callable

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

_ACTIVATE_MSG = b"activate"


def _server_name() -> str:
    appdata = os.environ.get("APPDATA", "").strip() or os.path.expanduser("~")
    digest = hashlib.sha256(appdata.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"DanmuAI-{digest}"


class SingleInstanceGuard:
    def __init__(self) -> None:
        self._name = _server_name()
        self._server: QLocalServer | None = None
        self._activate_handler: Callable[[], None] | None = None

    def try_acquire(self) -> bool:
        """Return True if this process should become the primary instance."""
        if self._activate_existing_instance():
            return False
        if self._listen_primary():
            return True
        # Race window: another instance may have claimed the name between probe and listen.
        return False if self._activate_existing_instance() else False

    def _activate_existing_instance(self) -> bool:
        probe = QLocalSocket()
        probe.connectToServer(self._name)
        if not probe.waitForConnected(500):
            return False
        probe.write(_ACTIVATE_MSG)
        probe.flush()
        probe.waitForBytesWritten(1000)
        # Same-process tests: pump Qt so the listening guard handles newConnection.
        app = QCoreApplication.instance()
        if app is not None:
            app.processEvents()
        probe.waitForDisconnected(2000)
        if probe.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            probe.disconnectFromServer()
        return True

    def _listen_primary(self) -> bool:
        server = QLocalServer()
        if server.listen(self._name):
            server.newConnection.connect(self._on_new_connection)
            self._server = server
            return True

        if not QLocalServer.removeServer(self._name):
            return False

        retry_server = QLocalServer()
        if not retry_server.listen(self._name):
            return False
        retry_server.newConnection.connect(self._on_new_connection)
        self._server = retry_server
        return True

    def bind_activate(self, handler: Callable[[], None]) -> None:
        self._activate_handler = handler

    def _read_activate_payload(self, conn: QLocalSocket) -> bytes:
        """Read activate message; tolerate fast client disconnect on slow CI hosts."""
        chunks: list[bytes] = []
        for _ in range(6):
            if conn.bytesAvailable():
                chunks.append(conn.readAll().data())
            joined = b"".join(chunks)
            if joined == _ACTIVATE_MSG:
                return _ACTIVATE_MSG
            if len(joined) > len(_ACTIVATE_MSG):
                return joined
            if not conn.waitForReadyRead(500):
                break
        return b"".join(chunks)

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        if self._read_activate_payload(conn) == _ACTIVATE_MSG:
            handler = self._activate_handler
            if handler is not None:
                # newConnection is on the server thread (main); avoid singleShot race in tests/CI.
                handler()
        conn.disconnectFromServer()
