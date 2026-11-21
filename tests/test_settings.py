import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QSystemTrayIcon

from lhub.backends.base import BatteryInfo, Capability, Device, DeviceType
from lhub.main import parse_args
from lhub.manager import DeviceManager
from lhub.settings import (
    AUTOSTART_FILENAME,
    DEFAULT_SETTINGS,
    LOW_BATTERY_THRESHOLD_MAX,
    LOW_BATTERY_THRESHOLD_MIN,
    POLL_INTERVAL_MAX,
    POLL_INTERVAL_MIN,
    SettingsManager,
    build_autostart_desktop_entry,
    resolve_autostart_command,
)
from lhub.tray import LHubTray

_app = QGuiApplication.instance() or QGuiApplication(sys.argv)
REPO_ROOT = Path(__file__).resolve().parent.parent


class TestSettingsManager(unittest.TestCase):
    def test_defaults_and_xdg_path_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            xdg_dir = Path(td) / "xdg-cfg"
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_dir)}):
                mgr = SettingsManager()

            self.assertEqual(mgr.config_file, xdg_dir / "lhub" / "settings.json")
            self.assertEqual(mgr.autostart_file, xdg_dir / "autostart" / AUTOSTART_FILENAME)
            self.assertEqual(mgr.as_dict(), DEFAULT_SETTINGS)
            self.assertFalse(mgr.config_file.exists())
            self.assertFalse(mgr.autostart_file.exists())

            # Empty/whitespace XDG_CONFIG_HOME must fall back to ~/.config
            fake_home = Path(td) / "fake-home"
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": "   "}), patch(
                "lhub.settings.Path.home", return_value=fake_home
            ):
                mgr_fallback = SettingsManager()
            self.assertEqual(mgr_fallback.config_file, fake_home / ".config" / "lhub" / "settings.json")
            self.assertEqual(
                mgr_fallback.autostart_file,
                fake_home / ".config" / "autostart" / AUTOSTART_FILENAME,
            )

    def test_atomic_save_and_reload_without_leftover_tmp(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "lhub" / "settings.json"
            autostart_dir = Path(td) / "autostart"
            mgr = SettingsManager(config_file=cfg, autostart_dir=autostart_dir)

            ok = mgr.update({
                "low_battery_threshold": 32,
                "notify_low_battery": False,
                "notify_profile_change": False,
                "poll_interval_sec": 75,
            })
            self.assertTrue(ok)
            self.assertTrue(cfg.exists())

            leftover_tmp = [p for p in cfg.parent.iterdir() if p.name.endswith(".tmp")]
            self.assertEqual(leftover_tmp, [])

            reloaded = SettingsManager(config_file=cfg, autostart_dir=autostart_dir)
            self.assertEqual(reloaded.low_battery_threshold, 32)
            self.assertFalse(reloaded.notify_low_battery)
            self.assertFalse(reloaded.notify_profile_change)
            self.assertEqual(reloaded.poll_interval_sec, 75)
            self.assertFalse(reloaded.autostart)
            self.assertFalse(reloaded.start_minimized)

    def test_validation_and_clamping(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "settings.json"
            autostart_dir = Path(td) / "autostart"
            mgr = SettingsManager(config_file=cfg, autostart_dir=autostart_dir)

            mgr.update({
                "low_battery_threshold": 1,
                "poll_interval_sec": 999,
                "notify_low_battery": "false",
                "notify_profile_change": 0,
                "unknown_key": "ignored",
            })
            self.assertEqual(mgr.low_battery_threshold, LOW_BATTERY_THRESHOLD_MIN)
            self.assertEqual(mgr.poll_interval_sec, POLL_INTERVAL_MAX)
            self.assertFalse(mgr.notify_low_battery)
            self.assertFalse(mgr.notify_profile_change)
            self.assertNotIn("unknown_key", mgr.as_dict())

            mgr.update({
                "low_battery_threshold": 80,
                "poll_interval_sec": 2,
                "notify_low_battery": "yes",
                "notify_profile_change": "on",
            })
            self.assertEqual(mgr.low_battery_threshold, LOW_BATTERY_THRESHOLD_MAX)
            self.assertEqual(mgr.poll_interval_sec, POLL_INTERVAL_MIN)
            self.assertTrue(mgr.notify_low_battery)
            self.assertTrue(mgr.notify_profile_change)

            # Booleans and invalid types must not coerce into int thresholds/intervals
            mgr.update({
                "low_battery_threshold": True,
                "poll_interval_sec": "not-a-number",
                "notify_low_battery": "maybe",
            })
            self.assertEqual(mgr.low_battery_threshold, LOW_BATTERY_THRESHOLD_MAX)
            self.assertEqual(mgr.poll_interval_sec, POLL_INTERVAL_MIN)
            self.assertTrue(mgr.notify_low_battery)

            # Float and numeric string coercion
            mgr.update({"low_battery_threshold": "27.6", "poll_interval_sec": 44.2})
            self.assertEqual(mgr.low_battery_threshold, 28)
            self.assertEqual(mgr.poll_interval_sec, 44)

    def test_corrupt_and_nondict_json_fallback_logs_warning(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "settings.json"
            autostart_dir = Path(td) / "autostart"

            cfg.write_text("{broken json", encoding="utf-8")
            with self.assertLogs("lhub.settings", level="WARNING") as cm:
                mgr = SettingsManager(config_file=cfg, autostart_dir=autostart_dir)
            self.assertEqual(mgr.as_dict(), DEFAULT_SETTINGS)
            self.assertTrue(any("Failed to load settings" in line for line in cm.output))

            cfg.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
            with self.assertLogs("lhub.settings", level="WARNING") as cm2:
                mgr2 = SettingsManager(config_file=cfg, autostart_dir=autostart_dir)
            self.assertEqual(mgr2.as_dict(), DEFAULT_SETTINGS)
            self.assertTrue(any("expected a JSON object" in line for line in cm2.output))

    def test_autostart_desktop_lifecycle_and_exec_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            xdg_dir = Path(td) / "xdg"
            local_bin = Path(td) / "bin" / "l-hub"
            local_bin.parent.mkdir(parents=True)

            # 1. Missing ~/.local/bin/l-hub falls back to python -m lhub + Path=
            exec_cmd, workdir = resolve_autostart_command(
                start_minimized=False,
                local_bin=local_bin,
                python_executable="/usr/bin/python3",
                project_root=Path("/opt/lhub repo"),
            )
            self.assertEqual(exec_cmd, "/usr/bin/python3 -m lhub")
            self.assertEqual(workdir, Path("/opt/lhub repo"))

            entry = build_autostart_desktop_entry(
                start_minimized=True,
                local_bin=local_bin,
                python_executable="/usr/bin/python3",
                project_root=Path("/opt/lhub repo"),
            )
            self.assertIn('Exec=/usr/bin/python3 -m lhub --minimized\n', entry)
            self.assertIn('Path=/opt/lhub repo\n', entry)
            self.assertIn("StartupNotify=false\n", entry)

            # 2. Non-executable l-hub still falls back to python -m lhub
            local_bin.write_text("#!/bin/sh\n", encoding="utf-8")
            local_bin.chmod(0o644)
            exec_cmd_nonexec, workdir_nonexec = resolve_autostart_command(
                start_minimized=False,
                local_bin=local_bin,
            )
            self.assertIn("-m lhub", exec_cmd_nonexec)
            self.assertIsNotNone(workdir_nonexec)

            # 3. Executable ~/.local/bin/l-hub is preferred directly
            local_bin.chmod(local_bin.stat().st_mode | stat.S_IXUSR)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_dir)}):
                mgr = SettingsManager(local_bin=local_bin)
                self.assertTrue(mgr.update({"autostart": True, "start_minimized": False}))

                desktop_file = xdg_dir / "autostart" / AUTOSTART_FILENAME
                self.assertTrue(desktop_file.exists())
                content = desktop_file.read_text(encoding="utf-8")
                self.assertIn("[Desktop Entry]\n", content)
                self.assertIn(f"Exec={local_bin}\n", content)
                self.assertNotIn("Exec=" + str(local_bin) + " --minimized", content)
                self.assertNotIn("\nPath=", content)
                self.assertIn("StartupNotify=true\n", content)

                # Update start_minimized -> adds --minimized to Exec=
                self.assertTrue(mgr.update({"start_minimized": True}))
                updated = desktop_file.read_text(encoding="utf-8")
                self.assertIn(f"Exec={local_bin} --minimized\n", updated)
                self.assertIn("StartupNotify=false\n", updated)

                # Disable autostart -> removes file cleanly
                self.assertTrue(mgr.set("autostart", False))
                self.assertFalse(desktop_file.exists())

                # Re-enable then reset_defaults() -> cleans up desktop file too
                self.assertTrue(mgr.set("autostart", True))
                self.assertTrue(desktop_file.exists())
                self.assertTrue(mgr.reset_defaults())
                self.assertFalse(desktop_file.exists())


class TestCliAndQmlStartup(unittest.TestCase):
    def test_parse_args_minimized_and_debug(self):
        args_default, qt_default = parse_args([])
        self.assertFalse(args_default.minimized)
        self.assertFalse(args_default.debug)
        self.assertEqual(qt_default, [])

        args_min, qt_min = parse_args(["--minimized", "--debug", "-platform", "offscreen"])
        self.assertTrue(args_min.minimized)
        self.assertTrue(args_min.debug)
        self.assertEqual(qt_min, ["-platform", "offscreen"])

    def test_qml_minimized_visibility_and_settings_dialog_offscreen(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            xdg_cfg = Path(td) / "cfg"
            xdg_rt = Path(td) / "rt"
            xdg_rt.mkdir(parents=True, exist_ok=True)
            xdg_rt.chmod(0o700)

            script = (
                "import os, sys\n"
                "from pathlib import Path\n"
                "from PySide6.QtCore import QObject, QUrl\n"
                "from PySide6.QtQml import QQmlApplicationEngine\n"
                "from PySide6.QtWidgets import QApplication\n"
                "from lhub.manager import DeviceManager\n"
                "from lhub.settings import SettingsManager\n"
                "from lhub.single_instance import restore_window\n"
                "app = QApplication(sys.argv)\n"
                "settings_mgr = SettingsManager()\n"
                "mgr = DeviceManager(auto_refresh=False, settings_mgr=settings_mgr)\n"
                "qml_url = QUrl.fromLocalFile(str(Path('lhub/qml/main.qml').resolve()))\n"
                "# Case 1: startMinimized=True hides window initially, restore_window shows it\n"
                "eng_min = QQmlApplicationEngine()\n"
                "eng_min.rootContext().setContextProperty('deviceManager', mgr)\n"
                "eng_min.rootContext().setContextProperty('startMinimized', True)\n"
                "eng_min.load(qml_url)\n"
                "assert eng_min.rootObjects(), 'Failed to load main.qml (minimized)'\n"
                "win_min = eng_min.rootObjects()[0]\n"
                "assert not win_min.isVisible(), 'Expected window hidden when startMinimized=True'\n"
                "restore_window(win_min)\n"
                "assert win_min.isVisible(), 'Expected restore_window to show hidden window'\n"
                "# Case 2: startMinimized=False shows window initially, open & save SettingsDialog inside main.qml\n"
                "eng_norm = QQmlApplicationEngine()\n"
                "eng_norm.rootContext().setContextProperty('deviceManager', mgr)\n"
                "eng_norm.rootContext().setContextProperty('startMinimized', False)\n"
                "eng_norm.load(qml_url)\n"
                "assert eng_norm.rootObjects(), 'Failed to load main.qml (normal)'\n"
                "win_norm = eng_norm.rootObjects()[0]\n"
                "assert win_norm.isVisible(), 'Expected window visible when startMinimized=False'\n"
                "sd = next((c for c in win_norm.findChildren(QObject) if 'SettingsDialog' in c.metaObject().className()), None)\n"
                "assert sd is not None, 'SettingsDialog child not found in main.qml'\n"
                "sd.open()\n"
                "app.processEvents()\n"
                "sd.setProperty('draftLowBatteryThreshold', 35)\n"
                "sd.setProperty('draftPollIntervalSec', 60)\n"
                "sd.saveSettings()\n"
                "app.processEvents()\n"
                "assert mgr.lowBatteryThreshold == 35\n"
                "assert mgr.pollIntervalSec == 60\n"
                "del win_min, win_norm, sd, eng_min, eng_norm\n"
                "print('QML_OK', flush=True)\n"
            )

            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["XDG_CONFIG_HOME"] = str(xdg_cfg)
            env["XDG_RUNTIME_DIR"] = str(xdg_rt)

            proc = subprocess.run(
                [sys.executable, "-c", script],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(proc.returncode, 0, f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}")
            self.assertIn("QML_OK", proc.stdout)
            self.assertNotIn("QML", proc.stderr)
            self.assertNotIn("TypeError", proc.stderr)
            self.assertNotIn("ReferenceError", proc.stderr)
            self.assertNotIn("Binding loop", proc.stderr)
            self.assertTrue((xdg_cfg / "lhub" / "settings.json").exists())


class TestManagerAndTraySettingsIntegration(unittest.TestCase):
    def _make_device(self, percentage: int = 50, is_charging: bool = False) -> Device:
        return Device(
            id="headset_046d_0aba",
            name="Logitech PRO X Wireless",
            vendor="Logitech",
            device_type=DeviceType.HEADSET,
            usb_vid="046d",
            usb_pid="0aba",
            capabilities=[Capability.BATTERY],
            battery=BatteryInfo(percentage=percentage, is_charging=is_charging, is_supported=True),
        )

    def test_live_poll_interval_and_reset(self):
        with tempfile.TemporaryDirectory() as td:
            sm = SettingsManager(
                config_file=Path(td) / "settings.json",
                autostart_dir=Path(td) / "autostart",
            )
            sm.update({"poll_interval_sec": 45})
            mgr = DeviceManager(auto_refresh=False, settings_mgr=sm)
            self.assertEqual(mgr._timer.interval(), 45000)

            changed = []
            mgr.settingsChanged.connect(lambda: changed.append(True))

            self.assertTrue(mgr.updateSettings({"pollIntervalSec": 90}))
            self.assertEqual(mgr.pollIntervalSec, 90)
            self.assertEqual(mgr._timer.interval(), 90000)
            self.assertEqual(len(changed), 1)

            self.assertTrue(mgr.resetSettings())
            self.assertEqual(mgr.pollIntervalSec, 30)
            self.assertEqual(mgr._timer.interval(), 30000)
            self.assertEqual(len(changed), 2)

    def test_live_battery_threshold_hysteresis_and_notification_gating(self):
        with tempfile.TemporaryDirectory() as td:
            sm = SettingsManager(
                config_file=Path(td) / "settings.json",
                autostart_dir=Path(td) / "autostart",
            )
            mgr = DeviceManager(auto_refresh=False, settings_mgr=sm)
            warnings = []
            mgr.batteryWarning.connect(lambda name, pct: warnings.append((name, pct)))

            # Raise threshold live to 35% (hysteresis reset becomes > 40%)
            mgr.updateSettings({"lowBatteryThreshold": 35})
            mgr._check_battery_warnings([self._make_device(percentage=36)])
            self.assertEqual(warnings, [])

            mgr._check_battery_warnings([self._make_device(percentage=35)])
            self.assertEqual(warnings, [("Logitech PRO X Wireless", 35)])

            # 40% is within hysteresis (35 + 5), so returning to 34% must not re-warn
            mgr._check_battery_warnings([self._make_device(percentage=40)])
            mgr._check_battery_warnings([self._make_device(percentage=34)])
            self.assertEqual(len(warnings), 1)

            # 41% resets hysteresis, then disable notifyLowBattery -> no warning emitted
            mgr._check_battery_warnings([self._make_device(percentage=41)])
            mgr.updateSettings({"notifyLowBattery": False})
            mgr._check_battery_warnings([self._make_device(percentage=25)])
            self.assertEqual(len(warnings), 1)

            # Re-enabling notifyLowBattery emits immediately for cached low-battery device
            mgr._devices = [self._make_device(percentage=25)]
            mgr.updateSettings({"notifyLowBattery": True})
            self.assertEqual(
                warnings,
                [("Logitech PRO X Wireless", 35), ("Logitech PRO X Wireless", 25)],
            )

    def test_onboard_profile_notification_gating_and_tray_guards(self):
        with tempfile.TemporaryDirectory() as td:
            sm = SettingsManager(
                config_file=Path(td) / "settings.json",
                autostart_dir=Path(td) / "autostart",
            )
            mgr = DeviceManager(auto_refresh=False, settings_mgr=sm)
            dev = Device(
                id="ratbag_mouse",
                name="Logitech G502 X",
                vendor="Logitech",
                device_type=DeviceType.MOUSE,
                usb_vid="046d",
                usb_pid="c099",
                onboard_profile_id=0,
                onboard_profile="Profile 1",
            )
            mgr._devices = [dev]
            mgr._cached_dict_devices = [{"id": dev.id, "deviceKey": "046d:c099", "onboardProfile": "Profile 1"}]

            profile_events = []
            mgr.onboardProfileChanged.connect(lambda n, lbl: profile_events.append((n, lbl)))

            with patch.object(mgr, "refresh_devices"), patch("lhub.manager.threading.Thread"):
                # Disabled -> state updates, signal suppressed
                mgr.updateSettings({"notifyProfileChange": False})
                mgr._on_hidpp_profile_event("046d:c099", 1)
                self.assertEqual(dev.onboard_profile_id, 1)
                self.assertEqual(profile_events, [])

                # Enabled -> signal emitted
                mgr.updateSettings({"notifyProfileChange": True})
                mgr._on_hidpp_profile_event("046d:c099", 2)
                self.assertEqual(len(profile_events), 1)
                self.assertEqual(profile_events[0][0], "Logitech G502 X")

            # LHubTray notification gates also respect settings
            tray_obj = LHubTray.__new__(LHubTray)
            tray_obj.manager = mgr
            tray_obj.tray = MagicMock()
            tray_obj.tray.isVisible.return_value = True

            with patch.object(QSystemTrayIcon, "supportsMessages", return_value=True):
                mgr.updateSettings({"notifyLowBattery": False, "notifyProfileChange": False})
                tray_obj._on_battery_warning("Logitech PRO X Wireless", 15)
                tray_obj._on_onboard_profile_changed("Logitech G502 X", "Profile 2")
                tray_obj.tray.showMessage.assert_not_called()

                mgr.updateSettings({"notifyLowBattery": True, "notifyProfileChange": True})
                tray_obj._on_battery_warning("Logitech PRO X Wireless", 15)
                tray_obj._on_onboard_profile_changed("Logitech G502 X", "Profile 2")
                self.assertEqual(tray_obj.tray.showMessage.call_count, 2)


if __name__ == "__main__":
    unittest.main()
