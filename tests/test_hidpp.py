import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lhub.backends import hidpp
from lhub.backends.ratbag import RatbagBackend


class TestHidppDpi(unittest.TestCase):
    def setUp(self):
        self.backend = RatbagBackend()
        self.backend._usb_ids["mouse"] = ("046d", "c099")

    @patch("subprocess.run")
    @patch("lhub.backends.ratbag.hidpp.set_dpi", return_value=True)
    def test_set_dpi_uses_hidpp_and_skips_ratbagctl(self, mock_hidpp, mock_run):
        self.assertTrue(self.backend.set_dpi("mouse", 2400))
        mock_hidpp.assert_called_once_with("046d", "c099", 2400)
        mock_run.assert_not_called()

    @patch("subprocess.run")
    @patch("lhub.backends.ratbag.hidpp.set_dpi", return_value=False)
    def test_set_dpi_falls_back_to_ratbagctl(self, mock_hidpp, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        self.backend._ctl = "ratbagctl"
        self.backend._resolution_maps["mouse"] = {}
        self.assertTrue(self.backend.set_dpi("mouse", 2400))
        self.assertTrue(mock_run.called)

    @patch("subprocess.run")
    @patch("lhub.backends.ratbag.hidpp.get_dpi", return_value=1200)
    def test_get_dpi_prefers_hardware_value(self, mock_hidpp, mock_run):
        # ratbagd reports a stale/invalid value
        mock_run.return_value = MagicMock(returncode=0, stdout="65535dpi\n", stderr="")
        info = self.backend._get_dpi("mouse", ["Resolutions:", "0: 800dpi", "1: 1600dpi (active)"])
        self.assertEqual(info.current, 1200)
        self.assertIn(1200, info.steps)

    def test_never_touches_non_logitech_devices(self):
        with patch("lhub.backends.hidpp.os.open") as mock_open:
            self.assertIsNone(hidpp.get_dpi("3434", "0861"))
            self.assertFalse(hidpp.set_dpi("3434", "0861", 800))
            mock_open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
