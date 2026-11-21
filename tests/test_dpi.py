import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lhub.backends.base import Capability, Device, DeviceType, DpiInfo
from lhub.backends.dbus_client import DBusCallError
from lhub.backends.ratbag import (
    RATBAG_DEVICE_IFACE,
    RATBAG_RESOLUTION_IFACE,
    RATBAG_SERVICE,
    RatbagBackend,
)
from lhub.manager import DeviceManager


def _make_dbus_mock(props_map, call_side_effect=None, set_side_effect=None):
    dbus = MagicMock()
    dbus.is_bus_available.return_value = True
    dbus.has_name_owner.return_value = True
    dbus.get_all_properties.side_effect = lambda svc, path, iface: dict(props_map.get((path, iface), {}))
    dbus.get_property.side_effect = lambda svc, path, iface, prop: props_map.get((path, iface), {}).get(prop)
    if call_side_effect is not None:
        dbus.call_method.side_effect = call_side_effect
    else:
        dbus.call_method.return_value = (0,)
    if set_side_effect is not None:
        dbus.set_property.side_effect = set_side_effect
    return dbus


class TestDpi(unittest.TestCase):
    def test_get_dpi_parses_current_and_filters_uninitialized_steps(self):
        props_map = {
            ("/dev/r0", RATBAG_RESOLUTION_IFACE): {
                "Index": 0,
                "Resolution": ("u", 1600),
                "Resolutions": [400, 800, 1600, 3200],
                "IsActive": True,
                "IsDisabled": False,
            },
            ("/dev/r1", RATBAG_RESOLUTION_IFACE): {
                "Index": 1,
                "Resolution": ("u", 65535),
                "IsActive": False,
                "IsDisabled": False,
            },
            ("/dev/r2", RATBAG_RESOLUTION_IFACE): {
                "Index": 2,
                "Resolution": ("u", 65535),
                "IsActive": False,
                "IsDisabled": False,
            },
        }
        backend = RatbagBackend(dbus_client=_make_dbus_mock(props_map))
        info = backend._read_dpi("test_mouse", ["/dev/r0", "/dev/r1", "/dev/r2"], profile_idx=2)
        self.assertEqual(info.current, 1600)
        # 65535 should be filtered out, default presets [400, 800, 1600, 3200] should be provided
        self.assertEqual(info.steps, [400, 800, 1600, 3200])
        self.assertEqual(info.min_dpi, 400)
        self.assertEqual(info.max_dpi, 3200)

    def test_get_dpi_supports_separate_xy_resolution_tuples(self):
        props_map = {
            ("/dev/r0", RATBAG_RESOLUTION_IFACE): {
                "Index": 0,
                "Resolution": ("(uu)", (1200, 1200)),
                "IsActive": True,
                "IsDisabled": False,
            },
        }
        backend = RatbagBackend(dbus_client=_make_dbus_mock(props_map))
        info = backend._read_dpi("test_mouse", ["/dev/r0"], profile_idx=0)
        self.assertEqual(info.current, 1200)
        self.assertTrue(backend._resolution_is_xy["test_mouse"][0][0])

    def test_get_dpi_with_custom_hardware_steps(self):
        props_map = {
            ("/dev/r0", RATBAG_RESOLUTION_IFACE): {"Index": 0, "Resolution": ("u", 600), "IsActive": False},
            ("/dev/r1", RATBAG_RESOLUTION_IFACE): {"Index": 1, "Resolution": ("u", 1200), "IsActive": True},
            ("/dev/r2", RATBAG_RESOLUTION_IFACE): {"Index": 2, "Resolution": ("u", 1800), "IsActive": False},
            ("/dev/r3", RATBAG_RESOLUTION_IFACE): {"Index": 3, "Resolution": ("u", 2400), "IsActive": False},
        }
        backend = RatbagBackend(dbus_client=_make_dbus_mock(props_map))
        info = backend._read_dpi("test_mouse", ["/dev/r0", "/dev/r1", "/dev/r2", "/dev/r3"], profile_idx=0)
        self.assertEqual(info.current, 1200)
        self.assertEqual(info.steps, [600, 1200, 1800, 2400])

    def test_set_dpi_uses_resolution_active_when_mapped(self):
        dev_path = "/org/freedesktop/ratbag1/device/mouse"
        r1_path = "/org/freedesktop/ratbag1/resolution/mouse/p0/r1"
        dbus = _make_dbus_mock({(r1_path, RATBAG_RESOLUTION_IFACE): {"Index": 1, "IsActive": False}})
        backend = RatbagBackend(dbus_client=dbus)
        backend._device_paths["test_mouse"] = dev_path
        backend._active_profiles["test_mouse"] = 0
        backend._profile_paths["test_mouse"] = {0: "/org/freedesktop/ratbag1/profile/mouse/p0"}
        backend._resolution_paths["test_mouse"] = {
            0: {
                0: "/org/freedesktop/ratbag1/resolution/mouse/p0/r0",
                1: r1_path,
            }
        }
        backend._resolution_is_xy["test_mouse"] = {0: {0: False, 1: False}}
        backend._resolution_maps["test_mouse"] = {800: 0, 1600: 1}

        success = backend.set_dpi("test_mouse", 1600)
        self.assertTrue(success)
        dbus.call_method.assert_any_call(RATBAG_SERVICE, r1_path, RATBAG_RESOLUTION_IFACE, "SetActive")
        dbus.call_method.assert_any_call(RATBAG_SERVICE, dev_path, RATBAG_DEVICE_IFACE, "Commit")
        dbus.set_property.assert_not_called()

    def test_set_dpi_writes_property_for_single_and_xy(self):
        dev_path = "/org/freedesktop/ratbag1/device/mouse"
        r0_path = "/org/freedesktop/ratbag1/resolution/mouse/p0/r0"
        props_map = {(r0_path, RATBAG_RESOLUTION_IFACE): {"Index": 0, "IsActive": True}}
        dbus = _make_dbus_mock(props_map)
        backend = RatbagBackend(dbus_client=dbus)
        backend._device_paths["test_mouse"] = dev_path
        backend._active_profiles["test_mouse"] = 0
        backend._profile_paths["test_mouse"] = {0: "/org/freedesktop/ratbag1/profile/mouse/p0"}
        backend._resolution_paths["test_mouse"] = {0: {0: r0_path}}
        backend._resolution_is_xy["test_mouse"] = {0: {0: False}}
        backend._resolution_maps["test_mouse"] = {}

        self.assertTrue(backend.set_dpi("test_mouse", 2400))
        dbus.set_property.assert_called_with(
            RATBAG_SERVICE, r0_path, RATBAG_RESOLUTION_IFACE, "Resolution", "v", ("u", 2400)
        )
        dbus.call_method.assert_called_with(RATBAG_SERVICE, dev_path, RATBAG_DEVICE_IFACE, "Commit")

        dbus.set_property.reset_mock()
        backend._resolution_is_xy["test_mouse"] = {0: {0: True}}
        self.assertTrue(backend.set_dpi("test_mouse", 2400))
        dbus.set_property.assert_called_with(
            RATBAG_SERVICE, r0_path, RATBAG_RESOLUTION_IFACE, "Resolution", "v", ("(uu)", (2400, 2400))
        )

    def test_set_dpi_recovers_missing_active_resolution(self):
        dev_path = "/org/freedesktop/ratbag1/device/mouse"
        r0_path = "/org/freedesktop/ratbag1/resolution/mouse/p0/r0"
        props_map = {(r0_path, RATBAG_RESOLUTION_IFACE): {"Index": 0, "IsActive": True}}

        set_attempts = {"count": 0}

        def set_side_effect(*args, **kwargs):
            set_attempts["count"] += 1
            if set_attempts["count"] == 1:
                raise DBusCallError("org.freedesktop.ratbag1.Error", "The device has no active resolution")

        dbus = _make_dbus_mock(props_map, set_side_effect=set_side_effect)
        backend = RatbagBackend(dbus_client=dbus)
        backend._device_paths["test_mouse"] = dev_path
        backend._active_profiles["test_mouse"] = 0
        backend._profile_paths["test_mouse"] = {0: "/org/freedesktop/ratbag1/profile/mouse/p0"}
        backend._resolution_paths["test_mouse"] = {0: {0: r0_path}}
        backend._resolution_is_xy["test_mouse"] = {0: {0: False}}
        backend._resolution_maps["test_mouse"] = {}

        success = backend.set_dpi("test_mouse", 1600)
        self.assertTrue(success)
        self.assertEqual(set_attempts["count"], 2)
        dbus.call_method.assert_any_call(RATBAG_SERVICE, r0_path, RATBAG_RESOLUTION_IFACE, "SetActive")
        dbus.call_method.assert_any_call(RATBAG_SERVICE, dev_path, RATBAG_DEVICE_IFACE, "Commit")

    @patch.object(RatbagBackend, "set_dpi", return_value=True)
    def test_manager_set_dpi_updates_cache_immediately(self, mock_backend_set):
        mgr = DeviceManager(auto_refresh=False, enable_hotplug=False)
        mgr.backends = []
        mgr.refresh_devices = MagicMock()
        self.addCleanup(mgr.cleanup)
        test_dev = Device(
            id="test_mouse_id",
            name="Test Mouse",
            vendor="Logitech",
            device_type=DeviceType.MOUSE,
            capabilities=[Capability.DPI],
            dpi=DpiInfo(current=800, steps=[400, 800, 1600, 3200]),
            backend_name="ratbagd",
        )
        mgr._devices = [test_dev]
        mgr._cached_dict_devices = [mgr._device_to_dict(test_dev)]

        signal_emitted = []
        mgr.devicesChanged.connect(lambda: signal_emitted.append(True))

        with patch("lhub.manager.threading.Thread"):
            success = mgr.setDpi("test_mouse_id", 1600)
        self.assertTrue(success)
        self.assertEqual(mgr._cached_dict_devices[0]["currentDpi"], 1600)
        self.assertTrue(len(signal_emitted) > 0)


if __name__ == "__main__":
    unittest.main()
