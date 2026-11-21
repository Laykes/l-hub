import os
import sys
import signal
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl

from .manager import DeviceManager
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

    engine = QQmlApplicationEngine()

    manager = DeviceManager()
    app.aboutToQuit.connect(manager.cleanup)
    engine.rootContext().setContextProperty("deviceManager", manager)

    qml_path = Path(__file__).resolve().parent / "qml" / "main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        print("Error: Could not load QML.", file=sys.stderr)
        sys.exit(1)

    window = engine.rootObjects()[0]
    window.installEventFilter(manager)
    tray = LHubTray(manager, window)

    sys.exit(app.exec())


if __name__ == "__main__":
    run()
