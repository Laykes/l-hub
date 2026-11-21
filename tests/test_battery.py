import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QSystemTrayIcon

from lhub.backends.base import Device, DeviceType, Capability, BatteryInfo
from lhub.backends.dbus_client import DBUS_PROPERTIES_IFACE, DBusSignalEvent
from lhub.backends.headset import HeadsetBackend, _estimate_logitech_charging_percentage
from lhub.backends.upower import (
    UPOWER_DEVICE_IFACE,
    UPOWER_DISPLAY_DEVICE_PATH,
    UPOWER_IFACE,
    UPOWER_PATH,
    UPOWER_SERVICE,
    UPowerBackend,
)
from lhub.manager import DeviceManager
from lhub.tray import LHubTray


class TestBatteryHandling(unittest.TestCase):
    def setUp(self):
        self.backend = HeadsetBackend()
        self.dev_id = "headset_046d_0aba"
        self.vendor = "Logitech"

    def test_logitech_charge_curve_estimation(self):
        # 4081 mV (the reading from user's headset) should estimate around 50%, not 89%
        self.assertEqual(_estimate_logitech_charging_percentage(4081), 50)
        self.assertEqual(_estimate_logitech_charging_percentage(4020), 20)
        self.assertEqual(_estimate_logitech_charging_percentage(4195), 100)
        self.assertEqual(_estimate_logitech_charging_percentage(3700), 0)

    def test_battery_discharging_to_charging_no_spike(self):
        t0 = 1000.0

        # Step 1: Discharging at 20%
        with patch("time.time", return_value=t0):
            bat_info = self.backend._process_battery_info(
                self.dev_id,
                self.vendor,
                {
                    "status": "BATTERY_AVAILABLE",
                    "level": 20,
                    "voltage_mv": 3740,
                },
            )
            self.assertEqual(bat_info.percentage, 20)
            self.assertFalse(bat_info.is_charging)
            self.assertEqual(bat_info.time_to_empty_min, 180)

        # Step 2: Plugged into charger!
        # When charging, headset battery percentage is unreliable; must report -1 ("Charging")
        with patch("time.time", return_value=t0 + 2.0):
            bat_info2 = self.backend._process_battery_info(
                self.dev_id,
                self.vendor,
                {
                    "status": "BATTERY_CHARGING",
                    "level": 87,
                    "voltage_mv": 4069,
                    "time_to_full_min": 15,
                },
            )
            self.assertEqual(bat_info2.percentage, -1)
            self.assertTrue(bat_info2.is_charging)
            self.assertIsNone(bat_info2.time_to_full_min)

        # Step 3: Rapid refreshes while charging stay -1
        for i in range(1, 6):
            with patch("time.time", return_value=t0 + 2.0 + i):
                bat_info_refresh = self.backend._process_battery_info(
                    self.dev_id,
                    self.vendor,
                    {
                        "status": "BATTERY_CHARGING",
                        "level": 89,
                        "voltage_mv": 4081,
                    },
                )
                self.assertEqual(bat_info_refresh.percentage, -1)
                self.assertTrue(bat_info_refresh.is_charging)

        # Step 4: Full battery detection reports 100%
        with patch("time.time", return_value=t0 + 2.0 + 1800.0):
            bat_info_full = self.backend._process_battery_info(
                self.dev_id,
                self.vendor,
                {
                    "status": "BATTERY_FULL",
                    "level": 100,
                    "voltage_mv": 4210,
                },
            )
            self.assertEqual(bat_info_full.percentage, 100)
            self.assertEqual(bat_info_full.time_to_full_min, 0)

        # Step 5: Unplugging from charger reports valid discharging level
        with patch("time.time", return_value=t0 + 1805.0):
            bat_info_unplug = self.backend._process_battery_info(
                self.dev_id,
                self.vendor,
                {
                    "status": "BATTERY_AVAILABLE",
                    "level": 90,
                    "voltage_mv": 4010,
                },
            )
            self.assertEqual(bat_info_unplug.percentage, 90)
            self.assertFalse(bat_info_unplug.is_charging)

    def test_cold_start_while_charging(self):
        # Fresh backend instance without prior discharging state
        fresh_backend = HeadsetBackend()
        t0 = 2000.0
        with patch("time.time", return_value=t0):
            bat_info = fresh_backend._process_battery_info(
                self.dev_id,
                self.vendor,
                {
                    "status": "BATTERY_CHARGING",
                    "level": 89,
                    "voltage_mv": 4081,
                },
            )
            # Should be -1 (Charging)
            self.assertEqual(bat_info.percentage, -1)
            self.assertTrue(bat_info.is_charging)

    def test_manager_battery_time_remaining_formatting(self):
        # We don't need a running Qt application for _device_to_dict
        dev_discharging = Device(
            id="dev1",
            name="Test Headset",
            vendor="Logitech",
            device_type=DeviceType.HEADSET,
            capabilities=[Capability.BATTERY],
            battery=BatteryInfo(percentage=20, is_charging=False, time_to_empty_min=180),
        )
        dev_charging = Device(
            id="dev2",
            name="Test Headset",
            vendor="Logitech",
            device_type=DeviceType.HEADSET,
            capabilities=[Capability.BATTERY],
            battery=BatteryInfo(percentage=20, is_charging=True, time_to_full_min=104),
        )
        dev_full = Device(
            id="dev3",
            name="Test Headset",
            vendor="Logitech",
            device_type=DeviceType.HEADSET,
            capabilities=[Capability.BATTERY],
            battery=BatteryInfo(percentage=100, is_charging=True, time_to_full_min=0),
        )

        manager = DeviceManager(auto_refresh=False, enable_hotplug=False)
        self.addCleanup(manager.cleanup)
        d_discharging = manager._device_to_dict(dev_discharging)
        self.assertEqual(d_discharging["batteryTimeRemaining"], "~3 hr 0 min")

        d_charging = manager._device_to_dict(dev_charging)
        self.assertEqual(d_charging["batteryTimeRemaining"], "Full in ~1 hr 44 min")

        d_full = manager._device_to_dict(dev_full)
        self.assertEqual(d_full["batteryTimeRemaining"], "Fully charged")

    def _make_battery_device(
        self,
        dev_id: str = "headset_046d_0aba",
        name: str = "Logitech PRO X Wireless",
        percentage: int = 50,
        is_charging: bool = False,
        is_supported: bool = True,
        vid: str = "046d",
        pid: str = "0aba",
    ) -> Device:
        return Device(
            id=dev_id,
            name=name,
            vendor="Logitech",
            device_type=DeviceType.HEADSET,
            usb_vid=vid,
            usb_pid=pid,
            capabilities=[Capability.BATTERY],
            battery=BatteryInfo(
                percentage=percentage,
                is_charging=is_charging,
                is_supported=is_supported,
            ),
        )

    def test_low_battery_warning_threshold_and_hysteresis(self):
        manager = DeviceManager(auto_refresh=False)
        warnings = []
        manager.batteryWarning.connect(lambda name, pct: warnings.append((name, pct)))

        # 21% -> no warning
        manager._check_battery_warnings([self._make_battery_device(percentage=21)])
        self.assertEqual(warnings, [])

        # 20% -> triggers warning once
        manager._check_battery_warnings([self._make_battery_device(percentage=20)])
        self.assertEqual(warnings, [("Logitech PRO X Wireless", 20)])

        # Repeated poll at 19% -> no duplicate
        manager._check_battery_warnings([self._make_battery_device(percentage=19)])
        self.assertEqual(len(warnings), 1)

        # Minor fluctuation up to 25% and back to 20% -> hysteresis prevents spam
        manager._check_battery_warnings([self._make_battery_device(percentage=25)])
        manager._check_battery_warnings([self._make_battery_device(percentage=20)])
        self.assertEqual(len(warnings), 1)

        # Above 25% resets warning state; dropping to <= 20% triggers again
        manager._check_battery_warnings([self._make_battery_device(percentage=26)])
        manager._check_battery_warnings([self._make_battery_device(percentage=15)])
        self.assertEqual(
            warnings,
            [("Logitech PRO X Wireless", 20), ("Logitech PRO X Wireless", 15)],
        )

    def test_low_battery_warning_resets_on_charging_and_ignores_invalid(self):
        manager = DeviceManager(auto_refresh=False)
        warnings = []
        manager.batteryWarning.connect(lambda name, pct: warnings.append((name, pct)))

        # Charging at 15%, unsupported, or unknown (-1) must not trigger
        manager._check_battery_warnings([
            self._make_battery_device(percentage=15, is_charging=True),
            self._make_battery_device(dev_id="d2", name="Off Headset", percentage=10, is_supported=False, vid="", pid=""),
            self._make_battery_device(dev_id="d3", name="Unknown", percentage=-1, vid="", pid=""),
        ])
        self.assertEqual(warnings, [])

        # Discharging at 0% triggers
        manager._check_battery_warnings([self._make_battery_device(percentage=0)])
        self.assertEqual(warnings, [("Logitech PRO X Wireless", 0)])

        # Plugging into charger resets warned state
        manager._check_battery_warnings([self._make_battery_device(percentage=-1, is_charging=True)])
        # Unplugging back at 18% warns again
        manager._check_battery_warnings([self._make_battery_device(percentage=18, is_charging=False)])
        self.assertEqual(
            warnings,
            [("Logitech PRO X Wireless", 0), ("Logitech PRO X Wireless", 18)],
        )

    def test_auto_refresh_false_defers_initial_scan(self):
        with patch.object(DeviceManager, "refresh_devices") as mock_refresh:
            DeviceManager(auto_refresh=False)
            mock_refresh.assert_not_called()

    def test_tray_notify_uses_tray_and_falls_back_to_notify_send(self):
        tray_obj = LHubTray.__new__(LHubTray)
        tray_obj.tray = MagicMock()
        tray_obj.tray.isVisible.return_value = True

        with patch.object(QSystemTrayIcon, "supportsMessages", return_value=True):
            tray_obj._on_battery_warning("Test Headset", 20)
            tray_obj.tray.showMessage.assert_called_once_with(
                "Low Battery",
                "Test Headset battery is down to 20%!",
                QSystemTrayIcon.Warning,
                6000,
            )

        tray_obj.tray.reset_mock()
        tray_obj.tray.isVisible.return_value = False
        with patch("lhub.tray.shutil.which", return_value="/usr/bin/notify-send"), \
             patch("lhub.tray.subprocess.Popen") as mock_popen:
            tray_obj._on_battery_warning("Test Headset", 15)
            tray_obj.tray.showMessage.assert_not_called()
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            self.assertEqual(cmd[0], "/usr/bin/notify-send")
            self.assertIn("Low Battery", cmd)
            self.assertIn("Test Headset battery is down to 15%!", cmd)


class TestUPowerDBusBackend(unittest.TestCase):
    def test_scan_devices_enumerates_peripherals_and_filters_power_supplies(self):
        mouse_path = "/org/freedesktop/UPower/devices/mouse_hidpp_battery_0"
        kb_path = "/org/freedesktop/UPower/devices/keyboard_dev_aa_bb_cc"
        ctrl_path = "/org/freedesktop/UPower/devices/battery_ps_controller_battery_1"
        headset_path = "/org/freedesktop/UPower/devices/headset_dev_11_22"
        bt_path = "/org/freedesktop/UPower/devices/bluetooth_generic_dev_33"
        laptop_bat = "/org/freedesktop/UPower/devices/battery_BAT0"
        line_ac = "/org/freedesktop/UPower/devices/line_power_AC"
        absent_mouse = "/org/freedesktop/UPower/devices/mouse_absent"

        props_by_path = {
            mouse_path: {
                "Type": 5,
                "PowerSupply": False,
                "IsPresent": True,
                "Model": "Logitech MX Master 3S",
                "Vendor": "Logitech",
                "Percentage": 64.6,
                "State": 2,
                "TimeToEmpty": 7200,
                "TimeToFull": 0,
                "NativePath": "/sys/devices/pci0000:00/0003:046D:B034.0002/power_supply/hidpp_battery_0",
            },
            kb_path: {
                "Type": 6,
                "PowerSupply": False,
                "IsPresent": True,
                "Model": "Keychron K8",
                "Vendor": "",
                "Percentage": 30.0,
                "State": 1,
                "TimeToEmpty": 0,
                "TimeToFull": 3600,
                "NativePath": "/sys/devices/virtual/misc/uhid/0005:3434:0280.0004/power_supply/bat",
            },
            ctrl_path: {
                "Type": 12,
                "PowerSupply": False,
                "IsPresent": True,
                "Model": "Sony Interactive Entertainment Wireless Controller",
                "Vendor": "",
                "Percentage": 100.0,
                "State": 4,  # Fully charged -> must NOT mark is_charging=True
                "TimeToEmpty": 0,
                "TimeToFull": 0,
                "NativePath": "ps-controller-battery-f4:93:9f:b9:9f:ef",
            },
            headset_path: {
                "Type": 17,
                "PowerSupply": False,
                "IsPresent": True,
                "Model": "SteelSeries Arctis Nova",
                "Vendor": "SteelSeries",
                "Percentage": 80.0,
                "State": 5,  # Pending charge
                "NativePath": "",
            },
            bt_path: {
                "Type": 28,
                "PowerSupply": False,
                "IsPresent": True,
                "Model": "Generic BT Peripheral",
                "Vendor": "Generic",
                "Percentage": 55.0,
                "State": 2,
                "NativePath": "",
            },
            laptop_bat: {
                "Type": 2,
                "PowerSupply": True,
                "IsPresent": True,
                "Model": "BAT0",
                "Percentage": 90.0,
                "State": 2,
            },
            absent_mouse: {
                "Type": 5,
                "PowerSupply": False,
                "IsPresent": False,
                "Model": "Absent Mouse",
                "Percentage": 0.0,
                "State": 0,
            },
        }

        dbus = MagicMock()
        dbus.is_bus_available.return_value = True
        dbus.has_name_owner.return_value = True
        dbus.call_method.return_value = (
            [
                UPOWER_DISPLAY_DEVICE_PATH,
                line_ac,
                laptop_bat,
                absent_mouse,
                mouse_path,
                kb_path,
                ctrl_path,
                headset_path,
                bt_path,
            ],
        )
        dbus.get_all_properties.side_effect = lambda svc, path, iface: dict(props_by_path.get(path, {}))

        backend = UPowerBackend(dbus_client=dbus)
        devices = backend.scan_devices()
        by_id = {d.id: d for d in devices}

        self.assertEqual(len(devices), 5)
        self.assertNotIn("upower_battery_BAT0", by_id)
        self.assertNotIn("upower_DisplayDevice", by_id)
        self.assertNotIn("upower_line_power_AC", by_id)
        self.assertNotIn("upower_mouse_absent", by_id)

        mouse = by_id["upower_mouse_hidpp_battery_0"]
        self.assertEqual(mouse.device_type, DeviceType.MOUSE)
        self.assertEqual(mouse.usb_vid, "046d")
        self.assertEqual(mouse.usb_pid, "b034")
        self.assertEqual(mouse.battery.percentage, 65)
        self.assertFalse(mouse.battery.is_charging)
        self.assertEqual(mouse.battery.time_to_empty_min, 120)
        self.assertEqual(mouse.battery.status_text, "Discharging")

        kb = by_id["upower_keyboard_dev_aa_bb_cc"]
        self.assertEqual(kb.device_type, DeviceType.KEYBOARD)
        self.assertEqual(kb.vendor, "Keychron")
        self.assertEqual(kb.usb_vid, "3434")
        self.assertEqual(kb.usb_pid, "0280")
        self.assertTrue(kb.battery.is_charging)
        self.assertEqual(kb.battery.time_to_full_min, 60)

        ctrl = by_id["upower_battery_ps_controller_battery_1"]
        self.assertEqual(ctrl.device_type, DeviceType.OTHER)
        self.assertEqual(ctrl.battery.percentage, 100)
        self.assertFalse(ctrl.battery.is_charging)
        self.assertEqual(ctrl.battery.status_text, "Fully charged")

        headset = by_id["upower_headset_dev_11_22"]
        self.assertEqual(headset.device_type, DeviceType.HEADSET)
        self.assertTrue(headset.battery.is_charging)
        self.assertEqual(headset.battery.status_text, "Pending charge")

        self.assertIn(laptop_bat, backend._ignored_paths)

    def test_hotplug_signal_subscriptions_and_filtering(self):
        callbacks = []
        sub_counter = {"n": 0}

        def fake_subscribe(svc, path, iface, sig, cb):
            sub_counter["n"] += 1
            callbacks.append((svc, path, iface, sig, cb, sub_counter["n"]))
            return sub_counter["n"]

        dbus = MagicMock()
        dbus.subscribe_signal.side_effect = fake_subscribe
        backend = UPowerBackend(dbus_client=dbus)
        backend._ignored_paths.add("/org/freedesktop/UPower/devices/battery_BAT0")

        changes = []
        self.assertTrue(backend.supports_hotplug)
        self.assertTrue(backend.start_monitoring(lambda: changes.append(True)))
        self.assertEqual(len(callbacks), 4)

        by_sig = {(iface, sig): cb for _svc, _path, iface, sig, cb, _sid in callbacks}

        # DisplayDevice and ignored PowerSupply paths must be ignored on PropertiesChanged
        prop_cb = by_sig[(DBUS_PROPERTIES_IFACE, "PropertiesChanged")]
        prop_cb(DBusSignalEvent(UPOWER_SERVICE, UPOWER_DISPLAY_DEVICE_PATH, DBUS_PROPERTIES_IFACE, "PropertiesChanged", (UPOWER_DEVICE_IFACE,)))
        prop_cb(DBusSignalEvent(UPOWER_SERVICE, "/org/freedesktop/UPower/devices/battery_BAT0", DBUS_PROPERTIES_IFACE, "PropertiesChanged", (UPOWER_DEVICE_IFACE,)))
        self.assertEqual(len(changes), 0)

        # Peripheral PropertiesChanged triggers callback
        prop_cb(DBusSignalEvent(UPOWER_SERVICE, "/org/freedesktop/UPower/devices/mouse_1", DBUS_PROPERTIES_IFACE, "PropertiesChanged", (UPOWER_DEVICE_IFACE,)))
        self.assertEqual(len(changes), 1)

        # DeviceAdded & DeviceRemoved trigger callback
        by_sig[(UPOWER_IFACE, "DeviceAdded")](
            DBusSignalEvent(UPOWER_SERVICE, UPOWER_PATH, UPOWER_IFACE, "DeviceAdded", ("/org/freedesktop/UPower/devices/mouse_2",))
        )
        by_sig[(UPOWER_IFACE, "DeviceRemoved")](
            DBusSignalEvent(UPOWER_SERVICE, UPOWER_PATH, UPOWER_IFACE, "DeviceRemoved", ("/org/freedesktop/UPower/devices/mouse_2",))
        )
        self.assertEqual(len(changes), 3)

        backend.stop_monitoring()
        self.assertEqual(dbus.unsubscribe_signal.call_count, 4)


if __name__ == "__main__":
    unittest.main()
