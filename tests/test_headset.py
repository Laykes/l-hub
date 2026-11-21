import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication

from lhub.backends.base import BatteryInfo, Capability, Device, DeviceType
from lhub.backends.headset import HeadsetBackend
from lhub.manager import DeviceManager
from lhub.serializers import device_to_dict
from lhub.settings import (
    DEFAULT_SETTINGS,
    HEADSET_INACTIVE_TIME_MAX,
    HEADSET_SIDETONE_MAX,
    SettingsManager,
)

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)
REPO_ROOT = Path(__file__).resolve().parent.parent


class _FakeHeadsetBackend(HeadsetBackend):
    """In-memory HeadsetBackend double for deterministic manager persistence/reconnect tests."""

    def __init__(self):
        super().__init__()
        self._cmd = "/usr/bin/headsetcontrol"
        self.scanned: list[Device] = []
        self.sidetone_calls: list[tuple[str, int]] = []
        self.inactive_calls: list[tuple[str, int]] = []
        self.sidetone_results: list[bool] = []
        self.inactive_results: list[bool] = []
        self.default_sidetone_ok: bool = True
        self.default_inactive_ok: bool = True

    def is_available(self) -> bool:
        return True

    def scan_devices(self):
        return list(self.scanned)

    def set_sidetone(self, device_id: str, level: int) -> bool:
        level = max(0, min(HEADSET_SIDETONE_MAX, int(level)))
        self.sidetone_calls.append((device_id, level))
        ok = self.sidetone_results.pop(0) if self.sidetone_results else self.default_sidetone_ok
        if ok:
            self._saved_sidetone[device_id] = level
        return ok

    def set_inactive_time(self, device_id: str, minutes: int) -> bool:
        minutes = max(0, min(HEADSET_INACTIVE_TIME_MAX, int(minutes)))
        self.inactive_calls.append((device_id, minutes))
        ok = self.inactive_results.pop(0) if self.inactive_results else self.default_inactive_ok
        if ok:
            self._saved_inactive[device_id] = minutes
        return ok


def _make_headset(
    *,
    dev_id: str = "headset_046d_0aba",
    vid: str = "046d",
    pid: str = "0aba",
    online: bool = True,
    with_battery: bool = True,
    sidetone: int = 0,
    inactive_time: int = 15,
    caps: list[Capability] | None = None,
) -> Device:
    if caps is None:
        caps = [Capability.SIDETONE, Capability.INACTIVE_TIME]
        if with_battery:
            caps.insert(0, Capability.BATTERY)

    battery = None
    if with_battery:
        if online:
            battery = BatteryInfo(percentage=75, is_charging=False, is_supported=True, status_text="BATTERY_AVAILABLE")
        else:
            battery = BatteryInfo(percentage=-1, is_charging=False, is_supported=False, status_text="BATTERY_UNAVAILABLE")

    return Device(
        id=dev_id,
        name="Logitech PRO X Wireless",
        vendor="Logitech",
        device_type=DeviceType.HEADSET,
        usb_vid=vid,
        usb_pid=pid,
        capabilities=caps,
        battery=battery,
        sidetone=sidetone if Capability.SIDETONE in caps else None,
        inactive_time=inactive_time if Capability.INACTIVE_TIME in caps else None,
        backend_name="headsetcontrol",
    )


def _wait_until(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestHeadset(unittest.TestCase):
    def setUp(self):
        self.backend = HeadsetBackend()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.cfg_path = Path(self._tmpdir.name) / "settings.json"
        self.autostart_dir = Path(self._tmpdir.name) / "autostart"

    def _make_settings_mgr(self) -> SettingsManager:
        return SettingsManager(config_file=self.cfg_path, autostart_dir=self.autostart_dir)

    @patch("subprocess.run")
    def test_set_sidetone_uses_correct_device_hex_prefix(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.object(self.backend, "is_available", return_value=True):
            res = self.backend.set_sidetone("headset_046d_0aba", 64)
            self.assertTrue(res)
            mock_run.assert_called_once()
            called_cmd = mock_run.call_args[0][0]
            self.assertIn("-s", called_cmd)
            self.assertIn("64", called_cmd)
            self.assertIn("-d", called_cmd)
            self.assertIn("0x046d:0x0aba", called_cmd)

    @patch("subprocess.run")
    def test_set_inactive_time_uses_correct_device_hex_prefix_and_clamps(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch.object(self.backend, "is_available", return_value=True):
            res = self.backend.set_inactive_time("headset_046d_0aba", 120)
            self.assertTrue(res)
            mock_run.assert_called_once()
            called_cmd = mock_run.call_args[0][0]
            self.assertIn("-i", called_cmd)
            self.assertIn("90", called_cmd)
            self.assertIn("-d", called_cmd)
            self.assertIn("0x046d:0x0aba", called_cmd)

    def test_serializer_exposes_inactive_time(self):
        dev = _make_headset(sidetone=48, inactive_time=30)
        d = device_to_dict(dev)
        self.assertTrue(d["hasSidetone"])
        self.assertEqual(d["sidetone"], 48)
        self.assertTrue(d["hasInactiveTime"])
        self.assertEqual(d["inactiveTime"], 30)

        dev_no_inactive = _make_headset(caps=[Capability.SIDETONE], sidetone=12)
        d2 = device_to_dict(dev_no_inactive)
        self.assertTrue(d2["hasSidetone"])
        self.assertFalse(d2["hasInactiveTime"])
        self.assertEqual(d2["inactiveTime"], 15)

    def test_settings_manager_headset_persistence_and_validation(self):
        sm = self._make_settings_mgr()
        self.assertEqual(sm.get_headset_settings("046d:0aba"), {})

        self.assertTrue(sm.set_headset_setting("046d:0aba", "sidetone", 200))
        self.assertTrue(sm.set_headset_setting("046d:0aba", "inactive_time", -10))
        self.assertEqual(sm.get_headset_settings("046d:0aba"), {"sidetone": 128, "inactive_time": 0})

        # Invalid keys / values must be rejected without corrupting existing entries
        self.assertFalse(sm.set_headset_setting("046d:0aba", "unknown", 10))
        self.assertFalse(sm.set_headset_setting("", "sidetone", 10))
        self.assertFalse(sm.set_headset_setting("046d:0aba", "sidetone", True))
        self.assertFalse(sm.set_headset_setting("046d:0aba", "inactive_time", "nope"))
        self.assertEqual(sm.get_headset_settings("046d:0aba"), {"sidetone": 128, "inactive_time": 0})

        # Reloading from disk preserves both app settings and headset settings
        reloaded = self._make_settings_mgr()
        self.assertEqual(reloaded.as_dict(), DEFAULT_SETTINGS)
        self.assertEqual(reloaded.get_headset_settings("046d:0aba"), {"sidetone": 128, "inactive_time": 0})

        # Resetting app defaults keeps per-device headset settings intact
        self.assertTrue(reloaded.update({"poll_interval_sec": 60}))
        self.assertTrue(reloaded.reset_defaults())
        self.assertEqual(reloaded.poll_interval_sec, 30)
        self.assertEqual(reloaded.get_headset_settings("046d:0aba"), {"sidetone": 128, "inactive_time": 0})

        # Corrupt entries inside headset_settings are ignored cleanly on load
        raw = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        raw["headset_settings"]["046d:0aba"]["sidetone"] = "bad"
        raw["headset_settings"]["046d:0abb"] = {"sidetone": "42", "inactive_time": 999}
        raw["headset_settings"]["   "] = {"sidetone": 10}
        self.cfg_path.write_text(json.dumps(raw), encoding="utf-8")

        reloaded2 = self._make_settings_mgr()
        self.assertEqual(reloaded2.get_headset_settings("046d:0aba"), {"inactive_time": 0})
        self.assertEqual(reloaded2.get_headset_settings("046d:0abb"), {"sidetone": 42, "inactive_time": 90})

        self.assertTrue(reloaded2.clear_headset_settings("046d:0aba"))
        self.assertEqual(reloaded2.get_headset_settings("046d:0aba"), {})
        self.assertTrue(reloaded2.clear_headset_settings())
        self.assertEqual(reloaded2.get_headset_settings("046d:0abb"), {})

    def test_manager_set_sidetone_and_inactive_time_persist(self):
        sm = self._make_settings_mgr()
        backend = _FakeHeadsetBackend()
        mgr = DeviceManager(
            auto_refresh=False,
            enable_hotplug=False,
            backends=[backend],
            settings_mgr=sm,
        )
        self.addCleanup(mgr.cleanup)

        dev = _make_headset()
        mgr._devices = [dev]
        mgr._cached_dict_devices = [mgr._device_to_dict(dev)]

        mgr.setSidetone("headset_046d_0aba", 50)
        mgr.setInactiveTime("headset_046d_0aba", 30)

        # Immediate UI cache update
        self.assertEqual(mgr._cached_dict_devices[0]["sidetone"], 50)
        self.assertEqual(mgr._cached_dict_devices[0]["inactiveTime"], 30)

        self.assertTrue(
            _wait_until(
                lambda: backend.sidetone_calls == [("headset_046d_0aba", 50)]
                and backend.inactive_calls == [("headset_046d_0aba", 30)]
                and sm.get_headset_settings("046d:0aba") == {"sidetone": 50, "inactive_time": 30}
            )
        )

        # Re-read from disk to confirm atomic persistence
        reloaded = self._make_settings_mgr()
        self.assertEqual(reloaded.get_headset_settings("046d:0aba"), {"sidetone": 50, "inactive_time": 30})

    def test_startup_restore_skips_redundant_polls_and_reapplies_on_reconnect(self):
        sm = self._make_settings_mgr()
        sm.set_headset_setting("046d:0aba", "sidetone", 72)
        sm.set_headset_setting("046d:0aba", "inactive_time", 45)

        backend = _FakeHeadsetBackend()
        backend.scanned = [_make_headset(online=True)]

        mgr = DeviceManager(
            auto_refresh=False,
            enable_hotplug=False,
            backends=[backend],
            settings_mgr=sm,
        )
        self.addCleanup(mgr.cleanup)

        # 1. Initial scan restores saved settings once and populates UI cache
        mgr._scan_worker()
        self.assertEqual(backend.sidetone_calls, [("headset_046d_0aba", 72)])
        self.assertEqual(backend.inactive_calls, [("headset_046d_0aba", 45)])
        self.assertEqual(mgr._cached_dict_devices[0]["sidetone"], 72)
        self.assertEqual(mgr._cached_dict_devices[0]["inactiveTime"], 45)

        # 2. Subsequent regular poll while still online must NOT spam headsetcontrol
        mgr._scan_worker()
        self.assertEqual(len(backend.sidetone_calls), 1)
        self.assertEqual(len(backend.inactive_calls), 1)

        # 3. Wireless headset powers off (dongle still plugged in -> BATTERY_UNAVAILABLE)
        backend.scanned = [_make_headset(online=False)]
        mgr._scan_worker()
        self.assertEqual(len(backend.sidetone_calls), 1)
        self.assertEqual(len(backend.inactive_calls), 1)
        # UI still displays the persisted values while offline
        self.assertEqual(mgr._cached_dict_devices[0]["sidetone"], 72)
        self.assertEqual(mgr._cached_dict_devices[0]["inactiveTime"], 45)

        # 4. Wireless headset turns back on -> settings are re-applied once
        backend.scanned = [_make_headset(online=True)]
        mgr._scan_worker()
        self.assertEqual(backend.sidetone_calls, [("headset_046d_0aba", 72), ("headset_046d_0aba", 72)])
        self.assertEqual(backend.inactive_calls, [("headset_046d_0aba", 45), ("headset_046d_0aba", 45)])

        # 5. Physical unplug -> replug also re-applies settings once
        backend.scanned = []
        mgr._scan_worker()
        backend.scanned = [_make_headset(online=True)]
        mgr._scan_worker()
        self.assertEqual(len(backend.sidetone_calls), 3)
        self.assertEqual(len(backend.inactive_calls), 3)

    def test_no_unasked_writes_when_no_settings_saved(self):
        sm = self._make_settings_mgr()
        backend = _FakeHeadsetBackend()
        backend.scanned = [_make_headset(online=True)]

        mgr = DeviceManager(
            auto_refresh=False,
            enable_hotplug=False,
            backends=[backend],
            settings_mgr=sm,
        )
        self.addCleanup(mgr.cleanup)

        mgr._scan_worker()
        self.assertEqual(backend.sidetone_calls, [])
        self.assertEqual(backend.inactive_calls, [])

    def test_offline_edit_persists_and_applies_when_headset_wakes(self):
        sm = self._make_settings_mgr()
        backend = _FakeHeadsetBackend()
        backend.default_inactive_ok = False  # fails while wireless headset is powered off
        backend.scanned = [_make_headset(online=False)]

        mgr = DeviceManager(
            auto_refresh=False,
            enable_hotplug=False,
            backends=[backend],
            settings_mgr=sm,
        )
        self.addCleanup(mgr.cleanup)

        mgr._scan_worker()
        mgr.setInactiveTime("headset_046d_0aba", 20)
        self.assertTrue(
            _wait_until(lambda: sm.get_headset_settings("046d:0aba") == {"inactive_time": 20})
        )

        # Now the headset wakes up and accepts commands -> automatically applied!
        backend.default_inactive_ok = True
        backend.inactive_calls.clear()
        backend.scanned = [_make_headset(online=True)]
        mgr._scan_worker()

        self.assertEqual(backend.inactive_calls, [("headset_046d_0aba", 20)])
        self.assertEqual(mgr._cached_dict_devices[0]["inactiveTime"], 20)

    def test_restore_retries_transient_failure_and_caps_permanent_failure(self):
        sm = self._make_settings_mgr()
        sm.set_headset_setting("046d:0aba", "sidetone", 64)

        backend = _FakeHeadsetBackend()
        backend.sidetone_results = [False, True]
        backend.scanned = [_make_headset(online=True, with_battery=False)]

        mgr = DeviceManager(
            auto_refresh=False,
            enable_hotplug=False,
            backends=[backend],
            settings_mgr=sm,
        )
        self.addCleanup(mgr.cleanup)

        # Attempt 1 fails -> retries on next scan and succeeds
        mgr._scan_worker()
        mgr._scan_worker()
        mgr._scan_worker()  # already succeeded on attempt 2 -> no 3rd call
        self.assertEqual(backend.sidetone_calls, [("headset_046d_0aba", 64), ("headset_046d_0aba", 64)])

        # Disconnect + reconnect with permanent failures stops at HEADSET_RESTORE_MAX_RETRIES
        backend.scanned = []
        mgr._scan_worker()
        backend.sidetone_calls.clear()
        backend.default_sidetone_ok = False
        backend.scanned = [_make_headset(online=True, with_battery=False)]
        for _ in range(5):
            mgr._scan_worker()
        self.assertEqual(len(backend.sidetone_calls), DeviceManager.HEADSET_RESTORE_MAX_RETRIES)

    def test_headset_section_qml_loads_cleanly_offscreen(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as td:
            xdg_cfg = Path(td) / "cfg"
            xdg_rt = Path(td) / "rt"
            xdg_rt.mkdir(parents=True, exist_ok=True)
            xdg_rt.chmod(0o700)

            script = (
                "import sys\n"
                "from pathlib import Path\n"
                "from PySide6.QtCore import QUrl\n"
                "from PySide6.QtQml import QQmlApplicationEngine\n"
                "from PySide6.QtWidgets import QApplication\n"
                "from lhub.backends.base import BatteryInfo, Capability, Device, DeviceType\n"
                "from lhub.manager import DeviceManager\n"
                "from lhub.settings import SettingsManager\n"
                "app = QApplication(sys.argv)\n"
                "sm = SettingsManager()\n"
                "mgr = DeviceManager(auto_refresh=False, enable_hotplug=False, settings_mgr=sm)\n"
                "dev = Device(\n"
                "    id='headset_046d_0aba', name='Logitech PRO X Wireless', vendor='Logitech',\n"
                "    device_type=DeviceType.HEADSET, usb_vid='046d', usb_pid='0aba',\n"
                "    capabilities=[Capability.BATTERY, Capability.SIDETONE, Capability.INACTIVE_TIME],\n"
                "    battery=BatteryInfo(percentage=80, is_supported=True, status_text='BATTERY_AVAILABLE'),\n"
                "    sidetone=64, inactive_time=30, backend_name='headsetcontrol',\n"
                ")\n"
                "mgr._devices = [dev]\n"
                "mgr._cached_dict_devices = [mgr._device_to_dict(dev)]\n"
                "eng = QQmlApplicationEngine()\n"
                "eng.rootContext().setContextProperty('deviceManager', mgr)\n"
                "eng.rootContext().setContextProperty('startMinimized', False)\n"
                "eng.load(QUrl.fromLocalFile(str(Path('lhub/qml/main.qml').resolve())))\n"
                "assert eng.rootObjects(), 'Failed to load main.qml'\n"
                "app.processEvents()\n"
                "mgr.cleanup()\n"
                "del eng\n"
                "print('HEADSET_QML_OK', flush=True)\n"
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
            self.assertIn("HEADSET_QML_OK", proc.stdout)
            self.assertNotIn("QML", proc.stderr)
            self.assertNotIn("TypeError", proc.stderr)
            self.assertNotIn("ReferenceError", proc.stderr)
            self.assertNotIn("Binding loop", proc.stderr)


if __name__ == "__main__":
    unittest.main()
