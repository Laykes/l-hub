import argparse
import logging
import signal
import sys
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl, QTimer

from .logging_config import configure_logging
from .manager import DeviceManager
from .single_instance import SingleInstanceGuard, restore_window
from .tray import LHubTray

logger = logging.getLogger(__name__)

ICON_PATH = Path(__file__).resolve().parent / "assets" / "io.github.lhub.LHub.svg"


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser for L-Hub."""
    parser = argparse.ArgumentParser(
        prog="l-hub",
        description="L-Hub — Linux peripheral control center",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging",
    )
    return parser


def parse_args(argv: Optional[Sequence[str]] = None) -> tuple[argparse.Namespace, list[str]]:
    """Parse known L-Hub CLI flags while preserving Qt arguments."""
    return build_arg_parser().parse_known_args(argv)


def load_app_icon() -> QIcon:
    if ICON_PATH.exists():
        icon = QIcon(str(ICON_PATH))
        if not icon.isNull():
            return icon
    return QIcon.fromTheme(
        "io.github.lhub.LHub",
        QIcon.fromTheme("input-gaming", QIcon.fromTheme("preferences-desktop-peripherals")),
    )


def run(argv: Optional[Sequence[str]] = None):
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    args, qt_args = parse_args(argv)
    configure_logging(debug=args.debug)
    logger.info("Starting L-Hub (debug=%s)", args.debug)
    logger.debug("Passing Qt arguments: %s", qt_args)

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("L-Hub")
    app.setOrganizationName("LHub")
    app.setDesktopFileName("io.github.lhub.LHub")
    app.setWindowIcon(load_app_icon())
    app.setQuitOnLastWindowClosed(False)

    instance_guard = SingleInstanceGuard(parent=app)
    if not instance_guard.try_become_primary():
        if instance_guard.notify_primary():
            sys.exit(0)
        if not instance_guard.try_become_primary():
            logger.warning("L-Hub is already running.")
            sys.exit(0)
    app.aboutToQuit.connect(instance_guard.close)

    engine = QQmlApplicationEngine()

    manager = DeviceManager(auto_refresh=False)
    app.aboutToQuit.connect(manager.cleanup)
    engine.rootContext().setContextProperty("deviceManager", manager)

    qml_path = Path(__file__).resolve().parent / "qml" / "main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        instance_guard.close()
        logger.error("Could not load QML from %s.", qml_path)
        sys.exit(1)

    window = engine.rootObjects()[0]
    window.installEventFilter(manager)
    instance_guard.activationRequested.connect(lambda token: restore_window(window, token))
    tray = LHubTray(manager, window)
    QTimer.singleShot(0, manager.refresh_devices)

    sys.exit(app.exec())


if __name__ == "__main__":
    run()
