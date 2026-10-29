from __future__ import annotations

import logging
import sys
import tempfile
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(threadName)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _build_file_handler(log_dir: Path) -> tuple[RotatingFileHandler, Path]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "agentbell.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
        delay=True,
    )
    return handler, log_path


def setup_logging(log_dir: Path) -> tuple[logging.Logger, Path]:
    """Configure file + optional console logging and return the app logger.

    If the preferred directory is not writable (e.g. the exe sits in Program Files),
    fall back to the system temp directory instead of refusing to start.
    """
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    file_handler: RotatingFileHandler | None = None
    log_path: Path

    try:
        file_handler, log_path = _build_file_handler(log_dir)
    except OSError:
        fallback_dir = Path(tempfile.gettempdir()) / "AgentBell" / "logs"
        file_handler, log_path = _build_file_handler(fallback_dir)

    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(file_handler)

    if sys.stderr is not None:
        console = logging.StreamHandler(stream=sys.stderr)
        console.setFormatter(formatter)
        root.addHandler(console)

    logging.getLogger("uvicorn.access").disabled = True

    logger = logging.getLogger("agentbell")
    logger.info("日志文件：%s", log_path)
    return logger, log_path


def install_exception_hooks(logger: logging.Logger) -> None:
    def handle_exception(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("未捕获异常", exc_info=(exc_type, exc_value, exc_tb))

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        logger.critical(
            "线程 %s 未捕获异常", args.thread.name if args.thread else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception
