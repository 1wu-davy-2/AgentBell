from __future__ import annotations

import logging
import os
import socket
import threading
from collections.abc import Callable
from typing import Any

import uvicorn

LOOPBACK_HOST = "127.0.0.1"


class ListenerError(RuntimeError):
    """Raised when the loopback listener cannot be created."""


def bind_listener(port: int) -> socket.socket:
    """Bind the loopback socket synchronously so port conflicts fail fast."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            # Prevent another local process from re-binding the same port.
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                listener.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((LOOPBACK_HOST, port))
    except OSError as exc:
        listener.close()
        raise ListenerError(
            f"无法监听 {LOOPBACK_HOST}:{port}（{exc.strerror or exc}）"
        ) from exc
    return listener


class UvicornServerThread(threading.Thread):
    def __init__(
        self,
        app: Any,
        port: int,
        listener: socket.socket,
        logger: logging.Logger,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(name="http-server", daemon=True)
        self.logger = logger
        self.listener = listener
        self.on_error = on_error
        self._stop_requested = False
        self._uvicorn = uvicorn.Server(
            uvicorn.Config(
                app=app,
                host=LOOPBACK_HOST,
                port=port,
                loop="asyncio",
                http="h11",
                ws=None,
                lifespan="off",
                log_config=None,
                log_level="info",
                access_log=False,
                server_header=False,
                date_header=False,
                proxy_headers=False,
            )
        )

    def run(self) -> None:
        try:
            self._uvicorn.run(sockets=[self.listener])
        except BaseException as exc:
            if not self._stop_requested:
                self.logger.exception("HTTP 服务异常退出")
                if self.on_error is not None:
                    self.on_error(str(exc))
        finally:
            try:
                self.listener.close()
            except OSError:
                pass

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_requested = True
        self._uvicorn.should_exit = True
        if self.is_alive():
            self.join(timeout)
        if self.is_alive():
            self._uvicorn.force_exit = True
            self.join(1.0)
        if self.is_alive():
            self.logger.warning("HTTP 服务线程未能及时退出")
        try:
            self.listener.close()
        except OSError:
            pass
