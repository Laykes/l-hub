import logging
import math
import time
import threading
from typing import List, Dict, Any, Optional, Set, Tuple
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, QEvent, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent, QKeySequence

from .backends import (
    Device,
    Capability,
    BaseBackend,
    RatbagBackend,
    HeadsetBackend,
    UPowerBackend,
)
from .backends import hidpp, hid_input
from .backends.ratbag import (
    parse_button_action,
    KEY_DISPLAY_NAMES,
    format_key_combo,
    actions_match,
)
from .health import log_health_checks, run_health_checks, SEVERITY_ERROR
from .profiles import ProfileManager

logger = logging.getLogger(__name__)


_QT_MODIFIER_KEYS: Dict[int, str] = {
    Qt.Key.Key_Shift: "KEY_LEFTSHIFT",
    Qt.Key.Key_Control: "KEY_LEFTCTRL",
    Qt.Key.Key_Meta: "KEY_LEFTMETA",
    Qt.Key.Key_Alt: "KEY_LEFTALT",
    Qt.Key.Key_AltGr: "KEY_RIGHTALT",
}

_QT_TO_LINUX_KEY: Dict[int, str] = {
    Qt.Key.Key_Escape: "KEY_ESC",
    Qt.Key.Key_Tab: "KEY_TAB",
    Qt.Key.Key_Backtab: "KEY_TAB",
    Qt.Key.Key_Backspace: "KEY_BACKSPACE",
    Qt.Key.Key_Return: "KEY_ENTER",
    Qt.Key.Key_Enter: "KEY_ENTER",
    Qt.Key.Key_Insert: "KEY_INSERT",
    Qt.Key.Key_Delete: "KEY_DELETE",
    Qt.Key.Key_Pause: "KEY_PAUSE",
    Qt.Key.Key_Print: "KEY_PRINT",
    Qt.Key.Key_Home: "KEY_HOME",
    Qt.Key.Key_End: "KEY_END",
    Qt.Key.Key_Left: "KEY_LEFT",
    Qt.Key.Key_Up: "KEY_UP",
    Qt.Key.Key_Right: "KEY_RIGHT",
    Qt.Key.Key_Down: "KEY_DOWN",
    Qt.Key.Key_PageUp: "KEY_PAGEUP",
    Qt.Key.Key_PageDown: "KEY_PAGEDOWN",
    Qt.Key.Key_CapsLock: "KEY_CAPSLOCK",
    Qt.Key.Key_NumLock: "KEY_NUMLOCK",
    Qt.Key.Key_ScrollLock: "KEY_SCROLLLOCK",
    Qt.Key.Key_Space: "KEY_SPACE",
    Qt.Key.Key_Minus: "KEY_MINUS",
    Qt.Key.Key_Equal: "KEY_EQUAL",
    Qt.Key.Key_BracketLeft: "KEY_LEFTBRACE",
    Qt.Key.Key_BracketRight: "KEY_RIGHTBRACE",
    Qt.Key.Key_Semicolon: "KEY_SEMICOLON",
    Qt.Key.Key_Apostrophe: "KEY_APOSTROPHE",
    Qt.Key.Key_QuoteLeft: "KEY_GRAVE",
    Qt.Key.Key_Backslash: "KEY_BACKSLASH",
    Qt.Key.Key_Comma: "KEY_COMMA",
    Qt.Key.Key_Period: "KEY_DOT",
    Qt.Key.Key_Slash: "KEY_SLASH",
    Qt.Key.Key_VolumeUp: "KEY_VOLUMEUP",
    Qt.Key.Key_VolumeDown: "KEY_VOLUMEDOWN",
    Qt.Key.Key_VolumeMute: "KEY_MUTE",
    Qt.Key.Key_MediaPlay: "KEY_PLAYPAUSE",
    Qt.Key.Key_MediaPause: "KEY_PLAYPAUSE",
    Qt.Key.Key_MediaTogglePlayPause: "KEY_PLAYPAUSE",
    Qt.Key.Key_MediaNext: "KEY_NEXTSONG",
    Qt.Key.Key_MediaPrevious: "KEY_PREVIOUSSONG",
    Qt.Key.Key_MediaStop: "KEY_STOPCD",
    **_QT_MODIFIER_KEYS,
}
for _i in range(1, 25):
    _QT_TO_LINUX_KEY[getattr(Qt.Key, f"Key_F{_i}")] = f"KEY_F{_i}"


def _qt_key_to_linux(key: int) -> Optional[str]:
    if key in _QT_TO_LINUX_KEY:
        return _QT_TO_LINUX_KEY[key]
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return f"KEY_{chr(key)}"
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return f"KEY_{chr(key)}"
    return None


def _qt_modifiers_to_linux(modifiers) -> List[str]:
    mod_val = int(modifiers.value) if hasattr(modifiers, "value") else int(modifiers)
    mods: List[str] = []
    if mod_val & int(Qt.KeyboardModifier.ControlModifier.value):
        mods.append("KEY_LEFTCTRL")
    if mod_val & int(Qt.KeyboardModifier.AltModifier.value):
        mods.append("KEY_LEFTALT")
    if mod_val & int(Qt.KeyboardModifier.ShiftModifier.value):
        mods.append("KEY_LEFTSHIFT")
    if mod_val & int(Qt.KeyboardModifier.MetaModifier.value):
        mods.append("KEY_LEFTMETA")
    return mods




class DeviceManager(QObject):
    LOW_BATTERY_THRESHOLD = 20
    LOW_BATTERY_RESET_THRESHOLD = 25

    devicesChanged = Signal()
    statusChanged = Signal()
    healthChecksChanged = Signal()
    batteryWarning = Signal(str, int)  # device_name, percentage
    onboardProfileChanged = Signal(str, str)  # device_name, profile_label
    testStateChanged = Signal()
    testResultChanged = Signal()
    _hidppProfileEvent = Signal(str, int)  # device_key, profile_id
    _hidppDpiEvent = Signal(str, int)  # device_key, dpi
    _hidInputEvent = Signal(str, str)  # action, detected_name

    def __init__(self, parent=None, auto_refresh: bool = True):
        super().__init__(parent)
        self.profile_mgr = ProfileManager()
        self.backends: List[BaseBackend] = [
            HeadsetBackend(),
            RatbagBackend(),
            UPowerBackend(),
        ]
        self._devices: List[Device] = []
        self._cached_dict_devices: List[Dict[str, Any]] = []
        self._health_checks: List[Dict[str, Any]] = []
        self._last_health_signature: Optional[Tuple[Tuple[str, str, str, str], ...]] = None
        self._is_scanning = False
        self._warned_devices: Set[str] = set()
        self._hidpp_monitors: Dict[str, hidpp.OnboardProfileMonitor] = {}
        self._monitors_lock = threading.Lock()

        self._hidppProfileEvent.connect(self._on_hidpp_profile_event)
        self._hidppDpiEvent.connect(self._on_hidpp_dpi_event)
        self._hidInputEvent.connect(self._on_hid_input_event)

        # Button tester state
        self._is_testing_button = False
        self._testing_device_id = ""
        self._tested_button_result: Dict[str, Any] = {}
        self._hid_input_monitor: Optional[hid_input.HidInputMonitor] = None
        self._pending_qt_mods: List[str] = []
        self._pending_mod_timer = QTimer(self)
        self._pending_mod_timer.setSingleShot(True)
        self._pending_mod_timer.setInterval(int(hid_input.MODIFIER_HOLD_TIMEOUT * 1000))
        self._pending_mod_timer.timeout.connect(self._on_pending_mod_timeout)
        self._suppress_qt_until: float = 0.0
        self._suppress_qt_action: str = ""
        self._test_timer = QTimer(self)
        self._test_timer.setSingleShot(True)
        self._test_timer.setInterval(15000)
        self._test_timer.timeout.connect(self._on_test_timeout)

        # Background refresh timer every 30 seconds
        self._timer = QTimer(self)
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self.refresh_devices)
        self._timer.start()

        # Initial scan
        if auto_refresh:
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
                    except Exception as exc:
                        logger.warning(
                            "Backend %s scan failed: %s",
                            b.name,
                            exc,
                            exc_info=logger.isEnabledFor(logging.DEBUG),
                        )
                else:
                    logger.debug("Backend %s unavailable: %s", b.name, b.get_missing_reason() or "not found")

            merged = self._merge_devices(detected)

            # Ensure default profile for devices with configurable buttons
            for d in merged:
                if d.buttons:
                    dev_key = self._get_device_key(d)
                    b_map = {b.index: b.action_value for b in d.buttons}
                    dpi_val = d.dpi.current if (d.dpi and not d.dpi.is_disabled) else None
                    self.profile_mgr.ensure_default_profile(dev_key, b_map, dpi_val)

            # Check low battery warnings
            self._check_battery_warnings(merged)

            dict_devs = [self._device_to_dict(d) for d in merged]

            # Update cache and notify in main thread safe manner
            self._devices = merged
            self._cached_dict_devices = dict_devs
            self._sync_hidpp_monitors(merged)
            logger.debug("Device scan complete: %d device(s) active", len(merged))
            self.devicesChanged.emit()
            self._update_health_checks(merged)
            self.statusChanged.emit()
        finally:
            self._is_scanning = False

    def _check_battery_warnings(self, devices: List[Device]):
        for d in devices:
            if not d.battery or not d.battery.is_supported:
                continue
            dev_key = self._get_device_key(d)
            if d.battery.is_charging:
                self._warned_devices.discard(dev_key)
            elif 0 <= d.battery.percentage <= self.LOW_BATTERY_THRESHOLD:
                if dev_key not in self._warned_devices:
                    self._warned_devices.add(dev_key)
                    self.batteryWarning.emit(d.name, d.battery.percentage)
            elif d.battery.percentage > self.LOW_BATTERY_RESET_THRESHOLD:
                self._warned_devices.discard(dev_key)

    def _sync_hidpp_monitors(self, devices: List[Device]):
        active_keys: Set[str] = set()
        with self._monitors_lock:
            for d in devices:
                if (
                    d.usb_vid
                    and d.usb_pid
                    and d.usb_vid.lower() == hidpp.LOGITECH_VID
                    and d.onboard_profile_id is not None
                ):
                    dev_key = self._get_device_key(d)
                    active_keys.add(dev_key)
                    existing = self._hidpp_monitors.get(dev_key)
                    if existing is None or not existing.is_running:
                        mon = hidpp.OnboardProfileMonitor(
                            d.usb_vid,
                            d.usb_pid,
                            on_profile_changed=lambda pid, k=dev_key: self._hidppProfileEvent.emit(k, pid),
                            on_dpi_changed=lambda dpi, k=dev_key: self._hidppDpiEvent.emit(k, dpi),
                        )
                        if mon.start():
                            self._hidpp_monitors[dev_key] = mon
                        else:
                            logger.debug("HID++ onboard profile monitor unavailable for %s", dev_key)

            for stale_key in list(self._hidpp_monitors.keys()):
                if stale_key not in active_keys:
                    self._hidpp_monitors.pop(stale_key).stop()

    def _on_hidpp_profile_event(self, device_key: str, profile_id: int):
        label = hidpp.format_onboard_profile(profile_id)
        target_dev: Optional[Device] = None
        for d in self._devices:
            if self._get_device_key(d) == device_key:
                target_dev = d
                break
        if target_dev is None:
            return

        changed = target_dev.onboard_profile_id != profile_id
        target_dev.onboard_profile_id = profile_id
        target_dev.onboard_profile = label

        for entry in self._cached_dict_devices:
            if entry.get("deviceKey") == device_key:
                entry["hasOnboardProfile"] = True
                entry["onboardProfile"] = label
                break

        if changed:
            self.devicesChanged.emit()
            self.onboardProfileChanged.emit(target_dev.name, label)
            if target_dev.usb_vid and target_dev.usb_pid:
                vid, pid = target_dev.usb_vid, target_dev.usb_pid

                def _read_new_dpi():
                    dpi = hidpp.get_dpi(vid, pid)
                    if dpi and 50 <= dpi <= 30000:
                        self._hidppDpiEvent.emit(device_key, dpi)

                threading.Thread(target=_read_new_dpi, daemon=True).start()
            self.refresh_devices()

    def _on_hidpp_dpi_event(self, device_key: str, dpi: int):
        updated = False
        for d in self._devices:
            if self._get_device_key(d) == device_key and d.dpi:
                if d.dpi.current != dpi:
                    d.dpi.current = dpi
                    if dpi not in d.dpi.steps:
                        d.dpi.steps = sorted(set(d.dpi.steps + [dpi]))
                    updated = True
                break

        if not updated:
            return

        for entry in self._cached_dict_devices:
            if entry.get("deviceKey") == device_key:
                entry["currentDpi"] = dpi
                steps = entry.get("dpiSteps", [])
                if dpi not in steps:
                    entry["dpiSteps"] = sorted(set(steps + [dpi]))
                break

        self.devicesChanged.emit()

    @Slot()
    def cleanup(self):
        self._stop_hid_input_monitor()
        with self._monitors_lock:
            for mon in self._hidpp_monitors.values():
                mon.stop()
            self._hidpp_monitors.clear()

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
                elif existing.backend_name != "headsetcontrol" and dev.battery and dev.battery.percentage >= 0:
                    existing.battery = dev.battery

        return merged

    def _device_to_dict(self, dev: Device) -> Dict[str, Any]:
        time_str = ""
        if dev.battery:
            if dev.battery.is_charging:
                if dev.battery.time_to_full_min is not None:
                    if dev.battery.time_to_full_min == 0:
                        time_str = "Fully charged"
                    else:
                        hrs = dev.battery.time_to_full_min // 60
                        mins = dev.battery.time_to_full_min % 60
                        time_str = f"Full in ~{hrs} hr {mins} min" if hrs > 0 else f"Full in ~{mins} min"
                else:
                    time_str = ""
            elif dev.battery.time_to_empty_min:
                hrs = dev.battery.time_to_empty_min // 60
                mins = dev.battery.time_to_empty_min % 60
                time_str = f"~{hrs} hr {mins} min" if hrs > 0 else f"~{mins} min"

        dev_key = self._get_device_key(dev)
        profiles = self.profile_mgr.get_profiles(dev_key)
        active_profile = self.profile_mgr.get_active_profile(dev_key)

        return {
            "id": dev.id,
            "name": dev.name,
            "vendor": dev.vendor,
            "type": dev.device_type.value,
            "deviceKey": dev_key,
            "profiles": profiles,
            "activeProfile": active_profile,
            "hasOnboardProfile": bool(dev.onboard_profile),
            "onboardProfile": dev.onboard_profile or "",
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
            "hasButtons": Capability.BUTTON_REMAP in dev.capabilities,
            "buttons": [
                {
                    "index": b.index,
                    "name": b.name,
                    "label": getattr(b, "label", "") or b.name,
                    "location": getattr(b, "location", ""),
                    "group": getattr(b, "group", "main"),
                    "defaultAction": getattr(b, "default_action", ""),
                    "action": b.action_value,
                    "actionDisplay": b.action_display or b.action_value,
                    "isCustomized": bool(getattr(b, "default_action", "") and b.action_value != getattr(b, "default_action", "")),
                }
                for b in dev.buttons
            ],
            "statusNote": dev.status_note,
            "backend": dev.backend_name,
        }

    def _get_device_key(self, dev: Device) -> str:
        if dev.usb_vid and dev.usb_pid:
            return f"{dev.usb_vid}:{dev.usb_pid}"
        return dev.name.lower().replace("-", " ").strip()

    def _get_device_by_id(self, device_id: str) -> Optional[Device]:
        for d in self._devices:
            if d.id == device_id:
                return d
        return None

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

    def _update_health_checks(self, devices: Optional[List[Device]] = None) -> List[Dict[str, Any]]:
        items = run_health_checks(devices=devices, log_results=False)
        signature = tuple((i.id, i.severity, i.title, i.description) for i in items)
        if signature != self._last_health_signature:
            self._last_health_signature = signature
            log_health_checks(items)
        else:
            logger.debug(
                "System health unchanged (%d checks, %d issues)",
                len(items),
                sum(1 for i in items if i.is_issue),
            )
        self._health_checks = [i.to_dict() for i in items]
        self.healthChecksChanged.emit()
        return self._health_checks

    @Property("QVariantList", notify=healthChecksChanged)
    def healthChecks(self) -> List[Dict[str, Any]]:
        return self._health_checks

    @Property("QVariantList", notify=healthChecksChanged)
    def healthIssues(self) -> List[Dict[str, Any]]:
        issues = [item for item in self._health_checks if item.get("isIssue")]
        issues.sort(key=lambda item: 0 if item.get("severity") == SEVERITY_ERROR else 1)
        return issues

    @Property(bool, notify=healthChecksChanged)
    def hasHealthIssues(self) -> bool:
        return any(item.get("isIssue") for item in self._health_checks)

    @Slot()
    def refreshHealth(self):
        devices_snapshot = list(self._devices)
        threading.Thread(
            target=lambda: self._update_health_checks(devices_snapshot),
            daemon=True,
        ).start()

    @Slot(str, result=bool)
    def copyToClipboard(self, text: str) -> bool:
        if not text:
            return False
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            logger.warning("Clipboard is unavailable; could not copy text")
            return False
        clipboard.setText(text)
        return True

    @Slot(str, int, result=bool)
    def setDpi(self, device_id: str, dpi: int) -> bool:
        dev = self._get_device_by_id(device_id)
        # Update local cache immediately for responsive UI
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                d["currentDpi"] = dpi
                self.devicesChanged.emit()
                break

        def _worker():
            for b in self.backends:
                if isinstance(b, RatbagBackend):
                    if b.set_dpi(device_id, dpi):
                        if dev:
                            if dev.dpi:
                                dev.dpi.current = dpi
                            dev_key = self._get_device_key(dev)
                            self.profile_mgr.update_active_dpi(dev_key, dpi)
                        break
            self.refresh_devices()

        threading.Thread(target=_worker, daemon=True).start()
        return True

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

    @Slot(str, int, str, result=bool)
    def remapButton(self, device_id: str, button_idx: int, action: str) -> bool:
        norm_action, norm_display = parse_button_action(action)
        dev = self._get_device_by_id(device_id)
        if dev and dev.buttons:
            for b in dev.buttons:
                if b.index == button_idx:
                    b.action_value = norm_action
                    b.action_display = norm_display
                    break

        # Update local cache immediately for responsive UI
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                for btn in d.get("buttons", []):
                    if btn["index"] == button_idx:
                        btn["action"] = norm_action
                        btn["actionDisplay"] = norm_display
                        btn["isCustomized"] = bool(
                            btn.get("defaultAction") and norm_action != btn.get("defaultAction")
                        )
                        break
                self.devicesChanged.emit()
                break

        def _worker():
            for b in self.backends:
                if isinstance(b, RatbagBackend):
                    if b.remap_button(device_id, button_idx, action):
                        if dev:
                            dev_key = self._get_device_key(dev)
                            self.profile_mgr.update_active_button(dev_key, button_idx, action)
                        break
            self.refresh_devices()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    @Slot(str, int, result=bool)
    def resetButtonToDefault(self, device_id: str, button_idx: int) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or not dev.buttons:
            return False
        default_act = None
        for b in dev.buttons:
            if b.index == button_idx:
                default_act = getattr(b, "default_action", "")
                break
        if not default_act:
            return False
        return self.remapButton(device_id, button_idx, default_act)

    @Slot(int, int, result="QVariantMap")
    def resolveKeyAction(self, key: int, modifiers: int) -> Dict[str, Any]:
        linux_key = _qt_key_to_linux(key)
        if not linux_key:
            return {}

        if key in _QT_MODIFIER_KEYS:
            act, disp = format_key_combo([linux_key], None)
        else:
            mods = _qt_modifiers_to_linux(modifiers)
            act, disp = format_key_combo(mods, linux_key)
        return {"action": act, "display": disp} if act else {}

    @Slot(str, str, result=bool)
    def applyProfile(self, device_id: str, profile_name: str) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev:
            return False
        dev_key = self._get_device_key(dev)
        prof_data = self.profile_mgr.get_profile_data(dev_key, profile_name)
        if not prof_data:
            return False

        self.profile_mgr.set_active_profile(dev_key, profile_name)

        # Update local cache immediately
        buttons_data = prof_data.get("buttons", {})
        if dev.buttons:
            for b in dev.buttons:
                idx_str = str(b.index)
                if idx_str in buttons_data:
                    norm_act, norm_disp = parse_button_action(buttons_data[idx_str])
                    b.action_value = norm_act
                    b.action_display = norm_disp
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                d["activeProfile"] = profile_name
                for btn in d.get("buttons", []):
                    idx_str = str(btn["index"])
                    if idx_str in buttons_data:
                        norm_act, norm_disp = parse_button_action(buttons_data[idx_str])
                        btn["action"] = norm_act
                        btn["actionDisplay"] = norm_disp
                        btn["isCustomized"] = bool(
                            btn.get("defaultAction") and norm_act != btn.get("defaultAction")
                        )
                if "dpi" in prof_data:
                    d["currentDpi"] = prof_data["dpi"]
                self.devicesChanged.emit()
                break

        def _worker():
            buttons = {int(k): v for k, v in prof_data.get("buttons", {}).items()}
            dpi = prof_data.get("dpi")
            for b in self.backends:
                if isinstance(b, RatbagBackend):
                    if buttons:
                        b.batch_remap_buttons(device_id, buttons)
                    if dpi and dev.dpi and not dev.dpi.is_disabled:
                        b.set_dpi(device_id, int(dpi))
            self.refresh_devices()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    @Slot(str, str, result=bool)
    def saveProfile(self, device_id: str, profile_name: str) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or not profile_name.strip():
            return False
        dev_key = self._get_device_key(dev)
        buttons = {b.index: b.action_value for b in dev.buttons}
        dpi = dev.dpi.current if (dev.dpi and not dev.dpi.is_disabled) else None
        self.profile_mgr.save_profile(dev_key, profile_name.strip(), buttons, dpi)

        # Update local cache immediately
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                if profile_name.strip() not in d.get("profiles", []):
                    d["profiles"].append(profile_name.strip())
                d["activeProfile"] = profile_name.strip()
                self.devicesChanged.emit()
                break

        self.refresh_devices()
        return True

    @Slot(str, str, result=bool)
    def deleteProfile(self, device_id: str, profile_name: str) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or not profile_name:
            return False
        dev_key = self._get_device_key(dev)
        if self.profile_mgr.delete_profile(dev_key, profile_name):
            active = self.profile_mgr.get_active_profile(dev_key)

            # Update local cache immediately
            for d in self._cached_dict_devices:
                if d["id"] == device_id:
                    if profile_name in d.get("profiles", []):
                        d["profiles"].remove(profile_name)
                    self.devicesChanged.emit()
                    break

            self.applyProfile(device_id, active)
            return True
        return False

    @Slot(str, result=bool)
    def resetDeviceToDefault(self, device_id: str) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev:
            return False
        dev_key = self._get_device_key(dev)

        defaults_map = {
            0: ("button 1", "Left Click"),
            1: ("button 2", "Right Click"),
            2: ("button 3", "Middle Click"),
            3: ("button 4", "Back (Button 4)"),
            4: ("special resolution-alternate", "DPI Shift (Sniper)"),
            5: ("button 5", "Forward (Button 5)"),
            6: ("special wheel-left", "Scroll Wheel Left"),
            7: ("special wheel-right", "Scroll Wheel Right"),
            8: ("special profile-cycle-up", "Cycle Profile"),
            9: ("special resolution-up", "DPI +"),
            10: ("special resolution-down", "DPI -"),
        }

        # Update local cache immediately
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                d["activeProfile"] = "Default"
                for btn in d.get("buttons", []):
                    if btn["index"] in defaults_map:
                        btn["action"] = defaults_map[btn["index"]][0]
                        btn["actionDisplay"] = defaults_map[btn["index"]][1]
                self.devicesChanged.emit()
                break

        def _worker():
            for b in self.backends:
                if isinstance(b, RatbagBackend):
                    b.reset_defaults(device_id)
                    updated = b.scan_devices()
                    for ud in updated:
                        if ud.id == device_id or self._get_device_key(ud) == dev_key:
                            b_map = {btn.index: btn.action_value for btn in ud.buttons}
                            dpi_val = ud.dpi.current if (ud.dpi and not ud.dpi.is_disabled) else 800
                            self.profile_mgr.reset_to_default(dev_key, b_map, dpi_val)
                            break
            self.refresh_devices()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    @Property(bool, notify=testStateChanged)
    def isTestingButton(self) -> bool:
        return self._is_testing_button

    @Property(str, notify=testStateChanged)
    def testingDeviceId(self) -> str:
        return self._testing_device_id

    @Property("QVariantMap", notify=testResultChanged)
    def testedButtonResult(self) -> Dict[str, Any]:
        return self._tested_button_result

    def _stop_hid_input_monitor(self):
        mon = self._hid_input_monitor
        self._hid_input_monitor = None
        if mon is not None:
            mon.stop()

    def _clear_pending_qt_mods(self):
        self._pending_qt_mods.clear()
        self._pending_mod_timer.stop()

    @Slot(str)
    def startButtonTest(self, device_id: str):
        self._stop_hid_input_monitor()
        self._clear_pending_qt_mods()
        self._suppress_qt_until = 0.0
        self._suppress_qt_action = ""
        self._is_testing_button = True
        self._testing_device_id = device_id
        self._tested_button_result = {}
        self._test_timer.start(15000)

        dev = self._get_device_by_id(device_id)
        if dev and dev.usb_vid and dev.usb_pid:
            mon = hid_input.HidInputMonitor(
                dev.usb_vid,
                dev.usb_pid,
                on_input=lambda act, name: self._hidInputEvent.emit(act, name),
            )
            if mon.start():
                self._hid_input_monitor = mon
            else:
                logger.debug("Raw hidraw monitor unavailable for %s; using Qt events", device_id)

        self.testResultChanged.emit()
        self.testStateChanged.emit()

    @Slot()
    def stopButtonTest(self):
        self._stop_hid_input_monitor()
        self._clear_pending_qt_mods()
        if self._is_testing_button:
            self._is_testing_button = False
            self._test_timer.stop()
            self.testStateChanged.emit()

    @Slot()
    def clearTestResult(self):
        self._tested_button_result = {}
        self.testResultChanged.emit()

    def _on_test_timeout(self):
        self._stop_hid_input_monitor()
        self._clear_pending_qt_mods()
        if self._is_testing_button:
            self._is_testing_button = False
            self._tested_button_result = {
                "deviceId": self._testing_device_id,
                "detectedName": "",
                "statusNote": "No button press detected within 15 seconds.",
                "matchingIndices": [],
                "matchingNames": [],
            }
            self.testStateChanged.emit()
            self.testResultChanged.emit()

    def _on_pending_mod_timeout(self):
        if not self._is_testing_button or not self._pending_qt_mods:
            return
        mods = list(self._pending_qt_mods)
        self._clear_pending_qt_mods()
        action, detected_name = format_key_combo(mods, None)
        if action and detected_name:
            self._handle_detected_button(action, detected_name, relaxed_modifiers=True)

    def _on_hid_input_event(self, action: str, detected_name: str):
        if not self._is_testing_button:
            return
        self._suppress_qt_until = time.monotonic() + 0.15
        self._suppress_qt_action = action
        self._handle_detected_button(action, detected_name, relaxed_modifiers=False)

    def eventFilter(self, watched, event):
        ev_type = event.type()

        if not self._is_testing_button:
            if self._suppress_qt_action and time.monotonic() < self._suppress_qt_until:
                if ev_type == QEvent.Type.MouseButtonPress and self._suppress_qt_action.startswith("button "):
                    self._suppress_qt_until = 0.0
                    self._suppress_qt_action = ""
                    return True
                if ev_type == QEvent.Type.Wheel and self._suppress_qt_action in (
                    "special wheel-left",
                    "special wheel-right",
                ):
                    self._suppress_qt_until = 0.0
                    self._suppress_qt_action = ""
                    return True
                if ev_type == QEvent.Type.KeyPress and (
                    self._suppress_qt_action.startswith("key ") or self._suppress_qt_action.startswith("macro ")
                ):
                    return True
            return super().eventFilter(watched, event)

        action = None
        detected_name = None
        relaxed_modifiers = False

        if ev_type == QEvent.Type.MouseButtonPress:
            action, detected_name = self._map_mouse_button(event.button())
        elif ev_type == QEvent.Type.Wheel:
            dx = event.angleDelta().x()
            if event.inverted():
                dx = -dx
            if dx > 0:
                action, detected_name = "special wheel-left", "Scroll Wheel Left"
            elif dx < 0:
                action, detected_name = "special wheel-right", "Scroll Wheel Right"
            else:
                return super().eventFilter(watched, event)
        elif ev_type == QEvent.Type.KeyPress:
            if event.isAutoRepeat():
                return True
            key = event.key()
            mods = _qt_modifiers_to_linux(event.modifiers())
            if key == Qt.Key.Key_Escape and not mods and not self._pending_qt_mods:
                self.stopButtonTest()
                return True
            if key in _QT_MODIFIER_KEYS:
                mod_name = _QT_MODIFIER_KEYS[key]
                if mod_name not in self._pending_qt_mods:
                    self._pending_qt_mods.append(mod_name)
                self._pending_mod_timer.start()
                return True
            merged_mods = list(dict.fromkeys(self._pending_qt_mods + mods))
            self._clear_pending_qt_mods()
            action, detected_name = self._map_key_event(event, extra_modifiers=merged_mods)
            relaxed_modifiers = True
        elif ev_type == QEvent.Type.KeyRelease:
            if event.isAutoRepeat():
                return True
            if self._pending_qt_mods and event.key() in _QT_MODIFIER_KEYS:
                released_mod = _QT_MODIFIER_KEYS[event.key()]
                remaining = [m for m in _qt_modifiers_to_linux(event.modifiers()) if m != released_mod]
                if not remaining:
                    mods = list(self._pending_qt_mods)
                    self._clear_pending_qt_mods()
                    action, detected_name = format_key_combo(mods, None)
                    relaxed_modifiers = True

        if action and detected_name:
            self._handle_detected_button(action, detected_name, relaxed_modifiers=relaxed_modifiers)
            return True

        return super().eventFilter(watched, event)

    def _map_mouse_button(self, btn: Qt.MouseButton) -> Tuple[str, str]:
        mouse_button_actions = {
            Qt.MouseButton.LeftButton: ("button 1", "Left Click (Button 1)"),
            Qt.MouseButton.RightButton: ("button 2", "Right Click (Button 2)"),
            Qt.MouseButton.MiddleButton: ("button 3", "Middle Click (Button 3)"),
            Qt.MouseButton.BackButton: ("button 4", "Back (Button 4)"),
            Qt.MouseButton.ForwardButton: ("button 5", "Forward (Button 5)"),
            Qt.MouseButton.TaskButton: ("button 6", "Button 6"),
            Qt.MouseButton.ExtraButton4: ("button 7", "Button 7"),
            Qt.MouseButton.ExtraButton5: ("button 8", "Button 8"),
            Qt.MouseButton.ExtraButton6: ("button 9", "Button 9"),
            Qt.MouseButton.ExtraButton7: ("button 10", "Button 10"),
            Qt.MouseButton.ExtraButton8: ("button 11", "Button 11"),
            Qt.MouseButton.ExtraButton9: ("button 12", "Button 12"),
        }
        if btn in mouse_button_actions:
            return mouse_button_actions[btn]

        try:
            val = int(btn.value) if hasattr(btn, "value") else int(btn)
            if val > 0:
                btn_num = int(math.log2(val)) + 1
                return f"button {btn_num}", f"Button {btn_num}"
        except Exception as exc:
            logger.debug("Could not map Qt mouse button %r: %s", btn, exc)
        return "unknown", "Unknown Mouse Button"

    def _map_key_event(
        self,
        event: QKeyEvent,
        extra_modifiers: Optional[List[str]] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        key = event.key()
        mods = list(dict.fromkeys((extra_modifiers or []) + _qt_modifiers_to_linux(event.modifiers())))
        linux_key = _qt_key_to_linux(key)
        if linux_key:
            if key in _QT_MODIFIER_KEYS:
                act, disp = format_key_combo([linux_key], None)
            else:
                act, disp = format_key_combo(mods, linux_key)
            return (act, disp) if act else (None, None)

        seq = QKeySequence(key).toString()
        if seq:
            clean_k = seq.upper().replace(" ", "_")
            fallback_key = f"KEY_{clean_k}"
            if mods:
                act, disp = format_key_combo(mods, fallback_key)
                return (act, disp) if act else (None, None)
            return f"key {fallback_key}", f"Key: {seq}"
        return None, None

    def _handle_detected_button(self, action: str, detected_name: str, relaxed_modifiers: bool = False):
        self._stop_hid_input_monitor()
        self._clear_pending_qt_mods()
        dev = self._get_device_by_id(self._testing_device_id)
        matching_indices = []
        matching_names = []

        if dev and dev.buttons:
            exact_matches = [
                btn for btn in dev.buttons
                if actions_match(btn.action_value, action, relaxed_modifiers=False)
            ]
            matches = exact_matches
            if not matches and relaxed_modifiers:
                matches = [
                    btn for btn in dev.buttons
                    if actions_match(btn.action_value, action, relaxed_modifiers=True)
                ]
            matching_indices = [btn.index for btn in matches]
            matching_names = [btn.name for btn in matches]

        self._tested_button_result = {
            "deviceId": self._testing_device_id,
            "detectedName": detected_name,
            "action": action,
            "matchingIndices": matching_indices,
            "matchingNames": matching_names,
            "timestamp": time.time(),
        }
        self._is_testing_button = False
        self._test_timer.stop()
        self.testStateChanged.emit()
        self.testResultChanged.emit()


