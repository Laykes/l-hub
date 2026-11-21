"""Serialization helpers converting Device dataclasses into QML dictionaries."""

from typing import Any, Dict, List, Optional

from .backends import BatteryInfo, ButtonMapping, Capability, Device, EqBand
from .backends.microphone import BUILTIN_EQ_PRESETS
from .profiles import ProfileManager


def get_device_key(dev: Device) -> str:
    """Return the stable profile-storage key for a device (VID:PID or normalized name)."""
    if dev.usb_vid and dev.usb_pid:
        return f"{dev.usb_vid}:{dev.usb_pid}"
    return dev.name.lower().replace("-", " ").strip()


def format_battery_time_remaining(battery: Optional[BatteryInfo]) -> str:
    """Format battery charge or discharge ETA into a human-readable string."""
    if not battery:
        return ""
    if battery.is_charging:
        if battery.time_to_full_min is not None:
            if battery.time_to_full_min == 0:
                return "Fully charged"
            hrs = battery.time_to_full_min // 60
            mins = battery.time_to_full_min % 60
            return f"Full in ~{hrs} hr {mins} min" if hrs > 0 else f"Full in ~{mins} min"
        return ""
    if battery.time_to_empty_min:
        hrs = battery.time_to_empty_min // 60
        mins = battery.time_to_empty_min % 60
        return f"~{hrs} hr {mins} min" if hrs > 0 else f"~{mins} min"
    return ""


def button_to_dict(btn: ButtonMapping) -> Dict[str, Any]:
    """Serialize a ButtonMapping dataclass into a QML-friendly dictionary."""
    default_action = getattr(btn, "default_action", "")
    return {
        "index": btn.index,
        "name": btn.name,
        "label": getattr(btn, "label", "") or btn.name,
        "location": getattr(btn, "location", ""),
        "group": getattr(btn, "group", "main"),
        "defaultAction": default_action,
        "action": btn.action_value,
        "actionDisplay": btn.action_display or btn.action_value,
        "isCustomized": bool(default_action and btn.action_value != default_action),
    }


def eq_band_to_dict(band: EqBand) -> Dict[str, Any]:
    """Serialize an EqBand dataclass into a QML-friendly dictionary."""
    return {
        "id": band.id,
        "label": band.label,
        "freq": band.freq,
        "freqLabel": band.freq_label,
        "filterType": band.filter_type,
        "gain": band.gain,
    }


def _preset_summaries() -> List[Dict[str, str]]:
    return [
        {"name": p["name"], "description": p["description"]}
        for p in BUILTIN_EQ_PRESETS
    ]


def device_to_dict(dev: Device, profile_mgr: Optional[ProfileManager] = None) -> Dict[str, Any]:
    """Serialize a Device dataclass and its profile metadata into a QML dictionary."""
    dev_key = get_device_key(dev)
    profiles = profile_mgr.get_profiles(dev_key) if profile_mgr is not None else ["Default"]
    active_profile = profile_mgr.get_active_profile(dev_key) if profile_mgr is not None else "Default"
    time_str = format_battery_time_remaining(dev.battery)
    mic = dev.microphone

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
        "hasInactiveTime": Capability.INACTIVE_TIME in dev.capabilities,
        "inactiveTime": dev.inactive_time if dev.inactive_time is not None else 15,
        "hasButtons": Capability.BUTTON_REMAP in dev.capabilities,
        "buttons": [button_to_dict(b) for b in dev.buttons],
        "hasMicrophone": mic is not None,
        "hasEqualizer": Capability.EQUALIZER in dev.capabilities and mic is not None,
        "hasMicMonitor": Capability.MIC_MONITOR in dev.capabilities and mic is not None,
        "micVolume": mic.volume if mic else 100,
        "micMuted": mic.muted if mic else False,
        "micEqEnabled": mic.eq_enabled if mic else False,
        "micHighpassEnabled": mic.highpass_enabled if mic else False,
        "micHighpassFreq": mic.highpass_freq if mic else 80,
        "micEqBands": [eq_band_to_dict(b) for b in mic.bands] if mic else [],
        "micMonitoring": mic.monitoring if mic else False,
        "micSourceName": mic.source_name if mic else "",
        "micVirtualSourceName": mic.virtual_source_name if mic else "",
        "micVirtualSourceDescription": mic.virtual_source_description if mic else "",
        "micVirtualSourceActive": mic.virtual_source_active if mic else False,
        "micIsEqDefaultSource": mic.is_eq_default_source if mic else False,
        "micIsRawDefaultSource": mic.is_raw_default_source if mic else False,
        "micPresets": _preset_summaries() if mic else [],
        "statusNote": dev.status_note,
        "backend": dev.backend_name,
    }
