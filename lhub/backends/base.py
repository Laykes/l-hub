from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any


class DeviceType(Enum):
    MOUSE = "mouse"
    KEYBOARD = "keyboard"
    HEADSET = "headset"
    OTHER = "other"


class Capability(Enum):
    BATTERY = "battery"
    DPI = "dpi"
    BUTTON_REMAP = "button_remap"
    PROFILES = "profiles"
    SIDETONE = "sidetone"
    EQUALIZER = "equalizer"
    LIGHTING = "lighting"
    POLLING_RATE = "polling_rate"
    INACTIVE_TIME = "inactive_time"


@dataclass
class BatteryInfo:
    percentage: int = -1  # 0-100 or -1 if unknown
    is_charging: bool = False
    is_supported: bool = True
    time_to_empty_min: Optional[int] = None
    time_to_full_min: Optional[int] = None
    voltage_mv: Optional[int] = None
    status_text: str = ""


@dataclass
class DpiInfo:
    current: int = 800
    steps: List[int] = field(default_factory=lambda: [400, 800, 1600, 3200])
    min_dpi: int = 100
    max_dpi: int = 25600
    is_disabled: bool = False


@dataclass
class ButtonMapping:
    index: int
    name: str
    action_type: str = "button"
    action_value: str = ""
    action_display: str = ""
    label: str = ""
    location: str = ""
    group: str = "main"
    default_action: str = ""



@dataclass
class Device:
    id: str
    name: str
    vendor: str
    device_type: DeviceType
    usb_vid: Optional[str] = None
    usb_pid: Optional[str] = None
    capabilities: List[Capability] = field(default_factory=list)
    battery: Optional[BatteryInfo] = None
    dpi: Optional[DpiInfo] = None
    buttons: List[ButtonMapping] = field(default_factory=list)
    sidetone: Optional[int] = None  # 0-128
    inactive_time: Optional[int] = None  # minutes
    status_note: str = ""
    extra_props: Dict[str, Any] = field(default_factory=dict)
    backend_name: str = ""


class BaseBackend:
    def __init__(self, name: str):
        self.name = name

    def is_available(self) -> bool:
        raise NotImplementedError

    def get_missing_reason(self) -> str:
        return ""

    def scan_devices(self) -> List[Device]:
        return []

    def set_dpi(self, device_id: str, dpi: int) -> bool:
        return False

    def set_sidetone(self, device_id: str, level: int) -> bool:
        return False

    def set_inactive_time(self, device_id: str, minutes: int) -> bool:
        return False

    def remap_button(self, device_id: str, button_idx: int, action: str) -> bool:
        return False

    def batch_remap_buttons(self, device_id: str, buttons: Dict[int, str]) -> bool:
        return False

    def reset_defaults(self, device_id: str) -> bool:
        return False

