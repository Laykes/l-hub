import json
import shutil
import subprocess
from typing import List, Dict, Optional
from .base import BaseBackend, Device, DeviceType, Capability, BatteryInfo


class HeadsetBackend(BaseBackend):
    """Backend for gaming headsets using HeadsetControl CLI."""

    def __init__(self):
        super().__init__("headsetcontrol")
        self._cmd = shutil.which("headsetcontrol")
        self._saved_sidetone: Dict[str, int] = {}
        self._saved_inactive: Dict[str, int] = {}

    def is_available(self) -> bool:
        return self._cmd is not None

    def get_missing_reason(self) -> str:
        if not self.is_available():
            return "HeadsetControl ist nicht installiert (sudo pacman -S headsetcontrol)"
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
                bat_info = BatteryInfo()
                bat_data = item.get("battery", {})
                if isinstance(bat_data, dict):
                    bat_info.percentage = bat_data.get("level", -1)
                    bat_info.voltage_mv = bat_data.get("voltage_mv")
                    bat_info.time_to_empty_min = bat_data.get("time_to_empty_min")
                    status = bat_data.get("status", "")
                    bat_info.status_text = status
                    bat_info.is_charging = "charging" in status.lower() and "discharging" not in status.lower()
                    bat_info.is_supported = status != "BATTERY_UNAVAILABLE"
                elif isinstance(bat_data, (int, float)):
                    bat_info.percentage = int(bat_data)

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
                    cmd.extend(["-d", f"{parts[1]}:{parts[2]}"])

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
                    cmd.extend(["-d", f"{parts[1]}:{parts[2]}"])

            res = subprocess.run(cmd, capture_output=True, timeout=3)
            if res.returncode == 0:
                self._saved_inactive[device_id] = minutes
                return True
        except Exception:
            pass
        return False
