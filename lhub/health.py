"""System health diagnostics for L-Hub hardware backends and permissions."""

from dataclasses import dataclass
import glob
import logging
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

SEVERITY_OK = "ok"
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
ISSUE_SEVERITIES = frozenset({SEVERITY_WARNING, SEVERITY_ERROR})

LOGITECH_VID = "046d"
RATBAGD_FIX_HINT = "sudo systemctl enable --now ratbagd"

_RATBAGD_ERROR_MARKERS = (
    "unable to connect",
    "ratbagd is not running",
    "no one currently owns",
    "ratbagd api version",
    "access denied",
    "permission denied",
)


@dataclass(frozen=True)
class HealthCheckItem:
    """Structured result for a single system health check."""

    id: str
    severity: str
    title: str
    description: str
    fix_hint: str = ""

    @property
    def is_issue(self) -> bool:
        return self.severity in ISSUE_SEVERITIES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "fixHint": self.fix_hint,
            "isIssue": self.is_issue,
        }


def _parse_hidraw_uevent(content: str) -> Tuple[str, str, str]:
    """Extract (vid, pid, hid_name) from a sysfs hidraw uevent file."""
    vid = ""
    pid = ""
    hid_name = ""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("HID_ID="):
            parts = line.split("=", 1)[1].split(":")
            if len(parts) >= 3:
                vid_raw = parts[1].strip().lower()
                pid_raw = parts[2].strip().lower()
                if vid_raw:
                    vid = vid_raw[-4:].zfill(4)
                if pid_raw:
                    pid = pid_raw[-4:].zfill(4)
        elif line.startswith("HID_NAME="):
            hid_name = line.split("=", 1)[1].strip()
    return vid, pid, hid_name


def _discover_relevant_hidraw_nodes(
    devices: Optional[Sequence[Any]] = None,
) -> List[Tuple[str, str, str, str]]:
    """Return (/dev/hidraw*, vid, pid, hid_name) for Logitech or headset devices."""
    known_pairs: Set[Tuple[str, str]] = set()
    if devices:
        for dev in devices:
            d_vid = (getattr(dev, "usb_vid", None) or "").strip().lower()
            d_pid = (getattr(dev, "usb_pid", None) or "").strip().lower()
            if d_vid and d_pid:
                known_pairs.add((d_vid[-4:].zfill(4), d_pid[-4:].zfill(4)))

    nodes: List[Tuple[str, str, str, str]] = []
    for sys_node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent_path = os.path.join(sys_node, "device", "uevent")
        try:
            with open(uevent_path, "r", encoding="utf-8", errors="ignore") as f:
                vid, pid, hid_name = _parse_hidraw_uevent(f.read())
        except OSError as exc:
            logger.debug("Could not read %s during health check: %s", uevent_path, exc)
            continue

        is_relevant = (
            vid == LOGITECH_VID
            or (bool(vid and pid) and (vid, pid) in known_pairs)
            or ("headset" in hid_name.lower())
        )
        if is_relevant:
            nodes.append((f"/dev/{os.path.basename(sys_node)}", vid, pid, hid_name))
    return nodes


def _build_hidraw_udev_hint(vids: Sequence[str]) -> str:
    """Build a copyable udev rule command for the given USB vendor IDs."""
    unique_vids: List[str] = []
    for raw_vid in vids:
        vid = raw_vid.strip().lower()
        if len(vid) == 4 and all(c in "0123456789abcdef" for c in vid):
            if vid not in unique_vids:
                unique_vids.append(vid)

    if not unique_vids:
        return "sudo udevadm control --reload-rules && sudo udevadm trigger"

    rules = [
        f'KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{{idVendor}}=="{vid}", TAG+="uaccess"'
        for vid in unique_vids
    ]
    reload_cmd = "sudo tee /etc/udev/rules.d/70-lhub-hidraw.rules && sudo udevadm control --reload-rules && sudo udevadm trigger"
    if len(rules) == 1:
        return f"echo '{rules[0]}' | {reload_cmd}"
    quoted_rules = " ".join(f"'{rule}'" for rule in rules)
    return f"printf '%s\\n' {quoted_rules} | {reload_cmd}"


def check_ratbagd() -> HealthCheckItem:
    """Verify ratbagctl is installed and the ratbagd daemon is reachable."""
    ratbagctl = shutil.which("ratbagctl")
    if not ratbagctl or not os.access(ratbagctl, os.X_OK):
        return HealthCheckItem(
            id="ratbagd",
            severity=SEVERITY_WARNING,
            title="libratbag (ratbagctl) is not installed",
            description=(
                "Gaming mouse configuration (DPI, profiles, button remapping) requires "
                "libratbag and the ratbagd daemon."
            ),
            fix_hint="sudo pacman -S libratbag && sudo systemctl enable --now ratbagd",
        )

    try:
        res = subprocess.run(
            [ratbagctl, "list"],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except subprocess.TimeoutExpired:
        return HealthCheckItem(
            id="ratbagd",
            severity=SEVERITY_ERROR,
            title="ratbagd service is not responding",
            description="Timed out waiting for ratbagctl to reach the ratbagd daemon.",
            fix_hint=RATBAGD_FIX_HINT,
        )
    except OSError as exc:
        return HealthCheckItem(
            id="ratbagd",
            severity=SEVERITY_ERROR,
            title="ratbagd check failed",
            description=f"Failed to execute ratbagctl: {exc}",
            fix_hint=RATBAGD_FIX_HINT,
        )

    combined = f"{res.stdout or ''}\n{res.stderr or ''}".strip()
    combined_lower = combined.lower()
    daemon_unreachable = res.returncode != 0 or any(
        marker in combined_lower for marker in _RATBAGD_ERROR_MARKERS
    )
    if daemon_unreachable:
        detail = combined.splitlines()[0] if combined else f"ratbagctl exited with code {res.returncode}."
        return HealthCheckItem(
            id="ratbagd",
            severity=SEVERITY_ERROR,
            title="ratbagd service is not running",
            description=f"Could not connect to ratbagd ({detail}). Mouse configuration is unavailable.",
            fix_hint=RATBAGD_FIX_HINT,
        )

    return HealthCheckItem(
        id="ratbagd",
        severity=SEVERITY_OK,
        title="ratbagd is running",
        description="libratbag daemon is reachable.",
        fix_hint="",
    )


def check_headsetcontrol() -> HealthCheckItem:
    """Verify the headsetcontrol CLI binary is installed and executable."""
    cmd = shutil.which("headsetcontrol")
    if not cmd or not os.access(cmd, os.X_OK):
        return HealthCheckItem(
            id="headsetcontrol",
            severity=SEVERITY_WARNING,
            title="HeadsetControl is not installed",
            description=(
                "Gaming headset battery, sidetone, and inactivity controls require "
                "the headsetcontrol CLI."
            ),
            fix_hint="sudo pacman -S headsetcontrol",
        )

    return HealthCheckItem(
        id="headsetcontrol",
        severity=SEVERITY_OK,
        title="HeadsetControl is available",
        description=f"Executable found at {cmd}.",
        fix_hint="",
    )


def check_hidraw_permissions(devices: Optional[Sequence[Any]] = None) -> HealthCheckItem:
    """Check read/write permissions on /dev/hidraw* nodes for Logitech/headset devices."""
    nodes = _discover_relevant_hidraw_nodes(devices)
    if not nodes:
        return HealthCheckItem(
            id="hidraw",
            severity=SEVERITY_OK,
            title="HID raw permissions OK",
            description="No Logitech or headset /dev/hidraw interfaces currently detected.",
            fix_hint="",
        )

    denied: List[Tuple[str, str, str, str]] = []
    accessible = 0
    for dev_path, vid, pid, hid_name in nodes:
        fd: Optional[int] = None
        try:
            fd = os.open(dev_path, os.O_RDWR | os.O_NONBLOCK)
            accessible += 1
        except PermissionError as exc:
            label = hid_name or (f"{vid}:{pid}" if vid and pid else dev_path)
            logger.warning("Permission denied accessing %s (%s): %s", dev_path, label, exc)
            denied.append((dev_path, vid, pid, hid_name))
        except OSError as exc:
            logger.debug("Skipping %s during permission check: %s", dev_path, exc)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError as exc:
                    logger.debug("Failed closing %s after permission check: %s", dev_path, exc)

    if denied:
        labels = [
            f"{name} ({path})" if name else path
            for path, _, _, name in denied[:3]
        ]
        summary = ", ".join(labels)
        if len(denied) > 3:
            summary += f" (+{len(denied) - 3} more)"
        hint = _build_hidraw_udev_hint([vid for _, vid, _, _ in denied if vid])
        return HealthCheckItem(
            id="hidraw",
            severity=SEVERITY_ERROR,
            title="Missing /dev/hidraw permissions",
            description=(
                f"Permission denied accessing {summary}. Direct HID++ controls, "
                "button testing, and headset access require udev permissions."
            ),
            fix_hint=hint,
        )

    return HealthCheckItem(
        id="hidraw",
        severity=SEVERITY_OK,
        title="HID raw permissions OK",
        description=f"Read/write access verified for {accessible} device interface(s).",
        fix_hint="",
    )


def check_upower() -> HealthCheckItem:
    """Check whether the optional UPower CLI fallback is available."""
    cmd = shutil.which("upower")
    if cmd and os.access(cmd, os.X_OK):
        return HealthCheckItem(
            id="upower",
            severity=SEVERITY_OK,
            title="UPower is available",
            description="UPower CLI is available as a wireless battery fallback.",
            fix_hint="",
        )

    return HealthCheckItem(
        id="upower",
        severity=SEVERITY_INFO,
        title="UPower not installed (optional)",
        description=(
            "UPower is an optional fallback for battery status of Bluetooth and "
            "generic wireless peripherals."
        ),
        fix_hint="sudo pacman -S upower",
    )


def log_health_checks(items: Sequence[HealthCheckItem]) -> None:
    """Emit structured log entries for health check outcomes."""
    for item in items:
        msg = f"Health [{item.id}] {item.title}: {item.description}"
        if item.fix_hint and item.is_issue:
            msg = f"{msg} | Fix: {item.fix_hint}"
        if item.severity == SEVERITY_ERROR:
            logger.error(msg)
        elif item.severity == SEVERITY_WARNING:
            logger.warning(msg)
        elif item.severity == SEVERITY_INFO:
            logger.info(msg)
        else:
            logger.debug(msg)


def run_health_checks(
    devices: Optional[Sequence[Any]] = None,
    log_results: bool = True,
) -> List[HealthCheckItem]:
    """Run all system health checks and return structured results."""
    items = [
        check_ratbagd(),
        check_headsetcontrol(),
        check_hidraw_permissions(devices=devices),
        check_upower(),
    ]
    if log_results:
        log_health_checks(items)
    return items
