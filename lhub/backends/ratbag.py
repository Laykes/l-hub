import shutil
import subprocess
from typing import List, Optional
from .base import BaseBackend, Device, DeviceType, Capability, DpiInfo, ButtonMapping


class RatbagBackend(BaseBackend):
    """Backend for gaming mice and keyboards using libratbag (ratbagd)."""

    def __init__(self):
        super().__init__("ratbagd")
        self._ctl = shutil.which("ratbagctl")

    def is_available(self) -> bool:
        return self._ctl is not None

    def get_missing_reason(self) -> str:
        if not self.is_available():
            return "libratbag ist nicht installiert (sudo pacman -S libratbag && sudo systemctl enable --now ratbagd)"
        return ""

    def scan_devices(self) -> List[Device]:
        if not self.is_available():
            return []

        devices: List[Device] = []
        try:
            res = subprocess.run(
                [self._ctl, "list"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode != 0:
                return []

            lines = res.stdout.strip().splitlines()
            for line in lines:
                if ":" not in line:
                    continue
                dev_id, dev_name = line.split(":", 1)
                dev_id = dev_id.strip()
                dev_name = dev_name.strip()

                dev = self._inspect_device(dev_id, dev_name)
                if dev:
                    devices.append(dev)

        except Exception:
            pass

        return devices

    def _inspect_device(self, dev_id: str, dev_name: str) -> Optional[Device]:
        try:
            info_res = subprocess.run(
                [self._ctl, dev_id, "info"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if info_res.returncode != 0:
                return None

            lines = info_res.stdout.splitlines()
            vid, pid = "", ""
            num_buttons = 0
            has_active_enabled_profile = False
            active_profile_str = ""

            for line in lines:
                line_s = line.strip()
                if "Model: usb:" in line_s:
                    parts = line_s.split("Model: usb:")[1].split(":")
                    if len(parts) >= 2:
                        vid, pid = parts[0].strip().lower(), parts[1].strip().lower()
                elif "Number of Buttons:" in line_s:
                    try:
                        num_buttons = int(line_s.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif line_s.startswith("Profile") and "(active)" in line_s:
                    active_profile_str = line_s
                    if "(disabled)" not in line_s:
                        has_active_enabled_profile = True

            caps = [Capability.PROFILES]
            status_note = ""
            dpi_info = DpiInfo()
            buttons: List[ButtonMapping] = []

            if not has_active_enabled_profile:
                dpi_info.is_disabled = True
                status_note = "Profil im On-Board-Speicher deaktiviert"
            else:
                caps.extend([Capability.DPI, Capability.BUTTON_REMAP])
                dpi_info = self._get_dpi(dev_id)
                buttons = self._get_buttons(dev_id, num_buttons)

            return Device(
                id=dev_id,
                name=dev_name,
                vendor="Logitech" if "logitech" in dev_name.lower() or "046d" in vid else "Generic",
                device_type=DeviceType.MOUSE,
                usb_vid=vid,
                usb_pid=pid,
                capabilities=caps,
                dpi=dpi_info,
                buttons=buttons,
                status_note=status_note,
                backend_name=self.name,
            )
        except Exception:
            return None

    def _get_dpi(self, dev_id: str) -> DpiInfo:
        info = DpiInfo()
        try:
            res = subprocess.run(
                [self._ctl, dev_id, "dpi", "get"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                lines = res.stdout.strip().splitlines()
                steps = []
                for line in lines:
                    cleaned = line.lower()
                    for word in cleaned.replace(":", " ").replace("*", " ").split():
                        if word.endswith("dpi"):
                            try:
                                val = int(word[:-3])
                                steps.append(val)
                                if "active" in cleaned or "*" in line:
                                    info.current = val
                            except ValueError:
                                pass
                if steps:
                    info.steps = steps
        except Exception:
            pass
        return info

    def _get_buttons(self, dev_id: str, count: int) -> List[ButtonMapping]:
        buttons = []
        # Max 12 buttons
        max_b = min(12, count if count > 0 else 8)
        for idx in range(max_b):
            try:
                res = subprocess.run(
                    [self._ctl, dev_id, "button", str(idx), "get"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
                action_text = ""
                if res.returncode == 0:
                    action_text = res.stdout.strip()
                buttons.append(
                    ButtonMapping(
                        index=idx,
                        name=f"Taste {idx + 1}",
                        action_value=action_text,
                    )
                )
            except Exception:
                pass
        return buttons

    def set_dpi(self, device_id: str, dpi: int) -> bool:
        if not self.is_available():
            return False
        try:
            res = subprocess.run(
                [self._ctl, device_id, "dpi", "set", str(dpi)],
                capture_output=True,
                timeout=3,
            )
            return res.returncode == 0
        except Exception:
            return False

    def remap_button(self, device_id: str, button_idx: int, action: str) -> bool:
        if not self.is_available():
            return False
        try:
            res = subprocess.run(
                [self._ctl, device_id, "button", str(button_idx), "action", "set", action],
                capture_output=True,
                timeout=3,
            )
            return res.returncode == 0
        except Exception:
            return False
