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
        self.tray.setToolTip("L-Hub - Peripheral Control Center")

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
            action = QAction("No devices connected", self.menu)
            action.setEnabled(False)
            self.menu.addAction(action)
        else:
            for d in devs:
                text = d["name"]
                if d.get("hasBattery"):
                    lvl = d.get("batteryPercentage", -1)
                    if d.get("isCharging"):
                        if lvl >= 0:
                            text = f"⚡ {lvl}% - {d['name']}"
                        else:
                            text = f"⚡ Charging - {d['name']}"
                    elif lvl >= 0:
                        text = f"🔋 {lvl}% - {d['name']}"
                action = QAction(text, self.menu)
                action.setEnabled(False)
                self.menu.addAction(action)

        self.menu.addSeparator()

        show_act = QAction("Open L-Hub", self.menu)
        show_act.triggered.connect(self._show_window)
        self.menu.addAction(show_act)

        quit_act = QAction("Quit", self.menu)
        quit_act.triggered.connect(self._quit)
        self.menu.addAction(quit_act)

    def _update_tray(self):
        # Don't rebuild if the context menu is currently visible/active to prevent closing under the user
        if not self.menu.isVisible():
            self._build_menu()

        tips = ["L-Hub"]
        for d in self.manager.devices:
            if d.get("hasBattery"):
                lvl = d.get("batteryPercentage", -1)
                if d.get("isCharging"):
                    if lvl >= 0:
                        tips.append(f"{d['name']}: ⚡ {lvl}%")
                    else:
                        tips.append(f"{d['name']}: ⚡ Charging")
                elif lvl >= 0:
                    tips.append(f"{d['name']}: 🔋 {lvl}%")
        self.tray.setToolTip("\n".join(tips))

    def _on_battery_warning(self, name: str, percentage: int):
        self.tray.showMessage(
            "Low Battery",
            f"{name} battery is down to {percentage}%!",
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
