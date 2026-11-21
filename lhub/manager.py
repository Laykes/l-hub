"""Device coordinator bridging hardware backends, profiles, health checks, and QML."""

from dataclasses import replace
import logging
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, QTimer, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication

from .backends import (
    BaseBackend,
    Device,
    HeadsetBackend,
    RatbagBackend,
    UPowerBackend,
    hidpp,
)
from .backends.ratbag import parse_button_action
from .button_tester import ButtonTesterController
from .device_layouts import get_factory_reset_defaults
from .health import SEVERITY_ERROR, log_health_checks, run_health_checks
from .keymap import resolve_key_action
from .profiles import ProfileManager
from .serializers import device_to_dict, get_device_key
from .settings import SettingsManager

logger = logging.getLogger(__name__)

_SETTINGS_KEY_MAP: Dict[str, str] = {
    "autostart": "autostart",
    "startMinimized": "start_minimized",
    "start_minimized": "start_minimized",
    "lowBatteryThreshold": "low_battery_threshold",
    "low_battery_threshold": "low_battery_threshold",
    "notifyLowBattery": "notify_low_battery",
    "notify_low_battery": "notify_low_battery",
    "notifyProfileChange": "notify_profile_change",
    "notify_profile_change": "notify_profile_change",
    "pollIntervalSec": "poll_interval_sec",
    "poll_interval_sec": "poll_interval_sec",
}


def _apply_button_dict_action(btn_dict: Dict[str, Any], norm_action: str, norm_display: str) -> None:
    btn_dict["action"] = norm_action
    btn_dict["actionDisplay"] = norm_display
    default_action = btn_dict.get("defaultAction")
    btn_dict["isCustomized"] = bool(default_action and norm_action != default_action)


class DeviceManager(QObject):
    """Main QML-exposed coordinator for peripheral discovery, settings, and diagnostics."""

    LOW_BATTERY_HYSTERESIS = 5
    HOTPLUG_DEBOUNCE_MS = 400

    devicesChanged = Signal()
    statusChanged = Signal()
    healthChecksChanged = Signal()
    settingsChanged = Signal()
    batteryWarning = Signal(str, int)  # device_name, percentage
    onboardProfileChanged = Signal(str, str)  # device_name, profile_label
    testStateChanged = Signal()
    testResultChanged = Signal()
    _hidppProfileEvent = Signal(str, int)  # device_key, profile_id
    _hidppDpiEvent = Signal(str, int)  # device_key, dpi
    _backendEvent = Signal(str)  # backend_name
    _scanFinished = Signal()

    def __init__(
        self,
        parent=None,
        auto_refresh: bool = True,
        backends: Optional[List[BaseBackend]] = None,
        enable_hotplug: bool = True,
        settings_mgr: Optional[SettingsManager] = None,
    ):
        super().__init__(parent)
        self.profile_mgr = ProfileManager()
        self.settings_mgr = settings_mgr if settings_mgr is not None else SettingsManager()
        self.backends: List[BaseBackend] = (
            list(backends)
            if backends is not None
            else [
                HeadsetBackend(),
                RatbagBackend(),
                UPowerBackend(),
            ]
        )
        self._devices: List[Device] = []
        self._cached_dict_devices: List[Dict[str, Any]] = []
        self._backend_devices: Dict[str, List[Device]] = {}
        self._backend_missing_reasons: Dict[str, str] = {}
        self._missing_backends: List[str] = []
        self._monitored_backends: List[BaseBackend] = []
        self._health_checks: List[Dict[str, Any]] = []
        self._last_health_signature: Optional[Tuple[Tuple[str, str, str, str], ...]] = None
        self._is_scanning = False
        self._pending_refresh = False
        self._warned_devices: Set[str] = set()
        self._hidpp_monitors: Dict[str, hidpp.OnboardProfileMonitor] = {}
        self._monitors_lock = threading.Lock()

        self._hidppProfileEvent.connect(self._on_hidpp_profile_event)
        self._hidppDpiEvent.connect(self._on_hidpp_dpi_event)
        self._backendEvent.connect(self._on_backend_event)
        self._scanFinished.connect(self._on_scan_finished)

        self._button_tester = ButtonTesterController(self._get_device_by_id, parent=self)
        self._button_tester.testStateChanged.connect(self.testStateChanged.emit)
        self._button_tester.testResultChanged.connect(self.testResultChanged.emit)

        self._hotplug_debounce_timer = QTimer(self)
        self._hotplug_debounce_timer.setSingleShot(True)
        self._hotplug_debounce_timer.setInterval(self.HOTPLUG_DEBOUNCE_MS)
        self._hotplug_debounce_timer.timeout.connect(self._on_hotplug_debounce_timeout)

        if enable_hotplug:
            self._start_backend_monitors()

        # Lightweight fallback polling timer for non-hotplug CLI backends (e.g. headsetcontrol),
        # driven live by SettingsManager.poll_interval_sec
        self._timer = QTimer(self)
        self._timer.setInterval(self.settings_mgr.poll_interval_sec * 1000)
        self._timer.timeout.connect(self._on_poll_timeout)
        self._timer.start()

        # Initial scan
        if auto_refresh:
            self.refresh_devices()

    def _start_backend_monitors(self) -> None:
        self._stop_backend_monitors()
        for backend in self.backends:
            if not backend.supports_hotplug:
                continue
            try:
                started = backend.start_monitoring(
                    lambda name=backend.name: self._backendEvent.emit(name)
                )
            except Exception as exc:
                logger.warning("Failed to start hotplug monitoring on %s: %s", backend.name, exc)
                started = False
            if started:
                self._monitored_backends.append(backend)
                logger.debug("Hotplug monitoring active for backend %s", backend.name)

    def _stop_backend_monitors(self) -> None:
        for backend in self._monitored_backends:
            try:
                backend.stop_monitoring()
            except Exception as exc:
                logger.debug("Failed to stop hotplug monitoring on %s: %s", backend.name, exc)
        self._monitored_backends.clear()

    def _on_backend_event(self, backend_name: str) -> None:
        logger.debug("Hotplug/property change event received from %s", backend_name)
        self._hotplug_debounce_timer.start()

    def _on_hotplug_debounce_timeout(self) -> None:
        if self._is_scanning:
            self._pending_refresh = True
            return
        self.refresh_devices()

    def _on_scan_finished(self) -> None:
        if self._pending_refresh:
            self._pending_refresh = False
            self._hotplug_debounce_timer.start()

    def _get_polling_backends(self) -> List[BaseBackend]:
        monitored_ids = {id(b) for b in self._monitored_backends}
        polling: List[BaseBackend] = []
        for b in self.backends:
            if b.supports_hotplug and id(b) in monitored_ids:
                continue
            # Avoid blocking D-Bus/IPC probes on the Qt main thread for unmonitored hotplug backends;
            # _scan_worker checks is_available() off-thread.
            if b.supports_hotplug or b.is_available():
                polling.append(b)
        return polling

    def _on_poll_timeout(self) -> None:
        polling_backends = self._get_polling_backends()
        if not polling_backends:
            logger.debug("Skipping fallback poll: all active backends use hotplug events")
            return
        self._start_scan(backends_to_scan=polling_backends)

    def _start_scan(self, backends_to_scan: Optional[List[BaseBackend]] = None) -> None:
        if self._is_scanning:
            return
        self._is_scanning = True

        # Run scan in background thread to avoid freezing GUI
        thread = threading.Thread(
            target=self._scan_worker,
            args=(backends_to_scan,),
            daemon=True,
        )
        thread.start()

    @Slot()
    def refresh_devices(self):
        self._start_scan(backends_to_scan=None)

    def _scan_worker(self, backends_to_scan: Optional[List[BaseBackend]] = None):
        try:
            targets = list(self.backends) if backends_to_scan is None else list(backends_to_scan)
            for b in targets:
                if b.is_available():
                    self._backend_missing_reasons.pop(b.name, None)
                    try:
                        devs = b.scan_devices()
                        self._backend_devices[b.name] = list(devs)
                    except Exception as exc:
                        self._backend_devices[b.name] = []
                        logger.warning(
                            "Backend %s scan failed: %s",
                            b.name,
                            exc,
                            exc_info=logger.isEnabledFor(logging.DEBUG),
                        )
                else:
                    self._backend_devices[b.name] = []
                    raw_reason = b.get_missing_reason()
                    self._backend_missing_reasons[b.name] = raw_reason
                    logger.debug("Backend %s unavailable: %s", b.name, raw_reason or "not found")

            self._missing_backends = [
                self._backend_missing_reasons[b.name]
                for b in self.backends
                if self._backend_missing_reasons.get(b.name)
            ]

            detected: List[Device] = []
            for b in self.backends:
                for dev in self._backend_devices.get(b.name, ()):
                    detected.append(replace(dev))

            merged = self._merge_devices(detected)

            # Ensure default profile for devices with configurable buttons
            for d in merged:
                if d.buttons:
                    dev_key = get_device_key(d)
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
            self._scanFinished.emit()

    def _check_battery_warnings(self, devices: List[Device]):
        threshold = self.settings_mgr.low_battery_threshold
        reset_threshold = threshold + self.LOW_BATTERY_HYSTERESIS
        notify_enabled = self.settings_mgr.notify_low_battery
        for d in devices:
            if not d.battery or not d.battery.is_supported:
                continue
            dev_key = get_device_key(d)
            if d.battery.is_charging:
                self._warned_devices.discard(dev_key)
            elif 0 <= d.battery.percentage <= threshold:
                if dev_key not in self._warned_devices and notify_enabled:
                    self._warned_devices.add(dev_key)
                    self.batteryWarning.emit(d.name, d.battery.percentage)
            elif d.battery.percentage > reset_threshold:
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
                    dev_key = get_device_key(d)
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
            if get_device_key(d) == device_key:
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
            if self.settings_mgr.notify_profile_change:
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
            if get_device_key(d) == device_key and d.dpi:
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
        self._timer.stop()
        self._hotplug_debounce_timer.stop()
        self._pending_refresh = False
        self._stop_backend_monitors()
        self._button_tester.cleanup()
        with self._monitors_lock:
            for mon in self._hidpp_monitors.values():
                mon.stop()
            self._hidpp_monitors.clear()

    def _merge_devices(self, raw_list: List[Device]) -> List[Device]:
        merged: List[Device] = []
        seen_keys: Dict[str, Device] = {}

        for dev in raw_list:
            key = get_device_key(dev)
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
        return device_to_dict(dev, self.profile_mgr)

    def _get_device_key(self, dev: Device) -> str:
        return get_device_key(dev)

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
        return list(self._missing_backends)

    @Property(bool, notify=settingsChanged)
    def autostart(self) -> bool:
        return self.settings_mgr.autostart

    @Property(bool, notify=settingsChanged)
    def startMinimized(self) -> bool:
        return self.settings_mgr.start_minimized

    @Property(int, notify=settingsChanged)
    def lowBatteryThreshold(self) -> int:
        return self.settings_mgr.low_battery_threshold

    @Property(bool, notify=settingsChanged)
    def notifyLowBattery(self) -> bool:
        return self.settings_mgr.notify_low_battery

    @Property(bool, notify=settingsChanged)
    def notifyProfileChange(self) -> bool:
        return self.settings_mgr.notify_profile_change

    @Property(int, notify=settingsChanged)
    def pollIntervalSec(self) -> int:
        return self.settings_mgr.poll_interval_sec

    @Property("QVariantMap", notify=settingsChanged)
    def appSettings(self) -> Dict[str, Any]:
        return self.settings_mgr.as_dict()

    def _apply_live_settings(self) -> None:
        new_interval_ms = self.settings_mgr.poll_interval_sec * 1000
        if self._timer.interval() != new_interval_ms:
            self._timer.setInterval(new_interval_ms)
        if self._devices:
            self._check_battery_warnings(self._devices)

    @Slot("QVariantMap", result=bool)
    def updateSettings(self, values: Dict[str, Any]) -> bool:
        if not isinstance(values, dict):
            return False
        normalized: Dict[str, Any] = {}
        for key, val in values.items():
            mapped = _SETTINGS_KEY_MAP.get(key)
            if mapped is not None:
                normalized[mapped] = val
        ok = self.settings_mgr.update(normalized)
        self._apply_live_settings()
        self.settingsChanged.emit()
        return ok

    @Slot(result=bool)
    def resetSettings(self) -> bool:
        ok = self.settings_mgr.reset_defaults()
        self._apply_live_settings()
        self.settingsChanged.emit()
        return ok

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
                            dev_key = get_device_key(dev)
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
                        _apply_button_dict_action(btn, norm_action, norm_display)
                        break
                self.devicesChanged.emit()
                break

        def _worker():
            for b in self.backends:
                if isinstance(b, RatbagBackend):
                    if b.remap_button(device_id, button_idx, action):
                        if dev:
                            dev_key = get_device_key(dev)
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
        return resolve_key_action(key, modifiers)

    @Slot(str, str, result=bool)
    def applyProfile(self, device_id: str, profile_name: str) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev:
            return False
        dev_key = get_device_key(dev)
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
                        _apply_button_dict_action(btn, norm_act, norm_disp)
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
        dev_key = get_device_key(dev)
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
        dev_key = get_device_key(dev)
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
        dev_key = get_device_key(dev)

        defaults = get_factory_reset_defaults(
            dev.name,
            dev.usb_vid or "",
            dev.usb_pid or "",
            total_buttons=len(dev.buttons) if dev.buttons else None,
        )

        # Update local cache immediately
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                d["activeProfile"] = "Default"
                for btn in d.get("buttons", []):
                    if btn["index"] in defaults:
                        norm_act, norm_disp = parse_button_action(defaults[btn["index"]])
                        _apply_button_dict_action(btn, norm_act, norm_disp)
                self.devicesChanged.emit()
                break

        def _worker():
            for b in self.backends:
                if isinstance(b, RatbagBackend):
                    b.reset_defaults(device_id)
                    updated = b.scan_devices()
                    for ud in updated:
                        if ud.id == device_id or get_device_key(ud) == dev_key:
                            b_map = {btn.index: btn.action_value for btn in ud.buttons}
                            dpi_val = ud.dpi.current if (ud.dpi and not ud.dpi.is_disabled) else 800
                            self.profile_mgr.reset_to_default(dev_key, b_map, dpi_val)
                            break
            self.refresh_devices()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    @Property(bool, notify=testStateChanged)
    def isTestingButton(self) -> bool:
        return self._button_tester.is_testing

    @Property(str, notify=testStateChanged)
    def testingDeviceId(self) -> str:
        return self._button_tester.testing_device_id

    @Property("QVariantMap", notify=testResultChanged)
    def testedButtonResult(self) -> Dict[str, Any]:
        return self._button_tester.tested_button_result

    @Slot(str)
    def startButtonTest(self, device_id: str):
        self._button_tester.start(device_id)

    @Slot()
    def stopButtonTest(self):
        self._button_tester.stop()

    @Slot()
    def clearTestResult(self):
        self._button_tester.clear_result()

    def _on_hid_input_event(self, action: str, detected_name: str):
        self._button_tester.handle_hid_input(action, detected_name)

    def eventFilter(self, watched, event):
        if self._button_tester.eventFilter(watched, event):
            return True
        return super().eventFilter(watched, event)
