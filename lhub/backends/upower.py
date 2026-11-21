"""UPower D-Bus backend for battery levels and hotplug monitoring of peripherals."""

import logging
import re
from typing import Callable, Dict, List, Optional, Set, Tuple

from .base import BaseBackend, BatteryInfo, Capability, Device, DeviceType
from .dbus_client import (
    DBUS_IFACE,
    DBUS_PATH,
    DBUS_PROPERTIES_IFACE,
    DBUS_SERVICE,
    DBusError,
    DBusSignalEvent,
    SystemDBusClient,
    get_system_dbus_client,
)

logger = logging.getLogger(__name__)

UPOWER_SERVICE = "org.freedesktop.UPower"
UPOWER_PATH = "/org/freedesktop/UPower"
UPOWER_IFACE = "org.freedesktop.UPower"
UPOWER_DEVICE_IFACE = "org.freedesktop.UPower.Device"
UPOWER_DEVICES_PREFIX = "/org/freedesktop/UPower/devices/"
UPOWER_DISPLAY_DEVICE_PATH = "/org/freedesktop/UPower/devices/DisplayDevice"

# UPower org.freedesktop.UPower.Device Type enum values for peripherals
_PERIPHERAL_TYPE_MAP: Dict[int, DeviceType] = {
    5: DeviceType.MOUSE,       # Mouse
    6: DeviceType.KEYBOARD,    # Keyboard
    12: DeviceType.OTHER,      # Gaming Input
    13: DeviceType.OTHER,      # Pen
    14: DeviceType.OTHER,      # Touchpad
    17: DeviceType.HEADSET,    # Headset
    19: DeviceType.HEADSET,    # Headphones
    28: DeviceType.OTHER,      # Bluetooth Generic
}

# UPower org.freedesktop.UPower.Device State enum -> (is_charging, status_text)
_UPOWER_STATE_MAP: Dict[int, Tuple[bool, str]] = {
    1: (True, "Charging"),
    2: (False, "Discharging"),
    3: (False, "Empty"),
    4: (False, "Fully charged"),
    5: (True, "Pending charge"),
    6: (False, "Pending discharge"),
}

_PERIPHERAL_KEYWORDS = (
    "mouse",
    "keyboard",
    "headset",
    "headphone",
    "controller",
    "gaming",
    "gamepad",
)

_HID_IDS_RE = re.compile(r"\b00(?:03|05):([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\b")


def _infer_device_type_from_text(*parts: str) -> DeviceType:
    combined = " ".join(p.lower() for p in parts if p)
    if "mouse" in combined:
        return DeviceType.MOUSE
    if "keyboard" in combined:
        return DeviceType.KEYBOARD
    if "headset" in combined or "headphone" in combined:
        return DeviceType.HEADSET
    return DeviceType.OTHER


def _extract_vid_pid(native_path: str) -> Tuple[str, str]:
    if not native_path:
        return "", ""
    match = _HID_IDS_RE.search(native_path)
    if not match:
        return "", ""
    return match.group(1).lower(), match.group(2).lower()


class UPowerBackend(BaseBackend):
    """Backend to detect battery levels and hotplug events via UPower D-Bus."""

    def __init__(self, dbus_client: Optional[SystemDBusClient] = None):
        super().__init__("upower")
        self._dbus = dbus_client or get_system_dbus_client()
        self._subscription_ids: List[int] = []
        self._ignored_paths: Set[str] = set()

    def is_available(self) -> bool:
        return self._dbus.is_bus_available() and self._dbus.has_name_owner(UPOWER_SERVICE)

    @property
    def supports_hotplug(self) -> bool:
        return True

    def start_monitoring(self, on_change: Callable[[], None]) -> bool:
        self.stop_monitoring()
        core_ids: List[int] = []

        def _on_device_added_or_removed(event: DBusSignalEvent) -> None:
            if event.args and isinstance(event.args[0], str):
                self._ignored_paths.discard(event.args[0])
            on_change()

        def _on_properties_changed(event: DBusSignalEvent) -> None:
            path = event.path or ""
            if (
                not path.startswith(UPOWER_DEVICES_PREFIX)
                or path == UPOWER_DISPLAY_DEVICE_PATH
                or path in self._ignored_paths
            ):
                return
            if event.args and isinstance(event.args[0], str) and event.args[0] != UPOWER_DEVICE_IFACE:
                return
            on_change()

        def _on_name_owner_changed(event: DBusSignalEvent) -> None:
            if event.args and event.args[0] == UPOWER_SERVICE:
                self._ignored_paths.clear()
                on_change()

        for sig_args in (
            (UPOWER_SERVICE, UPOWER_PATH, UPOWER_IFACE, "DeviceAdded", _on_device_added_or_removed),
            (UPOWER_SERVICE, UPOWER_PATH, UPOWER_IFACE, "DeviceRemoved", _on_device_added_or_removed),
            (UPOWER_SERVICE, "", DBUS_PROPERTIES_IFACE, "PropertiesChanged", _on_properties_changed),
        ):
            sub_id = self._dbus.subscribe_signal(*sig_args)
            if sub_id is not None:
                core_ids.append(sub_id)
                self._subscription_ids.append(sub_id)

        name_sub_id = self._dbus.subscribe_signal(
            DBUS_SERVICE,
            DBUS_PATH,
            DBUS_IFACE,
            "NameOwnerChanged",
            _on_name_owner_changed,
        )
        if name_sub_id is not None:
            self._subscription_ids.append(name_sub_id)

        return len(core_ids) > 0

    def stop_monitoring(self) -> None:
        for sub_id in self._subscription_ids:
            self._dbus.unsubscribe_signal(sub_id)
        self._subscription_ids.clear()

    def scan_devices(self) -> List[Device]:
        if not self.is_available():
            return []

        devices: List[Device] = []
        try:
            reply = self._dbus.call_method(
                UPOWER_SERVICE,
                UPOWER_PATH,
                UPOWER_IFACE,
                "EnumerateDevices",
            )
            raw_paths = reply[0] if reply else []
            if not isinstance(raw_paths, (list, tuple)):
                return []

            for raw_path in raw_paths:
                path = str(raw_path)
                if path == UPOWER_DISPLAY_DEVICE_PATH or "/line_power_" in path.lower():
                    self._ignored_paths.add(path)
                    continue

                try:
                    props = self._dbus.get_all_properties(UPOWER_SERVICE, path, UPOWER_DEVICE_IFACE)
                except DBusError as exc:
                    logger.debug("Failed to read UPower properties for %s: %s", path, exc)
                    continue

                if bool(props.get("PowerSupply", False)):
                    self._ignored_paths.add(path)
                    continue

                native_path = str(props.get("NativePath") or "")
                model = str(props.get("Model") or "").strip()
                dev_type_code = int(props.get("Type") or 0)

                if dev_type_code in _PERIPHERAL_TYPE_MAP:
                    dev_type = _PERIPHERAL_TYPE_MAP[dev_type_code]
                elif dev_type_code in (0, 2) and any(
                    kw in text
                    for text in (path.lower(), native_path.lower(), model.lower())
                    for kw in _PERIPHERAL_KEYWORDS
                ):
                    dev_type = _infer_device_type_from_text(path, native_path, model)
                else:
                    self._ignored_paths.add(path)
                    continue

                self._ignored_paths.discard(path)

                if props.get("IsPresent") is False:
                    continue

                raw_pct = props.get("Percentage")
                if isinstance(raw_pct, (int, float)):
                    percentage = max(0, min(100, int(round(float(raw_pct)))))
                else:
                    percentage = -1

                state_code = int(props.get("State") or 0)
                is_charging, status_text = _UPOWER_STATE_MAP.get(state_code, (False, ""))

                tte_raw = props.get("TimeToEmpty")
                time_to_empty_min = (
                    max(1, int(round(float(tte_raw) / 60.0)))
                    if isinstance(tte_raw, (int, float)) and tte_raw > 0
                    else None
                )

                ttf_raw = props.get("TimeToFull")
                time_to_full_min = (
                    max(1, int(round(float(ttf_raw) / 60.0)))
                    if isinstance(ttf_raw, (int, float)) and ttf_raw > 0
                    else None
                )

                if not model:
                    model = path.rsplit("/", 1)[-1].replace("_", " ").title()

                vendor_raw = str(props.get("Vendor") or "").strip()
                vendor = vendor_raw if vendor_raw and vendor_raw.lower() != "generic" else (
                    model.split()[0] if model else "Generic"
                )
                vid, pid = _extract_vid_pid(native_path)

                dev = Device(
                    id=f"upower_{path.rsplit('/', 1)[-1]}",
                    name=model,
                    vendor=vendor,
                    device_type=dev_type,
                    usb_vid=vid,
                    usb_pid=pid,
                    capabilities=[Capability.BATTERY],
                    battery=BatteryInfo(
                        percentage=percentage,
                        is_charging=is_charging,
                        time_to_empty_min=time_to_empty_min,
                        time_to_full_min=time_to_full_min,
                        status_text=status_text,
                    ),
                    extra_props={
                        "native_path": native_path,
                        "dbus_path": path,
                        "upower_type": dev_type_code,
                    },
                    backend_name=self.name,
                )
                devices.append(dev)

        except DBusError as exc:
            logger.warning("UPowerBackend D-Bus scan failed: %s", exc)
        except Exception as exc:
            logger.warning("UPowerBackend scan failed: %s", exc)

        return devices
