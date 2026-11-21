"""Device coordinator bridging hardware backends, profiles, health checks, and QML."""

from dataclasses import replace
import logging
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, QTimer, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication

from .backends import (
    BaseBackend,
    Capability,
    Device,
    DeviceType,
    HeadsetBackend,
    PipeWireMicBackend,
    RatbagBackend,
    UPowerBackend,
    hidpp,
)
from .backends.microphone import (
    apply_config_to_mic_info,
    clamp_eq_gain,
    clamp_hpf_freq,
    clamp_mic_volume,
    create_default_eq_bands,
    get_builtin_eq_preset,
    mic_info_to_config,
)
from .backends.ratbag import parse_button_action
from .button_tester import ButtonTesterController
from .device_layouts import get_factory_reset_defaults
from .health import SEVERITY_ERROR, log_health_checks, run_health_checks
from .keymap import resolve_key_action
from .profiles import ProfileManager
from .serializers import device_to_dict, get_device_key
from .settings import (
    HEADSET_INACTIVE_TIME_MAX,
    HEADSET_INACTIVE_TIME_MIN,
    HEADSET_SIDETONE_MAX,
    HEADSET_SIDETONE_MIN,
    SettingsManager,
)

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
    HEADSET_RESTORE_MAX_RETRIES = 2

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
                PipeWireMicBackend(),
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
        self._headset_lock = threading.Lock()
        self._headset_io_lock = threading.Lock()
        self._applied_headset_keys: Set[str] = set()
        self._headset_restore_failures: Dict[str, int] = {}
        self._headset_cmd_seq: Dict[Tuple[str, str], int] = {}
        self._mic_lock = threading.Lock()
        self._mic_io_lock = threading.Lock()
        self._applied_mic_keys: Set[str] = set()
        self._mic_eq_seq: Dict[str, int] = {}
        self._mic_vol_seq: Dict[str, int] = {}

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

            # Overlay persisted headset settings and restore on startup / reconnect
            self._sync_headset_settings(merged)

            # Ensure default profiles & restore PipeWire EQ for USB microphones
            self._sync_microphone_settings(merged)

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

    @staticmethod
    def _is_configurable_headset(dev: Device) -> bool:
        return (
            dev.device_type == DeviceType.HEADSET
            and (
                Capability.SIDETONE in dev.capabilities
                or Capability.INACTIVE_TIME in dev.capabilities
            )
        )

    @classmethod
    def _is_headset_online(cls, dev: Device) -> bool:
        if not cls._is_configurable_headset(dev):
            return False
        if Capability.BATTERY in dev.capabilities:
            return bool(dev.battery is not None and dev.battery.is_supported)
        return True

    @staticmethod
    def _fallback_headset_key(device_id: str) -> str:
        if device_id.startswith("headset_"):
            parts = device_id.split("_")
            if len(parts) >= 3 and len(parts[1]) == 4 and len(parts[2]) == 4:
                return f"{parts[1].lower()}:{parts[2].lower()}"
        return device_id

    def _get_headset_backends(self) -> List[HeadsetBackend]:
        return [b for b in self.backends if isinstance(b, HeadsetBackend)]

    def _sync_headset_settings(self, devices: List[Device]) -> None:
        headsets = [d for d in devices if self._is_configurable_headset(d)]
        online_keys = {get_device_key(d) for d in headsets if self._is_headset_online(d)}

        with self._headset_lock:
            self._applied_headset_keys.intersection_update(online_keys)
            for stale_key in list(self._headset_restore_failures):
                if stale_key not in online_keys:
                    del self._headset_restore_failures[stale_key]

        headset_backends = self._get_headset_backends()

        for dev in headsets:
            dev_key = get_device_key(dev)
            saved = self.settings_mgr.get_headset_settings(dev_key)

            if Capability.SIDETONE in dev.capabilities and "sidetone" in saved:
                dev.sidetone = saved["sidetone"]
            if Capability.INACTIVE_TIME in dev.capabilities and "inactive_time" in saved:
                dev.inactive_time = saved["inactive_time"]

            if dev_key not in online_keys:
                continue

            with self._headset_lock:
                if dev_key in self._applied_headset_keys:
                    continue
                if self._headset_restore_failures.get(dev_key, 0) >= self.HEADSET_RESTORE_MAX_RETRIES:
                    continue

            has_saved_applicable = (
                (Capability.SIDETONE in dev.capabilities and "sidetone" in saved)
                or (Capability.INACTIVE_TIME in dev.capabilities and "inactive_time" in saved)
            )
            if not has_saved_applicable:
                with self._headset_lock:
                    self._applied_headset_keys.add(dev_key)
                continue

            if not headset_backends:
                continue

            applied_summary: Dict[str, int] = {}
            all_ok = True
            with self._headset_io_lock:
                latest_saved = self.settings_mgr.get_headset_settings(dev_key)
                if Capability.SIDETONE in dev.capabilities and "sidetone" in latest_saved:
                    target_val = latest_saved["sidetone"]
                    dev.sidetone = target_val
                    ok = any(b.set_sidetone(dev.id, target_val) for b in headset_backends)
                    if ok:
                        applied_summary["sidetone"] = target_val
                    else:
                        all_ok = False
                if Capability.INACTIVE_TIME in dev.capabilities and "inactive_time" in latest_saved:
                    target_val = latest_saved["inactive_time"]
                    dev.inactive_time = target_val
                    ok = any(b.set_inactive_time(dev.id, target_val) for b in headset_backends)
                    if ok:
                        applied_summary["inactive_time"] = target_val
                    else:
                        all_ok = False

            with self._headset_lock:
                if all_ok:
                    self._applied_headset_keys.add(dev_key)
                    self._headset_restore_failures.pop(dev_key, None)
                    if applied_summary:
                        logger.info(
                            "Restored headset settings for %s (%s): %s",
                            dev.name,
                            dev_key,
                            applied_summary,
                        )
                else:
                    self._headset_restore_failures[dev_key] = (
                        self._headset_restore_failures.get(dev_key, 0) + 1
                    )
                    logger.debug(
                        "Failed to restore headset settings for %s (%s); attempt %d/%d",
                        dev.name,
                        dev_key,
                        self._headset_restore_failures[dev_key],
                        self.HEADSET_RESTORE_MAX_RETRIES,
                    )

    def _get_mic_backends(self) -> List[PipeWireMicBackend]:
        return [b for b in self.backends if isinstance(b, PipeWireMicBackend)]

    def _sync_microphone_settings(self, devices: List[Device]) -> None:
        mics = [d for d in devices if d.device_type == DeviceType.MICROPHONE and d.microphone is not None]
        online_keys = {get_device_key(d) for d in mics}

        with self._mic_lock:
            self._applied_mic_keys.intersection_update(online_keys)

        mic_backends = self._get_mic_backends()

        for dev in mics:
            assert dev.microphone is not None
            dev_key = get_device_key(dev)
            self.profile_mgr.ensure_default_mic_profile(dev_key, mic_info_to_config(dev.microphone))

            active_name = self.profile_mgr.get_active_profile(dev_key)
            prof_data = self.profile_mgr.get_profile_data(dev_key, active_name)
            mic_cfg = prof_data.get("microphone") if isinstance(prof_data, dict) else None
            if isinstance(mic_cfg, dict):
                # Overlay saved EQ/HPF settings while preserving live PipeWire volume/mute/flags
                eq_only = {k: v for k, v in mic_cfg.items() if k != "volume"}
                apply_config_to_mic_info(dev.microphone, eq_only)

            with self._mic_lock:
                already_applied = dev_key in self._applied_mic_keys

            if already_applied or not mic_backends:
                continue

            applied = False
            with self._mic_io_lock:
                for backend in mic_backends:
                    if backend.apply_eq(dev.id, dev.microphone):
                        applied = True
                        break

            if applied:
                dev.microphone.virtual_source_active = True
                with self._mic_lock:
                    self._applied_mic_keys.add(dev_key)
                logger.info("Activated PipeWire EQ filter-chain for %s (%s)", dev.name, dev_key)

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
                            device_name=d.name,
                            device_key=dev_key,
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
                dev_name = target_dev.name

                def _read_new_dpi():
                    dpi = hidpp.get_dpi(vid, pid, device_name=dev_name, device_key=device_key)
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
        for backend in self.backends:
            try:
                backend.cleanup()
            except Exception as exc:
                logger.debug("Backend %s cleanup failed: %s", backend.name, exc)
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

    def _apply_headset_setting(self, device_id: str, setting_key: str, value: int) -> None:
        if setting_key == "sidetone":
            clamped = max(HEADSET_SIDETONE_MIN, min(HEADSET_SIDETONE_MAX, int(value)))
            dict_key = "sidetone"
        elif setting_key == "inactive_time":
            clamped = max(HEADSET_INACTIVE_TIME_MIN, min(HEADSET_INACTIVE_TIME_MAX, int(value)))
            dict_key = "inactiveTime"
        else:
            return

        dev = self._get_device_by_id(device_id)
        if dev is not None:
            if setting_key == "sidetone":
                dev.sidetone = clamped
            else:
                dev.inactive_time = clamped
            dev_key = get_device_key(dev)
            is_offline = not self._is_headset_online(dev)
        else:
            dev_key = self._fallback_headset_key(device_id)
            is_offline = False

        # Update local cache immediately for responsive UI
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                d[dict_key] = clamped
                self.devicesChanged.emit()
                break

        cmd_id = (dev_key, setting_key)
        with self._headset_lock:
            seq = self._headset_cmd_seq.get(cmd_id, 0) + 1
            self._headset_cmd_seq[cmd_id] = seq

        def _worker():
            with self._headset_io_lock:
                with self._headset_lock:
                    if self._headset_cmd_seq.get(cmd_id) != seq:
                        return
                applied = False
                for b in self._get_headset_backends():
                    if setting_key == "sidetone":
                        if b.set_sidetone(device_id, clamped):
                            applied = True
                    else:
                        if b.set_inactive_time(device_id, clamped):
                            applied = True

                with self._headset_lock:
                    if self._headset_cmd_seq.get(cmd_id) != seq:
                        return
                    if applied:
                        self._headset_restore_failures.pop(dev_key, None)

                if applied or is_offline:
                    self.settings_mgr.set_headset_setting(dev_key, setting_key, clamped)

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(str, int)
    def setSidetone(self, device_id: str, level: int):
        self._apply_headset_setting(device_id, "sidetone", level)

    @Slot(str, int)
    def setInactiveTime(self, device_id: str, minutes: int):
        self._apply_headset_setting(device_id, "inactive_time", minutes)

    def _update_cached_mic_entry(self, dev: Device) -> None:
        updated_dict = self._device_to_dict(dev)
        for idx, entry in enumerate(self._cached_dict_devices):
            if entry.get("id") == dev.id:
                self._cached_dict_devices[idx] = updated_dict
                self.devicesChanged.emit()
                break

    def _push_mic_eq_async(self, dev: Device, persist_active: bool = True) -> None:
        if dev.microphone is None:
            return
        dev_key = get_device_key(dev)
        mic_snapshot = replace(dev.microphone, bands=[replace(b) for b in dev.microphone.bands])
        if persist_active:
            self.profile_mgr.update_active_mic_config(dev_key, mic_info_to_config(mic_snapshot))

        with self._mic_lock:
            seq = self._mic_eq_seq.get(dev.id, 0) + 1
            self._mic_eq_seq[dev.id] = seq

        def _worker():
            with self._mic_io_lock:
                with self._mic_lock:
                    if self._mic_eq_seq.get(dev.id) != seq:
                        return
                applied = False
                for backend in self._get_mic_backends():
                    if backend.apply_eq(dev.id, mic_snapshot):
                        applied = True
                        break
                if applied and dev.microphone is not None and not dev.microphone.virtual_source_active:
                    dev.microphone.virtual_source_active = True
                    self._update_cached_mic_entry(dev)

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(str, int, result=bool)
    def setMicVolume(self, device_id: str, volume: int) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or dev.microphone is None:
            return False
        clamped = clamp_mic_volume(volume)
        dev.microphone.volume = clamped
        self._update_cached_mic_entry(dev)
        dev_key = get_device_key(dev)
        self.profile_mgr.update_active_mic_config(dev_key, mic_info_to_config(dev.microphone))

        with self._mic_lock:
            seq = self._mic_vol_seq.get(device_id, 0) + 1
            self._mic_vol_seq[device_id] = seq

        def _worker():
            with self._mic_io_lock:
                with self._mic_lock:
                    if self._mic_vol_seq.get(device_id) != seq:
                        return
                for backend in self._get_mic_backends():
                    if backend.set_volume(device_id, clamped):
                        break

        threading.Thread(target=_worker, daemon=True).start()
        return True

    @Slot(str, bool, result=bool)
    def setMicMuted(self, device_id: str, muted: bool) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or dev.microphone is None:
            return False
        target_muted = bool(muted)
        dev.microphone.muted = target_muted
        self._update_cached_mic_entry(dev)

        def _worker():
            with self._mic_io_lock:
                for backend in self._get_mic_backends():
                    if backend.set_mute(device_id, target_muted):
                        break

        threading.Thread(target=_worker, daemon=True).start()
        return True

    @Slot(str, bool, result=bool)
    def setMicEqEnabled(self, device_id: str, enabled: bool) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or dev.microphone is None:
            return False
        dev.microphone.eq_enabled = bool(enabled)
        self._update_cached_mic_entry(dev)
        self._push_mic_eq_async(dev)
        return True

    @Slot(str, bool, int, result=bool)
    def setMicHighpass(self, device_id: str, enabled: bool, freq: int) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or dev.microphone is None:
            return False
        dev.microphone.highpass_enabled = bool(enabled)
        dev.microphone.highpass_freq = clamp_hpf_freq(freq)
        self._update_cached_mic_entry(dev)
        self._push_mic_eq_async(dev)
        return True

    @Slot(str, str, float, result=bool)
    def setMicEqBand(self, device_id: str, band_id: str, gain: float) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or dev.microphone is None:
            return False
        clamped = clamp_eq_gain(gain)
        found = False
        for band in dev.microphone.bands:
            if band.id == band_id:
                band.gain = clamped
                found = True
                break
        if not found:
            return False
        self._update_cached_mic_entry(dev)
        self._push_mic_eq_async(dev)
        return True

    @Slot(str, str, result=bool)
    def applyMicPreset(self, device_id: str, preset_name: str) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or dev.microphone is None:
            return False
        preset = get_builtin_eq_preset(preset_name)
        if preset is None:
            return False
        dev.microphone.eq_enabled = True
        dev.microphone.highpass_enabled = bool(preset["highpass_enabled"])
        dev.microphone.highpass_freq = clamp_hpf_freq(preset["highpass_freq"])
        band_gains = preset.get("bands", {})
        if not dev.microphone.bands:
            dev.microphone.bands = create_default_eq_bands(band_gains)
        else:
            for band in dev.microphone.bands:
                if band.id in band_gains:
                    band.gain = clamp_eq_gain(band_gains[band.id])
        self._update_cached_mic_entry(dev)
        self._push_mic_eq_async(dev)
        return True

    @Slot(str, bool, result=bool)
    def setMicMonitoring(self, device_id: str, enabled: bool) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or dev.microphone is None:
            return False
        target = bool(enabled)
        # Only one microphone monitor can be active at a time
        for other in self._devices:
            if other.microphone is not None and other.id != device_id and other.microphone.monitoring:
                other.microphone.monitoring = False
                self._update_cached_mic_entry(other)
        dev.microphone.monitoring = target
        self._update_cached_mic_entry(dev)

        def _worker():
            with self._mic_io_lock:
                ok = False
                for backend in self._get_mic_backends():
                    if backend.set_monitoring(device_id, target):
                        ok = True
                        break
                if not ok and target:
                    dev.microphone.monitoring = False
                    self._update_cached_mic_entry(dev)
                elif ok and target and not dev.microphone.virtual_source_active:
                    dev.microphone.virtual_source_active = True
                    self._update_cached_mic_entry(dev)

        threading.Thread(target=_worker, daemon=True).start()
        return True

    @Slot(str, bool, result=bool)
    def setMicAsDefault(self, device_id: str, use_eq_source: bool = True) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or dev.microphone is None:
            return False

        def _worker():
            with self._mic_io_lock:
                ok = False
                for backend in self._get_mic_backends():
                    if backend.set_default_source(device_id, use_eq_source=bool(use_eq_source)):
                        ok = True
                        break
                if ok and dev.microphone is not None:
                    dev.microphone.virtual_source_active = bool(use_eq_source) or dev.microphone.virtual_source_active
                    dev.microphone.is_eq_default_source = bool(use_eq_source)
                    dev.microphone.is_raw_default_source = not bool(use_eq_source)
                    self._update_cached_mic_entry(dev)

        threading.Thread(target=_worker, daemon=True).start()
        return True

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

        if dev.microphone is not None:
            mic_cfg = prof_data.get("microphone")
            if isinstance(mic_cfg, dict):
                apply_config_to_mic_info(dev.microphone, mic_cfg)
            self._update_cached_mic_entry(dev)
            mic_snapshot = replace(dev.microphone, bands=[replace(b) for b in dev.microphone.bands])
            apply_volume = isinstance(mic_cfg, dict) and "volume" in mic_cfg

            def _mic_worker():
                with self._mic_io_lock:
                    for b in self._get_mic_backends():
                        b.apply_eq(device_id, mic_snapshot)
                        if apply_volume:
                            b.set_volume(device_id, mic_snapshot.volume)
                        break

            threading.Thread(target=_mic_worker, daemon=True).start()
            return True

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
        clean_name = profile_name.strip() if profile_name else ""
        if not dev or not clean_name:
            return False
        dev_key = get_device_key(dev)

        if dev.microphone is not None:
            self.profile_mgr.save_mic_profile(dev_key, clean_name, mic_info_to_config(dev.microphone))
            self._update_cached_mic_entry(dev)
            return True

        buttons = {b.index: b.action_value for b in dev.buttons}
        dpi = dev.dpi.current if (dev.dpi and not dev.dpi.is_disabled) else None
        self.profile_mgr.save_profile(dev_key, clean_name, buttons, dpi)

        # Update local cache immediately
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                if clean_name not in d.get("profiles", []):
                    d["profiles"].append(clean_name)
                d["activeProfile"] = clean_name
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

        if dev.microphone is not None:
            dev.microphone.volume = 100
            dev.microphone.eq_enabled = True
            dev.microphone.highpass_enabled = False
            dev.microphone.highpass_freq = 80
            dev.microphone.bands = create_default_eq_bands()
            self.profile_mgr.reset_mic_to_default(dev_key, mic_info_to_config(dev.microphone))
            self._update_cached_mic_entry(dev)
            mic_snapshot = replace(dev.microphone, bands=[replace(b) for b in dev.microphone.bands])

            def _mic_reset_worker():
                with self._mic_io_lock:
                    for b in self._get_mic_backends():
                        b.apply_eq(device_id, mic_snapshot)
                        b.set_volume(device_id, 100)
                        break

            threading.Thread(target=_mic_reset_worker, daemon=True).start()
            return True

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
