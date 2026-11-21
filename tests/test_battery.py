import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QSystemTrayIcon

from lhub.backends.base import Device, DeviceType, Capability, BatteryInfo
from lhub.backends.headset import HeadsetBackend, _estimate_logitech_charging_percentage
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

        with patch.object(DeviceManager, "refresh_devices"):
            manager = DeviceManager()
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


if __name__ == "__main__":
    unittest.main()
