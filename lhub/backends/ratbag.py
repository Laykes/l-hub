"""Ratbagd D-Bus backend for gaming mice and keyboards (``org.freedesktop.ratbag1``)."""

from contextlib import contextmanager
from enum import IntEnum
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import hidpp
from .base import BaseBackend, ButtonMapping, Capability, Device, DeviceType, DpiInfo
from .dbus_client import (
    DBUS_IFACE,
    DBUS_PATH,
    DBUS_PROPERTIES_IFACE,
    DBUS_SERVICE,
    DBusCallError,
    DBusError,
    DBusSignalEvent,
    SystemDBusClient,
    get_system_dbus_client,
    unwrap_variant,
)
from .evdev_codes import evcode_to_key_name, key_name_to_evcode
from ..device_layouts import (
    find_device_layout,
    get_button_metadata as _get_button_metadata,
    get_factory_reset_defaults,
)

logger = logging.getLogger(__name__)

RATBAG_SERVICE = "org.freedesktop.ratbag1"
RATBAG_MANAGER_PATH = "/org/freedesktop/ratbag1"
RATBAG_MANAGER_IFACE = "org.freedesktop.ratbag1.Manager"
RATBAG_DEVICE_IFACE = "org.freedesktop.ratbag1.Device"
RATBAG_PROFILE_IFACE = "org.freedesktop.ratbag1.Profile"
RATBAG_RESOLUTION_IFACE = "org.freedesktop.ratbag1.Resolution"
RATBAG_BUTTON_IFACE = "org.freedesktop.ratbag1.Button"
RATBAG_API_VERSION = 2


class RatbagDeviceType(IntEnum):
    """DeviceType values exposed on ``org.freedesktop.ratbag1.Device``."""

    UNSPECIFIED = 0
    OTHER = 1
    MOUSE = 2
    KEYBOARD = 3


class RatbagActionType(IntEnum):
    """ActionType values exposed on ``org.freedesktop.ratbag1.Button``."""

    NONE = 0
    BUTTON = 1
    SPECIAL = 2
    KEY = 3
    MACRO = 4


class RatbagActionSpecial(IntEnum):
    """Special button action codes defined by libratbag."""

    INVALID = -1
    UNKNOWN = 1 << 30
    DOUBLECLICK = (1 << 30) + 1
    WHEEL_LEFT = (1 << 30) + 2
    WHEEL_RIGHT = (1 << 30) + 3
    WHEEL_UP = (1 << 30) + 4
    WHEEL_DOWN = (1 << 30) + 5
    RATCHET_MODE_SWITCH = (1 << 30) + 6
    RESOLUTION_CYCLE_UP = (1 << 30) + 7
    RESOLUTION_CYCLE_DOWN = (1 << 30) + 8
    RESOLUTION_UP = (1 << 30) + 9
    RESOLUTION_DOWN = (1 << 30) + 10
    RESOLUTION_ALTERNATE = (1 << 30) + 11
    RESOLUTION_DEFAULT = (1 << 30) + 12
    PROFILE_CYCLE_UP = (1 << 30) + 13
    PROFILE_CYCLE_DOWN = (1 << 30) + 14
    PROFILE_UP = (1 << 30) + 15
    PROFILE_DOWN = (1 << 30) + 16
    SECOND_MODE = (1 << 30) + 17
    BATTERY_LEVEL = (1 << 30) + 18


class RatbagMacroEvent(IntEnum):
    """Macro event types in ``org.freedesktop.ratbag1.Button.Mapping`` ``a(uu)``."""

    NONE = 0
    KEY_PRESS = 1
    KEY_RELEASE = 2
    WAIT = 3


SPECIAL_TO_NAME: Dict[int, str] = {
    int(item): item.name.lower().replace("_", "-")
    for item in RatbagActionSpecial
}
NAME_TO_SPECIAL: Dict[str, int] = {
    name: code
    for code, name in SPECIAL_TO_NAME.items()
    if code not in (int(RatbagActionSpecial.INVALID), int(RatbagActionSpecial.UNKNOWN))
}


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
    elif val.lower() == "unknown":
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
    ] or val in NAME_TO_SPECIAL:
        action = f"special {val}"
    else:
        action = val

    if action.startswith("key "):
        key_code = action[4:].strip()
        disp = f"Key: {KEY_DISPLAY_NAMES.get(key_code, key_code.replace('KEY_', ''))}"
    else:
        disp = ACTION_DISPLAY_NAMES.get(action, action)

    return action, disp


def unpack_dbus_resolution(raw_res: Any) -> Tuple[int, ...]:
    """Unpack ``org.freedesktop.ratbag1.Resolution.Resolution`` into a 1- or 2-int tuple."""
    val = unwrap_variant(raw_res, recursive=True)
    if isinstance(val, int):
        return (int(val),)
    if isinstance(val, (list, tuple)):
        return tuple(int(x) for x in val if isinstance(x, (int, float)))
    return ()


def decode_dbus_button_mapping(mapping: Any) -> Tuple[str, str]:
    """Decode ``org.freedesktop.ratbag1.Button.Mapping`` ``(uv)`` into ``(action, display)``."""
    unwrapped = unwrap_variant(mapping, recursive=False)
    if not isinstance(unwrapped, (list, tuple)) or len(unwrapped) != 2:
        return parse_button_action("UNKNOWN")

    action_type_raw, payload_raw = unwrapped
    try:
        action_type = int(action_type_raw)
    except (TypeError, ValueError):
        return parse_button_action("UNKNOWN")

    payload = unwrap_variant(payload_raw, recursive=True)

    if action_type == int(RatbagActionType.NONE):
        return parse_button_action("none")

    if action_type == int(RatbagActionType.BUTTON):
        try:
            btn_num = int(payload)
        except (TypeError, ValueError):
            return parse_button_action("UNKNOWN")
        return parse_button_action(f"button {btn_num}")

    if action_type == int(RatbagActionType.SPECIAL):
        try:
            spec_code = int(payload)
        except (TypeError, ValueError):
            return parse_button_action("UNKNOWN")
        spec_name = SPECIAL_TO_NAME.get(spec_code)
        if spec_name and spec_name not in ("unknown", "invalid"):
            return parse_button_action(spec_name)
        return parse_button_action("UNKNOWN")

    if action_type == int(RatbagActionType.KEY):
        try:
            key_code = int(payload)
        except (TypeError, ValueError):
            return parse_button_action("UNKNOWN")
        return parse_button_action(f"key {evcode_to_key_name(key_code)}")

    if action_type == int(RatbagActionType.MACRO):
        if not isinstance(payload, (list, tuple)) or not payload:
            return "macro", "Custom Macro"
        events: List[Tuple[int, int]] = []
        for entry in payload:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                try:
                    events.append((int(entry[0]), int(entry[1])))
                except (TypeError, ValueError):
                    continue
        if not events:
            return "macro", "Custom Macro"

        tokens: List[str] = []
        idx = 0
        while idx < len(events):
            ev_type, ev_val = events[idx]
            if ev_type == int(RatbagMacroEvent.WAIT):
                tokens.append(f"{ev_val}ms")
            elif ev_type == int(RatbagMacroEvent.KEY_PRESS):
                key_name = evcode_to_key_name(ev_val)
                if (
                    idx + 1 < len(events)
                    and events[idx + 1][0] == int(RatbagMacroEvent.KEY_RELEASE)
                    and events[idx + 1][1] == ev_val
                ):
                    tokens.append(f"↕{key_name}")
                    idx += 1
                else:
                    tokens.append(f"↓{key_name}")
            elif ev_type == int(RatbagMacroEvent.KEY_RELEASE):
                tokens.append(f"↑{evcode_to_key_name(ev_val)}")
            idx += 1
        return parse_macro(" ".join(tokens))

    return parse_button_action("UNKNOWN")


def encode_dbus_button_mapping(
    action: str,
    *,
    prefer_macro_for_keys: bool = False,
) -> Tuple[int, Tuple[str, Any]]:
    """Encode an action string (e.g. ``button 1``, ``key KEY_SPACE``, ``macro ...``) into ``(uv)``."""
    raw = str(action or "").strip()
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        raw = raw[1:-1].strip()

    lowered = raw.lower()
    if not raw or lowered in ("unknown", "standard / unbekannt", "default / unknown"):
        raise ValueError(f"Cannot encode unknown/empty action: {action!r}")

    if lowered in ("none", "disabled"):
        return (int(RatbagActionType.NONE), ("u", 0))

    if lowered.startswith("button "):
        btn_part = raw.split(None, 1)[1].strip()
        try:
            btn_num = int(btn_part)
        except ValueError as exc:
            raise ValueError(f"Invalid mouse button index in action {action!r}") from exc
        if btn_num <= 0:
            raise ValueError(f"Invalid mouse button number {btn_num} in action {action!r}")
        return (int(RatbagActionType.BUTTON), ("u", btn_num))

    if lowered.startswith("special ") or lowered in NAME_TO_SPECIAL:
        spec_name = raw.split(None, 1)[1].strip().lower() if lowered.startswith("special ") else lowered
        if spec_name not in NAME_TO_SPECIAL or spec_name == "unknown":
            raise ValueError(f"Unknown ratbag special action: {action!r}")
        return (int(RatbagActionType.SPECIAL), ("u", int(NAME_TO_SPECIAL[spec_name])))

    if lowered.startswith("key "):
        key_part = raw.split(None, 1)[1].strip().strip("'\"")
        norm_key = key_part.upper()
        code = key_name_to_evcode(key_part)
        # libratbag's hidpp20 0x8100 writer does not clear keyboard_keys.modifier_flags
        # for RATBAG_BUTTON_ACTION_TYPE_KEY, leaving stale modifier bits from prior
        # mappings; single non-modifier macros explicitly write modifier_flags = 0 and
        # match how hidpp20 reads keyboard/consumer keys back.
        if prefer_macro_for_keys and norm_key not in MODIFIER_KEYS:
            return (
                int(RatbagActionType.MACRO),
                (
                    "a(uu)",
                    [
                        (int(RatbagMacroEvent.KEY_PRESS), int(code)),
                        (int(RatbagMacroEvent.KEY_RELEASE), int(code)),
                    ],
                ),
            )
        return (int(RatbagActionType.KEY), ("u", int(code)))

    if lowered.startswith("macro ") or lowered.startswith("macro'"):
        body = raw[5:].strip()
        if body.startswith("'") and body.endswith("'") and len(body) >= 2:
            body = body[1:-1].strip()
        tokens = _normalize_macro_tokens(body)
        events: List[Tuple[int, int]] = []

        def _append_event(ev_type: int, ev_val: int) -> None:
            pair = (ev_type, ev_val)
            if not events or events[-1] != pair:
                events.append(pair)

        for tok in tokens:
            wait_match = re.fullmatch(r"[tT](\d+)(?:ms)?", tok)
            if wait_match:
                _append_event(int(RatbagMacroEvent.WAIT), int(wait_match.group(1)))
                continue
            if tok.startswith("+"):
                _append_event(int(RatbagMacroEvent.KEY_PRESS), key_name_to_evcode(tok[1:]))
            elif tok.startswith("-"):
                _append_event(int(RatbagMacroEvent.KEY_RELEASE), key_name_to_evcode(tok[1:]))
            else:
                code = key_name_to_evcode(tok)
                _append_event(int(RatbagMacroEvent.KEY_PRESS), code)
                _append_event(int(RatbagMacroEvent.KEY_RELEASE), code)

        if not events:
            raise ValueError(f"Empty macro action: {action!r}")
        return (int(RatbagActionType.MACRO), ("a(uu)", events))

    raise ValueError(f"Unsupported ratbag button action: {action!r}")


def _parse_model_usb_ids(model_str: str) -> Tuple[str, str]:
    parts = [p.strip().lower() for p in str(model_str or "").split(":")]
    if len(parts) >= 3 and parts[0] in ("usb", "bluetooth"):
        return parts[1], parts[2]
    return "", ""


class RatbagBackend(BaseBackend):
    """Backend for gaming mice and keyboards using libratbag (``ratbagd``) over D-Bus."""

    def __init__(self, dbus_client: Optional[SystemDBusClient] = None):
        super().__init__("ratbagd")
        self._dbus = dbus_client or get_system_dbus_client()
        self._topology_lock = threading.Lock()
        self._write_lock = threading.RLock()
        self._committing_devices: Dict[str, int] = {}
        self._device_paths: Dict[str, str] = {}
        self._profile_paths: Dict[str, Dict[int, str]] = {}
        self._resolution_paths: Dict[str, Dict[int, Dict[int, str]]] = {}
        self._resolution_is_xy: Dict[str, Dict[int, Dict[int, bool]]] = {}
        self._button_paths: Dict[str, Dict[int, Dict[int, str]]] = {}
        self._resolution_maps: Dict[str, Dict[int, int]] = {}
        self._usb_ids: Dict[str, Tuple[str, str]] = {}
        self._device_names: Dict[str, str] = {}
        self._active_profiles: Dict[str, int] = {}
        self._subscription_ids: List[int] = []
        self._activation_failed: bool = False

    def _is_logitech_device(self, device_id: str) -> bool:
        with self._topology_lock:
            usb_id = self._usb_ids.get(device_id)
        return bool(usb_id and usb_id[0].lower() == hidpp.LOGITECH_VID)

    def _is_committing(self, device_id: Optional[str] = None) -> bool:
        with self._topology_lock:
            if device_id is None:
                return bool(self._committing_devices)
            return self._committing_devices.get(device_id, 0) > 0

    @contextmanager
    def _commit_scope(self, device_id: str):
        with self._write_lock:
            with self._topology_lock:
                self._committing_devices[device_id] = self._committing_devices.get(device_id, 0) + 1
            try:
                yield
            finally:
                with self._topology_lock:
                    remaining = self._committing_devices.get(device_id, 0) - 1
                    if remaining <= 0:
                        self._committing_devices.pop(device_id, None)
                    else:
                        self._committing_devices[device_id] = remaining

    def _hidpp_kwargs(self, device_id: str) -> Dict[str, Any]:
        with self._topology_lock:
            dev_name = self._device_names.get(device_id)
        if dev_name:
            return {"device_name": dev_name, "device_key": device_id}
        return {}

    def _resolve_active_profile(self, device_id: str) -> Tuple[Optional[int], Optional[int]]:
        """Return (0-based ratbag profile index, 16-bit HID++ profile ID)."""
        with self._topology_lock:
            usb_id = self._usb_ids.get(device_id)
            active_profile = self._active_profiles.get(device_id)
        if usb_id:
            hw_id = hidpp.get_onboard_profile(*usb_id, **self._hidpp_kwargs(device_id))
            hw_idx = hidpp.onboard_profile_index(hw_id)
            if hw_idx is not None:
                with self._topology_lock:
                    self._active_profiles[device_id] = hw_idx
                return hw_idx, hw_id
        return active_profile, None

    def _finalize_hidpp_commit(
        self,
        device_id: str,
        hidpp_profile_id: Optional[int],
        *,
        commit_verified: bool = False,
    ) -> None:
        with self._topology_lock:
            usb_id = self._usb_ids.get(device_id)
        if not usb_id or hidpp_profile_id is None:
            return
        # ratbagd commits asynchronously over hidraw; wait before sending HID++ traffic
        # so we don't collide with the flash write, then reload the active profile into RAM.
        time.sleep(0.25 if commit_verified else 1.5)
        hidpp.set_onboard_profile(*usb_id, hidpp_profile_id, **self._hidpp_kwargs(device_id))

    def _ensure_ratbagd_running(self) -> bool:
        if not self._dbus.is_bus_available():
            return False
        if self._dbus.has_name_owner(RATBAG_SERVICE):
            self._activation_failed = False
            return True
        if self._activation_failed or not self._dbus.is_service_activatable(RATBAG_SERVICE):
            return False
        try:
            self._dbus.start_service_by_name(RATBAG_SERVICE)
            self._activation_failed = False
            return True
        except DBusError as exc:
            logger.debug("On-demand D-Bus activation of %s failed: %s", RATBAG_SERVICE, exc)
            self._activation_failed = True
            return False

    def is_available(self) -> bool:
        return self._ensure_ratbagd_running()

    def get_missing_reason(self) -> str:
        if not self.is_available():
            return "libratbag / ratbagd is unavailable (sudo pacman -S libratbag && sudo systemctl enable --now ratbagd)"
        return ""

    @property
    def supports_hotplug(self) -> bool:
        return True

    def start_monitoring(self, on_change: Callable[[], None]) -> bool:
        self.stop_monitoring()
        core_ids: List[int] = []

        def _on_ratbag_signal(event: DBusSignalEvent) -> None:
            # Ignore property/resync signals emitted while our own ratbagd commit is
            # in flight so DeviceManager does not trigger a mid-commit scan_devices()
            # whose HID++ queries collide with ratbagd's async flash write over hidraw.
            if (
                event.interface in (DBUS_PROPERTIES_IFACE, RATBAG_DEVICE_IFACE)
                and self._is_committing()
            ):
                return
            on_change()

        def _on_name_owner_changed(event: DBusSignalEvent) -> None:
            if event.args and event.args[0] == RATBAG_SERVICE:
                self._activation_failed = False
                on_change()

        for sig_args in (
            (RATBAG_SERVICE, "", DBUS_PROPERTIES_IFACE, "PropertiesChanged", _on_ratbag_signal),
            (RATBAG_SERVICE, "", RATBAG_DEVICE_IFACE, "Resync", _on_ratbag_signal),
            (RATBAG_SERVICE, RATBAG_MANAGER_PATH, RATBAG_MANAGER_IFACE, "DeviceNew", _on_ratbag_signal),
            (RATBAG_SERVICE, RATBAG_MANAGER_PATH, RATBAG_MANAGER_IFACE, "DeviceRemoved", _on_ratbag_signal),
        ):
            sub_id = self._dbus.subscribe_signal(*sig_args)
            if sub_id is not None:
                core_ids.append(sub_id)
                self._subscription_ids.append(sub_id)

        name_sub_id = self._dbus.subscribe_signal(
            DBUS_SERVICE,
            DBUS_PATH,
            DBUS_IFACE,
            "NameOwnerChanged",
            _on_name_owner_changed,
        )
        if name_sub_id is not None:
            self._subscription_ids.append(name_sub_id)

        return len(core_ids) > 0

    def stop_monitoring(self) -> None:
        for sub_id in self._subscription_ids:
            self._dbus.unsubscribe_signal(sub_id)
        self._subscription_ids.clear()

    def scan_devices(self) -> List[Device]:
        if not self.is_available():
            return []

        devices: List[Device] = []
        try:
            mgr_props = self._dbus.get_all_properties(
                RATBAG_SERVICE,
                RATBAG_MANAGER_PATH,
                RATBAG_MANAGER_IFACE,
            )
            raw_paths = mgr_props.get("Devices") or []
            if not isinstance(raw_paths, (list, tuple)):
                return []

            for raw_path in raw_paths:
                dev_path = str(raw_path)
                dev_id = f"ratbag_{dev_path.rsplit('/', 1)[-1]}"
                dev = self._inspect_device(dev_id, dev_path)
                if dev:
                    devices.append(dev)

        except DBusError as exc:
            logger.warning("RatbagBackend D-Bus scan_devices failed: %s", exc)
        except Exception as exc:
            logger.warning("RatbagBackend scan_devices failed: %s", exc)

        return devices

    def _resolve_device_path(self, device_id: str) -> Optional[str]:
        with self._topology_lock:
            cached = self._device_paths.get(device_id)
        if cached:
            return cached
        if device_id.startswith("/org/freedesktop/ratbag1/"):
            with self._topology_lock:
                self._device_paths[device_id] = device_id
            return device_id

        try:
            mgr_props = self._dbus.get_all_properties(
                RATBAG_SERVICE,
                RATBAG_MANAGER_PATH,
                RATBAG_MANAGER_IFACE,
            )
            for raw_path in mgr_props.get("Devices") or []:
                path = str(raw_path)
                leaf = path.rsplit("/", 1)[-1]
                if device_id in (path, leaf, f"ratbag_{leaf}"):
                    with self._topology_lock:
                        self._device_paths[device_id] = path
                    return path
        except DBusError as exc:
            logger.debug("Could not resolve ratbag device path for %s: %s", device_id, exc)
        return None

    def _ensure_device_profiles(self, device_id: str, dev_path: str) -> Dict[int, str]:
        with self._topology_lock:
            prof_map = self._profile_paths.get(device_id)
            if prof_map:
                return dict(prof_map)

        dev_props = self._dbus.get_all_properties(RATBAG_SERVICE, dev_path, RATBAG_DEVICE_IFACE)
        prof_paths = [str(p) for p in (dev_props.get("Profiles") or [])]
        new_map: Dict[int, str] = {}
        active_fallback: Optional[int] = None
        for i, prof_path in enumerate(prof_paths):
            prof_props = self._dbus.get_all_properties(RATBAG_SERVICE, prof_path, RATBAG_PROFILE_IFACE)
            p_idx = int(prof_props["Index"]) if "Index" in prof_props else i
            new_map[p_idx] = prof_path
            if prof_props.get("IsActive") and not prof_props.get("Disabled", False):
                active_fallback = p_idx
        with self._topology_lock:
            self._profile_paths[device_id] = new_map
            if device_id not in self._active_profiles and active_fallback is not None:
                self._active_profiles[device_id] = active_fallback
        return dict(new_map)

    def _ensure_profile_topology(self, device_id: str, dev_path: str, profile_idx: int) -> None:
        prof_map = self._ensure_device_profiles(device_id, dev_path)
        prof_path = prof_map.get(profile_idx)
        if not prof_path:
            return

        with self._topology_lock:
            prof_btn_map = self._button_paths.get(device_id, {}).get(profile_idx)
            prof_res_map = self._resolution_paths.get(device_id, {}).get(profile_idx)
        if prof_btn_map is not None and prof_res_map is not None:
            return

        prof_props = self._dbus.get_all_properties(RATBAG_SERVICE, prof_path, RATBAG_PROFILE_IFACE)
        new_res_dict: Optional[Dict[int, str]] = None
        new_xy_dict: Optional[Dict[int, bool]] = None
        if prof_res_map is None:
            new_res_dict = {}
            new_xy_dict = {}
            for i, raw_r in enumerate(prof_props.get("Resolutions") or []):
                r_path = str(raw_r)
                r_props = self._dbus.get_all_properties(RATBAG_SERVICE, r_path, RATBAG_RESOLUTION_IFACE)
                r_idx = int(r_props["Index"]) if "Index" in r_props else i
                new_res_dict[r_idx] = r_path
                new_xy_dict[r_idx] = len(unpack_dbus_resolution(r_props.get("Resolution"))) == 2

        new_btn_dict: Optional[Dict[int, str]] = None
        if prof_btn_map is None:
            new_btn_dict = {}
            for i, raw_b in enumerate(prof_props.get("Buttons") or []):
                b_path = str(raw_b)
                b_props = self._dbus.get_all_properties(RATBAG_SERVICE, b_path, RATBAG_BUTTON_IFACE)
                b_idx = int(b_props["Index"]) if "Index" in b_props else i
                new_btn_dict[b_idx] = b_path

        with self._topology_lock:
            if new_res_dict is not None and new_xy_dict is not None:
                self._resolution_paths.setdefault(device_id, {})[profile_idx] = new_res_dict
                self._resolution_is_xy.setdefault(device_id, {})[profile_idx] = new_xy_dict
            if new_btn_dict is not None:
                self._button_paths.setdefault(device_id, {})[profile_idx] = new_btn_dict

    def _wait_for_commit_settled(self, profile_path: Optional[str]) -> Optional[bool]:
        """Wait for ratbagd's deferred commit to finish and check ``Profile.IsDirty``.

        Returns ``True`` when the profile is clean (``IsDirty == False``), ``False`` when
        it remained dirty after ratbagd's commit attempt, or ``None`` when ``IsDirty``
        cannot be determined (e.g. missing ``profile_path`` or non-boolean test double).
        """
        if not profile_path:
            return None

        # ratbagd schedules Commit() via sd_event_add_defer on its single-threaded loop.
        # Wait briefly so the defer enters ratbag_device_commit(); our D-Bus Get("IsDirty")
        # then blocks until the hardware flash write finishes without touching /dev/hidraw.
        time.sleep(0.05)
        for attempt in range(6):
            call_start = time.monotonic()
            try:
                try:
                    is_dirty = self._dbus.get_property(
                        RATBAG_SERVICE,
                        profile_path,
                        RATBAG_PROFILE_IFACE,
                        "IsDirty",
                        timeout=10.0,
                    )
                except TypeError:
                    is_dirty = self._dbus.get_property(
                        RATBAG_SERVICE,
                        profile_path,
                        RATBAG_PROFILE_IFACE,
                        "IsDirty",
                    )
            except DBusError as exc:
                logger.warning(
                    "Failed verifying ratbagd IsDirty on %s after Commit: %s",
                    profile_path,
                    exc,
                )
                return False

            if is_dirty is False:
                return True
            if not isinstance(is_dirty, bool):
                return None

            elapsed = time.monotonic() - call_start
            # If ratbagd blocked our D-Bus call while running ratbag_device_commit()
            # and IsDirty is still True, this commit attempt already failed.
            if elapsed >= 0.3:
                return False
            if attempt < 5:
                time.sleep(0.15)
        return False

    def _commit(
        self,
        dev_path: str,
        profile_path: Optional[str] = None,
        retries: int = 1,
    ) -> bool:
        attempts = max(1, int(retries) + 1)
        for attempt in range(attempts):
            try:
                reply = self._dbus.call_method(
                    RATBAG_SERVICE,
                    dev_path,
                    RATBAG_DEVICE_IFACE,
                    "Commit",
                )
                if reply and int(reply[0]) != 0:
                    return False
            except DBusError as exc:
                logger.warning("ratbagd Commit failed on %s: %s", dev_path, exc)
                return False

            settled = self._wait_for_commit_settled(profile_path)
            if settled is True or settled is None:
                return True

            if attempt + 1 < attempts:
                logger.warning(
                    "ratbagd async commit left %s dirty on attempt %d/%d; retrying",
                    profile_path,
                    attempt + 1,
                    attempts,
                )
                time.sleep(0.5)
            else:
                logger.warning("ratbagd async commit failed: profile %s remained dirty", profile_path)
                return False
        return False

    def _set_resolution_active(self, res_path: str) -> bool:
        reply = self._dbus.call_method(
            RATBAG_SERVICE,
            res_path,
            RATBAG_RESOLUTION_IFACE,
            "SetActive",
        )
        return not reply or int(reply[0]) == 0

    def _inspect_device(self, dev_id: str, dev_path: Optional[str] = None) -> Optional[Device]:
        try:
            resolved_path = dev_path or self._resolve_device_path(dev_id)
            if not resolved_path:
                return None

            dev_props = self._dbus.get_all_properties(RATBAG_SERVICE, resolved_path, RATBAG_DEVICE_IFACE)
            if not dev_props:
                return None

            dev_name = str(dev_props.get("Name") or "").strip() or dev_id
            vid, pid = _parse_model_usb_ids(str(dev_props.get("Model") or ""))

            raw_dtype = int(dev_props.get("DeviceType") or int(RatbagDeviceType.MOUSE))
            if raw_dtype == int(RatbagDeviceType.KEYBOARD):
                device_type = DeviceType.KEYBOARD
            elif raw_dtype == int(RatbagDeviceType.OTHER):
                device_type = DeviceType.OTHER
            else:
                device_type = DeviceType.MOUSE

            local_profile_paths: Dict[int, str] = {}
            local_res_paths: Dict[int, str] = {}
            local_res_xy: Dict[int, bool] = {}
            local_btn_paths: Dict[int, str] = {}
            local_res_map: Dict[int, int] = {}

            profiles_info: Dict[int, Dict[str, Any]] = {}
            ratbag_active_idx: Optional[int] = None
            for i, raw_p in enumerate(dev_props.get("Profiles") or []):
                p_path = str(raw_p)
                p_props = self._dbus.get_all_properties(RATBAG_SERVICE, p_path, RATBAG_PROFILE_IFACE)
                p_idx = int(p_props["Index"]) if "Index" in p_props else i
                local_profile_paths[p_idx] = p_path
                disabled = bool(p_props.get("Disabled", False))
                is_active = bool(p_props.get("IsActive", False))
                profiles_info[p_idx] = {
                    "path": p_path,
                    "disabled": disabled,
                    "is_active": is_active,
                    "resolutions": [str(r) for r in (p_props.get("Resolutions") or [])],
                    "buttons": [str(b) for b in (p_props.get("Buttons") or [])],
                }
                if is_active:
                    ratbag_active_idx = p_idx

            caps = [Capability.PROFILES]
            usb_id = (vid, pid) if (vid and pid) else None
            hidpp_kwargs = {"device_name": dev_name, "device_key": dev_id} if dev_name else {}

            # ratbagd does not track hardware onboard profile switches; prefer live HID++ profile,
            # except while a ratbagd flash commit is active for this device.
            if self._is_committing(dev_id):
                onboard_profile_id = None
                onboard_profile = None
                with self._topology_lock:
                    hw_profile_idx = self._active_profiles.get(dev_id)
            else:
                onboard_profile_id = (
                    hidpp.get_onboard_profile(vid, pid, **hidpp_kwargs)
                    if usb_id
                    else None
                )
                onboard_profile = (
                    hidpp.format_onboard_profile(onboard_profile_id)
                    if onboard_profile_id is not None
                    else None
                )
                hw_profile_idx = hidpp.onboard_profile_index(onboard_profile_id)

            selected_profile_idx: Optional[int] = None
            if (
                hw_profile_idx is not None
                and hw_profile_idx in profiles_info
                and not profiles_info[hw_profile_idx]["disabled"]
            ):
                selected_profile_idx = hw_profile_idx
            elif (
                ratbag_active_idx is not None
                and ratbag_active_idx in profiles_info
                and not profiles_info[ratbag_active_idx]["disabled"]
            ):
                selected_profile_idx = ratbag_active_idx

            status_note = ""
            dpi_info = DpiInfo()
            buttons: List[ButtonMapping] = []

            if selected_profile_idx is None:
                dpi_info.is_disabled = True
                status_note = "On-board memory profile disabled"
            else:
                caps.extend([Capability.DPI, Capability.BUTTON_REMAP])
                prof_data = profiles_info[selected_profile_idx]
                dpi_info = self._read_dpi(
                    dev_id,
                    prof_data["resolutions"],
                    profile_idx=selected_profile_idx,
                    usb_id=usb_id,
                    hidpp_kwargs=hidpp_kwargs,
                    res_paths_out=local_res_paths,
                    res_xy_out=local_res_xy,
                    res_map_out=local_res_map,
                )
                buttons = self._read_buttons(
                    dev_id,
                    prof_data["buttons"],
                    dev_name=dev_name,
                    vid=vid,
                    pid=pid,
                    profile_idx=selected_profile_idx,
                    btn_paths_out=local_btn_paths,
                )

            layout = find_device_layout(dev_name, vid, pid)
            vendor = (
                layout.vendor
                if layout is not None
                else ("Logitech" if "logitech" in dev_name.lower() or "046d" in vid else "Generic")
            )

            with self._topology_lock:
                self._device_paths[dev_id] = resolved_path
                self._profile_paths[dev_id] = local_profile_paths
                if selected_profile_idx is not None:
                    self._resolution_paths[dev_id] = {selected_profile_idx: local_res_paths}
                    self._resolution_is_xy[dev_id] = {selected_profile_idx: local_res_xy}
                    self._button_paths[dev_id] = {selected_profile_idx: local_btn_paths}
                    self._resolution_maps[dev_id] = local_res_map
                    self._active_profiles[dev_id] = selected_profile_idx
                else:
                    self._resolution_paths[dev_id] = {}
                    self._resolution_is_xy[dev_id] = {}
                    self._button_paths[dev_id] = {}
                if usb_id:
                    self._usb_ids[dev_id] = usb_id
                if dev_name:
                    self._device_names[dev_id] = dev_name

            return Device(
                id=dev_id,
                name=dev_name,
                vendor=vendor,
                device_type=device_type,
                usb_vid=vid,
                usb_pid=pid,
                capabilities=caps,
                dpi=dpi_info,
                buttons=buttons,
                onboard_profile_id=onboard_profile_id,
                onboard_profile=onboard_profile,
                status_note=status_note,
                extra_props={"dbus_path": resolved_path},
                backend_name=self.name,
            )
        except Exception as exc:
            logger.warning("Failed to inspect ratbag device %s: %s", dev_id, exc)
            return None

    def _read_dpi(
        self,
        dev_id: str,
        res_paths: List[str],
        profile_idx: int = 0,
        usb_id: Optional[Tuple[str, str]] = None,
        hidpp_kwargs: Optional[Dict[str, Any]] = None,
        res_paths_out: Optional[Dict[int, str]] = None,
        res_xy_out: Optional[Dict[int, bool]] = None,
        res_map_out: Optional[Dict[int, int]] = None,
    ) -> DpiInfo:
        info = DpiInfo()
        valid_steps: List[int] = []
        current_from_ratbag: Optional[int] = None
        res_map: Dict[int, int] = res_map_out if res_map_out is not None else {}
        supported_vals: List[int] = []

        dev_res_paths: Dict[int, str] = res_paths_out if res_paths_out is not None else {}
        dev_res_xy: Dict[int, bool] = res_xy_out if res_xy_out is not None else {}

        for i, res_path in enumerate(res_paths):
            try:
                r_props = self._dbus.get_all_properties(
                    RATBAG_SERVICE,
                    res_path,
                    RATBAG_RESOLUTION_IFACE,
                )
            except DBusError as exc:
                logger.debug("Failed to read resolution %s for %s: %s", res_path, dev_id, exc)
                continue

            r_idx = int(r_props["Index"]) if "Index" in r_props else i
            dev_res_paths[r_idx] = res_path

            res_tuple = unpack_dbus_resolution(r_props.get("Resolution"))
            dev_res_xy[r_idx] = len(res_tuple) == 2

            for raw_supported in r_props.get("Resolutions") or []:
                if isinstance(raw_supported, (int, float)) and 50 <= int(raw_supported) <= 30000:
                    supported_vals.append(int(raw_supported))

            is_disabled = bool(r_props.get("IsDisabled", False))
            is_active = bool(r_props.get("IsActive", False))
            val = res_tuple[0] if res_tuple else 0

            if not is_disabled and 50 <= val <= 30000:
                if val not in valid_steps:
                    valid_steps.append(val)
                res_map[val] = r_idx
                if is_active:
                    current_from_ratbag = val

        if res_paths_out is None or res_xy_out is None or res_map_out is None:
            with self._topology_lock:
                if res_paths_out is None:
                    self._resolution_paths.setdefault(dev_id, {})[profile_idx] = dev_res_paths
                if res_xy_out is None:
                    self._resolution_is_xy.setdefault(dev_id, {})[profile_idx] = dev_res_xy
                if res_map_out is None:
                    self._resolution_maps[dev_id] = res_map

        if current_from_ratbag is not None:
            info.current = current_from_ratbag

        # ratbagd's value is stale when profile commits fail; the device itself is authoritative.
        if usb_id is None:
            with self._topology_lock:
                usb_id = self._usb_ids.get(dev_id)
        if usb_id and not self._is_committing(dev_id):
            kw = hidpp_kwargs if hidpp_kwargs is not None else self._hidpp_kwargs(dev_id)
            hw_dpi = hidpp.get_dpi(*usb_id, **kw)
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
        info.steps = sorted(steps_set)
        if supported_vals:
            info.min_dpi = min(supported_vals)
            info.max_dpi = max(supported_vals)
        return info

    def _read_buttons(
        self,
        dev_id: str,
        btn_paths: List[str],
        dev_name: str = "",
        vid: str = "",
        pid: str = "",
        profile_idx: int = 0,
        btn_paths_out: Optional[Dict[int, str]] = None,
    ) -> List[ButtonMapping]:
        buttons: List[ButtonMapping] = []
        dev_btn_paths: Dict[int, str] = btn_paths_out if btn_paths_out is not None else {}

        parsed_entries: List[Tuple[int, str, str]] = []
        for i, btn_path in enumerate(btn_paths):
            try:
                b_props = self._dbus.get_all_properties(
                    RATBAG_SERVICE,
                    btn_path,
                    RATBAG_BUTTON_IFACE,
                )
            except DBusError as exc:
                logger.debug("Failed to read button %s for %s: %s", btn_path, dev_id, exc)
                continue

            b_idx = int(b_props["Index"]) if "Index" in b_props else i
            dev_btn_paths[b_idx] = btn_path
            act_val, act_disp = decode_dbus_button_mapping(b_props.get("Mapping"))
            # If Button 0 (Left Click) is unmapped or unknown, keep Left Click safe
            if b_idx == 0 and act_val == "unknown":
                act_val, act_disp = "button 1", "Left Click"
            parsed_entries.append((b_idx, act_val, act_disp))

        if btn_paths_out is None:
            with self._topology_lock:
                self._button_paths.setdefault(dev_id, {})[profile_idx] = dev_btn_paths

        total_buttons = len(btn_paths) if btn_paths else len(parsed_entries)
        for b_idx, act_val, act_disp in sorted(parsed_entries, key=lambda item: item[0]):
            meta = get_button_metadata(dev_name, vid, pid, b_idx, act_val, total_buttons)
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
        return buttons

    def set_dpi(self, device_id: str, dpi: int) -> bool:
        with self._topology_lock:
            usb_id = self._usb_ids.get(device_id)
        if usb_id and hidpp.set_dpi(*usb_id, dpi, **self._hidpp_kwargs(device_id)):
            return True
        if not self.is_available():
            return False

        try:
            with self._commit_scope(device_id):
                dev_path = self._resolve_device_path(device_id)
                if not dev_path:
                    return False

                profile_idx, _hidpp_prof_id = self._resolve_active_profile(device_id)
                if profile_idx is None:
                    prof_map = self._ensure_device_profiles(device_id, dev_path)
                    with self._topology_lock:
                        profile_idx = self._active_profiles.get(device_id)
                    if profile_idx is None and prof_map:
                        profile_idx = sorted(prof_map.keys())[0]
                if profile_idx is None:
                    return False

                self._ensure_profile_topology(device_id, dev_path, profile_idx)
                with self._topology_lock:
                    prof_path = self._profile_paths.get(device_id, {}).get(profile_idx)
                    prof_res_paths = dict(self._resolution_paths.get(device_id, {}).get(profile_idx, {}))
                    prof_res_xy = dict(self._resolution_is_xy.get(device_id, {}).get(profile_idx, {}))
                    res_map = dict(self._resolution_maps.get(device_id, {}))

                # If the device has an existing resolution slot with this DPI, switch active resolution directly.
                if dpi in res_map:
                    slot_idx = res_map[dpi]
                    slot_path = prof_res_paths.get(slot_idx)
                    if slot_path:
                        try:
                            if self._set_resolution_active(slot_path) and self._commit(dev_path, profile_path=prof_path):
                                return True
                        except DBusError as exc:
                            logger.debug(
                                "ratbagd SetActive on slot %s failed for %s: %s",
                                slot_idx,
                                device_id,
                                exc,
                            )

                if not prof_res_paths:
                    return False

                active_slot: Optional[int] = None
                for r_idx, r_path in sorted(prof_res_paths.items()):
                    try:
                        if bool(
                            self._dbus.get_property(
                                RATBAG_SERVICE,
                                r_path,
                                RATBAG_RESOLUTION_IFACE,
                                "IsActive",
                            )
                        ):
                            active_slot = r_idx
                            break
                    except DBusError:
                        continue

                if active_slot is None:
                    first_slot = sorted(prof_res_paths.keys())[0]
                    try:
                        self._set_resolution_active(prof_res_paths[first_slot])
                    except DBusError as exc:
                        logger.debug("Could not activate fallback resolution 0 for %s: %s", device_id, exc)
                    active_slot = first_slot

                target_path = prof_res_paths[active_slot]
                is_xy = prof_res_xy.get(active_slot, False)
                res_variant = ("(uu)", (int(dpi), int(dpi))) if is_xy else ("u", int(dpi))

                try:
                    self._dbus.set_property(
                        RATBAG_SERVICE,
                        target_path,
                        RATBAG_RESOLUTION_IFACE,
                        "Resolution",
                        "v",
                        res_variant,
                    )
                    return self._commit(dev_path, profile_path=prof_path)
                except DBusCallError as exc:
                    logger.debug(
                        "ratbagd set Resolution %d failed for %s (%s); attempting active-slot recovery",
                        dpi,
                        device_id,
                        exc,
                    )
                    first_slot = sorted(prof_res_paths.keys())[0]
                    fallback_path = prof_res_paths[first_slot]
                    self._set_resolution_active(fallback_path)
                    fallback_xy = prof_res_xy.get(first_slot, False)
                    fallback_variant = ("(uu)", (int(dpi), int(dpi))) if fallback_xy else ("u", int(dpi))
                    self._dbus.set_property(
                        RATBAG_SERVICE,
                        fallback_path,
                        RATBAG_RESOLUTION_IFACE,
                        "Resolution",
                        "v",
                        fallback_variant,
                    )
                    return self._commit(dev_path, profile_path=prof_path)

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
            encoded = encode_dbus_button_mapping(
                action,
                prefer_macro_for_keys=self._is_logitech_device(device_id),
            )
        except ValueError as exc:
            logger.warning("Invalid button action for %s button %d: %s", device_id, button_idx, exc)
            return False

        try:
            with self._commit_scope(device_id):
                dev_path = self._resolve_device_path(device_id)
                if not dev_path:
                    return False

                profile_idx, hidpp_profile_id = self._resolve_active_profile(device_id)
                if profile_idx is None:
                    prof_map = self._ensure_device_profiles(device_id, dev_path)
                    with self._topology_lock:
                        profile_idx = self._active_profiles.get(device_id)
                    if profile_idx is None and prof_map:
                        profile_idx = sorted(prof_map.keys())[0]
                if profile_idx is None:
                    return False

                self._ensure_profile_topology(device_id, dev_path, profile_idx)
                with self._topology_lock:
                    prof_path = self._profile_paths.get(device_id, {}).get(profile_idx)
                    btn_path = self._button_paths.get(device_id, {}).get(profile_idx, {}).get(button_idx)
                if not btn_path:
                    logger.warning("No ratbag button path found for %s profile %d button %d", device_id, profile_idx, button_idx)
                    return False

                self._dbus.set_property(
                    RATBAG_SERVICE,
                    btn_path,
                    RATBAG_BUTTON_IFACE,
                    "Mapping",
                    "(uv)",
                    encoded,
                )
                if not self._commit(dev_path, profile_path=prof_path):
                    return False
                self._finalize_hidpp_commit(
                    device_id,
                    hidpp_profile_id,
                    commit_verified=bool(prof_path),
                )
                return True
        except Exception as exc:
            logger.warning("Failed to remap button %d on %s: %s", button_idx, device_id, exc)
            return False

    def batch_remap_buttons(
        self,
        device_id: str,
        buttons: Dict[int, str],
        profile_idx: Optional[int] = None,
    ) -> bool:
        if not self.is_available() or not buttons:
            return False
        try:
            prefer_macro = self._is_logitech_device(device_id)
            valid_items: List[Tuple[int, Tuple[int, Tuple[str, Any]]]] = []
            for idx, act in buttons.items():
                if not act or act.strip().lower() in ("unknown", "standard / unbekannt", "default / unknown"):
                    continue
                if idx == 0 and act.strip().lower() in ("disabled", "none"):
                    continue
                try:
                    valid_items.append(
                        (idx, encode_dbus_button_mapping(act, prefer_macro_for_keys=prefer_macro))
                    )
                except ValueError as exc:
                    logger.debug("Skipping invalid batch action for button %d on %s: %s", idx, device_id, exc)

            if not valid_items:
                return True

            with self._commit_scope(device_id):
                dev_path = self._resolve_device_path(device_id)
                if not dev_path:
                    return False

                if profile_idx is None:
                    target_profile_idx, hidpp_profile_id = self._resolve_active_profile(device_id)
                    if target_profile_idx is None:
                        prof_map = self._ensure_device_profiles(device_id, dev_path)
                        with self._topology_lock:
                            target_profile_idx = self._active_profiles.get(device_id)
                        if target_profile_idx is None and prof_map:
                            target_profile_idx = sorted(prof_map.keys())[0]
                else:
                    target_profile_idx = profile_idx
                    hidpp_profile_id = None

                if target_profile_idx is None:
                    return False

                self._ensure_profile_topology(device_id, dev_path, target_profile_idx)
                with self._topology_lock:
                    prof_path = self._profile_paths.get(device_id, {}).get(target_profile_idx)
                    btn_paths = dict(self._button_paths.get(device_id, {}).get(target_profile_idx, {}))

                written = 0
                for idx, encoded in valid_items:
                    btn_path = btn_paths.get(idx)
                    if not btn_path:
                        logger.debug("Missing button path for %s profile %d button %d", device_id, target_profile_idx, idx)
                        continue
                    self._dbus.set_property(
                        RATBAG_SERVICE,
                        btn_path,
                        RATBAG_BUTTON_IFACE,
                        "Mapping",
                        "(uv)",
                        encoded,
                    )
                    written += 1

                if written == 0:
                    return False

                ok = self._commit(dev_path, profile_path=prof_path)
                if ok and hidpp_profile_id is not None:
                    self._finalize_hidpp_commit(
                        device_id,
                        hidpp_profile_id,
                        commit_verified=bool(prof_path),
                    )
                return ok
        except Exception as exc:
            logger.warning("Failed batch remap on %s: %s", device_id, exc)
            return False

    def reset_defaults(self, device_id: str) -> bool:
        if not self.is_available():
            return False
        try:
            with self._commit_scope(device_id):
                dev_path = self._resolve_device_path(device_id)
                if not dev_path:
                    return False

                prof_map = self._ensure_device_profiles(device_id, dev_path)
                if 1 in prof_map:
                    try:
                        self._dbus.set_property(
                            RATBAG_SERVICE,
                            prof_map[1],
                            RATBAG_PROFILE_IFACE,
                            "Disabled",
                            "b",
                            False,
                        )
                        self._commit(dev_path, profile_path=prof_map[1])
                    except DBusError as exc:
                        logger.debug("Could not enable profile 1 on %s during reset: %s", device_id, exc)

                dev = self._inspect_device(device_id, dev_path)
                with self._topology_lock:
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
                with self._topology_lock:
                    has_prof_0 = 0 in self._profile_paths.get(device_id, {})
                    active_prof = self._active_profiles.get(device_id)
                if has_prof_0 and active_prof != 0:
                    self.batch_remap_buttons(device_id, defaults, profile_idx=0)

                target_dpi = 1600 if (dev and dev.dpi and 1600 in dev.dpi.steps) else 800
                self.set_dpi(device_id, target_dpi)
                return True
        except Exception as exc:
            logger.warning("Failed resetting defaults on %s: %s", device_id, exc)
            return False
