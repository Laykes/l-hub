import re
import shutil
import subprocess
import time
from typing import List, Optional, Dict, Tuple
from .base import BaseBackend, Device, DeviceType, Capability, DpiInfo, ButtonMapping


ACTION_DISPLAY_NAMES: Dict[str, str] = {
    "button 1": "Left Click",
    "button 2": "Right Click",
    "button 3": "Middle Click",
    "button 4": "Back (Button 4)",
    "button 5": "Forward (Button 5)",
    "button 6": "Button 6",
    "button 7": "Button 7",
    "button 8": "Button 8",
    "special doubleclick": "Double Click",
    "special resolution-alternate": "DPI Shift (Sniper)",
    "special resolution-up": "DPI +",
    "special resolution-down": "DPI -",
    "special resolution-cycle-up": "Cycle DPI",
    "special profile-cycle-up": "Cycle Profile",
    "special second-mode": "G-Shift (Secondary Mode)",
    "special wheel-left": "Scroll Wheel Left",
    "special wheel-right": "Scroll Wheel Right",
    "disabled": "Disabled",
    "unknown": "Default / Unknown",
}

KEY_DISPLAY_NAMES: Dict[str, str] = {
    "KEY_ENTER": "Enter",
    "KEY_SPACE": "Space",
    "KEY_ESC": "Escape",
    "KEY_TAB": "Tab",
    "KEY_BACKSPACE": "Backspace",
    "KEY_DELETE": "Delete",
    "KEY_INSERT": "Insert",
    "KEY_HOME": "Home",
    "KEY_END": "End",
    "KEY_PAGEUP": "Page Up",
    "KEY_PAGEDOWN": "Page Down",
    "KEY_UP": "Up Arrow",
    "KEY_DOWN": "Down Arrow",
    "KEY_LEFT": "Left Arrow",
    "KEY_RIGHT": "Right Arrow",
    "KEY_LEFTSHIFT": "Left Shift",
    "KEY_RIGHTSHIFT": "Right Shift",
    "KEY_LEFTCTRL": "Left Ctrl",
    "KEY_RIGHTCTRL": "Right Ctrl",
    "KEY_LEFTALT": "Left Alt",
    "KEY_RIGHTALT": "Right Alt",
    "KEY_LEFTMETA": "Super / Win",
    "KEY_RIGHTMETA": "Right Super",
    "KEY_PRINT": "Screenshot (PrintScreen)",
    "KEY_VOLUMEUP": "Volume Up",
    "KEY_VOLUMEDOWN": "Volume Down",
    "KEY_MUTE": "Mute",
    "KEY_PLAYPAUSE": "Play/Pause",
    "KEY_NEXTSONG": "Next Track",
    "KEY_PREVIOUSSONG": "Previous Track",
    "KEY_STOPCD": "Stop",
}
for _i in range(1, 25):
    KEY_DISPLAY_NAMES[f"KEY_F{_i}"] = f"F{_i}"


def parse_macro(s: str) -> Tuple[str, str]:
    raw = s.strip()
    if raw.startswith("macro"):
        raw = raw[5:].strip()
    if raw.startswith("'") and raw.endswith("'"):
        raw = raw[1:-1]

    shortcuts = [
        (("KEY_LEFTCTRL", "KEY_C"), "Copy (Ctrl+C)", "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL"),
        (("KEY_LEFTCTRL", "KEY_V"), "Paste (Ctrl+V)", "macro +KEY_LEFTCTRL KEY_V -KEY_LEFTCTRL"),
        (("KEY_LEFTCTRL", "KEY_X"), "Cut (Ctrl+X)", "macro +KEY_LEFTCTRL KEY_X -KEY_LEFTCTRL"),
        (("KEY_LEFTCTRL", "KEY_Z"), "Undo (Ctrl+Z)", "macro +KEY_LEFTCTRL KEY_Z -KEY_LEFTCTRL"),
        (("KEY_LEFTCTRL", "KEY_Y"), "Redo (Ctrl+Y)", "macro +KEY_LEFTCTRL KEY_Y -KEY_LEFTCTRL"),
        (("KEY_LEFTCTRL", "KEY_A"), "Select All (Ctrl+A)", "macro +KEY_LEFTCTRL KEY_A -KEY_LEFTCTRL"),
        (("KEY_LEFTCTRL", "KEY_S"), "Save (Ctrl+S)", "macro +KEY_LEFTCTRL KEY_S -KEY_LEFTCTRL"),
        (("KEY_LEFTCTRL", "KEY_F"), "Find (Ctrl+F)", "macro +KEY_LEFTCTRL KEY_F -KEY_LEFTCTRL"),
        (("KEY_LEFTCTRL", "KEY_T"), "New Tab (Ctrl+T)", "macro +KEY_LEFTCTRL KEY_T -KEY_LEFTCTRL"),
        (("KEY_LEFTCTRL", "KEY_W"), "Close Tab (Ctrl+W)", "macro +KEY_LEFTCTRL KEY_W -KEY_LEFTCTRL"),
        (("KEY_LEFTALT", "KEY_TAB"), "Switch App (Alt+Tab)", "macro +KEY_LEFTALT KEY_TAB -KEY_LEFTALT"),
    ]
    for (k1, k2), disp, act in shortcuts:
        if k1 in raw and k2 in raw:
            return act, disp

    keys = re.findall(r"KEY_[A-Z0-9]+", raw)
    seen = []
    for k in keys:
        clean = KEY_DISPLAY_NAMES.get(k, k.replace("KEY_LEFT", "").replace("KEY_RIGHT", "").replace("KEY_", ""))
        if clean not in seen:
            seen.append(clean)
    disp = "Macro: " + " + ".join(seen) if seen else "Custom Macro"
    clean_act = s.strip()
    if clean_act.startswith("'") and clean_act.endswith("'"):
        clean_act = clean_act[1:-1]
    if not clean_act.startswith("macro "):
        clean_act = f"macro {clean_act}"
    return clean_act, disp


def get_button_metadata(dev_name: str, vid: str, pid: str, b_idx: int, act_val: str, total_buttons: int) -> Dict[str, str]:
    name_lower = dev_name.lower()
    is_g502 = "g502" in name_lower or (vid == "046d" and pid in ("c099", "c092", "c07d", "c332", "c08b"))

    if is_g502:
        g502_meta = {
            0: {"name": "Left Click (LMB)", "label": "Left Click", "location": "Primary Left", "group": "main", "default": "button 1"},
            1: {"name": "Right Click (RMB)", "label": "Right Click", "location": "Primary Right", "group": "main", "default": "button 2"},
            2: {"name": "Middle Click (Wheel)", "label": "Wheel Click", "location": "Scroll Wheel", "group": "wheel", "default": "button 3"},
            3: {"name": "Side Back (G4)", "label": "Back", "location": "Thumb Rest (Rear)", "group": "side", "default": "button 4"},
            4: {"name": "DPI Shift / Sniper (G6)", "label": "Sniper / Shift", "location": "Thumb Tip (Front)", "group": "side", "default": "special resolution-alternate"},
            5: {"name": "Side Forward (G5)", "label": "Forward", "location": "Thumb Rest (Front)", "group": "side", "default": "button 5"},
            6: {"name": "Wheel Tilt Left", "label": "Tilt Left", "location": "Scroll Wheel", "group": "wheel", "default": "special wheel-left"},
            7: {"name": "Wheel Tilt Right", "label": "Tilt Right", "location": "Scroll Wheel", "group": "wheel", "default": "special wheel-right"},
            8: {"name": "Profile Switch (G9)", "label": "Profile Switch", "location": "Behind Wheel", "group": "dpi", "default": "special profile-cycle-up"},
            9: {"name": "DPI Up (G8)", "label": "DPI Up", "location": "Left of LMB", "group": "dpi", "default": "special resolution-up"},
            10: {"name": "DPI Down (G7)", "label": "DPI Down", "location": "Left of LMB", "group": "dpi", "default": "special resolution-down"},
        }
        if b_idx in g502_meta:
            return g502_meta[b_idx]

    if b_idx == 0:
        return {"name": "Left Click", "label": "Left Click", "location": "Primary Left", "group": "main", "default": "button 1"}
    if b_idx == 1:
        return {"name": "Right Click", "label": "Right Click", "location": "Primary Right", "group": "main", "default": "button 2"}
    if b_idx == 2:
        return {"name": "Middle Click", "label": "Wheel Click", "location": "Scroll Wheel", "group": "wheel", "default": "button 3"}
    if b_idx == 3:
        return {"name": "Side Back (Button 4)", "label": "Back", "location": "Side Thumb", "group": "side", "default": "button 4"}
    if b_idx == 4 and total_buttons <= 6:
        return {"name": "Side Forward (Button 5)", "label": "Forward", "location": "Side Thumb", "group": "side", "default": "button 5"}

    act_lower = act_val.lower()
    if "wheel-left" in act_lower:
        return {"name": "Wheel Tilt Left", "label": "Tilt Left", "location": "Scroll Wheel", "group": "wheel", "default": "special wheel-left"}
    if "wheel-right" in act_lower:
        return {"name": "Wheel Tilt Right", "label": "Tilt Right", "location": "Scroll Wheel", "group": "wheel", "default": "special wheel-right"}
    if "resolution-alternate" in act_lower or "sniper" in act_lower:
        return {"name": "DPI Shift / Sniper", "label": "Sniper", "location": "Thumb Rest", "group": "side", "default": "special resolution-alternate"}
    if "resolution-up" in act_lower:
        return {"name": "DPI Up", "label": "DPI Up", "location": "Top Controls", "group": "dpi", "default": "special resolution-up"}
    if "resolution-down" in act_lower:
        return {"name": "DPI Down", "label": "DPI Down", "location": "Top Controls", "group": "dpi", "default": "special resolution-down"}
    if "resolution-cycle" in act_lower:
        return {"name": "Cycle DPI", "label": "Cycle DPI", "location": "Top Controls", "group": "dpi", "default": "special resolution-cycle-up"}
    if "profile-cycle" in act_lower:
        return {"name": "Cycle Profile", "label": "Cycle Profile", "location": "Top Controls", "group": "dpi", "default": "special profile-cycle-up"}
    if act_lower == "button 4":
        return {"name": "Side Back (Button 4)", "label": "Back", "location": "Side Thumb", "group": "side", "default": "button 4"}
    if act_lower == "button 5":
        return {"name": "Side Forward (Button 5)", "label": "Forward", "location": "Side Thumb", "group": "side", "default": "button 5"}

    return {
        "name": f"Button {b_idx + 1}",
        "label": f"Button {b_idx + 1}",
        "location": "Mouse",
        "group": "main" if b_idx < 3 else ("side" if b_idx < 6 else "dpi"),
        "default": f"button {b_idx + 1}",
    }


def parse_button_action(raw_val: str) -> Tuple[str, str]:
    val = raw_val.strip()
    if val.startswith("'") and val.endswith("'"):
        val = val[1:-1]

    if val.startswith("macro ") or val.startswith("macro'"):
        return parse_macro(val)
    elif val.startswith("button "):
        action = val
    elif val.startswith("key "):
        k = val[4:].strip().strip("'\"")
        action = f"key {k}"
    elif val == "none":
        action = "disabled"
    elif val == "UNKNOWN":
        action = "unknown"
    elif val in [
        "resolution-alternate",
        "resolution-up",
        "resolution-down",
        "resolution-cycle-up",
        "doubleclick",
        "wheel-left",
        "wheel-right",
        "profile-cycle-up",
        "second-mode",
    ]:
        action = f"special {val}"
    else:
        action = val

    if action.startswith("key "):
        key_code = action[4:].strip()
        disp = f"Key: {KEY_DISPLAY_NAMES.get(key_code, key_code.replace('KEY_', ''))}"
    else:
        disp = ACTION_DISPLAY_NAMES.get(action, action)

    return action, disp



class RatbagBackend(BaseBackend):
    """Backend for gaming mice and keyboards using libratbag (ratbagd)."""

    def __init__(self):
        super().__init__("ratbagd")
        self._ctl = shutil.which("ratbagctl")
        self._resolution_maps: Dict[str, Dict[int, int]] = {}

    def is_available(self) -> bool:
        return self._ctl is not None

    def get_missing_reason(self) -> str:
        if not self.is_available():
            return "libratbag is not installed (sudo pacman -S libratbag && sudo systemctl enable --now ratbagd)"
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
                timeout=6,
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
                timeout=8,
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
                status_note = "On-board memory profile disabled"
            else:
                caps.extend([Capability.DPI, Capability.BUTTON_REMAP])
                in_active_profile = False
                active_profile_lines = []
                for line in lines:
                    line_s = line.strip()
                    if line_s.startswith("Profile ") and "(active)" in line_s:
                        in_active_profile = True
                        continue
                    elif line_s.startswith("Profile ") and in_active_profile:
                        in_active_profile = False
                        break
                    if in_active_profile:
                        active_profile_lines.append(line_s)

                dpi_info = self._get_dpi(dev_id, active_profile_lines)

                for line_s in active_profile_lines:
                    if line_s.startswith("Button:"):
                        m = re.match(r"Button:\s*(\d+)\s+is mapped to\s+(.*)", line_s)
                        if m:
                            b_idx = int(m.group(1))
                            raw_val = m.group(2).strip()
                            act_val, act_disp = parse_button_action(raw_val)
                            # If Button 0 (Left Click) is unmapped or unknown, keep Left Click safe
                            if b_idx == 0 and act_val == "unknown":
                                act_val, act_disp = "button 1", "Left Click"
                            meta = get_button_metadata(dev_name, vid, pid, b_idx, act_val, num_buttons)
                            buttons.append(
                                ButtonMapping(
                                    index=b_idx,
                                    name=meta["name"],
                                    action_value=act_val,
                                    action_display=act_disp,
                                    label=meta["label"],
                                    location=meta["location"],
                                    group=meta["group"],
                                    default_action=meta["default"],
                                )
                            )

                if not buttons:
                    buttons = self._get_buttons(dev_id, num_buttons, dev_name, vid, pid)


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

    def _get_dpi(self, dev_id: str, active_profile_lines: Optional[List[str]] = None) -> DpiInfo:
        info = DpiInfo()
        valid_steps: List[int] = []
        current_from_lines: Optional[int] = None
        res_map: Dict[int, int] = {}

        if active_profile_lines:
            in_res = False
            for line in active_profile_lines:
                line_s = line.strip()
                if line_s.startswith("Resolutions:"):
                    in_res = True
                    continue
                elif in_res and (line_s.startswith("Button:") or line_s.startswith("Led:") or line_s.startswith("Report Rate:")):
                    in_res = False
                if in_res:
                    m = re.search(r"(\d+):\s*(\d+)(?:x\d+)?\s*dpi", line_s.lower())
                    if m:
                        idx = int(m.group(1))
                        val = int(m.group(2))
                        if 50 <= val <= 30000:
                            if val not in valid_steps:
                                valid_steps.append(val)
                            res_map[val] = idx
                            if "(active)" in line_s.lower():
                                current_from_lines = val

        self._resolution_maps[dev_id] = res_map

        try:
            res = subprocess.run(
                [self._ctl, dev_id, "dpi", "get"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0:
                m = re.search(r"(\d+)(?:x\d+)?\s*dpi", res.stdout.strip().lower())
                if m:
                    val = int(m.group(1))
                    if 50 <= val <= 30000:
                        info.current = val
            elif current_from_lines:
                info.current = current_from_lines
        except Exception:
            if current_from_lines:
                info.current = current_from_lines

        default_presets = [400, 800, 1600, 3200]
        if len(valid_steps) >= 2:
            steps_set = set(valid_steps)
        elif len(valid_steps) == 1 and valid_steps[0] in default_presets:
            steps_set = set(default_presets)
        else:
            steps_set = set(default_presets + valid_steps)
        if info.current:
            steps_set.add(info.current)
        info.steps = sorted(list(steps_set))
        return info

    def _get_buttons(self, dev_id: str, count: int, dev_name: str = "", vid: str = "", pid: str = "") -> List[ButtonMapping]:
        buttons = []
        max_b = min(12, count if count > 0 else 8)
        for idx in range(max_b):
            try:
                res = subprocess.run(
                    [self._ctl, dev_id, "button", str(idx), "action", "get"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
                act_val, act_disp = "unknown", "Default / Unknown"
                if res.returncode == 0:
                    raw = res.stdout.strip()
                    if " is mapped to " in raw:
                        raw = raw.split(" is mapped to ", 1)[1]
                    act_val, act_disp = parse_button_action(raw)
                meta = get_button_metadata(dev_name, vid, pid, idx, act_val, max_b)
                buttons.append(
                    ButtonMapping(
                        index=idx,
                        name=meta["name"],
                        action_value=act_val,
                        action_display=act_disp,
                        label=meta["label"],
                        location=meta["location"],
                        group=meta["group"],
                        default_action=meta["default"],
                    )
                )
            except Exception:
                pass
        return buttons

    def set_dpi(self, device_id: str, dpi: int) -> bool:
        if not self.is_available():
            return False
        try:
            # If the device has an existing resolution slot with this DPI, switch active resolution directly.
            # This is fast, atomic, and avoids rewriting profile/EEPROM.
            res_map = self._resolution_maps.get(device_id, {})
            if dpi in res_map:
                slot_idx = res_map[dpi]
                res = subprocess.run(
                    [self._ctl, device_id, "resolution", "active", "set", str(slot_idx)],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if res.returncode == 0:
                    return True

            # If not in resolution slots or resolution switch failed, set DPI directly
            res = subprocess.run(
                [self._ctl, device_id, "dpi", "set", str(dpi)],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if res.returncode == 0:
                return True
            # Recovery: ensure an active resolution exists and retry
            subprocess.run([self._ctl, device_id, "resolution", "active", "set", "0"], timeout=3)
            retry = subprocess.run(
                [self._ctl, device_id, "dpi", "set", str(dpi)],
                capture_output=True,
                text=True,
                timeout=4,
            )
            return retry.returncode == 0
        except Exception:
            return False

    def remap_button(self, device_id: str, button_idx: int, action: str) -> bool:
        if not self.is_available():
            return False
        if not action or action.strip().lower() in ("unknown", "standard / unbekannt", "default / unknown"):
            return False
        # Prevent disabling or unmapping primary left click (Button 0)
        if button_idx == 0 and action.strip().lower() in ("disabled", "none"):
            return False
        try:
            parts = action.strip().split()
            if not parts:
                return False
            cmd = [self._ctl, device_id, "button", str(button_idx), "action", "set"] + parts
            res = subprocess.run(
                cmd,
                capture_output=True,
                timeout=3,
            )
            return res.returncode == 0
        except Exception:
            return False

    def batch_remap_buttons(self, device_id: str, buttons: Dict[int, str]) -> bool:
        if not self.is_available() or not buttons:
            return False
        try:
            valid_items = [
                (idx, act)
                for idx, act in buttons.items()
                if act and act.strip().lower() not in ("unknown", "standard / unbekannt", "default / unknown")
            ]
            if not valid_items:
                return True
            for i, (idx, action) in enumerate(valid_items):
                parts = action.strip().split()
                if not parts:
                    continue
                is_last = (i == len(valid_items) - 1)
                cmd = [self._ctl]
                if not is_last:
                    cmd.append("--nocommit")
                cmd.extend([device_id, "button", str(idx), "action", "set"] + parts)
                subprocess.run(cmd, capture_output=True, timeout=3)
                time.sleep(0.04)
            return True
        except Exception:
            return False

    def reset_defaults(self, device_id: str) -> bool:
        if not self.is_available():
            return False
        try:
            # Ensure profile 1 (or active) is enabled
            subprocess.run([self._ctl, device_id, "profile", "1", "enable"], capture_output=True, timeout=3)

            dev = self._inspect_device(device_id, "")
            num_buttons = len(dev.buttons) if (dev and dev.buttons) else 11

            if num_buttons >= 11:
                defaults = {
                    0: "button 1",
                    1: "button 2",
                    2: "button 3",
                    3: "button 4",
                    4: "special resolution-alternate",
                    5: "button 5",
                    6: "special wheel-left",
                    7: "special wheel-right",
                    8: "special profile-cycle-up",
                    9: "special resolution-up",
                    10: "special resolution-down",
                }
            else:
                defaults = {
                    0: "button 1",
                    1: "button 2",
                    2: "button 3",
                    3: "button 4",
                    4: "button 5",
                }

            # Apply defaults to active profile
            self.batch_remap_buttons(device_id, defaults)

            # Ensure profile 0 also has valid mappings to prevent broken fallback
            for idx, action in defaults.items():
                parts = action.split()
                subprocess.run(
                    [self._ctl, device_id, "profile", "0", "button", str(idx), "action", "set"] + parts,
                    capture_output=True,
                    timeout=3,
                )
                time.sleep(0.04)

            target_dpi = 1600 if (dev and dev.dpi and 1600 in dev.dpi.steps) else 800
            self.set_dpi(device_id, target_dpi)
            return True
        except Exception:
            return False

