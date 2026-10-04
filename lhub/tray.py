from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QObject


class LHubTray(QObject):
    def __init__(self, manager, window, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.window = window

        self.tray = QSystemTrayIcon(self)
        icon = QIcon.fromTheme("input-gaming", QIcon.fromTheme("preferences-desktop-peripherals"))
        self.tray.setIcon(icon)
        self.tray.setToolTip("L-Hub - Peripherie-Zentrale")

        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)

        self.tray.activated.connect(self._on_tray_activated)
        self.manager.devicesChanged.connect(self._update_tray)
        self.manager.batteryWarning.connect(self._on_battery_warning)

        self._build_menu()
        self.tray.show()

    def _build_menu(self):
        self.menu.clear()

        devs = self.manager.devices
        if not devs:
            action = QAction("Keine Geräte verbunden", self.menu)
            action.setEnabled(False)
            self.menu.addAction(action)
        else:
            for d in devs:
                text = d["name"]
                if d.get("hasBattery"):
                    lvl = d["batteryPercentage"]
                    if lvl >= 0:
                        charge = "⚡ " if d.get("isCharging") else "🔋 "
                        text = f"{charge}{lvl}% - {d['name']}"
                action = QAction(text, self.menu)
                action.setEnabled(False)
                self.menu.addAction(action)

        self.menu.addSeparator()

        show_act = QAction("L-Hub öffnen", self.menu)
        show_act.triggered.connect(self._show_window)
        self.menu.addAction(show_act)

        quit_act = QAction("Beenden", self.menu)
        quit_act.triggered.connect(self._quit)
        self.menu.addAction(quit_act)

    def _update_tray(self):
        # Don't rebuild if the context menu is currently visible/active to prevent closing under the user
        if not self.menu.isVisible():
            self._build_menu()

        tips = ["L-Hub"]
        for d in self.manager.devices:
            if d.get("hasBattery") and d["batteryPercentage"] >= 0:
                tips.append(f"{d['name']}: {d['batteryPercentage']}%")
        self.tray.setToolTip("\n".join(tips))

    def _on_battery_warning(self, name: str, percentage: int):
        self.tray.showMessage(
            "Niedriger Akkustand",
            f"{name} hat nur noch {percentage}% Akku!",
            QSystemTrayIcon.Warning,
            6000,
        )

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._show_window()

    def _show_window(self):
        if self.window:
            self.window.show()
            self.window.raise_()
            self.window.requestActivate()

    def _quit(self):
        QApplication.instance().quit()
