import shutil
import subprocess
from pathlib import Path

from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QObject

from .single_instance import restore_window

ICON_PATH = Path(__file__).resolve().parent / "assets" / "io.github.lhub.LHub.svg"


class LHubTray(QObject):
    def __init__(self, manager, window, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.window = window

        self.tray = QSystemTrayIcon(self)
        icon = QApplication.windowIcon()
        if icon.isNull() and ICON_PATH.exists():
            icon = QIcon(str(ICON_PATH))
        if icon.isNull():
            icon = QIcon.fromTheme(
                "io.github.lhub.LHub",
                QIcon.fromTheme("input-gaming", QIcon.fromTheme("preferences-desktop-peripherals")),
            )
        self.tray.setIcon(icon)
        self.tray.setToolTip("L-Hub - Peripheral Control Center")

        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)

        self.tray.activated.connect(self._on_tray_activated)
        self.tray.messageClicked.connect(self._show_window)
        self.manager.devicesChanged.connect(self._update_tray)
        self.manager.batteryWarning.connect(self._on_battery_warning)
        self.manager.onboardProfileChanged.connect(self._on_onboard_profile_changed)

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
                if d.get("hasOnboardProfile") and d.get("onboardProfile"):
                    text = f"{text} ({d['onboardProfile']})"
                if d.get("hasBattery"):
                    lvl = d.get("batteryPercentage", -1)
                    if d.get("isCharging"):
                        if lvl >= 0:
                            text = f"⚡ {lvl}% - {text}"
                        else:
                            text = f"⚡ Charging - {text}"
                    elif lvl >= 0:
                        text = f"🔋 {lvl}% - {text}"
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
            parts = []
            if d.get("hasOnboardProfile") and d.get("onboardProfile"):
                parts.append(d["onboardProfile"])
            if d.get("hasBattery"):
                lvl = d.get("batteryPercentage", -1)
                if d.get("isCharging"):
                    parts.append(f"⚡ {lvl}%" if lvl >= 0 else "⚡ Charging")
                elif lvl >= 0:
                    parts.append(f"🔋 {lvl}%")
            if parts:
                tips.append(f"{d['name']}: {' • '.join(parts)}")
        self.tray.setToolTip("\n".join(tips))

    def _notify(self, title: str, message: str, icon=QSystemTrayIcon.Information, timeout_ms: int = 5000):
        if self.tray.isVisible() and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, message, icon, timeout_ms)
            return
        notify_send = shutil.which("notify-send")
        if notify_send:
            urgency = "critical" if icon == QSystemTrayIcon.Critical else "normal"
            try:
                subprocess.Popen(
                    [notify_send, "-a", "L-Hub", "-u", urgency, "-t", str(timeout_ms), title, message],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                pass

    def _on_battery_warning(self, name: str, percentage: int):
        self._notify(
            "Low Battery",
            f"{name} battery is down to {percentage}%!",
            QSystemTrayIcon.Warning,
            6000,
        )

    def _on_onboard_profile_changed(self, device_name: str, profile_label: str):
        self._notify(
            device_name,
            f"Onboard Profile: {profile_label}",
            QSystemTrayIcon.Information,
            2500,
        )

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._show_window()

    def _show_window(self):
        restore_window(self.window)

    def _quit(self):
        QApplication.instance().quit()
