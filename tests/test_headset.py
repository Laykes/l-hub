import unittest
from unittest.mock import MagicMock, patch
import time

from lhub.backends.base import Capability, Device, DeviceType, BatteryInfo
from lhub.backends.headset import HeadsetBackend
from lhub.manager import DeviceManager


class TestHeadset(unittest.TestCase):
    def setUp(self):
        self.backend = HeadsetBackend()

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

    @patch.object(HeadsetBackend, "set_sidetone")
    def test_manager_set_sidetone_spawns_thread_and_calls_backend(self, mock_backend_sidetone):
        mgr = DeviceManager()
        dev = Device(
            id="headset_046d_0aba",
            name="Test Headset",
            vendor="Logitech",
            device_type=DeviceType.HEADSET,
            capabilities=[Capability.SIDETONE],
            sidetone=0,
            backend_name="headsetcontrol",
        )
        mgr._devices = [dev]
        mgr._cached_dict_devices = [mgr._device_to_dict(dev)]

        mgr.setSidetone("headset_046d_0aba", 50)
        # Immediate UI cache update
        self.assertEqual(mgr._cached_dict_devices[0]["sidetone"], 50)

        # Worker thread executes in background
        time.sleep(0.05)
        mock_backend_sidetone.assert_called_once_with("headset_046d_0aba", 50)


if __name__ == "__main__":
    unittest.main()
