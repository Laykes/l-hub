import io
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from PySide6.QtGui import QGuiApplication

from lhub.backends import hidpp
from lhub.backends.base import BaseBackend, Device, DeviceType
from lhub.backends.dbus_client import DBusCallError, DBusTimeoutError
from lhub.backends.ratbag import RATBAG_SERVICE
from lhub.backends.upower import UPOWER_SERVICE
from lhub.health import (
    HealthCheckItem,
    RATBAGD_FIX_HINT,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_OK,
    SEVERITY_WARNING,
    check_headsetcontrol,
    check_hidraw_permissions,
    check_ratbagd,
    check_upower,
    run_health_checks,
)
from lhub.logging_config import configure_logging
from lhub.main import parse_args
from lhub.manager import DeviceManager
from lhub.profiles import ProfileManager

_app = QGuiApplication.instance() or QGuiApplication(sys.argv)


class TestLoggingAndCli(unittest.TestCase):
    def setUp(self):
        self._lhub_logger = logging.getLogger("lhub")
        self._prev_level = self._lhub_logger.level
        self.addCleanup(self._restore_logging)

    def _restore_logging(self):
        self._lhub_logger.setLevel(self._prev_level)
        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, "_lhub_managed", False):
                root.removeHandler(handler)

    def test_configure_logging_defaults_and_idempotence(self):
        logger = configure_logging(debug=False)
        self.assertEqual(logger.level, logging.WARNING)

        managed_count_first = sum(
            1 for h in logging.getLogger().handlers if getattr(h, "_lhub_managed", False)
        )
        self.assertEqual(managed_count_first, 1)

        logger = configure_logging(debug=True)
        self.assertEqual(logger.level, logging.DEBUG)
        managed_count_second = sum(
            1 for h in logging.getLogger().handlers if getattr(h, "_lhub_managed", False)
        )
        self.assertEqual(managed_count_second, 1)

    def test_configure_logging_debug_emits_formatted_output(self):
        buf = io.StringIO()
        with patch("lhub.logging_config.sys.stderr", buf):
            configure_logging(debug=True)
            test_logger = logging.getLogger("lhub.test_emit")
            test_logger.debug("structured debug line")

        output = buf.getvalue()
        self.assertIn("[DEBUG] lhub.test_emit: structured debug line", output)

    def test_parse_args_handles_debug_and_qt_passthrough(self):
        args, qt_args = parse_args(["--debug", "-platform", "offscreen"])
        self.assertTrue(args.debug)
        self.assertEqual(qt_args, ["-platform", "offscreen"])

        args_default, qt_args_default = parse_args([])
        self.assertFalse(args_default.debug)
        self.assertEqual(qt_args_default, [])

    def test_profile_manager_logs_corrupt_json(self):
        with tempfile.TemporaryDirectory() as td:
            conf = Path(td) / "profiles.json"
            conf.write_text("{corrupt json", encoding="utf-8")
            with self.assertLogs("lhub.profiles", level="WARNING") as cm:
                pm = ProfileManager(config_file=conf)
            self.assertEqual(pm.get_profiles("046d:c099"), ["Default"])
            self.assertTrue(any("Failed to load profiles" in msg for msg in cm.output))

    def test_hidpp_locate_logs_permission_error(self):
        with patch.dict(hidpp._cache, {}, clear=True), \
             patch("lhub.backends.hidpp._candidate_paths", return_value=["/dev/hidraw9"]), \
             patch("lhub.backends.hidpp.os.open", side_effect=PermissionError("Permission denied")):
            with self.assertLogs("lhub.backends.hidpp", level="WARNING") as cm:
                self.assertIsNone(hidpp._locate("046d", "c099", 0x2201))
            self.assertTrue(any("Permission denied opening /dev/hidraw9" in msg for msg in cm.output))

    def test_manager_scan_worker_logs_backend_exception(self):
        class BrokenBackend(BaseBackend):
            def __init__(self):
                super().__init__("broken")

            def is_available(self) -> bool:
                return True

            def scan_devices(self):
                raise RuntimeError("boom")

        mgr = DeviceManager(auto_refresh=False)
        mgr.backends = [BrokenBackend()]
        with patch.object(mgr, "_update_health_checks", return_value=[]):
            with self.assertLogs("lhub.manager", level="WARNING") as cm:
                mgr._scan_worker()
        self.assertTrue(any("Backend broken scan failed: boom" in msg for msg in cm.output))


class TestHealthChecks(unittest.TestCase):
    def _make_dbus_client(
        self,
        bus_ok=True,
        owners=None,
        activatable=None,
        api_version=2,
        get_prop_error=None,
    ):
        owners = set(owners or ())
        activatable = set(activatable or ())
        client = MagicMock()
        client.is_bus_available.return_value = bus_ok
        client.has_name_owner.side_effect = lambda svc: svc in owners
        client.is_service_activatable.side_effect = lambda svc: svc in activatable
        if get_prop_error is not None:
            client.get_property.side_effect = get_prop_error
        else:
            client.get_property.return_value = api_version
        return client

    def test_ratbagd_not_installed(self):
        client = self._make_dbus_client(bus_ok=True, owners=(), activatable=())
        with patch("lhub.health.shutil.which", return_value=None):
            item = check_ratbagd(dbus_client=client)
        self.assertEqual(item.id, "ratbagd")
        self.assertEqual(item.severity, SEVERITY_WARNING)
        self.assertTrue(item.is_issue)
        self.assertIn("sudo systemctl enable --now ratbagd", item.fix_hint)

    def test_ratbagd_installed_but_not_running(self):
        client = self._make_dbus_client(bus_ok=True, owners=(), activatable={RATBAG_SERVICE})
        item = check_ratbagd(dbus_client=client)
        self.assertEqual(item.severity, SEVERITY_ERROR)
        self.assertTrue(item.is_issue)
        self.assertEqual(item.fix_hint, RATBAGD_FIX_HINT)

    def test_ratbagd_bus_unavailable_timeout_and_call_error(self):
        no_bus = self._make_dbus_client(bus_ok=False)
        no_bus_item = check_ratbagd(dbus_client=no_bus)
        self.assertEqual(no_bus_item.severity, SEVERITY_ERROR)
        self.assertEqual(no_bus_item.fix_hint, RATBAGD_FIX_HINT)

        timeout_client = self._make_dbus_client(
            bus_ok=True,
            owners={RATBAG_SERVICE},
            get_prop_error=DBusTimeoutError("timed out"),
        )
        timeout_item = check_ratbagd(dbus_client=timeout_client)
        self.assertEqual(timeout_item.severity, SEVERITY_ERROR)
        self.assertEqual(timeout_item.fix_hint, RATBAGD_FIX_HINT)

        err_client = self._make_dbus_client(
            bus_ok=True,
            owners={RATBAG_SERVICE},
            get_prop_error=DBusCallError("org.freedesktop.DBus.Error.AccessDenied", "denied"),
        )
        err_item = check_ratbagd(dbus_client=err_client)
        self.assertEqual(err_item.severity, SEVERITY_ERROR)
        self.assertEqual(err_item.fix_hint, RATBAGD_FIX_HINT)

    def test_ratbagd_running_ok_via_dbus(self):
        client = self._make_dbus_client(bus_ok=True, owners={RATBAG_SERVICE}, api_version=2)
        item = check_ratbagd(dbus_client=client)
        self.assertEqual(item.severity, SEVERITY_OK)
        self.assertFalse(item.is_issue)
        self.assertEqual(item.fix_hint, "")

    def test_headsetcontrol_missing_non_executable_and_ok(self):
        with patch("lhub.health.shutil.which", return_value=None):
            missing = check_headsetcontrol()
        self.assertEqual(missing.severity, SEVERITY_WARNING)
        self.assertTrue(missing.is_issue)
        self.assertIn("headsetcontrol", missing.fix_hint)

        with patch("lhub.health.shutil.which", return_value="/usr/bin/headsetcontrol"), \
             patch("lhub.health.os.access", return_value=False):
            not_exec = check_headsetcontrol()
        self.assertEqual(not_exec.severity, SEVERITY_WARNING)
        self.assertTrue(not_exec.is_issue)

        with patch("lhub.health.shutil.which", return_value="/usr/bin/headsetcontrol"), \
             patch("lhub.health.os.access", return_value=True):
            ok = check_headsetcontrol()
        self.assertEqual(ok.severity, SEVERITY_OK)
        self.assertFalse(ok.is_issue)

    def test_hidraw_permission_error_logitech_device(self):
        uevent = (
            "DRIVER=hid-generic\n"
            "HID_ID=0003:0000046D:0000C099\n"
            "HID_NAME=Logitech G502 X\n"
        )
        with patch("lhub.health.glob.glob", return_value=["/sys/class/hidraw/hidraw6"]), \
             patch("builtins.open", mock_open(read_data=uevent)), \
             patch("lhub.health.os.open", side_effect=PermissionError("Permission denied")):
            item = check_hidraw_permissions()

        self.assertEqual(item.id, "hidraw")
        self.assertEqual(item.severity, SEVERITY_ERROR)
        self.assertTrue(item.is_issue)
        self.assertIn("Logitech G502 X", item.description)
        self.assertIn("/dev/hidraw6", item.description)
        self.assertIn("046d", item.fix_hint)
        self.assertIn("hidraw", item.fix_hint)
        self.assertIn("udevadm", item.fix_hint)

    def test_hidraw_permission_error_for_detected_non_logitech_headset(self):
        headset = Device(
            id="headset_1038_12ad",
            name="SteelSeries Arctis 7",
            vendor="SteelSeries",
            device_type=DeviceType.HEADSET,
            usb_vid="1038",
            usb_pid="12ad",
        )
        uevent = (
            "DRIVER=hid-generic\n"
            "HID_ID=0003:00001038:000012AD\n"
            "HID_NAME=SteelSeries Arctis 7\n"
        )
        with patch("lhub.health.glob.glob", return_value=["/sys/class/hidraw/hidraw2"]), \
             patch("builtins.open", mock_open(read_data=uevent)), \
             patch("lhub.health.os.open", side_effect=PermissionError("Permission denied")):
            item = check_hidraw_permissions(devices=[headset])

        self.assertEqual(item.severity, SEVERITY_ERROR)
        self.assertIn("1038", item.fix_hint)

    def test_hidraw_ignores_unrelated_devices_and_closes_accessible_fds(self):
        unrelated_uevent = (
            "DRIVER=hid-generic\n"
            "HID_ID=0003:00003434:00000861\n"
            "HID_NAME=Keychron Keychron Q6 Max\n"
        )
        with patch("lhub.health.glob.glob", return_value=["/sys/class/hidraw/hidraw0"]), \
             patch("builtins.open", mock_open(read_data=unrelated_uevent)), \
             patch("lhub.health.os.open", side_effect=PermissionError("Permission denied")) as m_open:
            item_ignored = check_hidraw_permissions()
        self.assertEqual(item_ignored.severity, SEVERITY_OK)
        m_open.assert_not_called()

        logi_uevent = (
            "DRIVER=hid-generic\n"
            "HID_ID=0003:0000046D:00000ABA\n"
            "HID_NAME=Logitech PRO X Wireless Gaming Headset\n"
        )
        with patch("lhub.health.glob.glob", return_value=["/sys/class/hidraw/hidraw3"]), \
             patch("builtins.open", mock_open(read_data=logi_uevent)), \
             patch("lhub.health.os.open", return_value=42) as m_open, \
             patch("lhub.health.os.close") as m_close:
            item_ok = check_hidraw_permissions()
        self.assertEqual(item_ok.severity, SEVERITY_OK)
        m_open.assert_called_once()
        m_close.assert_called_once_with(42)

    def test_upower_optional_and_all_ok(self):
        missing_client = self._make_dbus_client(bus_ok=True, owners=(), activatable=())
        missing = check_upower(dbus_client=missing_client)
        self.assertEqual(missing.severity, SEVERITY_INFO)
        self.assertFalse(missing.is_issue)

        activatable_client = self._make_dbus_client(bus_ok=True, owners=(), activatable={UPOWER_SERVICE})
        inactive = check_upower(dbus_client=activatable_client)
        self.assertEqual(inactive.severity, SEVERITY_INFO)
        self.assertFalse(inactive.is_issue)
        self.assertIn("upower", inactive.fix_hint)

        all_ok_client = self._make_dbus_client(
            bus_ok=True,
            owners={RATBAG_SERVICE, UPOWER_SERVICE},
            api_version=2,
        )
        logi_uevent = "HID_ID=0003:0000046D:0000C099\nHID_NAME=Logitech G502 X\n"
        with patch("lhub.health.shutil.which", return_value="/usr/bin/headsetcontrol"), \
             patch("lhub.health.os.access", return_value=True), \
             patch("lhub.health.glob.glob", return_value=["/sys/class/hidraw/hidraw6"]), \
             patch("builtins.open", mock_open(read_data=logi_uevent)), \
             patch("lhub.health.os.open", return_value=7), \
             patch("lhub.health.os.close"):
            items = run_health_checks(log_results=False, dbus_client=all_ok_client)

        self.assertEqual([i.id for i in items], ["ratbagd", "headsetcontrol", "hidraw", "upower"])
        self.assertTrue(all(i.severity == SEVERITY_OK for i in items))
        self.assertFalse(any(i.is_issue for i in items))


class TestDeviceManagerHealthIntegration(unittest.TestCase):
    def test_manager_exposes_sorted_health_issues_and_signals(self):
        mgr = DeviceManager(auto_refresh=False)
        emitted = []
        mgr.healthChecksChanged.connect(lambda: emitted.append(True))

        sample_items = [
            HealthCheckItem(id="ratbagd", severity=SEVERITY_WARNING, title="Missing ratbagctl", description="d1", fix_hint="hint1"),
            HealthCheckItem(id="headsetcontrol", severity=SEVERITY_OK, title="OK", description="d2"),
            HealthCheckItem(id="hidraw", severity=SEVERITY_ERROR, title="No hidraw perms", description="d3", fix_hint="hint3"),
            HealthCheckItem(id="upower", severity=SEVERITY_INFO, title="UPower optional", description="d4"),
        ]
        with patch("lhub.manager.run_health_checks", return_value=sample_items):
            mgr._update_health_checks([])

        self.assertEqual(len(emitted), 1)
        self.assertEqual(len(mgr.healthChecks), 4)
        self.assertTrue(mgr.hasHealthIssues)
        # Errors must come before warnings, and ok/info must be excluded
        self.assertEqual([i["id"] for i in mgr.healthIssues], ["hidraw", "ratbagd"])
        self.assertEqual(mgr.healthIssues[0]["fixHint"], "hint3")

    def test_manager_all_ok_or_info_only_has_no_health_issues(self):
        mgr = DeviceManager(auto_refresh=False)
        sample_items = [
            HealthCheckItem(id="ratbagd", severity=SEVERITY_OK, title="OK", description="ok"),
            HealthCheckItem(id="headsetcontrol", severity=SEVERITY_OK, title="OK", description="ok"),
            HealthCheckItem(id="hidraw", severity=SEVERITY_OK, title="OK", description="ok"),
            HealthCheckItem(id="upower", severity=SEVERITY_INFO, title="Optional", description="info"),
        ]
        with patch("lhub.manager.run_health_checks", return_value=sample_items):
            mgr._update_health_checks([])

        self.assertFalse(mgr.hasHealthIssues)
        self.assertEqual(mgr.healthIssues, [])

    def test_copy_to_clipboard(self):
        mgr = DeviceManager(auto_refresh=False)
        self.assertFalse(mgr.copyToClipboard(""))
        self.assertTrue(mgr.copyToClipboard("sudo systemctl enable --now ratbagd"))
        self.assertEqual(QGuiApplication.clipboard().text(), "sudo systemctl enable --now ratbagd")


if __name__ == "__main__":
    unittest.main()
