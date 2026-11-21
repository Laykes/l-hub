import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtDBus import QDBusArgument, QDBusObjectPath, QDBusVariant
from PySide6.QtGui import QGuiApplication
from jeepney.low_level import HeaderFields, MessageFlag
from jeepney.wrappers import new_error, new_method_return

from lhub.backends.base import BaseBackend, BatteryInfo, Capability, Device, DeviceType
from lhub.backends.dbus_client import (
    DBUS_PROPERTIES_IFACE,
    DBusCallError,
    DBusSignalEvent,
    DBusTimeoutError,
    DBusUnavailableError,
    SystemDBusClient,
    extract_qdbus_message_args,
    unpack_qdbus_argument,
    unwrap_dbus_properties,
    unwrap_variant,
)
from lhub.backends.evdev_codes import evcode_to_key_name, key_name_to_evcode
from lhub.backends.ratbag import (
    RATBAG_DEVICE_IFACE,
    RATBAG_MANAGER_IFACE,
    RATBAG_MANAGER_PATH,
    RATBAG_SERVICE,
    RatbagBackend,
)
from lhub.manager import DeviceManager

_app = QGuiApplication.instance() or QGuiApplication(sys.argv)


def _process_qt_events_for(duration_sec: float) -> None:
    loop = QEventLoop()
    QTimer.singleShot(int(duration_sec * 1000), loop.quit)
    loop.exec()


class _FakeQDBusArg:
    """Duck-typed QDBusArgument test double supporting map, array, structure, and variant."""

    def __init__(self, element_type, payload):
        self._element_type = element_type
        self._payload = payload
        self._items = []
        self._idx = 0

    def currentType(self):
        return self._element_type

    def atEnd(self):
        return self._idx >= len(self._items)

    def beginMap(self):
        self._items = list(self._payload.items())
        self._idx = 0
        self._pair = None
        self._pair_pos = 0

    def beginMapEntry(self):
        self._pair = self._items[self._idx]
        self._idx += 1
        self._pair_pos = 0

    def endMapEntry(self):
        self._pair = None

    def endMap(self):
        return None

    def beginArray(self):
        self._items = list(self._payload)
        self._idx = 0

    def endArray(self):
        return None

    def beginStructure(self):
        self._items = list(self._payload)
        self._idx = 0

    def endStructure(self):
        return None

    def asVariant(self):
        if getattr(self, "_pair", None) is not None:
            val = self._pair[self._pair_pos]
            self._pair_pos += 1
            return val
        if self._element_type in (
            QDBusArgument.ElementType.ArrayType,
            QDBusArgument.ElementType.StructureType,
        ):
            val = self._items[self._idx]
            self._idx += 1
            return val
        return self._payload


class TestDBusVariantAndArgumentUnpacking(unittest.TestCase):
    def test_unwrap_variant_handles_jeepney_and_qt_wrappers(self):
        self.assertEqual(unwrap_variant(("u", 800)), 800)
        self.assertEqual(unwrap_variant(("v", ("u", 800))), ("u", 800))
        self.assertEqual(unwrap_variant(("v", ("u", 800)), recursive=True), 800)
        self.assertEqual(unwrap_variant(QDBusVariant(1600)), 1600)
        self.assertEqual(unwrap_variant(QDBusObjectPath("/org/freedesktop/ratbag1")), "/org/freedesktop/ratbag1")
        # Plain non-signature tuples such as ("button", 1) must NOT be unwrapped!
        self.assertEqual(unwrap_variant(("button", 1)), ("button", 1))
        self.assertEqual(unwrap_variant(("button", 1), recursive=True), ("button", 1))

    def test_unwrap_dbus_properties_preserves_inner_typed_variants(self):
        raw = {
            "Index": ("u", 0),
            "IsActive": ("b", True),
            "Resolution": ("v", ("(uu)", (1600, 1600))),
            "Mapping": ("(uv)", (2, ("u", 1073741835))),
            "Devices": ("ao", ["/org/freedesktop/ratbag1/device/hidraw6"]),
        }
        unwrapped = unwrap_dbus_properties(raw)
        self.assertEqual(unwrapped["Index"], 0)
        self.assertIs(unwrapped["IsActive"], True)
        self.assertEqual(unwrapped["Resolution"], ("(uu)", (1600, 1600)))
        self.assertEqual(unwrapped["Mapping"], (2, ("u", 1073741835)))
        self.assertEqual(unwrapped["Devices"], ["/org/freedesktop/ratbag1/device/hidraw6"])

    def test_unpack_qdbus_argument_and_extract_message_args(self):
        ET = QDBusArgument.ElementType
        fake_struct = _FakeQDBusArg(ET.StructureType, [1, QDBusVariant(42)])
        fake_array = _FakeQDBusArg(ET.ArrayType, [QDBusObjectPath("/dev/a"), QDBusObjectPath("/dev/b")])
        fake_map = _FakeQDBusArg(
            ET.MapType,
            {
                "Paths": fake_array,
                "Mapping": fake_struct,
                "Percentage": QDBusVariant(77.5),
            },
        )
        unpacked = unpack_qdbus_argument(fake_map)
        self.assertEqual(
            unpacked,
            {
                "Paths": ["/dev/a", "/dev/b"],
                "Mapping": (1, 42),
                "Percentage": 77.5,
            },
        )

        msg = MagicMock()
        msg.arguments.return_value = [
            "org.freedesktop.UPower.Device",
            fake_map,
            ["Model"],
        ]
        extracted = extract_qdbus_message_args(msg)
        self.assertEqual(extracted[0], "org.freedesktop.UPower.Device")
        self.assertEqual(extracted[1]["Percentage"], 77.5)
        self.assertEqual(extracted[2], ["Model"])


class TestSystemDBusClient(unittest.TestCase):
    def test_rpc_methods_flags_and_property_helpers(self):
        sent_messages = []

        def fake_send(msg, timeout=None):
            sent_messages.append((msg, timeout))
            member = msg.header.fields[HeaderFields.member]
            if member == "NameHasOwner":
                return new_method_return(msg, "b", (True,))
            if member == "ListActivatableNames":
                return new_method_return(msg, "as", (["org.freedesktop.ratbag1", "org.freedesktop.UPower"],))
            if member == "Get":
                return new_method_return(msg, "v", (("v", ("u", 1600)),))
            if member == "GetAll":
                return new_method_return(
                    msg,
                    "a{sv}",
                    ({"APIVersion": ("i", 2), "Devices": ("ao", ["/org/freedesktop/ratbag1/device/hidraw6"])},),
                )
            if member == "Set":
                return new_method_return(msg)
            return new_method_return(msg, "u", (0,))

        fake_conn = MagicMock()
        fake_conn.send_and_get_reply.side_effect = fake_send
        client = SystemDBusClient(timeout=2.5, connection_factory=lambda: fake_conn)

        self.assertTrue(client.is_bus_available())
        self.assertTrue(client.has_name_owner("org.freedesktop.ratbag1"))
        self.assertTrue(client.is_service_activatable("org.freedesktop.UPower"))
        self.assertFalse(client.is_service_activatable("org.example.Missing"))

        res = client.get_property("org.freedesktop.ratbag1", "/r0", "org.freedesktop.ratbag1.Resolution", "Resolution")
        self.assertEqual(res, ("u", 1600))

        props = client.get_all_properties("org.freedesktop.ratbag1", "/org/freedesktop/ratbag1", "org.freedesktop.ratbag1.Manager")
        self.assertEqual(props, {"APIVersion": 2, "Devices": ["/org/freedesktop/ratbag1/device/hidraw6"]})

        client.set_property("org.freedesktop.ratbag1", "/r0", "org.freedesktop.ratbag1.Resolution", "Resolution", "v", ("u", 2400))

        # Verify no_auto_start flag is set on RPC calls by default
        for msg, _t in sent_messages:
            self.assertTrue(bool(msg.header.flags & MessageFlag.no_auto_start))

        client.close()
        fake_conn.close.assert_called_once()

    def test_exception_mapping_and_reconnect_on_broken_pipe(self):
        conn1 = MagicMock()
        conn2 = MagicMock()
        conns = iter([conn1, conn2])

        def send_conn1(msg, timeout=None):
            raise BrokenPipeError("stale socket")

        def send_conn2(msg, timeout=None):
            member = msg.header.fields[HeaderFields.member]
            if member == "PingOk":
                return new_method_return(msg, "s", ("pong",))
            if member == "UnknownSvc":
                return new_error(msg, "org.freedesktop.DBus.Error.ServiceUnknown", "s", ("no service",))
            if member == "FailMethod":
                return new_error(msg, "org.freedesktop.DBus.Error.AccessDenied", "s", ("denied",))
            raise TimeoutError("timed out")

        conn1.send_and_get_reply.side_effect = send_conn1
        conn2.send_and_get_reply.side_effect = send_conn2

        client = SystemDBusClient(connection_factory=lambda: next(conns))

        # BrokenPipeError on conn1 transparently reconnects to conn2 and succeeds
        out = client.call_method("org.example", "/p", "org.example.Iface", "PingOk")
        self.assertEqual(out, ("pong",))
        conn1.close.assert_called_once()

        with self.assertRaises(DBusUnavailableError):
            client.call_method("org.example", "/p", "org.example.Iface", "UnknownSvc")

        with self.assertRaises(DBusCallError) as ctx:
            client.call_method("org.example", "/p", "org.example.Iface", "FailMethod")
        self.assertEqual(ctx.exception.error_name, "org.freedesktop.DBus.Error.AccessDenied")

        with self.assertRaises(DBusTimeoutError):
            client.call_method("org.example", "/p", "org.example.Iface", "TimeoutMe")

    def test_signal_subscription_lifecycle_and_delivery(self):
        fake_bus = MagicMock()
        fake_bus.isConnected.return_value = True
        fake_bus.connect.return_value = True
        fake_bus.disconnect.return_value = True

        client = SystemDBusClient(qdbus_bus_factory=lambda: fake_bus)
        events = []

        sub_id = client.subscribe_signal(
            "org.freedesktop.UPower",
            "/org/freedesktop/UPower",
            "org.freedesktop.UPower",
            "DeviceAdded",
            events.append,
        )
        self.assertIsNotNone(sub_id)
        fake_bus.connect.assert_called_once()
        receiver = fake_bus.connect.call_args[0][4]

        fake_msg = MagicMock()
        fake_msg.service.return_value = "org.freedesktop.UPower"
        fake_msg.path.return_value = "/org/freedesktop/UPower"
        fake_msg.interface.return_value = "org.freedesktop.UPower"
        fake_msg.member.return_value = "DeviceAdded"
        fake_msg.arguments.return_value = [QDBusObjectPath("/org/freedesktop/UPower/devices/mouse_1")]
        receiver.handle_signal(fake_msg)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].args, ("/org/freedesktop/UPower/devices/mouse_1",))

        self.assertTrue(client.unsubscribe_signal(sub_id))
        fake_bus.disconnect.assert_called_once()
        self.assertFalse(client.unsubscribe_signal(sub_id))


class TestEvdevCodes(unittest.TestCase):
    def test_roundtrip_and_unknown_key(self):
        for key_name, expected_code in (
            ("KEY_SPACE", 57),
            ("KEY_LEFTCTRL", 29),
            ("KEY_C", 46),
            ("KEY_F5", 63),
            ("KEY_PLAYPAUSE", 164),
        ):
            self.assertEqual(key_name_to_evcode(key_name), expected_code)
            self.assertEqual(evcode_to_key_name(expected_code), key_name)

        with self.assertRaises(ValueError):
            key_name_to_evcode("KEY_DEFINITELY_NOT_A_KEY_12345")


class TestRatbagHotplugSignals(unittest.TestCase):
    def test_ratbag_hotplug_subscriptions_and_cleanup(self):
        callbacks = []
        counter = {"n": 0}

        def fake_sub(svc, path, iface, sig, cb):
            counter["n"] += 1
            callbacks.append((svc, path, iface, sig, cb))
            return counter["n"]

        dbus = MagicMock()
        dbus.subscribe_signal.side_effect = fake_sub
        backend = RatbagBackend(dbus_client=dbus)
        changes = []

        self.assertTrue(backend.supports_hotplug)
        self.assertTrue(backend.start_monitoring(lambda: changes.append(True)))
        self.assertEqual(len(callbacks), 5)

        by_sig = {(iface, sig): cb for _svc, _path, iface, sig, cb in callbacks}
        by_sig[(RATBAG_MANAGER_IFACE, "DeviceNew")](
            DBusSignalEvent(RATBAG_SERVICE, RATBAG_MANAGER_PATH, RATBAG_MANAGER_IFACE, "DeviceNew", ("/dev/0",))
        )
        by_sig[(RATBAG_MANAGER_IFACE, "DeviceRemoved")](
            DBusSignalEvent(RATBAG_SERVICE, RATBAG_MANAGER_PATH, RATBAG_MANAGER_IFACE, "DeviceRemoved", ("/dev/0",))
        )
        by_sig[(RATBAG_DEVICE_IFACE, "Resync")](
            DBusSignalEvent(RATBAG_SERVICE, "/dev/0", RATBAG_DEVICE_IFACE, "Resync", ())
        )
        by_sig[(DBUS_PROPERTIES_IFACE, "PropertiesChanged")](
            DBusSignalEvent(RATBAG_SERVICE, "/dev/0", DBUS_PROPERTIES_IFACE, "PropertiesChanged", ())
        )
        # NameOwnerChanged only triggers for org.freedesktop.ratbag1
        by_sig[("org.freedesktop.DBus", "NameOwnerChanged")](
            DBusSignalEvent("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameOwnerChanged", ("org.other.Service", "", ":1.1"))
        )
        self.assertEqual(len(changes), 4)
        by_sig[("org.freedesktop.DBus", "NameOwnerChanged")](
            DBusSignalEvent("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameOwnerChanged", (RATBAG_SERVICE, "", ":1.2"))
        )
        self.assertEqual(len(changes), 5)

        backend.stop_monitoring()
        self.assertEqual(dbus.unsubscribe_signal.call_count, 5)


class _DummyHotplugBackend(BaseBackend):
    def __init__(self, name="dummy_dbus", devices=None):
        super().__init__(name)
        self._devices = list(devices or [])
        self._cb = None
        self.scan_calls = 0
        self.stopped = False

    def is_available(self) -> bool:
        return True

    @property
    def supports_hotplug(self) -> bool:
        return True

    def start_monitoring(self, on_change):
        self._cb = on_change
        self.stopped = False
        return True

    def stop_monitoring(self) -> None:
        self.stopped = True
        self._cb = None

    def trigger_event(self):
        if self._cb is not None:
            self._cb()

    def scan_devices(self):
        self.scan_calls += 1
        return list(self._devices)


class _DummyPollingBackend(BaseBackend):
    def __init__(self, name="headsetcontrol", devices=None):
        super().__init__(name)
        self._devices = list(devices or [])
        self.scan_calls = 0

    def is_available(self) -> bool:
        return True

    def scan_devices(self):
        self.scan_calls += 1
        return list(self._devices)


class TestDeviceManagerHotplugAndDebounce(unittest.TestCase):
    def test_burst_hotplug_events_debounce_into_single_refresh(self):
        hp = _DummyHotplugBackend()
        mgr = DeviceManager(auto_refresh=False, backends=[hp], enable_hotplug=True)
        mgr._hotplug_debounce_timer.setInterval(40)
        self.addCleanup(mgr.cleanup)

        with patch.object(mgr, "refresh_devices") as mock_refresh:
            for _ in range(5):
                hp.trigger_event()
            _process_qt_events_for(0.15)
            mock_refresh.assert_called_once()

    def test_hotplug_event_during_active_scan_defers_followup_refresh(self):
        hp = _DummyHotplugBackend()
        mgr = DeviceManager(auto_refresh=False, backends=[hp], enable_hotplug=True)
        mgr._hotplug_debounce_timer.setInterval(20)
        self.addCleanup(mgr.cleanup)

        mgr._is_scanning = True
        with patch.object(mgr, "refresh_devices") as mock_refresh:
            hp.trigger_event()
            _process_qt_events_for(0.06)
            mock_refresh.assert_not_called()
            self.assertTrue(mgr._pending_refresh)

            mgr._is_scanning = False
            mgr._scanFinished.emit()
            _process_qt_events_for(0.06)
            mock_refresh.assert_called_once()

    def test_poll_timeout_skips_hotplug_backends_and_preserves_cached_devices(self):
        mouse = Device(
            id="ratbag_hidraw6",
            name="Logitech G502 X",
            vendor="Logitech",
            device_type=DeviceType.MOUSE,
            usb_vid="046d",
            usb_pid="c099",
        )
        headset = Device(
            id="headset_046d_0aba",
            name="Logitech PRO X Wireless",
            vendor="Logitech",
            device_type=DeviceType.HEADSET,
            usb_vid="046d",
            usb_pid="0aba",
            capabilities=[Capability.BATTERY],
            battery=BatteryInfo(percentage=75),
            backend_name="headsetcontrol",
        )
        hp = _DummyHotplugBackend("ratbagd", devices=[mouse])
        cli = _DummyPollingBackend("headsetcontrol", devices=[headset])

        # 1. All hotplug -> _on_poll_timeout does nothing
        mgr_only_hp = DeviceManager(auto_refresh=False, backends=[hp], enable_hotplug=True)
        self.addCleanup(mgr_only_hp.cleanup)
        with patch.object(mgr_only_hp, "_start_scan") as mock_start_scan:
            mgr_only_hp._on_poll_timeout()
            mock_start_scan.assert_not_called()

        # 2. Mixed hotplug + CLI -> _on_poll_timeout scans ONLY CLI backend and keeps cached mouse
        mgr = DeviceManager(auto_refresh=False, backends=[cli, hp], enable_hotplug=True)
        self.addCleanup(mgr.cleanup)

        with patch.object(mgr, "_update_health_checks", return_value=[]):
            mgr._scan_worker()  # initial full scan
            self.assertEqual(hp.scan_calls, 1)
            self.assertEqual(cli.scan_calls, 1)
            self.assertEqual(len(mgr._devices), 2)

            # Simulate fallback poll timer tick
            mgr._on_poll_timeout()
            deadline = time.monotonic() + 1.0
            while mgr._is_scanning and time.monotonic() < deadline:
                _process_qt_events_for(0.02)

        self.assertEqual(hp.scan_calls, 1)
        self.assertEqual(cli.scan_calls, 2)
        self.assertEqual({d.id for d in mgr._devices}, {"ratbag_hidraw6", "headset_046d_0aba"})

    def test_cleanup_stops_timers_and_backend_monitors(self):
        hp = _DummyHotplugBackend()
        mgr = DeviceManager(auto_refresh=False, backends=[hp], enable_hotplug=True)
        hp.trigger_event()
        self.assertTrue(mgr._timer.isActive())
        self.assertTrue(mgr._hotplug_debounce_timer.isActive())

        mgr.cleanup()
        self.assertFalse(mgr._timer.isActive())
        self.assertFalse(mgr._hotplug_debounce_timer.isActive())
        self.assertTrue(hp.stopped)


if __name__ == "__main__":
    unittest.main()
