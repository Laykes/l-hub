import logging
import re
import shutil
import subprocess
import time
from typing import Any, List, Optional, Dict, Tuple
from .base import BaseBackend, Device, DeviceType, Capability, DpiInfo, ButtonMapping
from . import hidpp
from ..device_layouts import (
    find_device_layout,
    get_button_metadata as _get_button_metadata,
    get_factory_reset_defaults,
)

logger = logging.getLogger(__name__)


def _stderr_text(stderr: Any) -> str:
    if isinstance(stderr, bytes):
        return stderr.decode("utf-8", errors="replace").strip()
    if isinstance(stderr, str):
        return stderr.strip()
    return ""


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
    "KEY_SYSRQ": "Screenshot (PrintScreen)",
    "KEY_PAUSE": "Pause",
    "KEY_CAPSLOCK": "Caps Lock",
    "KEY_NUMLOCK": "Num Lock",
    "KEY_SCROLLLOCK": "Scroll Lock",
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


MODIFIER_KEYS = frozenset({
    "KEY_LEFTCTRL",
    "KEY_RIGHTCTRL",
    "KEY_LEFTALT",
    "KEY_RIGHTALT",
    "KEY_LEFTSHIFT",
    "KEY_RIGHTSHIFT",
    "KEY_LEFTMETA",
    "KEY_RIGHTMETA",
})

_MODIFIER_SHORT_NAMES: Dict[str, str] = {
    "KEY_LEFTCTRL": "Ctrl",
    "KEY_RIGHTCTRL": "Right Ctrl",
    "KEY_LEFTALT": "Alt",
    "KEY_RIGHTALT": "Right Alt",
    "KEY_LEFTSHIFT": "Shift",
    "KEY_RIGHTSHIFT": "Right Shift",
    "KEY_LEFTMETA": "Super",
    "KEY_RIGHTMETA": "Right Super",
}

_MODIFIER_ORDER: Dict[str, int] = {
    "KEY_LEFTCTRL": 0,
    "KEY_RIGHTCTRL": 1,
    "KEY_LEFTALT": 2,
    "KEY_RIGHTALT": 3,
    "KEY_LEFTSHIFT": 4,
    "KEY_RIGHTSHIFT": 5,
    "KEY_LEFTMETA": 6,
    "KEY_RIGHTMETA": 7,
}

_KEY_ALIASES: Dict[str, str] = {
    "KEY_SYSRQ": "KEY_PRINT",
}

_RIGHT_TO_LEFT_MOD: Dict[str, str] = {
    "KEY_RIGHTCTRL": "KEY_LEFTCTRL",
    "KEY_RIGHTSHIFT": "KEY_LEFTSHIFT",
    "KEY_RIGHTALT": "KEY_LEFTALT",
    "KEY_RIGHTMETA": "KEY_LEFTMETA",
}

_KNOWN_SHORTCUTS = [
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


def format_key_combo(modifiers: List[str], main_key: Optional[str]) -> Tuple[str, str]:
    """Build canonical (ratbag_action, display_label) for a key or modifier+key combo."""
    mods = sorted(set(modifiers), key=lambda m: _MODIFIER_ORDER.get(m, 99))

    if main_key is None:
        if len(mods) == 1:
            k = mods[0]
            return f"key {k}", f"Key: {KEY_DISPLAY_NAMES.get(k, k.replace('KEY_', ''))}"
        if len(mods) > 1:
            macro_parts = [f"+{m}" for m in mods] + [f"-{m}" for m in reversed(mods)]
            disp = " + ".join(_MODIFIER_SHORT_NAMES.get(m, m.replace("KEY_", "")) for m in mods)
            return "macro " + " ".join(macro_parts), disp
        return "", ""

    if not mods:
        k_disp = KEY_DISPLAY_NAMES.get(main_key, main_key.replace("KEY_", ""))
        return f"key {main_key}", f"Key: {k_disp}"

    if len(mods) == 1:
        for (k1, k2), disp, act in _KNOWN_SHORTCUTS:
            if mods[0] == k1 and main_key == k2:
                return act, disp

    macro_parts = [f"+{m}" for m in mods] + [main_key] + [f"-{m}" for m in reversed(mods)]
    disp_parts = [_MODIFIER_SHORT_NAMES.get(m, m.replace("KEY_", "")) for m in mods]
    disp_parts.append(KEY_DISPLAY_NAMES.get(main_key, main_key.replace("KEY_", "")))
    return "macro " + " ".join(macro_parts), " + ".join(disp_parts)


def _normalize_macro_tokens(raw: str) -> List[str]:
    tokens: List[str] = []
    for tok in raw.split():
        if tok.startswith("↓"):
            tokens.append("+" + tok[1:])
        elif tok.startswith("↑"):
            tokens.append("-" + tok[1:])
        elif tok.startswith("↕"):
            tokens.append(tok[1:])
        elif tok.startswith("⏱"):
            tokens.append("t" + tok[1:])
        elif re.fullmatch(r"\d+ms", tok):
            tokens.append("t" + tok)
        else:
            tokens.append(tok)
    return tokens


def parse_macro(s: str) -> Tuple[str, str]:
    raw = s.strip()
    if raw.startswith("macro"):
        raw = raw[5:].strip()
    if raw.startswith("'") and raw.endswith("'"):
        raw = raw[1:-1]

    tokens = _normalize_macro_tokens(raw)
    keys = re.findall(r"KEY_[A-Z0-9_]+", " ".join(tokens))
    unique_keys = list(dict.fromkeys(keys))

    if len(unique_keys) == 2:
        key_set = set(unique_keys)
        for (k1, k2), disp, act in _KNOWN_SHORTCUTS:
            if key_set == {k1, k2}:
                return act, disp

    seen = []
    for k in unique_keys:
        clean = KEY_DISPLAY_NAMES.get(k, k.replace("KEY_LEFT", "").replace("KEY_RIGHT", "").replace("KEY_", ""))
        if clean not in seen:
            seen.append(clean)
    disp = "Macro: " + " + ".join(seen) if seen else "Custom Macro"
    clean_act = ("macro " + " ".join(tokens)) if tokens else "macro"
    return clean_act, disp


def _action_key_signature(
    action: str,
    relaxed_modifiers: bool = False,
) -> Optional[Tuple[frozenset, Tuple[str, ...]]]:
    act = action.strip()
    if act.startswith("key "):
        k = act[4:].strip().strip("'\"")
        if not k:
            return None
        k = _KEY_ALIASES.get(k, k)
        if relaxed_modifiers:
            k = _RIGHT_TO_LEFT_MOD.get(k, k)
        if k in MODIFIER_KEYS:
            return frozenset({k}), ()
        return frozenset(), (k,)

    if act.startswith("macro ") or act.startswith("macro'"):
        norm_act, _ = parse_macro(act)
        raw = norm_act[6:].strip()
        mods = set()
        non_mods: List[str] = []
        for tok in raw.split():
            if re.fullmatch(r"t\d+ms", tok):
                continue
            is_release = tok.startswith("-")
            key_name = tok.lstrip("+-")
            if not key_name.startswith("KEY_"):
                continue
            key_name = _KEY_ALIASES.get(key_name, key_name)
            if relaxed_modifiers:
                key_name = _RIGHT_TO_LEFT_MOD.get(key_name, key_name)
            if key_name in MODIFIER_KEYS:
                if not is_release:
                    mods.add(key_name)
            elif not is_release:
                non_mods.append(key_name)
        if not mods and not non_mods:
            return None
        return frozenset(mods), tuple(non_mods)

    return None


def actions_match(configured_action: str, detected_action: str, relaxed_modifiers: bool = False) -> bool:
    """Return True if a configured button action matches a detected input action."""
    if not configured_action or not detected_action:
        return False
    if configured_action == detected_action:
        return True
    sig_a = _action_key_signature(configured_action, relaxed_modifiers=relaxed_modifiers)
    sig_b = _action_key_signature(detected_action, relaxed_modifiers=relaxed_modifiers)
    return sig_a is not None and sig_a == sig_b


def get_button_metadata(dev_name: str, vid: str, pid: str, b_idx: int, act_val: str, total_buttons: int) -> Dict[str, str]:
    """Return button metadata from matching device layout JSON or generic fallback."""
    return _get_button_metadata(dev_name, vid, pid, b_idx, act_val, total_buttons)


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
        self._usb_ids: Dict[str, Tuple[str, str]] = {}
        self._active_profiles: Dict[str, int] = {}

    def _resolve_active_profile(self, device_id: str) -> Tuple[Optional[int], Optional[int]]:
        """Return (0-based ratbag profile index, 16-bit HID++ profile ID)."""
        usb_id = self._usb_ids.get(device_id)
        if usb_id:
            hw_id = hidpp.get_onboard_profile(*usb_id)
            hw_idx = hidpp.onboard_profile_index(hw_id)
            if hw_idx is not None:
                self._active_profiles[device_id] = hw_idx
                return hw_idx, hw_id
        return self._active_profiles.get(device_id), None

    def _finalize_hidpp_commit(self, device_id: str, hidpp_profile_id: Optional[int]) -> None:
        usb_id = self._usb_ids.get(device_id)
        if not usb_id or hidpp_profile_id is None:
            return
        # ratbagd commits asynchronously over hidraw; wait before sending HID++ traffic
        # so we don't collide with the flash write, then reload the active profile into RAM.
        time.sleep(1.5)
        hidpp.set_onboard_profile(*usb_id, hidpp_profile_id)

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
            stdout_txt = (res.stdout or "").strip()
            if res.returncode != 0 or "unable to connect to ratbagd" in stdout_txt.lower():
                detail = _stderr_text(res.stderr) or stdout_txt or "no output"
                logger.warning("ratbagctl list failed (rc=%d): %s", res.returncode, detail)
                return []

            lines = stdout_txt.splitlines()
            for line in lines:
                if ":" not in line:
                    continue
                dev_id, dev_name = line.split(":", 1)
                dev_id = dev_id.strip()
                dev_name = dev_name.strip()

                dev = self._inspect_device(dev_id, dev_name)
                if dev:
                    devices.append(dev)

        except Exception as exc:
            logger.warning("RatbagBackend scan_devices failed: %s", exc)

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
                logger.warning(
                    "ratbagctl %s info failed (rc=%d): %s",
                    dev_id,
                    info_res.returncode,
                    _stderr_text(info_res.stderr),
                )
                return None

            lines = info_res.stdout.splitlines()
            if not dev_name and lines and " - " in lines[0]:
                dev_name = lines[0].split(" - ", 1)[1].strip()
            vid, pid = "", ""
            num_buttons = 0
            profiles: Dict[int, Dict[str, object]] = {}
            current_prof_idx: Optional[int] = None
            ratbag_active_idx: Optional[int] = None

            for line in lines:
                line_s = line.strip()
                if "Model: usb:" in line_s:
                    parts = line_s.split("Model: usb:")[1].split(":")
                    if len(parts) >= 2:
                        vid, pid = parts[0].strip().lower(), parts[1].strip().lower()
                elif "Number of Buttons:" in line_s:
                    try:
                        num_buttons = int(line_s.split(":", 1)[1].strip())
                    except ValueError as exc:
                        logger.debug("Failed to parse button count for %s: %s", dev_id, exc)
                else:
                    pm = re.match(r"Profile\s+(\d+):", line_s)
                    if pm:
                        current_prof_idx = int(pm.group(1))
                        profiles[current_prof_idx] = {
                            "disabled": "(disabled)" in line_s,
                            "lines": [],
                        }
                        if "(active)" in line_s:
                            ratbag_active_idx = current_prof_idx
                    elif current_prof_idx is not None:
                        profiles[current_prof_idx]["lines"].append(line_s)

            caps = [Capability.PROFILES]
            if vid and pid:
                self._usb_ids[dev_id] = (vid, pid)

            # ratbagd does not track hardware onboard profile switches; prefer live HID++ profile.
            onboard_profile_id = hidpp.get_onboard_profile(vid, pid) if (vid and pid) else None
            onboard_profile = (
                hidpp.format_onboard_profile(onboard_profile_id)
                if onboard_profile_id is not None
                else None
            )
            hw_profile_idx = hidpp.onboard_profile_index(onboard_profile_id)

            selected_profile_idx: Optional[int] = None
            if (
                hw_profile_idx is not None
                and hw_profile_idx in profiles
                and not profiles[hw_profile_idx]["disabled"]
            ):
                selected_profile_idx = hw_profile_idx
            elif (
                ratbag_active_idx is not None
                and not profiles[ratbag_active_idx]["disabled"]
            ):
                selected_profile_idx = ratbag_active_idx

            status_note = ""
            dpi_info = DpiInfo()
            buttons: List[ButtonMapping] = []

            if selected_profile_idx is None:
                dpi_info.is_disabled = True
                status_note = "On-board memory profile disabled"
            else:
                self._active_profiles[dev_id] = selected_profile_idx
                caps.extend([Capability.DPI, Capability.BUTTON_REMAP])
                active_profile_lines: List[str] = profiles[selected_profile_idx]["lines"]  # type: ignore[assignment]

                dpi_info = self._get_dpi(dev_id, active_profile_lines, profile_idx=selected_profile_idx)

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
                    buttons = self._get_buttons(
                        dev_id, num_buttons, dev_name, vid, pid, profile_idx=selected_profile_idx
                    )

            layout = find_device_layout(dev_name, vid, pid)
            vendor = (
                layout.vendor
                if layout is not None
                else ("Logitech" if "logitech" in dev_name.lower() or "046d" in vid else "Generic")
            )

            return Device(
                id=dev_id,
                name=dev_name,
                vendor=vendor,
                device_type=DeviceType.MOUSE,
                usb_vid=vid,
                usb_pid=pid,
                capabilities=caps,
                dpi=dpi_info,
                buttons=buttons,
                onboard_profile_id=onboard_profile_id,
                onboard_profile=onboard_profile,
                status_note=status_note,
                backend_name=self.name,
            )
        except Exception as exc:
            logger.warning("Failed to inspect ratbag device %s: %s", dev_id, exc)
            return None

    def _get_dpi(
        self,
        dev_id: str,
        active_profile_lines: Optional[List[str]] = None,
        profile_idx: Optional[int] = None,
    ) -> DpiInfo:
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
            prof_args = ["profile", str(profile_idx)] if profile_idx is not None else []
            res = subprocess.run(
                [self._ctl, dev_id] + prof_args + ["dpi", "get"],
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
        except Exception as exc:
            logger.debug("ratbagctl dpi get failed for %s: %s", dev_id, exc)
            if current_from_lines:
                info.current = current_from_lines

        # ratbagd's value is stale when profile commits fail; the device itself is authoritative.
        usb_id = self._usb_ids.get(dev_id)
        if usb_id:
            hw_dpi = hidpp.get_dpi(*usb_id)
            if hw_dpi and 50 <= hw_dpi <= 30000:
                info.current = hw_dpi

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

    def _get_buttons(
        self,
        dev_id: str,
        count: int,
        dev_name: str = "",
        vid: str = "",
        pid: str = "",
        profile_idx: Optional[int] = None,
    ) -> List[ButtonMapping]:
        buttons = []
        max_b = min(12, count if count > 0 else 8)
        prof_args = ["profile", str(profile_idx)] if profile_idx is not None else []
        for idx in range(max_b):
            try:
                res = subprocess.run(
                    [self._ctl, dev_id] + prof_args + ["button", str(idx), "action", "get"],
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
            except Exception as exc:
                logger.debug("Failed to read button %d for %s: %s", idx, dev_id, exc)
        return buttons

    def set_dpi(self, device_id: str, dpi: int) -> bool:
        usb_id = self._usb_ids.get(device_id)
        if usb_id and hidpp.set_dpi(*usb_id, dpi):
            return True
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
                logger.debug(
                    "ratbagctl resolution active set %s failed for %s (rc=%d): %s",
                    slot_idx,
                    device_id,
                    res.returncode,
                    _stderr_text(res.stderr),
                )

            # If not in resolution slots or resolution switch failed, set DPI directly
            res = subprocess.run(
                [self._ctl, device_id, "dpi", "set", str(dpi)],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if res.returncode == 0:
                return True
            logger.debug(
                "ratbagctl dpi set %d failed for %s (rc=%d): %s; attempting recovery",
                dpi,
                device_id,
                res.returncode,
                _stderr_text(res.stderr),
            )
            # Recovery: ensure an active resolution exists and retry
            subprocess.run([self._ctl, device_id, "resolution", "active", "set", "0"], timeout=3)
            retry = subprocess.run(
                [self._ctl, device_id, "dpi", "set", str(dpi)],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if retry.returncode != 0:
                logger.warning(
                    "ratbagctl dpi set %d failed after recovery for %s (rc=%d): %s",
                    dpi,
                    device_id,
                    retry.returncode,
                    _stderr_text(retry.stderr),
                )
            return retry.returncode == 0
        except Exception as exc:
            logger.warning("Failed to set DPI %d on %s: %s", dpi, device_id, exc)
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
            profile_idx, hidpp_profile_id = self._resolve_active_profile(device_id)
            prof_args = ["profile", str(profile_idx)] if profile_idx is not None else []
            cmd = [self._ctl, device_id] + prof_args + ["button", str(button_idx), "action", "set"] + parts
            res = subprocess.run(
                cmd,
                capture_output=True,
                timeout=8,
            )
            if res.returncode != 0:
                logger.warning(
                    "ratbagctl remap_button failed for %s button %d (rc=%d): %s",
                    device_id,
                    button_idx,
                    res.returncode,
                    _stderr_text(res.stderr),
                )
                return False
            self._finalize_hidpp_commit(device_id, hidpp_profile_id)
            return True
        except Exception as exc:
            logger.warning("Failed to remap button %d on %s: %s", button_idx, device_id, exc)
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
            profile_idx, hidpp_profile_id = self._resolve_active_profile(device_id)
            prof_args = ["profile", str(profile_idx)] if profile_idx is not None else []
            last_ok = False
            for i, (idx, action) in enumerate(valid_items):
                parts = action.strip().split()
                if not parts:
                    continue
                is_last = (i == len(valid_items) - 1)
                cmd = [self._ctl]
                if not is_last:
                    cmd.append("--nocommit")
                cmd.extend([device_id] + prof_args + ["button", str(idx), "action", "set"] + parts)
                res = subprocess.run(cmd, capture_output=True, timeout=8 if is_last else 3)
                if is_last:
                    last_ok = (res.returncode == 0)
                    if not last_ok:
                        logger.warning(
                            "ratbagctl batch_remap commit failed for %s (rc=%d): %s",
                            device_id,
                            res.returncode,
                            _stderr_text(res.stderr),
                        )
                else:
                    if res.returncode != 0:
                        logger.debug(
                            "ratbagctl --nocommit step failed for %s button %d (rc=%d): %s",
                            device_id,
                            idx,
                            res.returncode,
                            _stderr_text(res.stderr),
                        )
                    time.sleep(0.04)
            if last_ok:
                self._finalize_hidpp_commit(device_id, hidpp_profile_id)
            return True
        except Exception as exc:
            logger.warning("Failed batch remap on %s: %s", device_id, exc)
            return False

    def reset_defaults(self, device_id: str) -> bool:
        if not self.is_available():
            return False
        try:
            # Ensure profile 1 (or active) is enabled
            subprocess.run([self._ctl, device_id, "profile", "1", "enable"], capture_output=True, timeout=3)

            dev = self._inspect_device(device_id, "")
            cached_vid, cached_pid = self._usb_ids.get(device_id, ("", ""))
            dev_name = dev.name if dev else ""
            vid = (dev.usb_vid if dev and dev.usb_vid else cached_vid) or ""
            pid = (dev.usb_pid if dev and dev.usb_pid else cached_pid) or ""
            total_buttons = len(dev.buttons) if (dev and dev.buttons) else None

            defaults = get_factory_reset_defaults(
                dev_name=dev_name,
                vid=vid,
                pid=pid,
                total_buttons=total_buttons,
            )

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
        except Exception as exc:
            logger.warning("Failed resetting defaults on %s: %s", device_id, exc)
            return False

