"""Single-instance guard via QLocalServer (one DanmuAI per user profile).

``QLocalServer`` + ``QLocalSocket`` 实现单实例：第一个进程 bind ``DanmuAI-{user-salt}``，
后续进程连 socket 发送 ``_ACTIVATE_MSG`` 后退出，激活原窗口。``_server_name`` 哈希
``USERNAME | APPDATA | Windows session ID``（BUG-006 混入 USERNAME；W-COMPAT-SINGLE-INSTANCE-SESSION-001
再混入会话 ID，避免快速用户切换 / 多会话 Terminal Services 误激活或互斥）。

竞态窗口：若原实例正在启动但 ``QLocalServer`` 尚未就绪，新进程 ``_activate_existing_instance``
超时返回 False，``_listen_primary`` 可能抢占成功（server 名尚未注册），导致双实例。
``main()`` 对 ``ACTIVATION_FAILED`` 结果执行最多 3 次重试（间隔 500ms），重试期间原实例
``QLocalServer`` 有机会就绪；重试耗尽则 ``sys.exit(2)`` 退出，阻止双实例。
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

_ACTIVATE_MSG = b"activate"


class SingleInstanceAcquireKind(str, Enum):
    PRIMARY = "primary"
    ACTIVATED_EXISTING = "activated_existing"
    ACTIVATION_FAILED = "activation_failed"


@dataclass(frozen=True)
class SingleInstanceAcquireResult:
    kind: SingleInstanceAcquireKind

    @property
    def became_primary(self) -> bool:
        return self.kind is SingleInstanceAcquireKind.PRIMARY

    @property
    def activated_existing(self) -> bool:
        return self.kind is SingleInstanceAcquireKind.ACTIVATED_EXISTING

    @property
    def activation_failed(self) -> bool:
        return self.kind is SingleInstanceAcquireKind.ACTIVATION_FAILED


def _windows_session_id() -> str:
    if sys.platform != "win32":
        return "0"
    try:
        import ctypes

        session_id = int(ctypes.windll.kernel32.WTSGetActiveConsoleSessionId())
        if session_id >= 0:
            return str(session_id)
    except (AttributeError, OSError, ValueError):
        pass
    return "0"


def _server_name() -> str:
    appdata = os.environ.get("APPDATA", "").strip() or os.path.expanduser("~")
    username = (
        os.environ.get("USERNAME", "").strip()
        or os.environ.get("USER", "").strip()
    )
    session_id = _windows_session_id()
    digest = hashlib.sha256(
        f"{username}|{appdata}|{session_id}".encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    return f"DanmuAI-{digest}"


class SingleInstanceGuard:
    def __init__(self) -> None:
        self._name = _server_name()
        self._server: QLocalServer | None = None
        self._activate_handler: Callable[[], None] | None = None

    def try_acquire(self) -> SingleInstanceAcquireResult:
        """Return explicit single-instance outcome for main() to branch on."""
        if self._activate_existing_instance():
            return SingleInstanceAcquireResult(
                SingleInstanceAcquireKind.ACTIVATED_EXISTING
            )
        if self._listen_primary():
            return SingleInstanceAcquireResult(SingleInstanceAcquireKind.PRIMARY)
        # Race window: another instance may have claimed the name between probe and listen.
        if self._activate_existing_instance():
            return SingleInstanceAcquireResult(
                SingleInstanceAcquireKind.ACTIVATED_EXISTING
            )
        return SingleInstanceAcquireResult(SingleInstanceAcquireKind.ACTIVATION_FAILED)

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
