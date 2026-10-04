import os
import sys
import signal
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl

from .manager import DeviceManager
from .tray import LHubTray


def run():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setApplicationName("L-Hub")
    app.setOrganizationName("LHub")
    app.setDesktopFileName("io.github.lhub.LHub")
    app.setQuitOnLastWindowClosed(False)

    engine = QQmlApplicationEngine()

    manager = DeviceManager()
    engine.rootContext().setContextProperty("deviceManager", manager)

    qml_path = Path(__file__).resolve().parent / "qml" / "main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        print("Fehler: QML konnte nicht geladen werden.", file=sys.stderr)
        sys.exit(1)

    window = engine.rootObjects()[0]
    tray = LHubTray(manager, window)

    sys.exit(app.exec())


if __name__ == "__main__":
    run()
