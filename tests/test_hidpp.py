import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lhub.backends import hidpp
from lhub.backends.base import Capability, Device, DeviceType, DpiInfo
from lhub.backends.ratbag import RatbagBackend
from lhub.manager import DeviceManager


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
            self.assertIsNone(hidpp.get_onboard_profile("3434", "0861"))
            mock_open.assert_not_called()


class TestHidppOnboardProfiles(unittest.TestCase):
    def test_format_onboard_profile(self):
        self.assertEqual(hidpp.format_onboard_profile(0x0001), "Profile 1")
        self.assertEqual(hidpp.format_onboard_profile(0x0003), "Profile 3")
        self.assertEqual(hidpp.format_onboard_profile(0x0102), "Profile 2 (Factory)")
        self.assertEqual(hidpp.format_onboard_profile(0x0205), "Profile 0x0205")

    def test_onboard_profile_index(self):
        self.assertEqual(hidpp.onboard_profile_index(0x0001), 0)
        self.assertEqual(hidpp.onboard_profile_index(0x0002), 1)
        self.assertEqual(hidpp.onboard_profile_index(0x0103), 2)
        self.assertIsNone(hidpp.onboard_profile_index(0x0000))
        self.assertIsNone(hidpp.onboard_profile_index(0x0201))
        self.assertIsNone(hidpp.onboard_profile_index(None))

    @patch("lhub.backends.ratbag.hidpp.get_dpi", return_value=1600)
    @patch("lhub.backends.ratbag.hidpp.get_onboard_profile", return_value=0x0001)
    @patch("subprocess.run")
    def test_inspect_device_uses_live_hidpp_profile_over_stale_ratbag_active(
        self, mock_run, mock_prof, mock_dpi
    ):
        info_out = (
            "chanting-squirrel - Logitech G502 X\n"
            "             Model: usb:046d:c099:0\n"
            " Number of Buttons: 11\n"
            "Profile 0:\n"
            "  Resolutions:\n"
            "    0: 1600dpi (active)\n"
            "  Button: 6 is mapped to 'wheel-left'\n"
            "Profile 1: (active)\n"
            "  Resolutions:\n"
            "    0: 1600dpi (active)\n"
            "  Button: 6 is mapped to key 'KEY_PLAYPAUSE'\n"
        )
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=info_out, stderr=""),
            MagicMock(returncode=0, stdout="1600dpi\n", stderr=""),
        ]
        backend = RatbagBackend()
        backend._ctl = "ratbagctl"
        dev = backend._inspect_device("chanting-squirrel", "Logitech G502 X")
        self.assertIsNotNone(dev)
        self.assertEqual(dev.onboard_profile_id, 0x0001)
        self.assertEqual(backend._active_profiles["chanting-squirrel"], 0)
        self.assertEqual(len(dev.buttons), 1)
        self.assertEqual(dev.buttons[0].action_value, "special wheel-left")

    @patch("lhub.backends.ratbag.time.sleep")
    @patch("lhub.backends.ratbag.hidpp.set_onboard_profile", return_value=True)
    @patch("lhub.backends.ratbag.hidpp.get_onboard_profile", return_value=0x0001)
    @patch("subprocess.run")
    def test_remap_button_targets_live_hidpp_profile_and_reloads(
        self, mock_run, mock_get_prof, mock_set_prof, mock_sleep
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        backend = RatbagBackend()
        backend._ctl = "ratbagctl"
        backend._usb_ids["mouse"] = ("046d", "c099")

        ok = backend.remap_button("mouse", 6, "key KEY_PLAYPAUSE")
        self.assertTrue(ok)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(
            cmd,
            ["ratbagctl", "mouse", "profile", "0", "button", "6", "action", "set", "key", "KEY_PLAYPAUSE"],
        )
        mock_sleep.assert_called_once()
        mock_set_prof.assert_called_once_with("046d", "c099", 0x0001)

    def test_parse_onboard_profile_change_events(self):
        # Long report: feature_idx=0x14, event=0, swid=0, profile=0x0002
        long_pkt = bytes([0x11, 0xFF, 0x14, 0x00, 0x00, 0x02]) + bytes(14)
        self.assertEqual(hidpp.parse_onboard_event(long_pkt, 0x14), ("profile", 0x0002))

        # Short report: feature_idx=0x14, event=0, swid=0, profile=0x0102
        short_pkt = bytes([0x10, 0xFF, 0x14, 0x00, 0x01, 0x02, 0x00])
        self.assertEqual(hidpp.parse_onboard_event(short_pkt, 0x14), ("profile", 0x0102))

        # Event 1: currentDPIIndexChanged
        dpi_pkt = bytes([0x11, 0xFF, 0x14, 0x10, 0x03, 0x00]) + bytes(14)
        self.assertEqual(hidpp.parse_onboard_event(dpi_pkt, 0x14), ("dpi_index", 3))

    def test_parse_onboard_event_ignores_replies_and_invalid_packets(self):
        # Non-zero SWID (reply to host request, not unsolicited event)
        reply_pkt = bytes([0x11, 0xFF, 0x14, 0x47, 0x00, 0x01]) + bytes(14)
        self.assertIsNone(hidpp.parse_onboard_event(reply_pkt, 0x14))

        # Wrong feature index
        wrong_feat = bytes([0x11, 0xFF, 0x12, 0x00, 0x00, 0x01]) + bytes(14)
        self.assertIsNone(hidpp.parse_onboard_event(wrong_feat, 0x14))

        # Zero profile ID
        zero_prof = bytes([0x11, 0xFF, 0x14, 0x00, 0x00, 0x00]) + bytes(14)
        self.assertIsNone(hidpp.parse_onboard_event(zero_prof, 0x14))

        # Truncated packet
        self.assertIsNone(hidpp.parse_onboard_event(bytes([0x11, 0xFF, 0x14, 0x00]), 0x14))

    @patch.object(DeviceManager, "refresh_devices")
    @patch("lhub.manager.hidpp.get_dpi", return_value=None)
    def test_manager_updates_onboard_profile_live_and_emits_signals(self, mock_dpi, mock_refresh):
        mgr = DeviceManager()
        dev = Device(
            id="chanting-squirrel",
            name="Logitech G502 X",
            vendor="Logitech",
            device_type=DeviceType.MOUSE,
            usb_vid="046d",
            usb_pid="c099",
            capabilities=[Capability.DPI, Capability.PROFILES],
            dpi=DpiInfo(current=1600, steps=[800, 1600, 3200]),
            onboard_profile_id=0x0001,
            onboard_profile="Profile 1",
            backend_name="ratbagd",
        )
        mgr._devices = [dev]
        mgr._cached_dict_devices = [mgr._device_to_dict(dev)]

        profile_events = []
        dev_changes = []
        mgr.onboardProfileChanged.connect(lambda n, p: profile_events.append((n, p)))
        mgr.devicesChanged.connect(lambda: dev_changes.append(True))

        # Profile changes from 0x0001 -> 0x0002
        mock_refresh.reset_mock()
        mgr._on_hidpp_profile_event("046d:c099", 0x0002)
        self.assertEqual(dev.onboard_profile_id, 0x0002)
        self.assertEqual(dev.onboard_profile, "Profile 2")
        self.assertEqual(mgr._cached_dict_devices[0]["onboardProfile"], "Profile 2")
        self.assertTrue(mgr._cached_dict_devices[0]["hasOnboardProfile"])
        self.assertEqual(profile_events, [("Logitech G502 X", "Profile 2")])
        self.assertEqual(len(dev_changes), 1)
        mock_refresh.assert_called_once()

        # Duplicate event for same profile does not re-emit
        mgr._on_hidpp_profile_event("046d:c099", 0x0002)
        self.assertEqual(len(profile_events), 1)
        self.assertEqual(len(dev_changes), 1)
        mock_refresh.assert_called_once()

        # Live DPI update event
        mgr._on_hidpp_dpi_event("046d:c099", 2400)
        self.assertEqual(dev.dpi.current, 2400)
        self.assertIn(2400, dev.dpi.steps)
        self.assertEqual(mgr._cached_dict_devices[0]["currentDpi"], 2400)
        self.assertEqual(len(dev_changes), 2)

        mgr.cleanup()


if __name__ == "__main__":
    unittest.main()
