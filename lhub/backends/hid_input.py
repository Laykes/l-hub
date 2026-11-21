"""Read-only raw USB HID input monitor for mouse button identification.

Listens directly on the target device's /dev/hidraw* interfaces (matched by USB VID:PID)
using each interface's kernel HID report descriptor. This allows identifying custom button
binds — including media keys (Play/Pause, Volume, Mute), system shortcuts (Super, Alt+Tab,
PrintScreen), multi-key macros, and layout-independent keys — even when the desktop
environment intercepts them before Qt receives a window event.
"""

from dataclasses import dataclass, field
import glob
import logging
import os
import re
import select
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

from .hidpp import (
    LOGITECH_VID,
    _is_generic_receiver_name,
    _name_match_score,
    _parse_uevent_lines,
    is_receiver_pid,
)
from .ratbag import ACTION_DISPLAY_NAMES, KEY_DISPLAY_NAMES, format_key_combo

logger = logging.getLogger(__name__)


MODIFIER_HOLD_TIMEOUT = 0.35

# Standard USB HID Usage Page 0x07 (Keyboard/Keypad) -> Linux KEY_* name
HID_KEYBOARD_TO_LINUX: Dict[int, str] = {
    0x28: "KEY_ENTER",
    0x29: "KEY_ESC",
    0x2A: "KEY_BACKSPACE",
    0x2B: "KEY_TAB",
    0x2C: "KEY_SPACE",
    0x2D: "KEY_MINUS",
    0x2E: "KEY_EQUAL",
    0x2F: "KEY_LEFTBRACE",
    0x30: "KEY_RIGHTBRACE",
    0x31: "KEY_BACKSLASH",
    0x32: "KEY_BACKSLASH",
    0x33: "KEY_SEMICOLON",
    0x34: "KEY_APOSTROPHE",
    0x35: "KEY_GRAVE",
    0x36: "KEY_COMMA",
    0x37: "KEY_DOT",
    0x38: "KEY_SLASH",
    0x39: "KEY_CAPSLOCK",
    0x46: "KEY_SYSRQ",
    0x47: "KEY_SCROLLLOCK",
    0x48: "KEY_PAUSE",
    0x49: "KEY_INSERT",
    0x4A: "KEY_HOME",
    0x4B: "KEY_PAGEUP",
    0x4C: "KEY_DELETE",
    0x4D: "KEY_END",
    0x4E: "KEY_PAGEDOWN",
    0x4F: "KEY_RIGHT",
    0x50: "KEY_LEFT",
    0x51: "KEY_DOWN",
    0x52: "KEY_UP",
    0x53: "KEY_NUMLOCK",
    0x54: "KEY_KPSLASH",
    0x55: "KEY_KPASTERISK",
    0x56: "KEY_KPMINUS",
    0x57: "KEY_KPPLUS",
    0x58: "KEY_KPENTER",
    0x62: "KEY_KP0",
    0x63: "KEY_KPDOT",
    0x64: "KEY_102ND",
    0x65: "KEY_COMPOSE",
    0x67: "KEY_KPEQUAL",
    0x7F: "KEY_MUTE",
    0x80: "KEY_VOLUMEUP",
    0x81: "KEY_VOLUMEDOWN",
    0xE0: "KEY_LEFTCTRL",
    0xE1: "KEY_LEFTSHIFT",
    0xE2: "KEY_LEFTALT",
    0xE3: "KEY_LEFTMETA",
    0xE4: "KEY_RIGHTCTRL",
    0xE5: "KEY_RIGHTSHIFT",
    0xE6: "KEY_RIGHTALT",
    0xE7: "KEY_RIGHTMETA",
}
for _i in range(26):
    HID_KEYBOARD_TO_LINUX[0x04 + _i] = f"KEY_{chr(ord('A') + _i)}"
for _i in range(9):
    HID_KEYBOARD_TO_LINUX[0x1E + _i] = f"KEY_{_i + 1}"
HID_KEYBOARD_TO_LINUX[0x27] = "KEY_0"
for _i in range(12):
    HID_KEYBOARD_TO_LINUX[0x3A + _i] = f"KEY_F{_i + 1}"
for _i in range(12):
    HID_KEYBOARD_TO_LINUX[0x68 + _i] = f"KEY_F{_i + 13}"
for _i in range(9):
    HID_KEYBOARD_TO_LINUX[0x59 + _i] = f"KEY_KP{_i + 1}"

# Standard USB HID Usage Page 0x0C (Consumer Control) -> Linux KEY_* name
HID_CONSUMER_TO_LINUX: Dict[int, str] = {
    0x00B5: "KEY_NEXTSONG",
    0x00B6: "KEY_PREVIOUSSONG",
    0x00B7: "KEY_STOPCD",
    0x00CD: "KEY_PLAYPAUSE",
    0x00E2: "KEY_MUTE",
    0x00E9: "KEY_VOLUMEUP",
    0x00EA: "KEY_VOLUMEDOWN",
    0x0183: "KEY_CONFIG",
    0x018A: "KEY_MAIL",
    0x0192: "KEY_CALC",
    0x0194: "KEY_FILE",
    0x0208: "KEY_PRINT",
    0x0221: "KEY_SEARCH",
    0x0223: "KEY_HOMEPAGE",
    0x0224: "KEY_BACK",
    0x0225: "KEY_FORWARD",
    0x0226: "KEY_STOP",
    0x0227: "KEY_REFRESH",
}

_MOUSE_BUTTON_NAMES: Dict[int, str] = {
    1: "Left Click (Button 1)",
    2: "Right Click (Button 2)",
    3: "Middle Click (Button 3)",
    4: "Back (Button 4)",
    5: "Forward (Button 5)",
}


@dataclass
class ReportLayout:
    report_id: int
    # (bit_offset, button_number)
    mouse_buttons: List[Tuple[int, int]] = field(default_factory=list)
    # (bit_offset, bit_size, is_signed)
    hwheel: Optional[Tuple[int, int, bool]] = None
    # (bit_offset, hid_usage)
    kb_mod_bits: List[Tuple[int, int]] = field(default_factory=list)
    kb_key_bits: List[Tuple[int, int]] = field(default_factory=list)
    # (bit_offset, bit_size, count, logical_min, usage_min)
    kb_key_arrays: List[Tuple[int, int, int, int, int]] = field(default_factory=list)
    # (bit_offset, hid_consumer_usage)
    consumer_bits: List[Tuple[int, int]] = field(default_factory=list)
    # (bit_offset, bit_size, count, logical_min, usage_min)
    consumer_arrays: List[Tuple[int, int, int, int, int]] = field(default_factory=list)

    @property
    def has_inputs(self) -> bool:
        return bool(
            self.mouse_buttons
            or self.hwheel is not None
            or self.kb_mod_bits
            or self.kb_key_bits
            or self.kb_key_arrays
            or self.consumer_bits
            or self.consumer_arrays
        )


def _signed_int(raw: bytes) -> int:
    if not raw:
        return 0
    return int.from_bytes(raw, "little", signed=True)


def _unsigned_int(raw: bytes) -> int:
    if not raw:
        return 0
    return int.from_bytes(raw, "little", signed=False)


def _extract_bits(data: bytes, bit_offset: int, bit_size: int, signed: bool = False) -> int:
    if bit_size <= 0:
        return 0
    byte_idx = bit_offset // 8
    bit_shift = bit_offset % 8
    end_byte = (bit_offset + bit_size + 7) // 8
    if end_byte > len(data):
        return 0
    val = int.from_bytes(data[byte_idx:end_byte], "little")
    val = (val >> bit_shift) & ((1 << bit_size) - 1)
    if signed and (val & (1 << (bit_size - 1))):
        val -= 1 << bit_size
    return val


def inspect_report_descriptor(desc: bytes) -> Tuple[Dict[int, ReportLayout], Set[Tuple[int, int]]]:
    """Parse a USB HID report descriptor into input ReportLayouts and top-level Application Collections."""
    layouts: Dict[int, ReportLayout] = {}
    bit_offsets: Dict[int, int] = {}
    top_level_collections: Set[Tuple[int, int]] = set()
    collection_is_vendor: List[bool] = []

    global_state = {
        "usage_page": 0,
        "logical_min": 0,
        "logical_max": 0,
        "report_size": 0,
        "report_id": 0,
        "report_count": 0,
    }
    stack: List[Dict[str, int]] = []
    local_usages: List[Tuple[int, int]] = []  # (usage_page, usage_id)
    usage_min: Optional[Tuple[int, int]] = None
    usage_max: Optional[Tuple[int, int]] = None

    i = 0
    n = len(desc)
    while i < n:
        header = desc[i]
        i += 1
        if header == 0xFE:  # Long item
            if i >= n:
                break
            data_len = desc[i]
            i += 2 + data_len
            continue

        size_code = header & 0x03
        size = 4 if size_code == 3 else size_code
        item_type = (header >> 2) & 0x03
        tag = (header >> 4) & 0x0F
        if i + size > n:
            break
        raw = desc[i : i + size]
        i += size

        if item_type == 1:  # Global
            if tag == 0:
                global_state["usage_page"] = _unsigned_int(raw)
            elif tag == 1:
                global_state["logical_min"] = _signed_int(raw)
            elif tag == 2:
                global_state["logical_max"] = _signed_int(raw)
            elif tag == 7:
                global_state["report_size"] = _unsigned_int(raw)
            elif tag == 8:
                global_state["report_id"] = _unsigned_int(raw)
            elif tag == 9:
                global_state["report_count"] = _unsigned_int(raw)
            elif tag == 10:  # Push
                stack.append(dict(global_state))
            elif tag == 11 and stack:  # Pop
                global_state = stack.pop()
        elif item_type == 2:  # Local
            val = _unsigned_int(raw)
            if size == 4:
                upage = (val >> 16) & 0xFFFF
                uid = val & 0xFFFF
            else:
                upage = global_state["usage_page"]
                uid = val
            if tag == 0:
                local_usages.append((upage, uid))
            elif tag == 1:
                usage_min = (upage, uid)
            elif tag == 2:
                usage_max = (upage, uid)
        elif item_type == 0:  # Main
            if tag == 10:  # Collection
                coll_type = _unsigned_int(raw) if raw else 0
                if local_usages:
                    coll_up, coll_uid = local_usages[-1]
                elif usage_min is not None:
                    coll_up, coll_uid = usage_min
                else:
                    coll_up, coll_uid = global_state["usage_page"], 0
                if not collection_is_vendor and coll_type == 0x01:
                    top_level_collections.add((coll_up, coll_uid))
                in_vendor_parent = collection_is_vendor[-1] if collection_is_vendor else False
                collection_is_vendor.append(in_vendor_parent or coll_up >= 0xFF00)
            elif tag == 12:  # End Collection
                if collection_is_vendor:
                    collection_is_vendor.pop()
            elif tag == 8:  # Input
                flags = _unsigned_int(raw)
                is_const = bool(flags & 0x01)
                is_var = bool(flags & 0x02)
                report_id = global_state["report_id"]
                report_size = global_state["report_size"]
                report_count = global_state["report_count"]
                usage_page = global_state["usage_page"]
                logical_min = global_state["logical_min"]

                if report_id not in bit_offsets:
                    bit_offsets[report_id] = 8 if report_id != 0 else 0
                start_bit = bit_offsets[report_id]
                bit_offsets[report_id] = start_bit + report_size * report_count

                in_vendor = any(collection_is_vendor) or usage_page >= 0xFF00
                if not in_vendor and not is_const and report_size > 0 and report_count > 0:
                    layout = layouts.setdefault(report_id, ReportLayout(report_id=report_id))

                    resolved: List[Tuple[int, int]] = []
                    if local_usages:
                        resolved = list(local_usages)
                        while len(resolved) < report_count:
                            resolved.append(resolved[-1])
                    elif usage_min is not None and usage_max is not None and usage_max[1] >= usage_min[1]:
                        up = usage_min[0]
                        count_range = min(report_count, usage_max[1] - usage_min[1] + 1)
                        resolved = [(up, usage_min[1] + idx) for idx in range(count_range)]

                    if is_var:
                        for idx, (up, uid) in enumerate(resolved[:report_count]):
                            bit_pos = start_bit + idx * report_size
                            if up == 0x09 and report_size == 1 and 1 <= uid <= 32:
                                layout.mouse_buttons.append((bit_pos, uid))
                            elif up == 0x0C and uid == 0x0238 and report_size >= 2:
                                layout.hwheel = (bit_pos, report_size, logical_min < 0)
                            elif up == 0x0C and report_size == 1 and uid in HID_CONSUMER_TO_LINUX:
                                layout.consumer_bits.append((bit_pos, uid))
                            elif up == 0x07 and report_size == 1:
                                if 0xE0 <= uid <= 0xE7:
                                    layout.kb_mod_bits.append((bit_pos, uid))
                                elif uid in HID_KEYBOARD_TO_LINUX:
                                    layout.kb_key_bits.append((bit_pos, uid))
                    else:
                        u_min_val = usage_min[1] if usage_min is not None else 0
                        if usage_page == 0x07 and report_size in (8, 16):
                            layout.kb_key_arrays.append(
                                (start_bit, report_size, report_count, logical_min, u_min_val)
                            )
                        elif usage_page == 0x0C and report_size in (8, 16):
                            layout.consumer_arrays.append(
                                (start_bit, report_size, report_count, logical_min, u_min_val)
                            )

            # Local items are cleared after every Main item.
            local_usages.clear()
            usage_min = None
            usage_max = None

    filtered_layouts = {rid: lay for rid, lay in layouts.items() if lay.has_inputs}
    return filtered_layouts, top_level_collections


def parse_report_descriptor(desc: bytes) -> Dict[int, ReportLayout]:
    """Parse a USB HID report descriptor and return input ReportLayouts by report ID."""
    layouts, _ = inspect_report_descriptor(desc)
    return layouts


class HidReportTracker:
    """Stateful decoder turning raw HID reports from one interface into button/key actions."""

    def __init__(self, layouts: Dict[int, ReportLayout]):
        self._layouts = layouts
        self._has_report_ids = 0 not in layouts
        self._prev_buttons: Dict[int, Set[int]] = {}
        self._prev_consumer: Dict[int, Set[int]] = {}
        self._prev_kb_mods: Dict[int, Set[str]] = {}
        self._prev_kb_keys: Dict[int, Set[str]] = {}
        self._pending_mods: List[str] = []
        self._pending_mod_since: Optional[float] = None

    @property
    def has_pending_modifier(self) -> bool:
        return bool(self._pending_mods) and self._pending_mod_since is not None

    def pending_timeout(self, now: Optional[float] = None) -> Optional[float]:
        if not self.has_pending_modifier or self._pending_mod_since is None:
            return None
        cur = time.monotonic() if now is None else now
        return max(0.0, MODIFIER_HOLD_TIMEOUT - (cur - self._pending_mod_since))

    def poll_pending(self, now: Optional[float] = None) -> Optional[Tuple[str, str]]:
        if not self.has_pending_modifier or self._pending_mod_since is None:
            return None
        cur = time.monotonic() if now is None else now
        if cur - self._pending_mod_since >= MODIFIER_HOLD_TIMEOUT:
            mods = list(self._pending_mods)
            self._pending_mods.clear()
            self._pending_mod_since = None
            act, disp = format_key_combo(mods, None)
            return (act, disp) if act else None
        return None

    def process_report(self, data: bytes, now: Optional[float] = None) -> Optional[Tuple[str, str]]:
        if not data:
            return None
        if self._has_report_ids:
            rid = data[0]
            layout = self._layouts.get(rid)
        else:
            rid = 0
            layout = self._layouts.get(0)
        if layout is None:
            return None

        cur_time = time.monotonic() if now is None else now

        # 1. Mouse buttons (rising edge)
        if layout.mouse_buttons:
            cur_btns = {
                btn_num
                for bit_pos, btn_num in layout.mouse_buttons
                if _extract_bits(data, bit_pos, 1)
            }
            prev_btns = self._prev_buttons.get(rid, set())
            newly_pressed = cur_btns - prev_btns
            self._prev_buttons[rid] = cur_btns
            if newly_pressed:
                btn_num = min(newly_pressed)
                act = f"button {btn_num}"
                disp = _MOUSE_BUTTON_NAMES.get(btn_num, ACTION_DISPLAY_NAMES.get(act, f"Button {btn_num}"))
                return act, disp

        # 2. Horizontal wheel / AC Pan
        if layout.hwheel is not None:
            bit_pos, bit_size, is_signed = layout.hwheel
            delta = _extract_bits(data, bit_pos, bit_size, signed=is_signed)
            if delta < 0:
                return "special wheel-left", "Scroll Wheel Left"
            if delta > 0:
                return "special wheel-right", "Scroll Wheel Right"

        # 3. Consumer Control (media keys, etc.)
        if layout.consumer_bits or layout.consumer_arrays:
            cur_consumer: Set[int] = set()
            for bit_pos, uid in layout.consumer_bits:
                if _extract_bits(data, bit_pos, 1):
                    cur_consumer.add(uid)
            for start_bit, bit_size, count, logical_min, u_min in layout.consumer_arrays:
                for idx in range(count):
                    val = _extract_bits(data, start_bit + idx * bit_size, bit_size)
                    if val != 0 and val >= logical_min:
                        usage = (val - logical_min) + u_min if u_min else val
                        if usage in HID_CONSUMER_TO_LINUX:
                            cur_consumer.add(usage)

            prev_consumer = self._prev_consumer.get(rid, set())
            new_consumer = cur_consumer - prev_consumer
            self._prev_consumer[rid] = cur_consumer
            if new_consumer:
                usage = min(new_consumer)
                linux_key = HID_CONSUMER_TO_LINUX[usage]
                disp = KEY_DISPLAY_NAMES.get(linux_key, linux_key.replace("KEY_", ""))
                return f"key {linux_key}", f"Key: {disp}"

        # 4. Keyboard modifiers & keys
        if layout.kb_mod_bits or layout.kb_key_bits or layout.kb_key_arrays:
            cur_mods: List[str] = []
            for bit_pos, uid in layout.kb_mod_bits:
                if _extract_bits(data, bit_pos, 1):
                    linux_key = HID_KEYBOARD_TO_LINUX.get(uid)
                    if linux_key and linux_key not in cur_mods:
                        cur_mods.append(linux_key)

            cur_keys: List[str] = []
            for bit_pos, uid in layout.kb_key_bits:
                if _extract_bits(data, bit_pos, 1):
                    linux_key = HID_KEYBOARD_TO_LINUX.get(uid)
                    if linux_key and linux_key not in cur_keys:
                        cur_keys.append(linux_key)

            for start_bit, bit_size, count, logical_min, u_min in layout.kb_key_arrays:
                for idx in range(count):
                    val = _extract_bits(data, start_bit + idx * bit_size, bit_size)
                    if val <= 0x03 or val < logical_min:
                        continue
                    usage = (val - logical_min) + u_min if u_min else val
                    linux_key = HID_KEYBOARD_TO_LINUX.get(usage)
                    if linux_key and linux_key not in cur_keys:
                        cur_keys.append(linux_key)

            prev_mods = self._prev_kb_mods.get(rid, set())
            prev_keys = self._prev_kb_keys.get(rid, set())
            new_keys = [k for k in cur_keys if k not in prev_keys]
            new_mods = [m for m in cur_mods if m not in prev_mods]
            self._prev_kb_mods[rid] = set(cur_mods)
            self._prev_kb_keys[rid] = set(cur_keys)

            if new_keys:
                # Non-modifier key pressed (possibly with active modifiers -> macro!)
                mods_for_combo = cur_mods if cur_mods else self._pending_mods
                self._pending_mods.clear()
                self._pending_mod_since = None
                act, disp = format_key_combo(mods_for_combo, new_keys[0])
                return (act, disp) if act else None

            if new_mods and not cur_keys:
                # Modifier pressed alone — wait briefly in case a macro key follows.
                for m in cur_mods:
                    if m not in self._pending_mods:
                        self._pending_mods.append(m)
                if self._pending_mod_since is None:
                    self._pending_mod_since = cur_time
                return None

            if not cur_mods and not cur_keys and self._pending_mods:
                # Standalone modifier(s) released without a main key.
                mods = list(self._pending_mods)
                self._pending_mods.clear()
                self._pending_mod_since = None
                act, disp = format_key_combo(mods, None)
                return (act, disp) if act else None

        return None


_DJ_RECEIVER_DRIVERS = frozenset({"logitech-djreceiver"})
_DJ_DEVICE_DRIVERS = frozenset({"logitech-hidpp-device", "logitech-djdevice"})


def _extract_dj_slot(phys: str) -> Optional[int]:
    m = re.search(r":([1-6])\s*$", phys or "")
    return int(m.group(1)) if m else None


def _uevent_vid_pid(uevent: Dict[str, str]) -> Tuple[str, str]:
    hid_id = uevent.get("HID_ID", "")
    parts = hid_id.split(":")
    if len(parts) < 3:
        return "", ""
    return parts[1][-4:].lower(), parts[2][-4:].lower()


def _phys_bus_prefix(phys: str) -> str:
    if not phys:
        return ""
    base = re.sub(r":[1-6]\s*$", "", phys.strip())
    return base.split("/input", 1)[0]


@dataclass
class _HidrawCandidate:
    path: str
    layouts: Dict[int, ReportLayout]
    collections: Set[Tuple[int, int]]
    is_direct: bool
    is_paired_child: bool
    dj_slot: Optional[int]
    hid_name: str
    hid_phys: str
    order: int


def _candidate_sort_key(cand: _HidrawCandidate) -> Tuple[int, int]:
    has_mouse = (0x01, 0x02) in cand.collections or any(
        lay.mouse_buttons or lay.hwheel is not None for lay in cand.layouts.values()
    )
    return (0 if has_mouse else 1, cand.order)


def _matching_hidraw_nodes(
    vid: str,
    pid: str,
    *,
    device_name: Optional[str] = None,
    device_index: Optional[int] = None,
) -> List[Tuple[str, Dict[int, ReportLayout]]]:
    if not vid or not pid:
        return []
    vid_l = vid.strip().lower()
    pid_l = pid.strip().lower()
    wanted = f"{vid_l.upper().zfill(8)}:{pid_l.upper().zfill(8)}"
    receiver_mode = is_receiver_pid(vid_l, pid_l)
    specific_name = bool(device_name and not _is_generic_receiver_name(device_name))

    candidates: List[_HidrawCandidate] = []
    receiver_phys_prefixes: Set[str] = set()

    for order, sys_node in enumerate(sorted(glob.glob("/sys/class/hidraw/hidraw*"))):
        try:
            with open(f"{sys_node}/device/uevent", "r", encoding="utf-8", errors="ignore") as f:
                uevent_text = f.read()
        except OSError as exc:
            logger.debug("Skipping %s while discovering hidraw nodes: %s", sys_node, exc)
            continue

        uevent = _parse_uevent_lines(uevent_text)
        driver = uevent.get("DRIVER", "").strip().lower()
        hid_phys = uevent.get("HID_PHYS", "")
        is_direct = wanted in uevent_text.upper()

        if is_direct and receiver_mode:
            prefix = _phys_bus_prefix(hid_phys)
            if prefix:
                receiver_phys_prefixes.add(prefix)

        if driver in _DJ_RECEIVER_DRIVERS:
            continue

        dj_slot = _extract_dj_slot(hid_phys)
        node_vid, _ = _uevent_vid_pid(uevent)
        is_paired_child = (
            receiver_mode
            and (node_vid == LOGITECH_VID or f"{vid_l.upper().zfill(8)}:" in uevent_text.upper())
            and (driver in _DJ_DEVICE_DRIVERS or dj_slot is not None)
        )
        if not is_direct and not is_paired_child:
            continue

        try:
            with open(f"{sys_node}/device/report_descriptor", "rb") as f:
                desc = f.read()
        except OSError as exc:
            logger.debug("Skipping %s while reading report descriptor: %s", sys_node, exc)
            continue

        layouts, collections = inspect_report_descriptor(desc)
        if not layouts:
            continue

        candidates.append(
            _HidrawCandidate(
                path=f"/dev/{os.path.basename(sys_node)}",
                layouts=layouts,
                collections=collections,
                is_direct=is_direct,
                is_paired_child=is_paired_child,
                dj_slot=dj_slot,
                hid_name=uevent.get("HID_NAME", ""),
                hid_phys=hid_phys,
                order=order,
            )
        )

    if not candidates:
        return []

    if receiver_mode:
        paired = [c for c in candidates if c.is_paired_child]
        direct = [c for c in candidates if c.is_direct]
        if receiver_phys_prefixes and paired:
            bus_matched = [c for c in paired if _phys_bus_prefix(c.hid_phys) in receiver_phys_prefixes]
            if bus_matched:
                paired = bus_matched

        selected: Optional[List[_HidrawCandidate]] = None
        if device_index is not None:
            slot_pool = [c for c in (paired + direct) if c.dj_slot == device_index]
            if slot_pool:
                selected = slot_pool

        if selected is None and specific_name:
            scored: List[Tuple[int, _HidrawCandidate]] = []
            for cand in paired + direct:
                if not cand.hid_name:
                    continue
                if not cand.is_paired_child and _is_generic_receiver_name(cand.hid_name):
                    continue
                score = _name_match_score(device_name, cand.hid_name)
                if score > 0:
                    scored.append((score, cand))
            if scored:
                best_score = max(score for score, _ in scored)
                selected = [cand for score, cand in scored if score == best_score]

        if selected is None:
            if direct:
                selected = direct
            else:
                mouse_paired = [c for c in paired if _candidate_sort_key(c)[0] == 0]
                selected = mouse_paired or paired
    else:
        selected = [c for c in candidates if c.is_direct]
        if device_index is not None:
            slot_pool = [c for c in selected if c.dj_slot == device_index]
            if slot_pool:
                selected = slot_pool

    selected.sort(key=_candidate_sort_key)
    return [(cand.path, cand.layouts) for cand in selected]


class HidInputMonitor:
    """Single-shot read-only hidraw listener for identifying mouse button presses."""

    def __init__(
        self,
        vid: str,
        pid: str,
        on_input: Callable[[str, str], None],
        *,
        device_name: Optional[str] = None,
        device_index: Optional[int] = None,
    ):
        self._vid = vid.lower()
        self._pid = pid.lower()
        self._on_input = on_input
        self._device_name = device_name
        self._device_index = device_index
        self._thread: Optional[threading.Thread] = None
        self._stop_w: Optional[int] = None
        self._pipe_lock = threading.Lock()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.is_running:
            return True
        candidates = _matching_hidraw_nodes(
            self._vid,
            self._pid,
            device_name=self._device_name,
            device_index=self._device_index,
        )
        if not candidates:
            return False

        opened: List[Tuple[int, HidReportTracker]] = []
        for path, layouts in candidates:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                opened.append((fd, HidReportTracker(layouts)))
            except PermissionError as exc:
                logger.warning(
                    "Permission denied opening %s for raw HID input monitoring (check udev rules): %s",
                    path,
                    exc,
                )
                continue
            except OSError as exc:
                logger.debug("Could not open %s for raw HID input monitoring: %s", path, exc)
                continue

        if not opened:
            return False

        try:
            stop_r, stop_w = os.pipe()
        except OSError as exc:
            logger.warning("Failed to create pipe for HidInputMonitor: %s", exc)
            for fd, _ in opened:
                try:
                    os.close(fd)
                except OSError as close_exc:
                    logger.debug("Failed closing hidraw fd after pipe error: %s", close_exc)
            return False

        self._stop_w = stop_w
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            args=(opened, stop_r),
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        with self._pipe_lock:
            stop_w = self._stop_w
            self._stop_w = None
        if stop_w is not None:
            try:
                os.write(stop_w, b"\x00")
            except OSError as exc:
                logger.debug("Error writing stop signal to HidInputMonitor pipe: %s", exc)
            try:
                os.close(stop_w)
            except OSError as exc:
                logger.debug("Error closing HidInputMonitor stop pipe write fd: %s", exc)

    def _run(self, opened: List[Tuple[int, HidReportTracker]], stop_r: int):
        fd_map = {fd: tracker for fd, tracker in opened}
        read_fds = [stop_r] + list(fd_map.keys())
        try:
            while self._running:
                timeout: Optional[float] = None
                now = time.monotonic()
                for tracker in fd_map.values():
                    t = tracker.pending_timeout(now)
                    if t is not None:
                        timeout = t if timeout is None else min(timeout, t)

                ready, _, _ = select.select(read_fds, [], [], timeout)
                if stop_r in ready or not self._running:
                    break

                now = time.monotonic()
                emitted = False
                for fd in ready:
                    if fd == stop_r:
                        continue
                    try:
                        data = os.read(fd, 64)
                    except BlockingIOError:
                        continue
                    except OSError as exc:
                        logger.debug("Error reading hidraw fd %d: %s", fd, exc)
                        continue
                    if not data:
                        continue
                    res = fd_map[fd].process_report(data, now=now)
                    if res is not None:
                        self._running = False
                        self._on_input(res[0], res[1])
                        emitted = True
                        break
                if emitted:
                    break

                for tracker in fd_map.values():
                    res = tracker.poll_pending(now=now)
                    if res is not None:
                        self._running = False
                        self._on_input(res[0], res[1])
                        emitted = True
                        break
                if emitted:
                    break
        except OSError as exc:
            logger.debug("HidInputMonitor loop exited on OSError: %s", exc)
        finally:
            self._running = False
            for fd in fd_map:
                try:
                    os.close(fd)
                except OSError as exc:
                    logger.debug("Error closing hidraw fd %d: %s", fd, exc)
            try:
                os.close(stop_r)
            except OSError as exc:
                logger.debug("Error closing HidInputMonitor stop read fd: %s", exc)
            with self._pipe_lock:
                stop_w = self._stop_w
                self._stop_w = None
            if stop_w is not None:
                try:
                    os.close(stop_w)
                except OSError as exc:
                    logger.debug("Error closing HidInputMonitor stop write fd: %s", exc)
