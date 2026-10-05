import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lhub.backends.base import Capability, Device, DeviceType, DpiInfo
from lhub.backends.ratbag import RatbagBackend
from lhub.manager import DeviceManager


class TestDpi(unittest.TestCase):
    def setUp(self):
        self.backend = RatbagBackend()

    @patch("subprocess.run")
    def test_get_dpi_parses_current_and_filters_uninitialized_steps(self, mock_run):
        # dpi get returns 1600dpi
        mock_run.return_value = MagicMock(returncode=0, stdout="1600dpi\n", stderr="")

        active_lines = [
            "Profile 2: (active)",
            "  Resolutions:",
            "    0: 1600dpi (active)",
            "    1: 65535dpi",
            "    2: 65535dpi",
        ]
        info = self.backend._get_dpi("test_mouse", active_lines)
        self.assertEqual(info.current, 1600)
        # 65535 should be filtered out, default presets [400, 800, 1600, 3200] should be provided
        self.assertEqual(info.steps, [400, 800, 1600, 3200])

    @patch("subprocess.run")
    def test_get_dpi_with_custom_hardware_steps(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="1200dpi\n", stderr="")

        active_lines = [
            "Profile 0: (active)",
            "  Resolutions:",
            "    0: 600dpi",
            "    1: 1200dpi (active)",
            "    2: 1800dpi",
            "    3: 2400dpi",
        ]
        info = self.backend._get_dpi("test_mouse", active_lines)
        self.assertEqual(info.current, 1200)
        self.assertEqual(info.steps, [600, 1200, 1800, 2400])

    @patch("subprocess.run")
    def test_set_dpi_recovers_missing_active_resolution(self, mock_run):
        # First call fails (e.g. no active resolution), resolution active set succeeds, second call succeeds
        def side_effect(cmd, **kwargs):
            if "resolution" in cmd and "active" in cmd:
                return MagicMock(returncode=0, stdout="", stderr="")
            if "dpi" in cmd and "set" in cmd:
                if side_effect.call_count == 0:
                    side_effect.call_count += 1
                    return MagicMock(returncode=1, stdout="", stderr="The device has no active resolution")
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        side_effect.call_count = 0
        mock_run.side_effect = side_effect

        with patch.object(self.backend, "is_available", return_value=True):
            success = self.backend.set_dpi("test_mouse", 1600)
            self.assertTrue(success)
            self.assertEqual(mock_run.call_count, 3)

    @patch.object(RatbagBackend, "set_dpi", return_value=True)
    def test_manager_set_dpi_updates_cache_immediately(self, mock_backend_set):
        mgr = DeviceManager()
        # Seed dummy device
        test_dev = Device(
            id="test_mouse_id",
            name="Test Mouse",
            vendor="Logitech",
            device_type=DeviceType.MOUSE,
            capabilities=[Capability.DPI],
            dpi=DpiInfo(current=800, steps=[400, 800, 1600, 3200]),
            backend_name="ratbag",
        )
        mgr._devices = [test_dev]
        mgr._cached_dict_devices = [mgr._device_to_dict(test_dev)]

        # Hook signal
        signal_emitted = []
        mgr.devicesChanged.connect(lambda: signal_emitted.append(True))

        success = mgr.setDpi("test_mouse_id", 1600)
        self.assertTrue(success)
        # Cached dict was updated
        self.assertEqual(mgr._cached_dict_devices[0]["currentDpi"], 1600)
        self.assertTrue(len(signal_emitted) > 0)

    @patch("subprocess.run")
    def test_set_dpi_uses_resolution_active_when_mapped(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        self.backend._resolution_maps["test_mouse"] = {800: 0, 1600: 1}

        with patch.object(self.backend, "is_available", return_value=True):
            success = self.backend.set_dpi("test_mouse", 1600)
            self.assertTrue(success)
            mock_run.assert_called_once()
            called_cmd = mock_run.call_args[0][0]
            self.assertIn("resolution", called_cmd)
            self.assertIn("active", called_cmd)
            self.assertIn("1", called_cmd)


if __name__ == "__main__":
    unittest.main()
