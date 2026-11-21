import os
import sys
import signal
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl, QTimer

from .manager import DeviceManager
from .single_instance import SingleInstanceGuard, restore_window
from .tray import LHubTray

ICON_PATH = Path(__file__).resolve().parent / "assets" / "io.github.lhub.LHub.svg"


def load_app_icon() -> QIcon:
    if ICON_PATH.exists():
        icon = QIcon(str(ICON_PATH))
        if not icon.isNull():
            return icon
    return QIcon.fromTheme(
        "io.github.lhub.LHub",
        QIcon.fromTheme("input-gaming", QIcon.fromTheme("preferences-desktop-peripherals")),
    )


def run():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
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
            print("L-Hub is already running.", file=sys.stderr)
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
        print("Error: Could not load QML.", file=sys.stderr)
        sys.exit(1)

    window = engine.rootObjects()[0]
    window.installEventFilter(manager)
    instance_guard.activationRequested.connect(lambda token: restore_window(window, token))
    tray = LHubTray(manager, window)
    QTimer.singleShot(0, manager.refresh_devices)

    sys.exit(app.exec())


if __name__ == "__main__":
    run()
