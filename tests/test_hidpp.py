import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lhub.backends import hidpp
from lhub.backends.base import Capability, Device, DeviceType, DpiInfo
from lhub.backends.ratbag import (
    RATBAG_BUTTON_IFACE,
    RATBAG_DEVICE_IFACE,
    RATBAG_PROFILE_IFACE,
    RATBAG_RESOLUTION_IFACE,
    RATBAG_SERVICE,
    RatbagActionType,
    RatbagBackend,
)
from lhub.manager import DeviceManager


def _make_dbus_mock(props_map):
    dbus = MagicMock()
    dbus.is_bus_available.return_value = True
    dbus.has_name_owner.return_value = True
    dbus.get_all_properties.side_effect = lambda svc, path, iface: dict(props_map.get((path, iface), {}))
    dbus.get_property.side_effect = lambda svc, path, iface, prop: props_map.get((path, iface), {}).get(prop)
    dbus.call_method.return_value = (0,)
    return dbus


class TestHidppDpi(unittest.TestCase):
    def test_set_dpi_uses_hidpp_and_skips_dbus(self):
        dbus = _make_dbus_mock({})
        backend = RatbagBackend(dbus_client=dbus)
        backend._usb_ids["mouse"] = ("046d", "c099")

        with patch("lhub.backends.ratbag.hidpp.set_dpi", return_value=True) as mock_hidpp:
            self.assertTrue(backend.set_dpi("mouse", 2400))
        mock_hidpp.assert_called_once_with("046d", "c099", 2400)
        dbus.set_property.assert_not_called()
        dbus.call_method.assert_not_called()

    @patch("lhub.backends.ratbag.hidpp.get_onboard_profile", return_value=None)
    @patch("lhub.backends.ratbag.hidpp.set_dpi", return_value=False)
    def test_set_dpi_falls_back_to_dbus(self, mock_hidpp, mock_get_prof):
        dev_path = "/org/freedesktop/ratbag1/device/mouse"
        r0_path = "/org/freedesktop/ratbag1/resolution/mouse/p0/r0"
        dbus = _make_dbus_mock({(r0_path, RATBAG_RESOLUTION_IFACE): {"Index": 0, "IsActive": True}})
        backend = RatbagBackend(dbus_client=dbus)
        backend._usb_ids["mouse"] = ("046d", "c099")
        backend._device_paths["mouse"] = dev_path
        backend._active_profiles["mouse"] = 0
        backend._profile_paths["mouse"] = {0: "/org/freedesktop/ratbag1/profile/mouse/p0"}
        backend._resolution_paths["mouse"] = {0: {0: r0_path}}
        backend._resolution_is_xy["mouse"] = {0: {0: False}}
        backend._resolution_maps["mouse"] = {}

        self.assertTrue(backend.set_dpi("mouse", 2400))
        dbus.set_property.assert_called_once_with(
            RATBAG_SERVICE, r0_path, RATBAG_RESOLUTION_IFACE, "Resolution", "v", ("u", 2400)
        )
        dbus.call_method.assert_called_once_with(RATBAG_SERVICE, dev_path, RATBAG_DEVICE_IFACE, "Commit")

    @patch("lhub.backends.ratbag.hidpp.get_dpi", return_value=1200)
    def test_get_dpi_prefers_hardware_value(self, mock_hidpp):
        props_map = {
            ("/r0", RATBAG_RESOLUTION_IFACE): {"Index": 0, "Resolution": ("u", 800), "IsActive": False},
            ("/r1", RATBAG_RESOLUTION_IFACE): {"Index": 1, "Resolution": ("u", 65535), "IsActive": True},
        }
        backend = RatbagBackend(dbus_client=_make_dbus_mock(props_map))
        backend._usb_ids["mouse"] = ("046d", "c099")
        info = backend._read_dpi("mouse", ["/r0", "/r1"], profile_idx=0)
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
    def test_inspect_device_uses_live_hidpp_profile_over_stale_ratbag_active(
        self, mock_prof, mock_dpi
    ):
        dev_path = "/org/freedesktop/ratbag1/device/hidraw6"
        p0 = "/org/freedesktop/ratbag1/profile/hidraw6/p0"
        p1 = "/org/freedesktop/ratbag1/profile/hidraw6/p1"
        props_map = {
            (dev_path, RATBAG_DEVICE_IFACE): {
                "Name": "Logitech G502 X",
                "Model": "usb:046d:c099:0",
                "DeviceType": 2,
                "Profiles": [p0, p1],
            },
            (p0, RATBAG_PROFILE_IFACE): {
                "Index": 0,
                "Disabled": False,
                "IsActive": False,
                "Resolutions": ["/r0"],
                "Buttons": ["/p0/b6"],
            },
            (p1, RATBAG_PROFILE_IFACE): {
                "Index": 1,
                "Disabled": False,
                "IsActive": True,
                "Resolutions": ["/r1"],
                "Buttons": ["/p1/b6"],
            },
            ("/r0", RATBAG_RESOLUTION_IFACE): {"Index": 0, "Resolution": ("u", 1600), "IsActive": True},
            ("/r1", RATBAG_RESOLUTION_IFACE): {"Index": 0, "Resolution": ("u", 1600), "IsActive": True},
            ("/p0/b6", RATBAG_BUTTON_IFACE): {
                "Index": 6,
                "Mapping": (int(RatbagActionType.SPECIAL), ("u", (1 << 30) + 2)),  # wheel-left
            },
            ("/p1/b6", RATBAG_BUTTON_IFACE): {
                "Index": 6,
                "Mapping": (int(RatbagActionType.KEY), ("u", 164)),  # KEY_PLAYPAUSE
            },
        }
        backend = RatbagBackend(dbus_client=_make_dbus_mock(props_map))
        dev = backend._inspect_device("ratbag_hidraw6", dev_path)
        self.assertIsNotNone(dev)
        self.assertEqual(dev.onboard_profile_id, 0x0001)
        self.assertEqual(backend._active_profiles["ratbag_hidraw6"], 0)
        self.assertEqual(len(dev.buttons), 1)
        self.assertEqual(dev.buttons[0].action_value, "special wheel-left")

    @patch("lhub.backends.ratbag.time.sleep")
    @patch("lhub.backends.ratbag.hidpp.set_onboard_profile", return_value=True)
    @patch("lhub.backends.ratbag.hidpp.get_onboard_profile", return_value=0x0001)
    def test_remap_button_targets_live_hidpp_profile_and_reloads(
        self, mock_get_prof, mock_set_prof, mock_sleep
    ):
        dev_path = "/org/freedesktop/ratbag1/device/mouse"
        btn_path = "/org/freedesktop/ratbag1/button/mouse/p0/b6"
        dbus = _make_dbus_mock({})
        backend = RatbagBackend(dbus_client=dbus)
        backend._usb_ids["mouse"] = ("046d", "c099")
        backend._device_paths["mouse"] = dev_path
        backend._profile_paths["mouse"] = {0: "/org/freedesktop/ratbag1/profile/mouse/p0"}
        backend._button_paths["mouse"] = {0: {6: btn_path}}
        backend._resolution_paths["mouse"] = {0: {}}
        backend._resolution_is_xy["mouse"] = {0: {}}

        ok = backend.remap_button("mouse", 6, "key KEY_PLAYPAUSE")
        self.assertTrue(ok)
        dbus.set_property.assert_called_once_with(
            RATBAG_SERVICE,
            btn_path,
            RATBAG_BUTTON_IFACE,
            "Mapping",
            "(uv)",
            (int(RatbagActionType.KEY), ("u", 164)),
        )
        dbus.call_method.assert_called_once_with(RATBAG_SERVICE, dev_path, RATBAG_DEVICE_IFACE, "Commit")
        mock_sleep.assert_called_once()
        mock_set_prof.assert_called_once_with("046d", "c099", 0x0001)

    def test_parse_onboard_profile_change_events(self):
        long_pkt = bytes([0x11, 0xFF, 0x14, 0x00, 0x00, 0x02]) + bytes(14)
        self.assertEqual(hidpp.parse_onboard_event(long_pkt, 0x14), ("profile", 0x0002))

        short_pkt = bytes([0x10, 0xFF, 0x14, 0x00, 0x01, 0x02, 0x00])
        self.assertEqual(hidpp.parse_onboard_event(short_pkt, 0x14), ("profile", 0x0102))

        dpi_pkt = bytes([0x11, 0xFF, 0x14, 0x10, 0x03, 0x00]) + bytes(14)
        self.assertEqual(hidpp.parse_onboard_event(dpi_pkt, 0x14), ("dpi_index", 3))

    def test_parse_onboard_event_ignores_replies_and_invalid_packets(self):
        reply_pkt = bytes([0x11, 0xFF, 0x14, 0x47, 0x00, 0x01]) + bytes(14)
        self.assertIsNone(hidpp.parse_onboard_event(reply_pkt, 0x14))

        wrong_feat = bytes([0x11, 0xFF, 0x12, 0x00, 0x00, 0x01]) + bytes(14)
        self.assertIsNone(hidpp.parse_onboard_event(wrong_feat, 0x14))

        zero_prof = bytes([0x11, 0xFF, 0x14, 0x00, 0x00, 0x00]) + bytes(14)
        self.assertIsNone(hidpp.parse_onboard_event(zero_prof, 0x14))

        self.assertIsNone(hidpp.parse_onboard_event(bytes([0x11, 0xFF, 0x14, 0x00]), 0x14))

    @patch.object(DeviceManager, "refresh_devices")
    @patch("lhub.manager.hidpp.get_dpi", return_value=None)
    def test_manager_updates_onboard_profile_live_and_emits_signals(self, mock_dpi, mock_refresh):
        mgr = DeviceManager(auto_refresh=False, enable_hotplug=False)
        self.addCleanup(mgr.cleanup)
        dev = Device(
            id="ratbag_hidraw6",
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

        mock_refresh.reset_mock()
        mgr._on_hidpp_profile_event("046d:c099", 0x0002)
        self.assertEqual(dev.onboard_profile_id, 0x0002)
        self.assertEqual(dev.onboard_profile, "Profile 2")
        self.assertEqual(mgr._cached_dict_devices[0]["onboardProfile"], "Profile 2")
        self.assertTrue(mgr._cached_dict_devices[0]["hasOnboardProfile"])
        self.assertEqual(profile_events, [("Logitech G502 X", "Profile 2")])
        self.assertEqual(len(dev_changes), 1)
        mock_refresh.assert_called_once()

        mgr._on_hidpp_profile_event("046d:c099", 0x0002)
        self.assertEqual(len(profile_events), 1)
        self.assertEqual(len(dev_changes), 1)
        mock_refresh.assert_called_once()

        mgr._on_hidpp_dpi_event("046d:c099", 2400)
        self.assertEqual(dev.dpi.current, 2400)
        self.assertIn(2400, dev.dpi.steps)
        self.assertEqual(mgr._cached_dict_devices[0]["currentDpi"], 2400)
        self.assertEqual(len(dev_changes), 2)


if __name__ == "__main__":
    unittest.main()
