from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from agentbell.single_instance import SingleInstanceGuard

pytest.importorskip("PySide6")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_SECOND_INSTANCE = """
import sys
from PySide6.QtCore import QCoreApplication
from agentbell.single_instance import SingleInstanceGuard

app = QCoreApplication([])
guard = SingleInstanceGuard(sys.argv[1])
try:
    primary = guard.acquire()
except Exception as exc:
    print(f"error:{exc}", file=sys.stderr)
    raise SystemExit(2)
guard.close()
print("primary" if primary else "secondary")
"""


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def unique_name() -> str:
    return f"AgentBell-test-{uuid.uuid4().hex[:10]}"


def run_second_instance(name: str) -> tuple[int, str, str]:
    # The subprocess needs this process's Qt event loop to answer the handshake,
    # so pump events on the main thread while it runs.
    environment = os.environ.copy()
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    process = subprocess.Popen(
        [sys.executable, "-c", _SECOND_INSTANCE, name],
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 30
    while process.poll() is None:
        if time.monotonic() > deadline:
            process.kill()
            break
        QTest.qWait(50)
    stdout, stderr = process.communicate(timeout=5)
    return process.returncode, stdout, stderr


def test_acquire_is_idempotent_and_close_releases(qapp):
    name = unique_name()
    first = SingleInstanceGuard(name)
    try:
        assert first.acquire() is True
        assert first.acquire() is True
    finally:
        first.close()

    second = SingleInstanceGuard(name)
    try:
        assert second.acquire() is True
    finally:
        second.close()


def test_primary_receives_open_request_and_acks(qapp):
    name = unique_name()
    guard = SingleInstanceGuard(name)
    received: list[bool] = []
    guard.open_requested.connect(lambda: received.append(True))
    socket = QLocalSocket()
    try:
        assert guard.acquire() is True
        socket.connectToServer(name)
        assert socket.waitForConnected(1000) is True
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
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(1500)
        loop.exec()
        timer.stop()
        socket.readyRead.disconnect(read_reply)
        socket.disconnected.disconnect(loop.quit)

        assert received == [True]
        assert b"ok" in reply
    finally:
        socket.disconnectFromServer()
        guard.close()


def test_second_process_does_not_become_primary_and_wakes_first(qapp):
    name = unique_name()
    guard = SingleInstanceGuard(name)
    received: list[bool] = []
    guard.open_requested.connect(lambda: received.append(True))
    try:
        assert guard.acquire() is True
        exit_code, stdout, stderr = run_second_instance(name)
        assert exit_code == 0, stderr
        assert stdout.strip() == "secondary"
        assert received == [True]
    finally:
        guard.close()


def test_second_process_becomes_primary_after_close(qapp):
    name = unique_name()
    guard = SingleInstanceGuard(name)
    assert guard.acquire() is True
    guard.close()

    exit_code, stdout, stderr = run_second_instance(name)
    assert exit_code == 0, stderr
    assert stdout.strip() == "primary"
