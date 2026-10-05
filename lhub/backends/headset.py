import json
import shutil
import subprocess
import time
from typing import List, Dict, Optional, Any
from .base import BaseBackend, Device, DeviceType, Capability, BatteryInfo


# Logitech charging curve for Li-Ion battery under ~500mA USB charge rate
LOGITECH_CHARGING_CURVE = [
    (4190, 100),
    (4160, 90),
    (4130, 75),
    (4100, 60),
    (4080, 50),
    (4050, 35),
    (4020, 20),
    (3950, 10),
    (3850, 5),
    (3700, 0),
]


def _estimate_logitech_charging_percentage(voltage_mv: int) -> int:
    if voltage_mv >= LOGITECH_CHARGING_CURVE[0][0]:
        return 100
    if voltage_mv <= LOGITECH_CHARGING_CURVE[-1][0]:
        return 0
    for i in range(len(LOGITECH_CHARGING_CURVE) - 1):
        v_high, p_high = LOGITECH_CHARGING_CURVE[i]
        v_low, p_low = LOGITECH_CHARGING_CURVE[i + 1]
        if v_low <= voltage_mv <= v_high:
            ratio = (voltage_mv - v_low) / (v_high - v_low)
            return int(p_low + ratio * (p_high - p_low))
    return 50


class HeadsetBackend(BaseBackend):
    """Backend for gaming headsets using HeadsetControl CLI."""

    def __init__(self):
        super().__init__("headsetcontrol")
        self._cmd = shutil.which("headsetcontrol")
        self._saved_sidetone: Dict[str, int] = {}
        self._saved_inactive: Dict[str, int] = {}
        self._battery_tracker: Dict[str, Dict[str, Any]] = {}

    def is_available(self) -> bool:
        return self._cmd is not None

    def get_missing_reason(self) -> str:
        if not self.is_available():
            return "HeadsetControl is not installed (sudo pacman -S headsetcontrol)"
        return ""

    def scan_devices(self) -> List[Device]:
        if not self.is_available():
            return []

        devices: List[Device] = []
        try:
            res = subprocess.run(
                [self._cmd, "-o", "json"],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if res.returncode != 0 or not res.stdout:
                return []

            data = json.loads(res.stdout)
            raw_devices = data.get("devices", [])
            if not raw_devices and isinstance(data, list):
                raw_devices = data

            for item in raw_devices:
                if not isinstance(item, dict):
                    continue

                vendor = item.get("vendor") or "Logitech"
                product = item.get("product") or item.get("device") or "Wireless Gaming Headset"
                full_name = f"{vendor} {product}".strip() if vendor.lower() not in product.lower() else product

                vid_raw = item.get("id_vendor", "")
                pid_raw = item.get("id_product", "")
                vid = vid_raw.replace("0x", "").lower().zfill(4) if vid_raw else ""
                pid = pid_raw.replace("0x", "").lower().zfill(4) if pid_raw else ""
                dev_id = f"headset_{vid}_{pid}" if vid and pid else f"headset_{product}"

                caps_list = item.get("capabilities_str", [])
                caps: List[Capability] = []
                if "battery" in caps_list or "battery_status" in caps_list:
                    caps.append(Capability.BATTERY)
                if "sidetone" in caps_list:
                    caps.append(Capability.SIDETONE)
                if "inactive time" in caps_list or "inactive_time" in caps_list:
                    caps.append(Capability.INACTIVE_TIME)
                if "equalizer" in caps_list:
                    caps.append(Capability.EQUALIZER)
                if "lights" in caps_list or "leds" in caps_list:
                    caps.append(Capability.LIGHTING)

                # Battery
                bat_info = self._process_battery_info(dev_id, vendor, item.get("battery", {}))

                # Sidetone
                sidetone_val = self._saved_sidetone.get(dev_id, 0)
                inactive_val = self._saved_inactive.get(dev_id, 15)

                dev = Device(
                    id=dev_id,
                    name=full_name,
                    vendor=vendor,
                    device_type=DeviceType.HEADSET,
                    usb_vid=vid,
                    usb_pid=pid,
                    capabilities=caps,
                    battery=bat_info,
                    sidetone=sidetone_val if Capability.SIDETONE in caps else None,
                    inactive_time=inactive_val if Capability.INACTIVE_TIME in caps else None,
                    extra_props=item,
                    backend_name=self.name,
                )
                devices.append(dev)

        except Exception:
            pass

        return devices

    def set_sidetone(self, device_id: str, level: int) -> bool:
        if not self.is_available():
            return False
        # Clamp to 0-128
        level = max(0, min(128, int(level)))
        try:
            # We can target via device ID if available
            cmd = [self._cmd, "-s", str(level)]
            if "_" in device_id:
                parts = device_id.split("_")
                if len(parts) >= 3 and len(parts[1]) == 4 and len(parts[2]) == 4:
                    cmd.extend(["-d", f"0x{parts[1]}:0x{parts[2]}"])

            res = subprocess.run(cmd, capture_output=True, timeout=3)
            if res.returncode == 0:
                self._saved_sidetone[device_id] = level
                return True
        except Exception:
            pass
        return False

    def set_inactive_time(self, device_id: str, minutes: int) -> bool:
        if not self.is_available():
            return False
        minutes = max(0, min(90, int(minutes)))
        try:
            cmd = [self._cmd, "-i", str(minutes)]
            if "_" in device_id:
                parts = device_id.split("_")
                if len(parts) >= 3 and len(parts[1]) == 4 and len(parts[2]) == 4:
                    cmd.extend(["-d", f"0x{parts[1]}:0x{parts[2]}"])

            res = subprocess.run(cmd, capture_output=True, timeout=3)
            if res.returncode == 0:
                self._saved_inactive[device_id] = minutes
                return True
        except Exception:
            pass
        return False

    def _process_battery_info(self, dev_id: str, vendor: str, bat_data: Any) -> BatteryInfo:
        bat_info = BatteryInfo()
        if not bat_data:
            return bat_info

        if isinstance(bat_data, (int, float)):
            bat_info.percentage = int(bat_data)
            return bat_info

        if not isinstance(bat_data, dict):
            return bat_info

        raw_level = bat_data.get("level", -1)
        voltage_mv = bat_data.get("voltage_mv")
        status = bat_data.get("status", "")
        bat_info.voltage_mv = voltage_mv
        bat_info.status_text = status
        is_charging = ("charging" in status.lower() or "full" in status.lower()) and "discharging" not in status.lower()
        bat_info.is_charging = is_charging
        bat_info.is_supported = status != "BATTERY_UNAVAILABLE"

        if not bat_info.is_supported or (raw_level < 0 and not is_charging):
            bat_info.percentage = -1
            return bat_info

        now = time.time()
        tracker = self._battery_tracker.setdefault(dev_id, {
            "last_discharging_level": None,
            "charging_start_time": None,
            "charging_start_level": None,
            "last_percentage": raw_level,
        })

        is_logitech = "logitech" in vendor.lower() or "046d" in dev_id.lower()

        if not is_charging:
            # Device running on battery (discharging)
            tracker["charging_start_time"] = None
            tracker["charging_start_level"] = None
            if raw_level >= 0:
                tracker["last_discharging_level"] = raw_level
                tracker["last_percentage"] = raw_level
                bat_info.percentage = raw_level
            else:
                bat_info.percentage = tracker.get("last_percentage", -1)

            bat_info.time_to_empty_min = bat_data.get("time_to_empty_min")
            if not bat_info.time_to_empty_min and bat_info.percentage > 0:
                bat_info.time_to_empty_min = int(bat_info.percentage * 9)
        else:
            # Device is connected to charger (charging)
            # Logitech headsets report inaccurate voltage/percentage under charge load.
            # Avoid displaying misleading numbers; report -1 so UI displays "Charging" without false numbers.
            if "full" in status.lower() or status == "BATTERY_FULL":
                bat_info.percentage = 100
                bat_info.time_to_full_min = 0
            else:
                bat_info.percentage = -1
                bat_info.time_to_full_min = None

        return bat_info
