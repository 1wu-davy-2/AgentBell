from __future__ import annotations

import argparse
import logging
import queue
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import __version__
from .api import QUEUE_MAX_SIZE, create_app
from .app import AgentBellApp
from .autostart import configure_autostart
from .config import ConfigError, load_config
from .log import install_exception_hooks, setup_logging
from .models import Notification
from .paths import config_file
from .server import ListenerError, bind_listener
from .single_instance import SingleInstanceError, SingleInstanceGuard, default_server_name
from .storage import NotificationStorage, StorageError
from .store import NotificationStore
from .ui.icons import make_app_icon


def _pick_ui_font() -> str:
    families = set(QFontDatabase.families())
    for family in (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "PingFang SC",
        "Noto Sans CJK SC",
        "Segoe UI",
        "DejaVu Sans",
    ):
        if family in families:
            return family
    return QApplication.font().family()


def _port_error_text(port: int, error: Exception) -> str:
    return (
        f"无法在 127.0.0.1:{port} 启动 HTTP 服务。\n\n"
        f"{error}\n\n"
        "可能的处理方式：\n"
        "1. 修改 config.json 中的 port 为其他端口后重试；\n"
        "2. 关闭占用该端口的程序后重试。\n\n"
        f"Windows 可执行以下命令查看占用：\n"
        f"netstat -ano | findstr :{port}"
    )


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(prog="AgentBell", add_help=True)
    parser.add_argument("--config", type=Path, default=None, help="配置文件路径")
    parser.add_argument("--port", type=int, default=None, help="覆盖监听端口")
    parser.add_argument("--instance", default=None, help="单实例名称后缀（用于并行调试）")
    return parser.parse_known_args(argv)


def _resolve_history_path(config_path: Path, configured: str) -> Path:
    if not configured:
        return config_path.parent / "agentbell.db"
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    options, qt_args = _parse_args(args[1:])
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication([args[0], *qt_args])
    app.setApplicationName("AgentBell")
    app.setApplicationDisplayName("AgentBell")
    app.setOrganizationName("AgentBell")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setFont(QFont(_pick_ui_font(), 10))
    app.setWindowIcon(make_app_icon())

    config_path: Path = (options.config or config_file()).expanduser().resolve()
    logger, log_path = setup_logging(config_path.parent / "logs")
    install_exception_hooks(logger)

    try:
        config, created = load_config(config_path)
    except ConfigError as exc:
        logger.error("配置加载失败：%s", exc)
        QMessageBox.critical(
            None,
            "AgentBell 配置错误",
            f"{exc}\n\n配置文件：{config_path}\n"
            "请修正 JSON 或删除该文件以重新生成默认配置。",
        )
        logging.shutdown()
        return 2

    if options.port is not None:
        config = replace(config, port=options.port)
    if options.instance is not None:
        config = replace(config, instance_name=options.instance)

    logger.info(
        "===== AgentBell %s 启动 | Python %s | 配置=%s | 日志=%s =====",
        __version__,
        platform_python(),
        config_path,
        log_path,
    )
    if created:
        logger.info("首次运行，已生成默认配置文件")

    guard = SingleInstanceGuard(default_server_name(config.instance_name), parent=app)
    try:
        is_primary = guard.acquire()
    except SingleInstanceError as exc:
        logger.error("单实例检查失败：%s", exc)
        QMessageBox.critical(
            None,
            "AgentBell 启动失败",
            f"无法确认 AgentBell 是否已在运行：\n\n{exc}",
        )
        logging.shutdown()
        return 6

    if not is_primary:
        logger.info("AgentBell 已在运行，已通知现有实例打开通知中心；本次启动退出")
        logging.shutdown()
        return 0
    logger.info("单实例锁已获取：%s", guard.name)

    if not config.auth_enabled:
        logger.warning(
            "X-Token 鉴权未开启：本机任何进程都可以调用 /notify。"
            "建议在 config.json 中设置 token。"
        )
    elif config.token == "your-token":
        logger.warning("当前仍使用示例 token（your-token），建议更换为随机值。")
    else:
        logger.info("X-Token 鉴权已开启")

    configure_autostart(config.autostart, logger)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        logger.error("系统托盘不可用，程序无法常驻")
        QMessageBox.critical(
            None,
            "AgentBell 启动失败",
            "当前桌面环境不支持系统托盘，AgentBell 无法常驻运行。",
        )
        guard.close()
        logging.shutdown()
        return 3

    try:
        listener = bind_listener(config.port)
    except ListenerError as exc:
        logger.error("%s", exc)
        QMessageBox.critical(
            None,
            "AgentBell 启动失败",
            _port_error_text(config.port, exc),
        )
        guard.close()
        logging.shutdown()
        return 4

    storage: NotificationStorage | None = None
    if config.history.enabled:
        db_path = _resolve_history_path(config_path, config.history.path)
        try:
            storage = NotificationStorage(db_path, logger)
            logger.info("历史数据库：%s（保留 %d 条）", db_path, config.history.limit)
        except StorageError as exc:
            logger.warning("%s；将继续使用内存历史", exc)

    inbox: queue.Queue[Notification] = queue.Queue(maxsize=QUEUE_MAX_SIZE)
    store = NotificationStore(
        config.history.limit if config.history.enabled else QUEUE_MAX_SIZE,
        storage=storage,
        logger=logger,
    )
    asgi_app = create_app(config, inbox, logger, store=store)
    controller: AgentBellApp | None = None
    try:
        controller = AgentBellApp(
            qapp=app,
            config=config,
            logger=logger,
            inbox=inbox,
            store=store,
            asgi_app=asgi_app,
            listener=listener,
            config_path=config_path,
        )
        controller.start()
        guard.open_requested.connect(
            lambda: controller.open_notification_center(animate=True)
        )
    except Exception as exc:
        logger.exception("AgentBell 启动异常")
        if controller is not None:
            controller.shutdown()
        else:
            try:
                listener.close()
            except OSError:
                pass
        guard.close()
        QMessageBox.critical(
            None,
            "AgentBell 启动失败",
            f"程序初始化失败：\n{exc}\n\n详细信息请查看日志：{log_path}",
        )
        logging.shutdown()
        return 5

    exit_code = 0
    try:
        exit_code = app.exec()
    finally:
        controller.shutdown()
        guard.close()
        logger.info("AgentBell 主循环结束")
        logging.shutdown()
    return exit_code


def platform_python() -> str:
    return sys.version.split()[0]
