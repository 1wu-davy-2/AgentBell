from __future__ import annotations

import getpass
import hashlib
import os
import time

from PySide6.QtCore import QDir, QEventLoop, QLockFile, QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_CONNECT_TIMEOUT_MS = 300
_ACK_TIMEOUT_MS = 400
_RETRY_COUNT = 10
_RETRY_DELAY_SECONDS = 0.1
_SERVER_PREFIX = "AgentBell-single"


def default_server_name() -> str:
    if hasattr(os, "getuid"):
        identity = str(os.getuid())
    else:
        identity = os.environ.get("USERNAME") or getpass.getuser()
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"{_SERVER_PREFIX}-{digest}"


class SingleInstanceError(RuntimeError):
    """Raised when the local single-instance channel cannot be established."""


class SingleInstanceGuard(QObject):
    open_requested = Signal()

    def __init__(self, name: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = name or default_server_name()
        self._lock_path = str(QDir.tempPath()) + QDir.separator() + self._name + ".lock"
        self._lock: QLockFile | None = None
        self._server: QLocalServer | None = None
        self._clients: list[QLocalSocket] = []
        self._acquired = False

    @property
    def name(self) -> str:
        return self._name

    def acquire(self) -> bool:
        """Become the primary instance, or wake the existing one and return False."""
        if self._acquired:
            return True

        lock = QLockFile(self._lock_path)
        if not lock.tryLock(0):
            if self._notify_existing_with_retry():
                return False
            raise SingleInstanceError(
                "已有 AgentBell 实例持有单实例锁，但无法连接。"
                "请检查托盘是否已有 AgentBell 图标；若没有，请删除锁文件后重试："
                f"{self._lock_path}"
            )

        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.newConnection.connect(self._accept_connections)
        QLocalServer.removeServer(self._name)
        if not server.listen(self._name):
            error = server.errorString()
            server.deleteLater()
            lock.unlock()
            raise SingleInstanceError(f"无法建立单实例通道：{error}")

        self._lock = lock
        self._server = server
        self._acquired = True
        return True

    def close(self) -> None:
        # Sockets and the server stay children of this object so Qt frees them
        # during teardown. Deferred deletes here can outlive the guard when the
        # process is already shutting down.
        for socket in list(self._clients):
            socket.abort()
        self._clients.clear()

        if self._server is not None:
            self._server.close()
            self._server = None

        if self._acquired:
            QLocalServer.removeServer(self._name)
            self._acquired = False

        if self._lock is not None:
            self._lock.unlock()
            self._lock = None

    def _notify_existing_with_retry(self) -> bool:
        for attempt in range(_RETRY_COUNT):
            if self._notify_existing():
                return True
            if attempt < _RETRY_COUNT - 1:
                time.sleep(_RETRY_DELAY_SECONDS)
        return False

    def _notify_existing(self) -> bool:
        socket = QLocalSocket(self)
        socket.connectToServer(self._name)
        if not socket.waitForConnected(_CONNECT_TIMEOUT_MS):
            socket.abort()
            socket.close()
            return False

        socket.write(b"open\n")
        socket.flush()

        reply = bytearray()
        loop = QEventLoop()

        def read_reply() -> None:
            reply.extend(bytes(socket.readAll()))
            if b"ok" in reply:
                loop.quit()

        socket.readyRead.connect(read_reply)
        socket.disconnected.connect(loop.quit)
        timer = QTimer(socket)
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(_ACK_TIMEOUT_MS)
        loop.exec()
        timer.stop()
        socket.readyRead.disconnect(read_reply)
        socket.disconnected.disconnect(loop.quit)

        socket.disconnectFromServer()
        if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            socket.waitForDisconnected(100)
        socket.close()
        return b"ok" in reply

    def _accept_connections(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                break
            self._clients.append(socket)
            socket.readyRead.connect(lambda item=socket: self._read_command(item))
            socket.disconnected.connect(lambda item=socket: self._forget(item))
            if socket.bytesAvailable() > 0:
                self._read_command(socket)

    def _read_command(self, socket: QLocalSocket) -> None:
        data = bytes(socket.readAll()).strip().lower()
        if b"open" in data.splitlines():
            socket.write(b"ok\n")
            socket.flush()
            self.open_requested.emit()

    def _forget(self, socket: QLocalSocket) -> None:
        if socket in self._clients:
            self._clients.remove(socket)
        socket.close()
