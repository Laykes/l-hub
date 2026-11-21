import logging
import shutil
import subprocess
from typing import List
from .base import BaseBackend, Device, DeviceType, Capability, BatteryInfo

logger = logging.getLogger(__name__)


class UPowerBackend(BaseBackend):
    """Fallback backend to detect battery levels of connected peripherals via UPower."""

    def __init__(self):
        super().__init__("upower")
        self._cmd = shutil.which("upower")

    def is_available(self) -> bool:
        return self._cmd is not None

    def scan_devices(self) -> List[Device]:
        if not self.is_available():
            return []

        devices: List[Device] = []
        try:
            res = subprocess.run(
                [self._cmd, "-e"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode != 0:
                logger.warning("upower -e failed (rc=%d): %s", res.returncode, (res.stderr or "").strip())
                return []

            paths = [
                p.strip()
                for p in res.stdout.splitlines()
                if any(x in p.lower() for x in ["mouse", "keyboard", "headset", "controller", "gaming"])
            ]

            for path in paths:
                info_res = subprocess.run(
                    [self._cmd, "-i", path],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if info_res.returncode != 0:
                    logger.debug("upower -i %s failed (rc=%d): %s", path, info_res.returncode, (info_res.stderr or "").strip())
                    continue

                model = ""
                vendor = "Generic"
                percentage = -1
                is_charging = False
                dev_type = DeviceType.OTHER
                vid, pid = "", ""

                for line in info_res.stdout.splitlines():
                    line_s = line.strip()
                    if line_s.startswith("model:"):
                        model = line_s.split(":", 1)[1].strip()
                    elif line_s.startswith("vendor:"):
                        vendor = line_s.split(":", 1)[1].strip()
                    elif line_s.startswith("percentage:"):
                        val_str = line_s.split(":", 1)[1].strip().replace("%", "")
                        try:
                            percentage = int(float(val_str))
                        except ValueError as exc:
                            logger.debug("Failed to parse UPower percentage %r for %s: %s", val_str, path, exc)
                    elif line_s.startswith("state:"):
                        is_charging = "charging" in line_s.lower() and "discharging" not in line_s.lower()

                path_lower = path.lower()
                if "mouse" in path_lower:
                    dev_type = DeviceType.MOUSE
                elif "keyboard" in path_lower:
                    dev_type = DeviceType.KEYBOARD
                elif "headset" in path_lower:
                    dev_type = DeviceType.HEADSET
                elif "controller" in path_lower or "gaming" in path_lower:
                    dev_type = DeviceType.OTHER

                if not model:
                    model = path.split("/")[-1].replace("_", " ").title()

                dev = Device(
                    id=f"upower_{path.split('/')[-1]}",
                    name=model,
                    vendor=vendor if vendor != "Generic" else model.split()[0],
                    device_type=dev_type,
                    usb_vid=vid,
                    usb_pid=pid,
                    capabilities=[Capability.BATTERY],
                    battery=BatteryInfo(percentage=percentage, is_charging=is_charging),
                    backend_name=self.name,
                )
                devices.append(dev)

        except Exception as exc:
            logger.warning("UPowerBackend scan failed: %s", exc)

        return devices
