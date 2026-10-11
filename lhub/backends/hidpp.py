"""Minimal HID++ 2.0 access for runtime DPI control (ADJUSTABLE_DPI, feature 0x2201).

libratbag commits onboard profiles, which fails with a USB timeout on some devices
(e.g. G502 X). ADJUSTABLE_DPI changes the DPI at runtime without writing a profile.

Only Logitech devices (VID 046d) are ever written to, and only the hidraw nodes whose
VID:PID match the requested device. Devices are addressed with index 0xFF (wired/direct).
"""
import glob
import os
import select
import threading
from typing import Dict, Optional, Tuple

LOGITECH_VID = "046d"
_REPORT_LONG = 0x11
_DEVICE_INDEX = 0xFF
_SWID = 0x07
_FEATURE_ADJUSTABLE_DPI = 0x2201
_TIMEOUT = 0.5
_RETRIES = 3

_lock = threading.Lock()
# (vid, pid) -> (hidraw path, feature index of ADJUSTABLE_DPI)
_cache: Dict[Tuple[str, str], Tuple[str, int]] = {}


def _request(fd: int, feature_idx: int, function: int, params: bytes = b"") -> Optional[bytes]:
    msg = bytes([_REPORT_LONG, _DEVICE_INDEX, feature_idx, (function << 4) | _SWID]) + params
    os.write(fd, msg.ljust(20, b"\x00"))
    for _ in range(20):
        ready, _, _ = select.select([fd], [], [], _TIMEOUT)
        if not ready:
            return None
        data = os.read(fd, 64)
        if len(data) < 4:
            continue
        if data[2] == 0xFF:  # HID++ 2.0 error report
            return None
        if data[1] == _DEVICE_INDEX and data[2] == feature_idx and (data[3] & 0x0F) == _SWID:
            return data
    return None


def _request_retry(fd: int, feature_idx: int, function: int, params: bytes = b"") -> Optional[bytes]:
    # The first request after opening a node is sometimes lost.
    for _ in range(_RETRIES):
        data = _request(fd, feature_idx, function, params)
        if data:
            return data
    return None


def _candidate_paths(vid: str, pid: str):
    wanted = f"{vid.upper().zfill(8)}:{pid.upper().zfill(8)}"
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(f"{node}/device/uevent") as f:
                if wanted in f.read().upper():
                    yield f"/dev/{os.path.basename(node)}"
        except OSError:
            continue


def _locate(vid: str, pid: str) -> Optional[Tuple[str, int]]:
    if vid.lower() != LOGITECH_VID:
        return None
    key = (vid.lower(), pid.lower())
    if key in _cache:
        return _cache[key]
    for path in _candidate_paths(vid, pid):
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError:
            continue
        try:
            root = _request_retry(fd, 0x00, 0, bytes([_FEATURE_ADJUSTABLE_DPI >> 8, _FEATURE_ADJUSTABLE_DPI & 0xFF]))
            if root and root[4] != 0:
                _cache[key] = (path, root[4])
                return _cache[key]
        except OSError:
            pass  # not the HID++ interface
        finally:
            os.close(fd)
    return None


def _with_device(vid: str, pid: str, action):
    with _lock:
        loc = _locate(vid, pid)
        if loc is None:
            return None
        path, feature_idx = loc
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError:
            _cache.pop((vid.lower(), pid.lower()), None)
            return None
        try:
            return action(fd, feature_idx)
        except OSError:
            _cache.pop((vid.lower(), pid.lower()), None)
            return None
        finally:
            os.close(fd)


def _read_dpi(fd: int, feature_idx: int) -> Optional[int]:
    data = _request_retry(fd, feature_idx, 2, bytes([0]))  # getSensorDpi(sensor 0)
    return ((data[5] << 8) | data[6]) if data else None


def get_dpi(vid: str, pid: str) -> Optional[int]:
    """Current DPI read from the device, or None if HID++ is unavailable."""
    return _with_device(vid, pid, _read_dpi)


def set_dpi(vid: str, pid: str, dpi: int) -> bool:
    """Set DPI at runtime; True only if the device reports the new value back."""
    def action(fd: int, feature_idx: int) -> bool:
        if not _request_retry(fd, feature_idx, 3, bytes([0, dpi >> 8, dpi & 0xFF])):  # setSensorDpi
            return False
        return _read_dpi(fd, feature_idx) == dpi
    return bool(_with_device(vid, pid, action))
