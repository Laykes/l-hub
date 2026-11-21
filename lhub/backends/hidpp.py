"""Minimal HID++ 2.0 access for runtime DPI control (0x2201) and onboard profile monitoring (0x8100).

libratbag commits onboard profiles, which fails with a USB timeout on some devices
(e.g. G502 X). ADJUSTABLE_DPI changes the DPI at runtime without writing a profile,
and ONBOARD_PROFILES provides live hardware profile-change notifications over hidraw.

Only Logitech devices (VID 046d) are ever accessed, and only the hidraw nodes whose
VID:PID match the requested device. Devices are addressed with index 0xFF (wired/direct).
"""
import glob
import logging
import os
import select
import threading
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

LOGITECH_VID = "046d"
_REPORT_SHORT = 0x10
_REPORT_LONG = 0x11
_DEVICE_INDEX = 0xFF
_SWID = 0x07
_FEATURE_ADJUSTABLE_DPI = 0x2201
_FEATURE_ONBOARD_PROFILES = 0x8100
_TIMEOUT = 0.5
_RETRIES = 3

_lock = threading.Lock()
# (vid, pid, feature_id) -> (hidraw path, feature index)
_cache: Dict[Tuple[str, str, int], Tuple[str, int]] = {}


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
        except OSError as exc:
            logger.debug("Skipping %s while scanning HID++ candidates: %s", node, exc)
            continue


def _locate(vid: str, pid: str, feature_id: int) -> Optional[Tuple[str, int]]:
    if vid.lower() != LOGITECH_VID:
        return None
    key = (vid.lower(), pid.lower(), feature_id)
    if key in _cache:
        return _cache[key]
    for path in _candidate_paths(vid, pid):
        try:
            fd = os.open(path, os.O_RDWR)
        except PermissionError as exc:
            logger.warning(
                "Permission denied opening %s for HID++ device %s:%s (check udev rules): %s",
                path,
                vid,
                pid,
                exc,
            )
            continue
        except OSError as exc:
            logger.debug("Could not open %s for HID++ probing: %s", path, exc)
            continue
        try:
            root = _request_retry(fd, 0x00, 0, bytes([feature_id >> 8, feature_id & 0xFF]))
            if root and root[4] != 0:
                _cache[key] = (path, root[4])
                return _cache[key]
        except OSError as exc:
            logger.debug("HID++ probe failed on %s (feature 0x%04X): %s", path, feature_id, exc)
        finally:
            os.close(fd)
    return None


def _with_device(vid: str, pid: str, feature_id: int, action):
    with _lock:
        loc = _locate(vid, pid, feature_id)
        if loc is None:
            return None
        path, feature_idx = loc
        try:
            fd = os.open(path, os.O_RDWR)
        except PermissionError as exc:
            logger.warning(
                "Permission denied opening %s for HID++ device %s:%s (check udev rules): %s",
                path,
                vid,
                pid,
                exc,
            )
            _cache.pop((vid.lower(), pid.lower(), feature_id), None)
            return None
        except OSError as exc:
            logger.debug("Could not reopen %s for HID++ request: %s", path, exc)
            _cache.pop((vid.lower(), pid.lower(), feature_id), None)
            return None
        try:
            return action(fd, feature_idx)
        except OSError as exc:
            logger.debug("HID++ request failed on %s: %s", path, exc)
            _cache.pop((vid.lower(), pid.lower(), feature_id), None)
            return None
        finally:
            os.close(fd)


def _read_dpi(fd: int, feature_idx: int) -> Optional[int]:
    data = _request_retry(fd, feature_idx, 2, bytes([0]))  # getSensorDpi(sensor 0)
    return ((data[5] << 8) | data[6]) if data else None


def get_dpi(vid: str, pid: str) -> Optional[int]:
    """Current DPI read from the device, or None if HID++ is unavailable."""
    return _with_device(vid, pid, _FEATURE_ADJUSTABLE_DPI, _read_dpi)


def set_dpi(vid: str, pid: str, dpi: int) -> bool:
    """Set DPI at runtime; True only if the device reports the new value back."""
    def action(fd: int, feature_idx: int) -> bool:
        if not _request_retry(fd, feature_idx, 3, bytes([0, dpi >> 8, dpi & 0xFF])):  # setSensorDpi
            return False
        return _read_dpi(fd, feature_idx) == dpi
    return bool(_with_device(vid, pid, _FEATURE_ADJUSTABLE_DPI, action))


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


def get_onboard_profile(vid: str, pid: str) -> Optional[int]:
    """Read current onboard profile ID via 0x8100 getCurrentProfile, or None."""
    def action(fd: int, feature_idx: int) -> Optional[int]:
        data = _request_retry(fd, feature_idx, 4)  # getCurrentProfile
        if not data or len(data) < 6:
            return None
        profile_id = (data[4] << 8) | data[5]
        return profile_id if profile_id != 0 else None
    return _with_device(vid, pid, _FEATURE_ONBOARD_PROFILES, action)


def set_onboard_profile(vid: str, pid: str, profile_id: int) -> bool:
    """Activate/reload an onboard profile via 0x8100 setCurrentProfile."""
    def action(fd: int, feature_idx: int) -> bool:
        data = _request_retry(fd, feature_idx, 3, bytes([(profile_id >> 8) & 0xFF, profile_id & 0xFF]))
        return data is not None
    return bool(_with_device(vid, pid, _FEATURE_ONBOARD_PROFILES, action))


def parse_onboard_event(data: bytes, feature_idx: int) -> Optional[Tuple[str, int]]:
    """Parse an unsolicited HID++ 0x8100 notification report."""
    if len(data) < 6:
        return None
    if data[0] not in (_REPORT_SHORT, _REPORT_LONG):
        return None
    if data[1] != _DEVICE_INDEX or data[2] != feature_idx:
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


class OnboardProfileMonitor:
    """Background hidraw listener for live HID++ 0x8100 profile/DPI change notifications."""

    def __init__(
        self,
        vid: str,
        pid: str,
        on_profile_changed: Callable[[int], None],
        on_dpi_changed: Optional[Callable[[int], None]] = None,
    ):
        self._vid = vid.lower()
        self._pid = pid.lower()
        self._on_profile_changed = on_profile_changed
        self._on_dpi_changed = on_dpi_changed
        self._thread: Optional[threading.Thread] = None
        self._stop_r: Optional[int] = None
        self._stop_w: Optional[int] = None
        self._pipe_lock = threading.Lock()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.is_running:
            return True
        with _lock:
            loc = _locate(self._vid, self._pid, _FEATURE_ONBOARD_PROFILES)
        if loc is None:
            return False
        path, feature_idx = loc
        try:
            fd = os.open(path, os.O_RDONLY)
        except PermissionError as exc:
            logger.warning(
                "Permission denied opening %s for HID++ monitor %s:%s (check udev rules): %s",
                path,
                self._vid,
                self._pid,
                exc,
            )
            return False
        except OSError as exc:
            logger.debug("Could not open %s for HID++ monitor: %s", path, exc)
            return False
        try:
            stop_r, stop_w = os.pipe()
        except OSError as exc:
            logger.warning("Failed to create pipe for HID++ monitor: %s", exc)
            os.close(fd)
            return False

        self._stop_r = stop_r
        self._stop_w = stop_w
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            args=(fd, stop_r, feature_idx),
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

    def _run(self, fd: int, stop_r: int, feature_idx: int):
        try:
            while self._running:
                ready, _, _ = select.select([fd, stop_r], [], [])
                if stop_r in ready or not self._running:
                    break
                if fd in ready:
                    data = os.read(fd, 64)
                    if not data:
                        break
                    ev = parse_onboard_event(data, feature_idx)
                    if ev is None:
                        continue
                    kind, val = ev
                    if kind == "profile":
                        self._on_profile_changed(val)
                    elif kind == "dpi_index" and self._on_dpi_changed is not None:
                        dpi = get_dpi(self._vid, self._pid)
                        if dpi and 50 <= dpi <= 30000:
                            self._on_dpi_changed(dpi)
        except OSError as exc:
            logger.debug("HID++ monitor stopped due to OSError: %s", exc)
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
