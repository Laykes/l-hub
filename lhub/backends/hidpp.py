"""HID++ 2.0 access for wired and wireless Logitech devices (runtime DPI & onboard profiles).

libratbag commits onboard profiles, which fails with a USB timeout on some devices
(e.g. G502 X). ADJUSTABLE_DPI changes the DPI at runtime without writing a profile,
and ONBOARD_PROFILES provides live hardware profile-change notifications over hidraw.

Only Logitech devices (VID 046d) are ever accessed. Supports both direct/wired USB
devices (device index 0xFF) and paired wireless devices behind Logitech Unifying,
Lightspeed, Bolt, and Nano receivers (device indices 1..6).
"""

import glob
import logging
import os
import re
import select
import threading
from typing import Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

LOGITECH_VID = "046d"
_REPORT_SHORT = 0x10
_REPORT_LONG = 0x11
_REPORT_DJ_SHORT = 0x20
_REPORT_DJ_LONG = 0x21

_DEVICE_INDEX_WIRED = 0xFF
_DEVICE_INDEX = _DEVICE_INDEX_WIRED
_RECEIVER_SLOTS = (1, 2, 3, 4, 5, 6)
_SWID = 0x07

_FEATURE_IROOT = 0x0000
_FEATURE_DEVICE_NAME = 0x0005
_FEATURE_WIRELESS_DEVICE_STATUS = 0x1D4B
_FEATURE_ADJUSTABLE_DPI = 0x2201
_FEATURE_ONBOARD_PROFILES = 0x8100

_TIMEOUT = 0.5
_RETRIES = 3

# HID++ 1.0 sub-IDs & registers used on receivers
_SUBID_GET_LONG_REGISTER = 0x83
_SUBID_ERROR_HIDPP10 = 0x8F
_SUBID_ERROR_HIDPP20 = 0xFF
_SUBID_DEVICE_DISCONNECTION = 0x40
_SUBID_DEVICE_CONNECTION = 0x41
_REG_PAIRING_INFORMATION = 0xB5

# DJ notification sub-IDs
_DJ_NOTIF_DEVICE_UNPAIRED = 0x40
_DJ_NOTIF_DEVICE_PAIRED = 0x41
_DJ_NOTIF_CONNECTION_STATUS = 0x42

# HID++ 1.0 error codes
ERR_HIDPP10_CONNECT_FAIL = 0x04
ERR_HIDPP10_BUSY = 0x07
ERR_HIDPP10_UNKNOWN_DEVICE = 0x08
ERR_HIDPP10_RESOURCE_ERROR = 0x09

# HID++ 2.0 error codes
ERR_HIDPP20_INVALID_FEATURE = 0x06
ERR_HIDPP20_INVALID_FUNCTION = 0x07
ERR_HIDPP20_BUSY = 0x08
ERR_HIDPP20_UNSUPPORTED = 0x09

_SLEEP_ERRORS_HIDPP10 = frozenset({
    ERR_HIDPP10_CONNECT_FAIL,
    ERR_HIDPP10_UNKNOWN_DEVICE,
    ERR_HIDPP10_RESOURCE_ERROR,
})
_SLEEP_ERRORS_HIDPP20 = frozenset({
    ERR_HIDPP20_BUSY,
})

# HID++ 2.0 DeviceName (0x0005) getDeviceType values
DEVICE_TYPE_KEYBOARD = 0
DEVICE_TYPE_MOUSE = 3
DEVICE_TYPE_TOUCHPAD = 4
DEVICE_TYPE_TRACKBALL = 5
_POINTER_DEVICE_TYPES = frozenset({DEVICE_TYPE_MOUSE, DEVICE_TYPE_TOUCHPAD, DEVICE_TYPE_TRACKBALL})

# Known Logitech receiver USB PIDs (lowercase 4-hex-digit strings)
UNIFYING_RECEIVER_PIDS = frozenset({"c52b", "c532"})
LIGHTSPEED_RECEIVER_PIDS = frozenset({
    "c537", "c539", "c53a", "c53d", "c53f", "c541", "c545", "c547", "c54d", "c54e", "c551",
})
BOLT_RECEIVER_PIDS = frozenset({"c548"})
NANO_RECEIVER_PIDS = frozenset({"c526", "c52e", "c52f", "c531", "c534"})
RECEIVER_PIDS = (
    UNIFYING_RECEIVER_PIDS | LIGHTSPEED_RECEIVER_PIDS | BOLT_RECEIVER_PIDS | NANO_RECEIVER_PIDS
)

_GENERIC_RECEIVER_TOKENS = frozenset({
    "logitech",
    "logi",
    "usb",
    "receiver",
    "unifying",
    "lightspeed",
    "bolt",
    "nano",
    "wireless",
    "gaming",
    "mouse",
    "keyboard",
    "dongle",
})


class HidppError(Exception):
    """Error reply emitted by a HID++ 1.0 receiver or HID++ 2.0 device."""

    def __init__(self, error_code: int, device_index: int, is_hidpp10: bool = False):
        self.error_code = error_code
        self.device_index = device_index
        self.is_hidpp10 = is_hidpp10
        proto = "HID++ 1.0" if is_hidpp10 else "HID++ 2.0"
        super().__init__(f"{proto} error 0x{error_code:02X} on device index 0x{device_index:02X}")

    @property
    def is_sleep_or_unreachable(self) -> bool:
        if self.is_hidpp10:
            return self.error_code in _SLEEP_ERRORS_HIDPP10
        return self.error_code in _SLEEP_ERRORS_HIDPP20

    @property
    def is_invalid_feature(self) -> bool:
        return not self.is_hidpp10 and self.error_code == ERR_HIDPP20_INVALID_FEATURE


_lock = threading.Lock()
# (device_key, feature_id) -> (hidraw_path, device_index, feature_idx)
_cache: Dict[Tuple[str, int], Tuple[str, int, int]] = {}


def receiver_kind(pid: str) -> Optional[str]:
    """Return the receiver family ('unifying', 'lightspeed', 'bolt', 'nano') or None."""
    pid_l = (pid or "").strip().lower()
    if pid_l in UNIFYING_RECEIVER_PIDS:
        return "unifying"
    if pid_l in LIGHTSPEED_RECEIVER_PIDS:
        return "lightspeed"
    if pid_l in BOLT_RECEIVER_PIDS:
        return "bolt"
    if pid_l in NANO_RECEIVER_PIDS:
        return "nano"
    return None


def is_receiver_pid(vid: str, pid: str) -> bool:
    """Return True if vid:pid belongs to a known Logitech wireless receiver."""
    return (vid or "").strip().lower() == LOGITECH_VID and receiver_kind(pid) is not None


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _strip_brand_prefix(norm: str) -> str:
    return re.sub(r"^(?:logitech|logi)\s+", "", norm).strip()


def _is_generic_receiver_name(name: Optional[str]) -> bool:
    if not name:
        return True
    norm = _normalize_name(name)
    if not norm:
        return True
    meaningful = [tok for tok in norm.split() if tok not in _GENERIC_RECEIVER_TOKENS]
    return len(meaningful) == 0


def _name_match_score(target_name: Optional[str], slot_name: Optional[str]) -> int:
    """Return a confidence score (0..100) comparing target device name against slot name."""
    if not target_name or not slot_name:
        return 0
    t_norm = _normalize_name(target_name)
    s_norm = _normalize_name(slot_name)
    if not t_norm or not s_norm:
        return 0

    t_stripped = _strip_brand_prefix(t_norm)
    s_stripped = _strip_brand_prefix(s_norm)
    if t_norm == s_norm or (t_stripped and t_stripped == s_stripped):
        return 100

    if t_stripped and s_stripped and not _is_generic_receiver_name(target_name) and not _is_generic_receiver_name(slot_name):
        if len(t_stripped) >= 2 and len(s_stripped) >= 2:
            if t_stripped in s_stripped or s_stripped in t_stripped:
                return 80

    t_meaningful = {tok for tok in t_stripped.split() if tok not in _GENERIC_RECEIVER_TOKENS}
    s_meaningful = {tok for tok in s_stripped.split() if tok not in _GENERIC_RECEIVER_TOKENS}
    if not t_meaningful or not s_meaningful:
        return 0

    if t_meaningful <= s_meaningful or s_meaningful <= t_meaningful:
        return 70

    overlap = t_meaningful & s_meaningful
    union = t_meaningful | s_meaningful
    ratio = len(overlap) / len(union)
    if ratio >= 0.6:
        return 40 + int(29 * ratio)
    return 0


def _make_device_key(
    vid: str,
    pid: str,
    device_name: Optional[str] = None,
    device_key: Optional[str] = None,
    device_index: Optional[int] = None,
) -> str:
    """Build a collision-free cache key for wired or multi-slot receiver devices."""
    vid_l = (vid or "").strip().lower()
    pid_l = (pid or "").strip().lower()
    default_vid_pid = f"{vid_l}:{pid_l}"
    base = device_key.strip().lower() if device_key and device_key.strip() else default_vid_pid

    if device_index is not None:
        return f"{base}@idx:{device_index}"
    if (
        base == default_vid_pid
        and device_name
        and is_receiver_pid(vid_l, pid_l)
        and not _is_generic_receiver_name(device_name)
    ):
        return f"{base}@{_normalize_name(device_name)}"
    return base


def invalidate_cache(device_key: Optional[str] = None) -> None:
    """Clear all cached HID++ routes, or those belonging to one device_key."""
    with _lock:
        if device_key is None:
            _cache.clear()
            return
        stale = [k for k in _cache if k[0] == device_key]
        for k in stale:
            _cache.pop(k, None)


def _request(
    fd: int,
    feature_idx: int,
    function: int,
    params: bytes = b"",
    device_index: int = _DEVICE_INDEX_WIRED,
    *,
    raise_on_error: bool = False,
) -> Optional[bytes]:
    msg = bytes([_REPORT_LONG, device_index, feature_idx, (function << 4) | _SWID]) + params
    os.write(fd, msg.ljust(20, b"\x00"))
    for _ in range(20):
        ready, _, _ = select.select([fd], [], [], _TIMEOUT)
        if not ready:
            return None
        data = os.read(fd, 64)
        if not data:
            return None
        if len(data) < 4:
            continue
        if data[0] not in (_REPORT_SHORT, _REPORT_LONG):
            continue
        if data[1] != device_index:
            continue

        if data[2] == _SUBID_ERROR_HIDPP20:
            if len(data) >= 6:
                if (data[3] == feature_idx and (data[4] & 0x0F) == _SWID) or (
                    data[3] == 0 and data[4] == 0
                ):
                    err = HidppError(data[5], device_index, is_hidpp10=False)
                    logger.debug("%s", err)
                    if raise_on_error:
                        raise err
                    return None
                continue
            err = HidppError(data[3], device_index, is_hidpp10=False)
            logger.debug("%s", err)
            if raise_on_error:
                raise err
            return None

        if data[2] == _SUBID_ERROR_HIDPP10:
            if len(data) >= 6:
                matches_req = data[3] == feature_idx and (data[4] & 0x0F) == _SWID
                is_general = data[3] == 0 and data[4] == 0
                is_sleep = data[5] in _SLEEP_ERRORS_HIDPP10
                if matches_req or is_general or is_sleep:
                    err = HidppError(data[5], device_index, is_hidpp10=True)
                    logger.debug("%s", err)
                    if raise_on_error:
                        raise err
                    return None
                continue
            err = HidppError(data[3], device_index, is_hidpp10=True)
            logger.debug("%s", err)
            if raise_on_error:
                raise err
            return None

        if data[2] == feature_idx and (data[3] & 0x0F) == _SWID:
            return data
    return None


def _request_retry(
    fd: int,
    feature_idx: int,
    function: int,
    params: bytes = b"",
    device_index: int = _DEVICE_INDEX_WIRED,
    *,
    retries: int = _RETRIES,
    raise_on_error: bool = False,
) -> Optional[bytes]:
    # The first request after opening a node is sometimes lost.
    last_err: Optional[HidppError] = None
    for _ in range(max(1, retries)):
        try:
            data = _request(
                fd,
                feature_idx,
                function,
                params,
                device_index=device_index,
                raise_on_error=True,
            )
            if data:
                return data
            last_err = None
        except HidppError as exc:
            last_err = exc
            if (
                exc.is_sleep_or_unreachable
                or exc.is_invalid_feature
                or (
                    not exc.is_hidpp10
                    and exc.error_code in (ERR_HIDPP20_INVALID_FUNCTION, ERR_HIDPP20_UNSUPPORTED)
                )
            ):
                if raise_on_error:
                    raise
                return None
    if last_err is not None and raise_on_error:
        raise last_err
    return None


def _descriptor_hidpp_priority(sys_node: str) -> int:
    """Return sort priority (0 = explicit HID++ vendor descriptor, 1 = unknown/vendor, 2 = input-only)."""
    try:
        with open(f"{sys_node}/device/report_descriptor", "rb") as f:
            desc = f.read()
    except OSError:
        return 1

    usage_page = 0
    has_vendor_page = False
    has_hidpp_reports = False
    i = 0
    n = len(desc)
    while i < n:
        header = desc[i]
        i += 1
        if header == 0xFE:
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
        if item_type == 1:
            val = int.from_bytes(raw, "little", signed=False) if raw else 0
            if tag == 0:
                usage_page = val
                if usage_page >= 0xFF00:
                    has_vendor_page = True
            elif tag == 8 and usage_page >= 0xFF00 and val in (_REPORT_SHORT, _REPORT_LONG):
                has_hidpp_reports = True

    if has_hidpp_reports:
        return 0
    if has_vendor_page:
        return 1
    return 2


def _parse_uevent_lines(text: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, val = line.split("=", 1)
            parsed[key.strip().upper()] = val.strip()
    return parsed


def _sysfs_dj_slot(path: str) -> Optional[int]:
    node = os.path.basename(path)
    try:
        with open(f"/sys/class/hidraw/{node}/device/uevent", "r", encoding="utf-8", errors="ignore") as f:
            uevent = _parse_uevent_lines(f.read())
    except OSError:
        return None
    phys = uevent.get("HID_PHYS", "")
    m = re.search(r":([1-6])\s*$", phys)
    return int(m.group(1)) if m else None


def _candidate_paths(vid: str, pid: str):
    wanted = f"{vid.upper().zfill(8)}:{pid.upper().zfill(8)}"
    matches: List[Tuple[int, int, str]] = []
    for idx, node in enumerate(sorted(glob.glob("/sys/class/hidraw/hidraw*"))):
        try:
            with open(f"{node}/device/uevent") as f:
                if wanted in f.read().upper():
                    prio = _descriptor_hidpp_priority(node)
                    matches.append((prio, idx, f"/dev/{os.path.basename(node)}"))
        except OSError as exc:
            logger.debug("Skipping %s while scanning HID++ candidates: %s", node, exc)
            continue
    matches.sort()
    for _, _, dev_path in matches:
        yield dev_path


def _receiver_candidate_paths() -> List[Tuple[str, str]]:
    """Return [(hidraw_path, receiver_pid), ...] for all Logitech receivers on the host."""
    found: List[Tuple[int, int, str, str]] = []
    for idx, node in enumerate(sorted(glob.glob("/sys/class/hidraw/hidraw*"))):
        try:
            with open(f"{node}/device/uevent") as f:
                uevent = _parse_uevent_lines(f.read())
        except OSError as exc:
            logger.debug("Skipping %s while scanning receivers: %s", node, exc)
            continue
        hid_id = uevent.get("HID_ID", "")
        parts = hid_id.split(":")
        if len(parts) < 3:
            continue
        node_vid = parts[1][-4:].lower()
        node_pid = parts[2][-4:].lower()
        if is_receiver_pid(node_vid, node_pid):
            prio = _descriptor_hidpp_priority(node)
            found.append((prio, idx, f"/dev/{os.path.basename(node)}", node_pid))
    found.sort()
    return [(dev_path, node_pid) for _, _, dev_path, node_pid in found]


def _read_device_name_and_type(fd: int, device_index: int) -> Tuple[Optional[str], Optional[int]]:
    """Query HID++ 2.0 feature 0x0005 (DeviceName) for the paired device's name and type."""
    root = _request_retry(
        fd,
        _FEATURE_IROOT,
        0,
        bytes([_FEATURE_DEVICE_NAME >> 8, _FEATURE_DEVICE_NAME & 0xFF]),
        device_index=device_index,
        retries=1,
    )
    if not root or len(root) < 5 or root[4] == 0:
        return None, None
    name_feat_idx = root[4]

    name: Optional[str] = None
    cnt_resp = _request_retry(fd, name_feat_idx, 0, device_index=device_index, retries=1)
    if cnt_resp and len(cnt_resp) >= 5:
        total_len = min(cnt_resp[4], 64)
        if total_len > 0:
            chunks = bytearray()
            offset = 0
            while len(chunks) < total_len:
                chunk_resp = _request_retry(
                    fd,
                    name_feat_idx,
                    1,
                    bytes([offset]),
                    device_index=device_index,
                    retries=1,
                )
                if not chunk_resp or len(chunk_resp) <= 4:
                    break
                part = chunk_resp[4:]
                chunks.extend(part)
                offset += len(part)
            raw_name = bytes(chunks[:total_len]).split(b"\x00", 1)[0]
            decoded = raw_name.decode("utf-8", errors="ignore").strip()
            if decoded:
                name = decoded

    type_resp = _request_retry(fd, name_feat_idx, 2, device_index=device_index, retries=1)
    dev_type = type_resp[4] if (type_resp and len(type_resp) >= 5) else None
    return name, dev_type


def _read_receiver_slot_wpid(fd: int, slot: int, recv_kind: Optional[str]) -> Optional[str]:
    """Query receiver pairing register 0xB5 for a slot's 16-bit wireless PID."""
    sub_param = (0x50 + slot) if recv_kind == "bolt" else (0x20 + (slot - 1))
    msg = bytes([_REPORT_SHORT, _DEVICE_INDEX_WIRED, _SUBID_GET_LONG_REGISTER, _REG_PAIRING_INFORMATION, sub_param, 0x00, 0x00])
    os.write(fd, msg)
    for _ in range(20):
        ready, _, _ = select.select([fd], [], [], _TIMEOUT)
        if not ready:
            return None
        data = os.read(fd, 64)
        if not data or len(data) < 6:
            continue
        if data[0] not in (_REPORT_SHORT, _REPORT_LONG):
            continue
        if data[1] != _DEVICE_INDEX_WIRED:
            continue
        if data[2] == _SUBID_ERROR_HIDPP10 and data[3] == _SUBID_GET_LONG_REGISTER and data[4] == _REG_PAIRING_INFORMATION:
            return None
        if (
            data[2] == _SUBID_GET_LONG_REGISTER
            and data[3] == _REG_PAIRING_INFORMATION
            and data[4] == sub_param
            and len(data) >= 9
        ):
            if recv_kind == "bolt":
                wpid = (data[7] << 8) | data[6]
            else:
                wpid = (data[7] << 8) | data[8]
            return f"{wpid:04x}" if wpid != 0 else None
    return None


def _open_hidpp_node(
    path: str,
    vid: str,
    pid: str,
    *,
    flags: int = os.O_RDWR,
    purpose: str = "device",
) -> Tuple[Optional[int], bool]:
    """Open a hidraw node, returning (fd, is_permission_error)."""
    try:
        return os.open(path, flags), False
    except PermissionError as exc:
        logger.warning(
            "Permission denied opening %s for HID++ %s %s:%s (check udev rules): %s",
            path,
            purpose,
            vid,
            pid,
            exc,
        )
        return None, True
    except OSError as exc:
        logger.debug("Could not open %s for HID++ %s: %s", path, purpose, exc)
        return None, False


def _probe_receiver_paths(
    path_pid_pairs: Sequence[Tuple[str, str]],
    feature_id: int,
    *,
    target_wpid: Optional[str] = None,
    device_name: Optional[str] = None,
) -> Optional[Tuple[str, int, int]]:
    """Enumerate slots 1..6 across receiver hidraw nodes and return best (path, slot, feat_idx)."""
    best: Optional[Tuple[int, str, int, int]] = None
    specific_name = bool(device_name and not _is_generic_receiver_name(device_name))
    target_wpid_l = target_wpid.lower() if target_wpid else None

    for path, recv_pid in path_pid_pairs:
        fd, _ = _open_hidpp_node(path, LOGITECH_VID, recv_pid, purpose="receiver")
        if fd is None:
            continue

        recv_kind = receiver_kind(recv_pid)
        try:
            for slot in _RECEIVER_SLOTS:
                root = _request_retry(
                    fd,
                    _FEATURE_IROOT,
                    0,
                    bytes([feature_id >> 8, feature_id & 0xFF]),
                    device_index=slot,
                    retries=1,
                )
                if not root or len(root) < 5 or root[4] == 0:
                    continue
                feat_idx = root[4]

                slot_name, slot_type = _read_device_name_and_type(fd, slot)

                if target_wpid_l is not None:
                    slot_wpid = _read_receiver_slot_wpid(fd, slot, recv_kind)
                    if slot_wpid == target_wpid_l:
                        return (path, slot, feat_idx)
                    if slot_wpid is not None and slot_wpid != target_wpid_l:
                        continue

                if specific_name:
                    n_score = _name_match_score(device_name, slot_name)
                    if n_score > 0:
                        score = n_score + (5 if slot_type in _POINTER_DEVICE_TYPES else 0)
                    elif slot_name is not None:
                        continue
                    elif slot_type != DEVICE_TYPE_KEYBOARD:
                        score = 10
                    else:
                        continue
                else:
                    if slot_type in _POINTER_DEVICE_TYPES:
                        score = 20
                    elif slot_type is None:
                        score = 15
                    elif slot_type == DEVICE_TYPE_KEYBOARD:
                        score = 5
                    else:
                        score = 10

                if score >= 100:
                    return (path, slot, feat_idx)
                if best is None or score > best[0]:
                    best = (score, path, slot, feat_idx)
        except OSError as exc:
            logger.debug("HID++ receiver probe failed on %s (feature 0x%04X): %s", path, feature_id, exc)
        finally:
            os.close(fd)

    if best is None:
        return None
    return (best[1], best[2], best[3])


def _probe_explicit_index(
    paths: Sequence[str],
    vid: str,
    pid: str,
    feature_id: int,
    device_index: int,
) -> Optional[Tuple[str, int, int]]:
    for path in paths:
        fd, _ = _open_hidpp_node(path, vid, pid)
        if fd is None:
            continue
        try:
            root = _request_retry(
                fd,
                _FEATURE_IROOT,
                0,
                bytes([feature_id >> 8, feature_id & 0xFF]),
                device_index=device_index,
            )
            if root and len(root) >= 5 and root[4] != 0:
                return (path, device_index, root[4])
        except OSError as exc:
            logger.debug("HID++ probe failed on %s (feature 0x%04X): %s", path, feature_id, exc)
        finally:
            os.close(fd)
    return None


def _locate(
    vid: str,
    pid: str,
    feature_id: int,
    *,
    device_name: Optional[str] = None,
    device_key: Optional[str] = None,
    device_index: Optional[int] = None,
) -> Optional[Tuple[str, int, int]]:
    if (vid or "").strip().lower() != LOGITECH_VID:
        return None
    eff_key = _make_device_key(
        vid,
        pid,
        device_name=device_name,
        device_key=device_key,
        device_index=device_index,
    )
    cache_key = (eff_key, feature_id)
    if cache_key in _cache:
        return _cache[cache_key]

    direct_paths = list(_candidate_paths(vid, pid))
    result: Optional[Tuple[str, int, int]] = None

    if device_index is not None:
        if direct_paths:
            result = _probe_explicit_index(direct_paths, vid, pid, feature_id, device_index)
        elif 1 <= device_index <= 6:
            recv_paths = [p for p, _ in _receiver_candidate_paths()]
            result = _probe_explicit_index(recv_paths, vid, pid, feature_id, device_index)
    elif is_receiver_pid(vid, pid):
        pid_l = (pid or "").strip().lower()
        result = _probe_receiver_paths(
            [(p, pid_l) for p in direct_paths],
            feature_id,
            target_wpid=None,
            device_name=device_name,
        )
    elif direct_paths:
        for path in direct_paths:
            dj_slot = _sysfs_dj_slot(path)
            indices = [dj_slot, _DEVICE_INDEX_WIRED] if dj_slot is not None else [_DEVICE_INDEX_WIRED]
            fd, _ = _open_hidpp_node(path, vid, pid)
            if fd is None:
                continue
            try:
                for dev_idx in indices:
                    retries = 1 if (dj_slot is not None and dev_idx == dj_slot) else _RETRIES
                    root = _request_retry(
                        fd,
                        _FEATURE_IROOT,
                        0,
                        bytes([feature_id >> 8, feature_id & 0xFF]),
                        device_index=dev_idx,
                        retries=retries,
                    )
                    if root and len(root) >= 5 and root[4] != 0:
                        result = (path, dev_idx, root[4])
                        break
                if result is not None:
                    break
            except OSError as exc:
                logger.debug("HID++ probe failed on %s (feature 0x%04X): %s", path, feature_id, exc)
            finally:
                os.close(fd)
    else:
        recv_pairs = _receiver_candidate_paths()
        if recv_pairs:
            result = _probe_receiver_paths(
                recv_pairs,
                feature_id,
                target_wpid=(pid or "").strip().lower(),
                device_name=device_name,
            )

    if result is not None:
        _cache[cache_key] = result
    return result


def _with_device(
    vid: str,
    pid: str,
    feature_id: int,
    action,
    *,
    device_name: Optional[str] = None,
    device_key: Optional[str] = None,
    device_index: Optional[int] = None,
):
    eff_key = _make_device_key(
        vid,
        pid,
        device_name=device_name,
        device_key=device_key,
        device_index=device_index,
    )
    cache_key = (eff_key, feature_id)

    with _lock:
        for attempt in range(2):
            used_cache = cache_key in _cache
            loc = _locate(
                vid,
                pid,
                feature_id,
                device_name=device_name,
                device_key=device_key,
                device_index=device_index,
            )
            if loc is None:
                return None
            path, dev_idx, feature_idx = loc

            fd, perm_err = _open_hidpp_node(path, vid, pid)
            if fd is None:
                _cache.pop(cache_key, None)
                if not perm_err and used_cache and attempt == 0:
                    continue
                return None

            try:
                result = action(fd, dev_idx, feature_idx)
                if result is None:
                    _cache.pop(cache_key, None)
                return result
            except HidppError as exc:
                logger.debug("HID++ request failed on %s: %s", path, exc)
                _cache.pop(cache_key, None)
                if exc.is_invalid_feature and used_cache and attempt == 0:
                    continue
                return None
            except OSError as exc:
                logger.debug("HID++ request failed on %s: %s", path, exc)
                _cache.pop(cache_key, None)
                if used_cache and attempt == 0:
                    continue
                return None
            finally:
                os.close(fd)
    return None


def _read_dpi(fd: int, device_index: int, feature_idx: int) -> Optional[int]:
    data = _request_retry(
        fd,
        feature_idx,
        2,
        bytes([0]),
        device_index=device_index,
        raise_on_error=True,
    )  # getSensorDpi(sensor 0)
    return ((data[5] << 8) | data[6]) if (data and len(data) >= 7) else None


def get_dpi(
    vid: str,
    pid: str,
    *,
    device_name: Optional[str] = None,
    device_key: Optional[str] = None,
    device_index: Optional[int] = None,
) -> Optional[int]:
    """Current DPI read from the device, or None if HID++ is unavailable."""
    return _with_device(
        vid,
        pid,
        _FEATURE_ADJUSTABLE_DPI,
        _read_dpi,
        device_name=device_name,
        device_key=device_key,
        device_index=device_index,
    )


def set_dpi(
    vid: str,
    pid: str,
    dpi: int,
    *,
    device_name: Optional[str] = None,
    device_key: Optional[str] = None,
    device_index: Optional[int] = None,
) -> bool:
    """Set DPI at runtime; True only if the device reports the new value back."""

    def action(fd: int, device_index_val: int, feature_idx: int) -> Optional[bool]:
        resp = _request_retry(
            fd,
            feature_idx,
            3,
            bytes([0, dpi >> 8, dpi & 0xFF]),
            device_index=device_index_val,
            raise_on_error=True,
        )  # setSensorDpi
        if not resp:
            return None
        cur = _read_dpi(fd, device_index_val, feature_idx)
        return None if cur is None else (cur == dpi)

    return bool(
        _with_device(
            vid,
            pid,
            _FEATURE_ADJUSTABLE_DPI,
            action,
            device_name=device_name,
            device_key=device_key,
            device_index=device_index,
        )
    )


def format_onboard_profile(profile_id: int) -> str:
    """Format a HID++ 0x8100 16-bit profile sector ID into a readable label."""
    high = (profile_id >> 8) & 0xFF
    low = profile_id & 0xFF
    if high == 0x00 and low > 0:
        return f"Profile {low}"
    if high == 0x01 and low > 0:
        return f"Profile {low} (Factory)"
    return f"Profile 0x{profile_id:04X}"


def onboard_profile_index(profile_id: Optional[int]) -> Optional[int]:
    """Convert a HID++ 0x8100 16-bit profile ID to a 0-based ratbag profile index."""
    if profile_id is None:
        return None
    high = (profile_id >> 8) & 0xFF
    low = profile_id & 0xFF
    if high in (0x00, 0x01) and low > 0:
        return low - 1
    return None


def get_onboard_profile(
    vid: str,
    pid: str,
    *,
    device_name: Optional[str] = None,
    device_key: Optional[str] = None,
    device_index: Optional[int] = None,
) -> Optional[int]:
    """Read current onboard profile ID via 0x8100 getCurrentProfile, or None."""

    def action(fd: int, device_index_val: int, feature_idx: int) -> Optional[int]:
        data = _request_retry(
            fd,
            feature_idx,
            4,
            device_index=device_index_val,
            raise_on_error=True,
        )  # getCurrentProfile
        if not data or len(data) < 6:
            return None
        profile_id = (data[4] << 8) | data[5]
        return profile_id if profile_id != 0 else None

    return _with_device(
        vid,
        pid,
        _FEATURE_ONBOARD_PROFILES,
        action,
        device_name=device_name,
        device_key=device_key,
        device_index=device_index,
    )


def set_onboard_profile(
    vid: str,
    pid: str,
    profile_id: int,
    *,
    device_name: Optional[str] = None,
    device_key: Optional[str] = None,
    device_index: Optional[int] = None,
) -> bool:
    """Activate/reload an onboard profile via 0x8100 setCurrentProfile."""

    def action(fd: int, device_index_val: int, feature_idx: int) -> Optional[bool]:
        data = _request_retry(
            fd,
            feature_idx,
            3,
            bytes([(profile_id >> 8) & 0xFF, profile_id & 0xFF]),
            device_index=device_index_val,
            raise_on_error=True,
        )
        return True if data is not None else None

    return bool(
        _with_device(
            vid,
            pid,
            _FEATURE_ONBOARD_PROFILES,
            action,
            device_name=device_name,
            device_key=device_key,
            device_index=device_index,
        )
    )


def parse_onboard_event(
    data: bytes,
    feature_idx: int,
    device_index: int = _DEVICE_INDEX_WIRED,
) -> Optional[Tuple[str, int]]:
    """Parse an unsolicited HID++ 0x8100 notification report for a specific device_index."""
    if len(data) < 6:
        return None
    if data[0] not in (_REPORT_SHORT, _REPORT_LONG):
        return None
    if data[1] != device_index or data[2] != feature_idx:
        return None
    if (data[3] & 0x0F) != 0:  # ignore replies to host requests (non-zero SWID)
        return None
    event_id = (data[3] >> 4) & 0x0F
    if event_id == 0:  # currentProfileChanged
        profile_id = (data[4] << 8) | data[5]
        return ("profile", profile_id) if profile_id != 0 else None
    if event_id == 1:  # currentDPIIndexChanged
        return ("dpi_index", data[4])
    return None


def parse_connection_event(
    data: bytes,
    device_index: int,
    *,
    wireless_status_feature_idx: Optional[int] = None,
) -> Optional[bool]:
    """Parse HID++ 1.0 / DJ / 0x1D4B connection events for one receiver slot.

    Returns True when the slot connected/woke, False when link lost/disconnected, or None.
    """
    if len(data) < 5 or data[1] != device_index:
        return None
    report_id = data[0]
    if report_id in (_REPORT_SHORT, _REPORT_LONG):
        if data[2] == _SUBID_DEVICE_DISCONNECTION:
            return False
        if data[2] == _SUBID_DEVICE_CONNECTION:
            return not bool(data[4] & 0x40)
        if wireless_status_feature_idx is not None and data[2] == wireless_status_feature_idx:
            if (data[3] & 0x0F) == 0 and (data[3] >> 4) == 0 and data[4] == 0x01:
                return True
        return None
    if report_id in (_REPORT_DJ_SHORT, _REPORT_DJ_LONG):
        if data[2] == _DJ_NOTIF_DEVICE_UNPAIRED:
            return False
        if data[2] == _DJ_NOTIF_DEVICE_PAIRED:
            return not bool(data[3] & 0x40)
        if data[2] == _DJ_NOTIF_CONNECTION_STATUS:
            return not bool(data[3] & 0x01)
    return None


class OnboardProfileMonitor:
    """Background hidraw listener for live HID++ 0x8100 profile/DPI change notifications."""

    def __init__(
        self,
        vid: str,
        pid: str,
        on_profile_changed: Callable[[int], None],
        on_dpi_changed: Optional[Callable[[int], None]] = None,
        *,
        device_name: Optional[str] = None,
        device_key: Optional[str] = None,
        device_index: Optional[int] = None,
        on_reconnected: Optional[Callable[[], None]] = None,
    ):
        self._vid = vid.lower()
        self._pid = pid.lower()
        self._on_profile_changed = on_profile_changed
        self._on_dpi_changed = on_dpi_changed
        self._device_name = device_name
        self._device_key = device_key
        self._device_index = device_index
        self._on_reconnected = on_reconnected
        self._eff_key = _make_device_key(
            self._vid,
            self._pid,
            device_name=device_name,
            device_key=device_key,
            device_index=device_index,
        )
        self._resolved_device_index: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_r: Optional[int] = None
        self._stop_w: Optional[int] = None
        self._pipe_lock = threading.Lock()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def device_index(self) -> Optional[int]:
        return self._resolved_device_index

    def start(self) -> bool:
        if self.is_running:
            return True
        with _lock:
            loc = _locate(
                self._vid,
                self._pid,
                _FEATURE_ONBOARD_PROFILES,
                device_name=self._device_name,
                device_key=self._device_key,
                device_index=self._device_index,
            )
        if loc is None:
            return False
        path, resolved_dev_idx, feature_idx = loc
        fd, _ = _open_hidpp_node(path, self._vid, self._pid, flags=os.O_RDONLY, purpose="monitor")
        if fd is None:
            return False
        try:
            stop_r, stop_w = os.pipe()
        except OSError as exc:
            logger.warning("Failed to create pipe for HID++ monitor: %s", exc)
            os.close(fd)
            return False

        self._resolved_device_index = resolved_dev_idx
        self._stop_r = stop_r
        self._stop_w = stop_w
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            args=(fd, stop_r, resolved_dev_idx, feature_idx),
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
                logger.debug("Error writing stop signal to HID++ monitor pipe: %s", exc)
            try:
                os.close(stop_w)
            except OSError as exc:
                logger.debug("Error closing stop pipe write fd in HID++ monitor: %s", exc)

    def _run(self, fd: int, stop_r: int, device_index: int, feature_idx: int):
        try:
            while self._running:
                ready, _, _ = select.select([fd, stop_r], [], [])
                if stop_r in ready or not self._running:
                    break
                if fd not in ready:
                    continue
                data = os.read(fd, 64)
                if not data:
                    break

                conn = parse_connection_event(data, device_index)
                if conn is False:
                    logger.debug(
                        "HID++ device %s (index 0x%02X) disconnected/asleep; waiting for wake",
                        self._eff_key,
                        device_index,
                    )
                    invalidate_cache(self._eff_key)
                    continue
                if conn is True:
                    logger.debug(
                        "HID++ device %s (index 0x%02X) connected/woke; resyncing",
                        self._eff_key,
                        device_index,
                    )
                    invalidate_cache(self._eff_key)
                    prof_id = get_onboard_profile(
                        self._vid,
                        self._pid,
                        device_name=self._device_name,
                        device_key=self._device_key,
                        device_index=self._device_index,
                    )
                    with _lock:
                        cached = _cache.get((self._eff_key, _FEATURE_ONBOARD_PROFILES))
                        if cached is not None:
                            feature_idx = cached[2]
                    if prof_id is not None:
                        self._on_profile_changed(prof_id)
                    if self._on_dpi_changed is not None:
                        dpi = get_dpi(
                            self._vid,
                            self._pid,
                            device_name=self._device_name,
                            device_key=self._device_key,
                            device_index=self._device_index,
                        )
                        if dpi and 50 <= dpi <= 30000:
                            self._on_dpi_changed(dpi)
                    if self._on_reconnected is not None:
                        self._on_reconnected()
                    continue

                ev = parse_onboard_event(data, feature_idx, device_index=device_index)
                if ev is None:
                    continue
                kind, val = ev
                if kind == "profile":
                    self._on_profile_changed(val)
                elif kind == "dpi_index" and self._on_dpi_changed is not None:
                    dpi = get_dpi(
                        self._vid,
                        self._pid,
                        device_name=self._device_name,
                        device_key=self._device_key,
                        device_index=self._device_index,
                    )
                    if dpi and 50 <= dpi <= 30000:
                        self._on_dpi_changed(dpi)
        except OSError as exc:
            logger.debug("HID++ monitor stopped due to OSError: %s", exc)
            invalidate_cache(self._eff_key)
        finally:
            self._running = False
            try:
                os.close(fd)
            except OSError as exc:
                logger.debug("Error closing HID++ monitor device fd: %s", exc)
            try:
                os.close(stop_r)
            except OSError as exc:
                logger.debug("Error closing HID++ monitor stop read fd: %s", exc)
            with self._pipe_lock:
                self._stop_r = None
                stop_w = self._stop_w
                self._stop_w = None
            if stop_w is not None:
                try:
                    os.close(stop_w)
                except OSError as exc:
                    logger.debug("Error closing HID++ monitor stop write fd: %s", exc)
