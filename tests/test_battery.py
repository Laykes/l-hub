import time
import unittest
from unittest.mock import patch

from lhub.backends.base import Device, DeviceType, Capability, BatteryInfo
from lhub.backends.headset import HeadsetBackend, _estimate_logitech_charging_percentage
from lhub.manager import DeviceManager


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


if __name__ == "__main__":
    unittest.main()
