import threading
from typing import List, Dict, Any, Optional, Set
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer

from .backends import (
    Device,
    DeviceType,
    Capability,
    BaseBackend,
    RatbagBackend,
    HeadsetBackend,
    UPowerBackend,
)


class DeviceManager(QObject):
    devicesChanged = Signal()
    statusChanged = Signal()
    batteryWarning = Signal(str, int)  # device_name, percentage

    def __init__(self, parent=None):
        super().__init__(parent)
        self.backends: List[BaseBackend] = [
            HeadsetBackend(),
            RatbagBackend(),
            UPowerBackend(),
        ]
        self._devices: List[Device] = []
        self._cached_dict_devices: List[Dict[str, Any]] = []
        self._is_scanning = False
        self._warned_devices: Set[str] = set()

        # Background refresh timer every 30 seconds
        self._timer = QTimer(self)
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self.refresh_devices)
        self._timer.start()

        # Initial scan
        self.refresh_devices()

    @Slot()
    def refresh_devices(self):
        if self._is_scanning:
            return
        self._is_scanning = True

        # Run scan in background thread to avoid freezing GUI
        thread = threading.Thread(target=self._scan_worker, daemon=True)
        thread.start()

    def _scan_worker(self):
        try:
            detected: List[Device] = []
            for b in self.backends:
                if b.is_available():
                    try:
                        devs = b.scan_devices()
                        detected.extend(devs)
                    except Exception:
                        pass

            merged = self._merge_devices(detected)

            # Check low battery warnings
            for d in merged:
                if d.battery and d.battery.percentage >= 0 and not d.battery.is_charging:
                    if d.battery.percentage <= 20 and d.id not in self._warned_devices:
                        self._warned_devices.add(d.id)
                        self.batteryWarning.emit(d.name, d.battery.percentage)
                    elif d.battery.percentage > 25 and d.id in self._warned_devices:
                        self._warned_devices.remove(d.id)

            dict_devs = [self._device_to_dict(d) for d in merged]

            # Update cache and notify in main thread safe manner
            self._devices = merged
            self._cached_dict_devices = dict_devs
            self.devicesChanged.emit()
            self.statusChanged.emit()
        finally:
            self._is_scanning = False

    def _merge_devices(self, raw_list: List[Device]) -> List[Device]:
        merged: List[Device] = []
        seen_keys = {}

        for dev in raw_list:
            # Build unique key: VID:PID or cleaned name
            key = ""
            if dev.usb_vid and dev.usb_pid:
                key = f"{dev.usb_vid}:{dev.usb_pid}"
            else:
                key = dev.name.lower().replace("-", " ").strip()

            if key not in seen_keys:
                seen_keys[key] = dev
                merged.append(dev)
            else:
                # Merge capabilities if existing backend has less info
                existing = seen_keys[key]
                if not existing.battery and dev.battery:
                    existing.battery = dev.battery
                elif existing.battery and dev.battery and dev.battery.percentage >= 0:
                    existing.battery = dev.battery

        return merged

    def _device_to_dict(self, dev: Device) -> Dict[str, Any]:
        time_str = ""
        if dev.battery and dev.battery.time_to_empty_min:
            hrs = dev.battery.time_to_empty_min // 60
            mins = dev.battery.time_to_empty_min % 60
            time_str = f"~{hrs} Std. {mins} Min." if hrs > 0 else f"~{mins} Min."

        return {
            "id": dev.id,
            "name": dev.name,
            "vendor": dev.vendor,
            "type": dev.device_type.value,
            "capabilities": [c.value for c in dev.capabilities],
            "hasBattery": Capability.BATTERY in dev.capabilities and dev.battery is not None and dev.battery.is_supported,
            "batteryPercentage": dev.battery.percentage if dev.battery else -1,
            "isCharging": dev.battery.is_charging if dev.battery else False,
            "batteryStatusText": dev.battery.status_text if dev.battery else "",
            "batteryTimeRemaining": time_str,
            "hasDpi": Capability.DPI in dev.capabilities,
            "currentDpi": dev.dpi.current if dev.dpi else 800,
            "dpiSteps": dev.dpi.steps if dev.dpi else [400, 800, 1600, 3200],
            "isDpiDisabled": dev.dpi.is_disabled if dev.dpi else False,
            "hasSidetone": Capability.SIDETONE in dev.capabilities,
            "sidetone": dev.sidetone if dev.sidetone is not None else 0,
            "hasInactiveTime": Capability.INACTIVE_TIME in dev.capabilities,
            "inactiveTime": dev.inactive_time if dev.inactive_time is not None else 15,
            "hasButtons": Capability.BUTTON_REMAP in dev.capabilities,
            "buttons": [
                {"index": b.index, "name": b.name, "action": b.action_value}
                for b in dev.buttons
            ],
            "statusNote": dev.status_note,
            "backend": dev.backend_name,
        }

    @Property("QVariantList", notify=devicesChanged)
    def devices(self) -> List[Dict[str, Any]]:
        return self._cached_dict_devices

    @Property("QVariantList", notify=statusChanged)
    def missingBackends(self) -> List[str]:
        missing = []
        for b in self.backends:
            if not b.is_available():
                msg = b.get_missing_reason()
                if msg:
                    missing.append(msg)
        return missing

    @Slot(str, int, result=bool)
    def setDpi(self, device_id: str, dpi: int) -> bool:
        for b in self.backends:
            if isinstance(b, RatbagBackend):
                if b.set_dpi(device_id, dpi):
                    self.refresh_devices()
                    return True
        return False

    @Slot(str, int)
    def setSidetone(self, device_id: str, level: int):
        # Update local cache immediately
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                d["sidetone"] = level
                self.devicesChanged.emit()
                break

        def _worker():
            for b in self.backends:
                if isinstance(b, HeadsetBackend):
                    b.set_sidetone(device_id, level)

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(str, int)
    def setInactiveTime(self, device_id: str, minutes: int):
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                d["inactiveTime"] = minutes
                self.devicesChanged.emit()
                break

        def _worker():
            for b in self.backends:
                if isinstance(b, HeadsetBackend):
                    b.set_inactive_time(device_id, minutes)

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(str, int, str, result=bool)
    def remapButton(self, device_id: str, button_idx: int, action: str) -> bool:
        for b in self.backends:
            if isinstance(b, RatbagBackend):
                if b.remap_button(device_id, button_idx, action):
                    self.refresh_devices()
                    return True
        return False
