from collections import deque
import io
import os
import select
import sys
import threading
import time
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


_HIDPP_VENDOR_DESC = bytes.fromhex(
    "06 00 ff 09 01 a1 01 85 10 75 08 95 06 15 00 26 ff 00 09 01 81 00 09 01 91 00 c0 "
    "06 00 ff 09 02 a1 01 85 11 75 08 95 13 15 00 26 ff 00 09 02 81 00 09 02 91 00 c0"
)
_MOUSE_ONLY_DESC = bytes.fromhex(
    "05 01 09 02 a1 01 09 01 a1 00 05 09 19 01 29 05 15 00 25 01 95 05 75 01 81 02 "
    "95 01 75 03 81 03 05 01 09 30 09 31 15 81 25 7f 75 08 95 02 81 06 c0 c0"
)


class _FakeHidDevice:
    """In-memory HID++ 1.0 / 2.0 device responder supporting wired (0xFF) and slots (1..6)."""

    def __init__(self, slots=None, receiver_kind=None):
        # slots: Dict[int, dict] keyed by device_index (0xFF or 1..6)
        self.slots = slots if slots is not None else {}
        self.receiver_kind = receiver_kind
        self.preface_packets = []  # unsolicited packets from other devices to emit first

    def handle_write(self, data: bytes, rx_queue: deque) -> None:
        while self.preface_packets:
            rx_queue.append(self.preface_packets.pop(0))

        if len(data) < 4:
            return
        report_id, dev_idx, feat_or_sub = data[0], data[1], data[2]

        # Receiver 0x83/0xB5 long register pairing info
        if report_id == 0x10 and dev_idx == 0xFF and feat_or_sub == 0x83 and data[3] == 0xB5:
            sub_param = data[4]
            if self.receiver_kind == "bolt" and 0x51 <= sub_param <= 0x56:
                slot = sub_param - 0x50
                info = self.slots.get(slot)
                if info and info.get("wpid"):
                    wpid = int(info["wpid"], 16)
                    pkt = bytearray(20)
                    pkt[0:8] = [0x11, 0xFF, 0x83, 0xB5, sub_param, 0x02, wpid & 0xFF, (wpid >> 8) & 0xFF]
                    rx_queue.append(bytes(pkt))
                    return
            elif 0x20 <= sub_param <= 0x25:
                slot = (sub_param - 0x20) + 1
                info = self.slots.get(slot)
                if info and info.get("wpid"):
                    wpid = int(info["wpid"], 16)
                    pkt = bytearray(20)
                    pkt[0:9] = [0x11, 0xFF, 0x83, 0xB5, sub_param, 0x08, 0x00, (wpid >> 8) & 0xFF, wpid & 0xFF]
                    rx_queue.append(bytes(pkt))
                    return
            rx_queue.append(bytes([0x10, 0xFF, 0x8F, 0x83, 0xB5, 0x08, 0x00]))
            return

        slot_cfg = self.slots.get(dev_idx)
        if slot_cfg is None:
            rx_queue.append(bytes([0x10, dev_idx, 0x8F, feat_or_sub, data[3], 0x08, 0x00]))
            return

        if slot_cfg.get("timeout"):
            return

        if slot_cfg.get("sleep_err10") is not None:
            rx_queue.append(bytes([0x10, dev_idx, 0x8F, feat_or_sub, data[3], slot_cfg["sleep_err10"], 0x00]))
            return

        if slot_cfg.get("err20") is not None:
            pkt = bytearray(20)
            pkt[0:6] = [0x11, dev_idx, 0xFF, feat_or_sub, data[3], slot_cfg["err20"]]
            rx_queue.append(bytes(pkt))
            return

        func = (data[3] >> 4) & 0x0F
        swid = data[3] & 0x0F
        features = slot_cfg.get("features", {})

        # IRoot (0x0000)
        if feat_or_sub == 0x00 and func == 0:
            feat_id = (data[4] << 8) | data[5]
            idx = features.get(feat_id, 0)
            pkt = bytearray(20)
            pkt[0:5] = [0x11, dev_idx, 0x00, swid, idx]
            rx_queue.append(bytes(pkt))
            return

        # DeviceName (0x0005)
        if feat_or_sub == features.get(0x0005):
            name_bytes = (slot_cfg.get("name") or "").encode("utf-8")
            pkt = bytearray(20)
            if func == 0:
                pkt[0:5] = [0x11, dev_idx, feat_or_sub, (0 << 4) | swid, len(name_bytes)]
            elif func == 1:
                offset = data[4]
                chunk = name_bytes[offset : offset + 16]
                pkt[0:4] = [0x11, dev_idx, feat_or_sub, (1 << 4) | swid]
                pkt[4 : 4 + len(chunk)] = chunk
            elif func == 2:
                dev_type = slot_cfg.get("device_type", hidpp.DEVICE_TYPE_MOUSE)
                pkt[0:5] = [0x11, dev_idx, feat_or_sub, (2 << 4) | swid, dev_type]
            rx_queue.append(bytes(pkt))
            return

        # AdjustableDPI (0x2201)
        if feat_or_sub == features.get(0x2201):
            pkt = bytearray(20)
            if func == 2:
                dpi = slot_cfg.get("dpi", 800)
                pkt[0:7] = [0x11, dev_idx, feat_or_sub, (2 << 4) | swid, 0, (dpi >> 8) & 0xFF, dpi & 0xFF]
            elif func == 3:
                new_dpi = (data[5] << 8) | data[6]
                slot_cfg["dpi"] = new_dpi
                pkt[0:7] = [0x11, dev_idx, feat_or_sub, (3 << 4) | swid, 0, (new_dpi >> 8) & 0xFF, new_dpi & 0xFF]
            rx_queue.append(bytes(pkt))
            return

        # OnboardProfiles (0x8100)
        if feat_or_sub == features.get(0x8100):
            pkt = bytearray(20)
            if func == 4:
                prof = slot_cfg.get("profile", 0x0001)
                pkt[0:6] = [0x11, dev_idx, feat_or_sub, (4 << 4) | swid, (prof >> 8) & 0xFF, prof & 0xFF]
            elif func == 3:
                slot_cfg["profile"] = (data[4] << 8) | data[5]
                pkt[0:4] = [0x11, dev_idx, feat_or_sub, (3 << 4) | swid]
            rx_queue.append(bytes(pkt))
            return


class _FakeHidrawEnv:
    """Context manager mocking /sys/class/hidraw/* and /dev/hidraw* without sleep/hardware."""

    def __init__(self):
        self.sys_files = {}
        self.sys_nodes = []
        self.devices = {}  # /dev/hidrawX -> _FakeHidDevice or Exception
        self._fd_seq = 1000
        self._open_fds = {}  # fd -> (dev_path, deque)
        self.closed_fds = set()
        self._real_open = open
        self._real_glob = hidpp.glob.glob
        self._real_os_open = os.open
        self._real_os_write = os.write
        self._real_os_read = os.read
        self._real_os_close = os.close
        self._real_select = select.select

    def add_node(self, name: str, vid: str, pid: str, *, hid_name: str = "Logitech Device",
                 hid_phys: str = "usb-0000:00:14.0-1/input2", driver: str = "hid-generic",
                 desc: bytes = _HIDPP_VENDOR_DESC, device: object = None):
        sys_node = f"/sys/class/hidraw/{name}"
        dev_path = f"/dev/{name}"
        if sys_node not in self.sys_nodes:
            self.sys_nodes.append(sys_node)
        self.sys_files[f"{sys_node}/device/uevent"] = (
            f"DRIVER={driver}\n"
            f"HID_ID=0003:{vid.upper().zfill(8)}:{pid.upper().zfill(8)}\n"
            f"HID_NAME={hid_name}\n"
            f"HID_PHYS={hid_phys}\n"
        )
        if desc is not None:
            self.sys_files[f"{sys_node}/device/report_descriptor"] = desc
        if device is not None:
            self.devices[dev_path] = device
        return dev_path

    def remove_node(self, name: str):
        sys_node = f"/sys/class/hidraw/{name}"
        dev_path = f"/dev/{name}"
        if sys_node in self.sys_nodes:
            self.sys_nodes.remove(sys_node)
        self.sys_files.pop(f"{sys_node}/device/uevent", None)
        self.sys_files.pop(f"{sys_node}/device/report_descriptor", None)
        self.devices.pop(dev_path, None)

    def _glob(self, pattern):
        if pattern == "/sys/class/hidraw/hidraw*":
            return sorted(self.sys_nodes)
        return self._real_glob(pattern)

    def _builtin_open(self, file, mode="r", *args, **kwargs):
        key = str(file)
        if key in self.sys_files:
            val = self.sys_files[key]
            if "b" in mode:
                return io.BytesIO(val if isinstance(val, bytes) else val.encode("utf-8"))
            return io.StringIO(val if isinstance(val, str) else val.decode("utf-8"))
        if key.startswith("/sys/class/hidraw/"):
            raise FileNotFoundError(key)
        return self._real_open(file, mode, *args, **kwargs)

    def _os_open(self, path, flags, *args, **kwargs):
        if str(path).startswith("/dev/hidraw"):
            target = self.devices.get(str(path))
            if target is None:
                raise FileNotFoundError(path)
            if isinstance(target, BaseException):
                raise target
            self._fd_seq += 1
            fd = self._fd_seq
            self._open_fds[fd] = (str(path), deque())
            return fd
        return self._real_os_open(path, flags, *args, **kwargs)

    def _os_write(self, fd, data):
        if fd in self._open_fds:
            path, rx_queue = self._open_fds[fd]
            dev = self.devices.get(path)
            if isinstance(dev, _FakeHidDevice):
                dev.handle_write(data, rx_queue)
            return len(data)
        return self._real_os_write(fd, data)

    def _os_read(self, fd, n):
        if fd in self._open_fds:
            _, rx_queue = self._open_fds[fd]
            return rx_queue.popleft() if rx_queue else b""
        return self._real_os_read(fd, n)

    def _os_close(self, fd):
        if fd in self._open_fds:
            self._open_fds.pop(fd)
            self.closed_fds.add(fd)
            return
        return self._real_os_close(fd)

    def _select(self, rlist, wlist, xlist, timeout=None):
        if any(fd in self._open_fds for fd in rlist):
            ready = [fd for fd in rlist if fd in self._open_fds and self._open_fds[fd][1]]
            return (ready, [], [])
        return self._real_select(rlist, wlist, xlist, timeout)

    def __enter__(self):
        self._stack = [
            patch.dict(hidpp._cache, {}, clear=True),
            patch("lhub.backends.hidpp.glob.glob", side_effect=self._glob),
            patch("builtins.open", side_effect=self._builtin_open),
            patch("lhub.backends.hidpp.os.open", side_effect=self._os_open),
            patch("lhub.backends.hidpp.os.write", side_effect=self._os_write),
            patch("lhub.backends.hidpp.os.read", side_effect=self._os_read),
            patch("lhub.backends.hidpp.os.close", side_effect=self._os_close),
            patch("lhub.backends.hidpp.select.select", side_effect=self._select),
        ]
        for p in self._stack:
            p.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        for p in reversed(self._stack):
            p.__exit__(exc_type, exc, tb)


class TestHidppWiredAndReceivers(unittest.TestCase):
    def test_receiver_pid_classification(self):
        self.assertTrue(hidpp.is_receiver_pid("046d", "c52b"))
        self.assertEqual(hidpp.receiver_kind("C52B"), "unifying")
        self.assertEqual(hidpp.receiver_kind("c532"), "unifying")
        self.assertTrue(hidpp.is_receiver_pid("046D", "c547"))
        self.assertEqual(hidpp.receiver_kind("c539"), "lightspeed")
        self.assertEqual(hidpp.receiver_kind("c53f"), "lightspeed")
        self.assertEqual(hidpp.receiver_kind("c547"), "lightspeed")
        self.assertEqual(hidpp.receiver_kind("c54d"), "lightspeed")
        self.assertTrue(hidpp.is_receiver_pid("046d", "c548"))
        self.assertEqual(hidpp.receiver_kind("c548"), "bolt")
        self.assertEqual(hidpp.receiver_kind("c52f"), "nano")
        self.assertFalse(hidpp.is_receiver_pid("046d", "c099"))
        self.assertIsNone(hidpp.receiver_kind("c099"))
        self.assertFalse(hidpp.is_receiver_pid("3434", "c52b"))

    def test_wired_device_0xff_backward_compatible(self):
        dev = _FakeHidDevice(
            slots={
                0xFF: {
                    "features": {0x2201: 0x0A, 0x8100: 0x14},
                    "dpi": 1600,
                    "profile": 0x0002,
                }
            }
        )
        with _FakeHidrawEnv() as env:
            # Mouse input interface listed before HID++ vendor interface: HID++ priority picks hidraw1
            env.add_node("hidraw0", "046d", "c099", desc=_MOUSE_ONLY_DESC, device=_FakeHidDevice())
            env.add_node("hidraw1", "046d", "c099", desc=_HIDPP_VENDOR_DESC, device=dev)

            self.assertEqual(hidpp.get_dpi("046d", "c099"), 1600)
            self.assertEqual(hidpp._cache[("046d:c099", 0x2201)], ("/dev/hidraw1", 0xFF, 0x0A))
            self.assertTrue(hidpp.set_dpi("046d", "c099", 2400))
            self.assertEqual(hidpp.get_dpi("046d", "c099"), 2400)
            self.assertEqual(hidpp.get_onboard_profile("046d", "c099"), 0x0002)
            self.assertTrue(hidpp.set_onboard_profile("046d", "c099", 0x0003))
            self.assertEqual(hidpp.get_onboard_profile("046d", "c099"), 0x0003)
            self.assertEqual(env._open_fds, {})

    def test_unifying_slot_enumeration_chunked_name_and_keyboard_skip(self):
        # Slot 1 empty, Slot 2 Keyboard (only 0x0005), Slot 3 Mouse with >16-byte name
        recv = _FakeHidDevice(
            receiver_kind="unifying",
            slots={
                2: {
                    "features": {0x0005: 0x02},
                    "name": "Logitech MX Keys",
                    "device_type": hidpp.DEVICE_TYPE_KEYBOARD,
                },
                3: {
                    "features": {0x0005: 0x02, 0x2201: 0x0C, 0x8100: 0x11},
                    "name": "Logitech MX Master 3 Wireless",
                    "device_type": hidpp.DEVICE_TYPE_MOUSE,
                    "dpi": 1800,
                    "profile": 0x0001,
                },
            },
        )
        with _FakeHidrawEnv() as env:
            env.add_node("hidraw0", "046d", "c52b", desc=_HIDPP_VENDOR_DESC, device=recv)
            self.assertEqual(
                hidpp.get_dpi("046d", "c52b", device_name="Logitech MX Master 3 Wireless"),
                1800,
            )
            loc = hidpp._locate("046d", "c52b", 0x2201, device_name="Logitech MX Master 3 Wireless")
            self.assertEqual(loc, ("/dev/hidraw0", 3, 0x0C))

    def test_lightspeed_receiver_backward_compatible_without_device_name(self):
        recv = _FakeHidDevice(
            receiver_kind="lightspeed",
            slots={
                1: {
                    "features": {0x0005: 0x02, 0x2201: 0x09, 0x8100: 0x12},
                    "name": "G502 X LIGHTSPEED",
                    "device_type": hidpp.DEVICE_TYPE_MOUSE,
                    "dpi": 3200,
                    "profile": 0x0002,
                }
            },
        )
        with _FakeHidrawEnv() as env:
            env.add_node("hidraw0", "046d", "c547", desc=_HIDPP_VENDOR_DESC, device=recv)
            # Callers that pass only (vid, pid) still work seamlessly on Lightspeed receivers
            self.assertEqual(hidpp.get_dpi("046d", "c547"), 3200)
            self.assertEqual(hidpp.get_onboard_profile("046d", "c547"), 0x0002)

    def test_bolt_multi_mouse_disambiguation_and_no_hijack_on_sleep(self):
        bolt = _FakeHidDevice(
            receiver_kind="bolt",
            slots={
                1: {
                    "features": {0x0005: 0x02, 0x2201: 0x0A, 0x8100: 0x14},
                    "name": "MX Anywhere 3",
                    "device_type": hidpp.DEVICE_TYPE_MOUSE,
                    "dpi": 1200,
                    "profile": 0x0001,
                },
                2: {
                    "features": {0x0005: 0x02, 0x2201: 0x0B, 0x8100: 0x15},
                    "name": "MX Master 3S",
                    "device_type": hidpp.DEVICE_TYPE_MOUSE,
                    "dpi": 2400,
                    "profile": 0x0002,
                },
            },
        )
        with _FakeHidrawEnv() as env:
            env.add_node("hidraw0", "046d", "c548", desc=_HIDPP_VENDOR_DESC, device=bolt)

            self.assertEqual(
                hidpp.get_dpi("046d", "c548", device_name="Logitech MX Anywhere 3", device_key="046d:c548"),
                1200,
            )
            self.assertEqual(
                hidpp.get_dpi("046d", "c548", device_name="Logitech MX Master 3S", device_key="046d:c548"),
                2400,
            )
            # Separate cache entries exist even though caller shared device_key="046d:c548"
            self.assertIn(("046d:c548@logitech mx anywhere 3", 0x2201), hidpp._cache)
            self.assertIn(("046d:c548@logitech mx master 3s", 0x2201), hidpp._cache)

            # Put MX Master 3S (slot 2) to deep sleep -> must return None, never hijack slot 1!
            bolt.slots[2]["sleep_err10"] = hidpp.ERR_HIDPP10_UNKNOWN_DEVICE
            self.assertIsNone(
                hidpp.get_dpi("046d", "c548", device_name="Logitech MX Master 3S", device_key="046d:c548")
            )
            # Slot 1 continues to work independently
            self.assertEqual(
                hidpp.get_dpi("046d", "c548", device_name="Logitech MX Anywhere 3", device_key="046d:c548"),
                1200,
            )

    def test_wireless_wpid_fallback_via_receiver_b5_pairing_info(self):
        # Lightspeed G305 (WPID 4074) behind Lightspeed receiver c53f (big-endian WPID)
        ls_recv = _FakeHidDevice(
            receiver_kind="lightspeed",
            slots={
                1: {
                    "wpid": "4074",
                    "features": {0x0005: 0x02, 0x2201: 0x09},
                    "name": "G305",
                    "device_type": hidpp.DEVICE_TYPE_MOUSE,
                    "dpi": 800,
                }
            },
        )
        # Bolt mouse (WPID b023) at slot 2 behind Bolt receiver c548 (little-endian WPID)
        bolt_recv = _FakeHidDevice(
            receiver_kind="bolt",
            slots={
                1: {
                    "wpid": "b369",
                    "features": {0x0005: 0x02, 0x2201: 0x0A},
                    "name": "MX Keys Mini",
                    "device_type": hidpp.DEVICE_TYPE_KEYBOARD,
                },
                2: {
                    "wpid": "b023",
                    "features": {0x0005: 0x02, 0x2201: 0x0C},
                    "name": "MX Master 3",
                    "device_type": hidpp.DEVICE_TYPE_MOUSE,
                    "dpi": 2000,
                },
            },
        )
        with _FakeHidrawEnv() as env:
            env.add_node("hidraw0", "046d", "c53f", desc=_HIDPP_VENDOR_DESC, device=ls_recv)
            env.add_node("hidraw1", "046d", "c548", desc=_HIDPP_VENDOR_DESC, device=bolt_recv)

            self.assertEqual(hidpp.get_dpi("046d", "4074", device_name="Logitech G305"), 800)
            self.assertEqual(hidpp.get_dpi("046d", "b023"), 2000)

    def test_dj_child_node_uses_slot_from_hid_phys(self):
        dj_child = _FakeHidDevice(
            slots={
                2: {
                    "features": {0x2201: 0x0B},
                    "dpi": 1600,
                }
            }
        )
        with _FakeHidrawEnv() as env:
            env.add_node(
                "hidraw2",
                "046d",
                "4093",
                driver="logitech-hidpp-device",
                hid_phys="usb-0000:00:14.0-2/input2:2",
                desc=_HIDPP_VENDOR_DESC,
                device=dj_child,
            )
            self.assertEqual(hidpp.get_dpi("046d", "4093"), 1600)
            self.assertEqual(hidpp._cache[("046d:4093", 0x2201)], ("/dev/hidraw2", 2, 0x0B))

    @patch("lhub.backends.ratbag.hidpp.set_dpi", return_value=True)
    @patch("lhub.backends.ratbag.hidpp.get_dpi", return_value=1600)
    @patch("lhub.backends.ratbag.hidpp.get_onboard_profile", return_value=0x0001)
    def test_ratbag_backend_forwards_device_name_and_key_to_hidpp(self, mock_prof, mock_dpi, mock_set_dpi):
        dev_path = "/org/freedesktop/ratbag1/device/hidraw5"
        p0_path = "/org/freedesktop/ratbag1/profile/hidraw5/p0"
        r0_path = "/org/freedesktop/ratbag1/resolution/hidraw5/p0/r0"
        props_map = {
            (dev_path, RATBAG_DEVICE_IFACE): {
                "Name": "Logitech MX Master 3S",
                "Model": "usb:046d:c548:0",
                "DeviceType": 2,
                "Profiles": [p0_path],
            },
            (p0_path, RATBAG_PROFILE_IFACE): {
                "Index": 0,
                "Disabled": False,
                "IsActive": True,
                "Resolutions": [r0_path],
                "Buttons": [],
            },
            (r0_path, RATBAG_RESOLUTION_IFACE): {
                "Index": 0,
                "Resolution": ("u", 1600),
                "Resolutions": [800, 1600],
                "IsDisabled": False,
                "IsActive": True,
            },
        }
        backend = RatbagBackend(dbus_client=_make_dbus_mock(props_map))
        dev = backend._inspect_device("wireless-mouse", dev_path)
        self.assertIsNotNone(dev)
        mock_prof.assert_called_once_with(
            "046d", "c548", device_name="Logitech MX Master 3S", device_key="wireless-mouse"
        )
        mock_dpi.assert_called_once_with(
            "046d", "c548", device_name="Logitech MX Master 3S", device_key="wireless-mouse"
        )
        self.assertTrue(backend.set_dpi("wireless-mouse", 2400))
        mock_set_dpi.assert_called_once_with(
            "046d", "c548", 2400, device_name="Logitech MX Master 3S", device_key="wireless-mouse"
        )


class TestHidppSleepWakeResilience(unittest.TestCase):
    def test_sleep_errors_and_timeouts_invalidate_cache_and_recover_on_wake(self):
        recv = _FakeHidDevice(
            receiver_kind="lightspeed",
            slots={
                1: {
                    "features": {0x0005: 0x02, 0x2201: 0x09, 0x8100: 0x12},
                    "name": "G Pro X Superlight",
                    "device_type": hidpp.DEVICE_TYPE_MOUSE,
                    "dpi": 1600,
                    "profile": 0x0001,
                }
            },
        )
        with _FakeHidrawEnv() as env:
            env.add_node("hidraw0", "046d", "c547", desc=_HIDPP_VENDOR_DESC, device=recv)

            # Warm cache
            self.assertEqual(hidpp.get_dpi("046d", "c547"), 1600)
            self.assertIn(("046d:c547", 0x2201), hidpp._cache)

            # 1) HID++ 1.0 0x08 (UnknownDevice / unreachable while sleeping)
            recv.slots[1]["sleep_err10"] = hidpp.ERR_HIDPP10_UNKNOWN_DEVICE
            self.assertIsNone(hidpp.get_dpi("046d", "c547"))
            self.assertNotIn(("046d:c547", 0x2201), hidpp._cache)

            # Wake -> recovers immediately
            recv.slots[1].pop("sleep_err10")
            self.assertEqual(hidpp.get_dpi("046d", "c547"), 1600)
            self.assertIn(("046d:c547", 0x2201), hidpp._cache)

            # 2) HID++ 1.0 0x09 (ResourceError) on set_dpi -> False & clears cache
            recv.slots[1]["sleep_err10"] = hidpp.ERR_HIDPP10_RESOURCE_ERROR
            self.assertFalse(hidpp.set_dpi("046d", "c547", 2400))
            self.assertNotIn(("046d:c547", 0x2201), hidpp._cache)

            # Wake -> succeeds
            recv.slots[1].pop("sleep_err10")
            self.assertTrue(hidpp.set_dpi("046d", "c547", 2400))
            self.assertEqual(hidpp.get_dpi("046d", "c547"), 2400)

            # 3) HID++ 2.0 0x08 (Busy) -> None & clears cache
            recv.slots[1]["err20"] = hidpp.ERR_HIDPP20_BUSY
            self.assertIsNone(hidpp.get_dpi("046d", "c547"))
            self.assertNotIn(("046d:c547", 0x2201), hidpp._cache)

            # Wake -> succeeds
            recv.slots[1].pop("err20")
            self.assertEqual(hidpp.get_dpi("046d", "c547"), 2400)

            # 4) Select timeout while sleeping -> None & clears cache
            recv.slots[1]["timeout"] = True
            self.assertIsNone(hidpp.get_dpi("046d", "c547"))
            self.assertNotIn(("046d:c547", 0x2201), hidpp._cache)

            # Wake -> recovers
            recv.slots[1].pop("timeout")
            self.assertEqual(hidpp.get_dpi("046d", "c547"), 2400)

    def test_stale_hidraw_path_and_invalid_feature_auto_relocate(self):
        recv = _FakeHidDevice(
            receiver_kind="lightspeed",
            slots={
                1: {
                    "features": {0x0005: 0x02, 0x2201: 0x0D},
                    "name": "G502 X PLUS",
                    "device_type": hidpp.DEVICE_TYPE_MOUSE,
                    "dpi": 1200,
                }
            },
        )
        with _FakeHidrawEnv() as env:
            env.add_node("hidraw0", "046d", "c547", desc=_HIDPP_VENDOR_DESC, device=recv)
            # Seed stale cache pointing at old hidraw9 node
            hidpp._cache[("046d:c547", 0x2201)] = ("/dev/hidraw9", 1, 0x09)
            self.assertEqual(hidpp.get_dpi("046d", "c547"), 1200)
            self.assertEqual(hidpp._cache[("046d:c547", 0x2201)], ("/dev/hidraw0", 1, 0x0D))

            # Seed stale feature index on valid hidraw0 -> 0x06 InvalidFeature -> auto re-locates!
            class _FeatureChangedOnce(_FakeHidDevice):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.sent_invalid = False

                def handle_write(self, data, rx_queue):
                    if not self.sent_invalid and data[2] == 0x09:
                        self.sent_invalid = True
                        pkt = bytearray(20)
                        pkt[0:6] = [0x11, data[1], 0xFF, data[2], data[3], hidpp.ERR_HIDPP20_INVALID_FEATURE]
                        rx_queue.append(bytes(pkt))
                        return
                    super().handle_write(data, rx_queue)

            env.devices["/dev/hidraw0"] = _FeatureChangedOnce(
                receiver_kind="lightspeed",
                slots=recv.slots,
            )
            hidpp._cache[("046d:c547", 0x2201)] = ("/dev/hidraw0", 1, 0x09)
            self.assertEqual(hidpp.get_dpi("046d", "c547"), 1200)
            self.assertEqual(hidpp._cache[("046d:c547", 0x2201)], ("/dev/hidraw0", 1, 0x0D))

    def test_interleaved_packets_from_other_slot_are_ignored(self):
        recv = _FakeHidDevice(
            receiver_kind="unifying",
            slots={
                2: {
                    "features": {0x0005: 0x02, 0x2201: 0x0A},
                    "name": "MX Master 3",
                    "device_type": hidpp.DEVICE_TYPE_MOUSE,
                    "dpi": 1000,
                }
            },
        )
        # Pre-seed cache so _request runs directly on slot 2 with interleaved slot 1 packet
        with _FakeHidrawEnv() as env:
            env.add_node("hidraw0", "046d", "c52b", desc=_HIDPP_VENDOR_DESC, device=recv)
            hidpp._cache[("046d:c52b@mx master 3", 0x2201)] = ("/dev/hidraw0", 2, 0x0A)
            # Slot 1 fake DPI/event packet arrives ahead of slot 2's reply
            recv.preface_packets.append(bytes([0x11, 0x01, 0x0A, 0x27, 0x00, 0x01, 0x90]) + bytes(13))
            self.assertEqual(hidpp.get_dpi("046d", "c52b", device_name="MX Master 3"), 1000)


class TestHidppMonitorMultiDeviceAndWake(unittest.TestCase):
    def test_parse_onboard_event_filters_by_device_index(self):
        slot2_profile = bytes([0x11, 0x02, 0x14, 0x00, 0x00, 0x03]) + bytes(14)
        self.assertEqual(hidpp.parse_onboard_event(slot2_profile, 0x14, device_index=2), ("profile", 0x0003))
        self.assertIsNone(hidpp.parse_onboard_event(slot2_profile, 0x14, device_index=1))
        self.assertIsNone(hidpp.parse_onboard_event(slot2_profile, 0x14))  # default 0xFF

    def test_parse_connection_events(self):
        # HID++ 1.0 Device Connection (0x41): bit 6 (0x40) = 0 -> connected, 1 -> link lost
        self.assertTrue(hidpp.parse_connection_event(bytes([0x10, 0x02, 0x41, 0x04, 0x00, 0x00, 0x00]), 2))
        self.assertFalse(hidpp.parse_connection_event(bytes([0x10, 0x02, 0x41, 0x04, 0x40, 0x00, 0x00]), 2))
        # Wrong device_index ignored
        self.assertIsNone(hidpp.parse_connection_event(bytes([0x10, 0x01, 0x41, 0x04, 0x00, 0x00, 0x00]), 2))
        # HID++ 1.0 Disconnection (0x40)
        self.assertFalse(hidpp.parse_connection_event(bytes([0x10, 0x02, 0x40, 0x02, 0x00, 0x00, 0x00]), 2))
        # DJ Connection Status (0x20 / 0x42): byte 3 == 0x00 -> connected, 0x01 -> link lost
        self.assertTrue(hidpp.parse_connection_event(bytes([0x20, 0x02, 0x42, 0x00]) + bytes(11), 2))
        self.assertFalse(hidpp.parse_connection_event(bytes([0x20, 0x02, 0x42, 0x01]) + bytes(11), 2))
        # DJ Paired / Unpaired
        self.assertTrue(hidpp.parse_connection_event(bytes([0x20, 0x02, 0x41, 0x00]) + bytes(11), 2))
        self.assertFalse(hidpp.parse_connection_event(bytes([0x20, 0x02, 0x41, 0x40]) + bytes(11), 2))
        self.assertFalse(hidpp.parse_connection_event(bytes([0x20, 0x02, 0x40, 0x00]) + bytes(11), 2))
        # 0x1D4B wireless status reconnection broadcast
        self.assertTrue(
            hidpp.parse_connection_event(
                bytes([0x11, 0x02, 0x0F, 0x00, 0x01]) + bytes(15),
                2,
                wireless_status_feature_idx=0x0F,
            )
        )

    def test_monitor_filters_slots_and_resyncs_on_wake(self):
        dev_r, dev_w = os.pipe()
        prof_events = []
        dpi_events = []
        reconnected = []
        prof_ev = threading.Event()
        wake_ev = threading.Event()

        def on_prof(p):
            prof_events.append(p)
            prof_ev.set()

        def on_dpi(d):
            dpi_events.append(d)

        def on_reconn():
            reconnected.append(True)
            wake_ev.set()

        mon = hidpp.OnboardProfileMonitor(
            "046d",
            "c548",
            on_profile_changed=on_prof,
            on_dpi_changed=on_dpi,
            device_name="Logitech MX Master 3S",
            device_key="046d:c548",
            on_reconnected=on_reconn,
        )

        # Seed cache for slot 2 so we also verify sleep invalidates it
        with hidpp._lock:
            hidpp._cache.clear()
            hidpp._cache[(mon._eff_key, 0x2201)] = ("/dev/hidraw-test-monitor", 2, 0x0A)

        def fake_locate(vid, pid, feature_id, **kwargs):
            if vid == "046d" and pid == "c548" and kwargs.get("device_key") == "046d:c548":
                return ("/dev/hidraw-test-monitor", 2, 0x14)
            return None

        def fake_open_node(path, vid, pid, **kwargs):
            if path == "/dev/hidraw-test-monitor":
                return (dev_r, False)
            return (None, False)

        def fake_get_profile(vid, pid, **kwargs):
            return 0x0003 if pid == "c548" else None

        def fake_get_dpi(vid, pid, **kwargs):
            return 3200 if pid == "c548" else None

        with patch("lhub.backends.hidpp._locate", side_effect=fake_locate), \
             patch("lhub.backends.hidpp._open_hidpp_node", side_effect=fake_open_node), \
             patch("lhub.backends.hidpp.get_onboard_profile", side_effect=fake_get_profile) as mock_get_prof, \
             patch("lhub.backends.hidpp.get_dpi", side_effect=fake_get_dpi) as mock_get_dpi:
            self.assertTrue(mon.start())
            self.assertEqual(mon.device_index, 2)
            try:
                # 1. Event for slot 1 must be ignored (multi-device isolation)
                os.write(dev_w, (bytes([0x11, 0x01, 0x14, 0x00, 0x00, 0x09]) + bytes(14)).ljust(64, b"\x00"))
                # 2. Event for slot 2 must be delivered
                os.write(dev_w, (bytes([0x11, 0x02, 0x14, 0x00, 0x00, 0x02]) + bytes(14)).ljust(64, b"\x00"))
                self.assertTrue(prof_ev.wait(timeout=2.0))
                self.assertEqual(prof_events, [0x0002])

                # 3. Slot 2 enters sleep (0x41 link lost): monitor stays alive, cache invalidated
                os.write(dev_w, bytes([0x10, 0x02, 0x41, 0x04, 0x40, 0x00, 0x00]).ljust(64, b"\x00"))
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    with hidpp._lock:
                        if (mon._eff_key, 0x2201) not in hidpp._cache:
                            break
                    time.sleep(0.01)
                self.assertTrue(mon.is_running)
                with hidpp._lock:
                    self.assertNotIn((mon._eff_key, 0x2201), hidpp._cache)

                # 4. Slot 2 wakes (0x41 link established): resyncs profile & DPI and notifies
                os.write(dev_w, bytes([0x10, 0x02, 0x41, 0x04, 0x00, 0x00, 0x00]).ljust(64, b"\x00"))
                self.assertTrue(wake_ev.wait(timeout=2.0))
                self.assertEqual(prof_events, [0x0002, 0x0003])
                self.assertEqual(dpi_events, [3200])
                self.assertEqual(reconnected, [True])
                mock_get_prof.assert_called()
                mock_get_dpi.assert_called()
            finally:
                mon.stop()
                if mon._thread is not None:
                    mon._thread.join(timeout=2.0)
                try:
                    os.close(dev_w)
                except OSError:
                    pass
                self.assertFalse(mon.is_running)


if __name__ == "__main__":
    unittest.main()
