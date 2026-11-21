"""Persistent application settings and XDG autostart desktop entry management."""

import json
import logging
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

APP_ID = "io.github.lhub.LHub"
AUTOSTART_FILENAME = f"{APP_ID}.desktop"

LOW_BATTERY_THRESHOLD_MIN = 5
LOW_BATTERY_THRESHOLD_MAX = 50
POLL_INTERVAL_MIN = 10
POLL_INTERVAL_MAX = 120

DEFAULT_SETTINGS: Dict[str, Any] = {
    "autostart": False,
    "start_minimized": False,
    "low_battery_threshold": 20,
    "notify_low_battery": True,
    "notify_profile_change": True,
    "poll_interval_sec": 30,
}

_DESKTOP_SPECIAL_CHARS = set(' \t\n"\'\\><~|&;$*?#()`')


def _xdg_config_home() -> Path:
    """Resolve XDG_CONFIG_HOME dynamically, falling back to ~/.config."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg_config:
        return Path(xdg_config).expanduser()
    return Path.home() / ".config"


def _coerce_bool(value: Any, default: bool) -> bool:
    """Coerce a value into a bool, falling back to default for invalid inputs."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return default
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _coerce_int_clamped(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Coerce a numeric value into an int clamped to [minimum, maximum]."""
    if isinstance(value, bool):
        return default
    parsed: Optional[int] = None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if math.isfinite(value):
            parsed = int(round(value))
    elif isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
                parsed = int(raw)
            except ValueError:
                try:
                    num = float(raw)
                except ValueError:
                    num = float("nan")
                if math.isfinite(num):
                    parsed = int(round(num))
    if parsed is None:
        return default
    return max(minimum, min(maximum, parsed))


def _validate_settings(raw: Dict[str, Any], base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge and validate known settings keys onto base (or DEFAULT_SETTINGS)."""
    merged = (base if base is not None else DEFAULT_SETTINGS).copy()
    if "autostart" in raw:
        merged["autostart"] = _coerce_bool(raw["autostart"], merged["autostart"])
    if "start_minimized" in raw:
        merged["start_minimized"] = _coerce_bool(raw["start_minimized"], merged["start_minimized"])
    if "low_battery_threshold" in raw:
        merged["low_battery_threshold"] = _coerce_int_clamped(
            raw["low_battery_threshold"],
            merged["low_battery_threshold"],
            LOW_BATTERY_THRESHOLD_MIN,
            LOW_BATTERY_THRESHOLD_MAX,
        )
    if "notify_low_battery" in raw:
        merged["notify_low_battery"] = _coerce_bool(raw["notify_low_battery"], merged["notify_low_battery"])
    if "notify_profile_change" in raw:
        merged["notify_profile_change"] = _coerce_bool(
            raw["notify_profile_change"],
            merged["notify_profile_change"],
        )
    if "poll_interval_sec" in raw:
        merged["poll_interval_sec"] = _coerce_int_clamped(
            raw["poll_interval_sec"],
            merged["poll_interval_sec"],
            POLL_INTERVAL_MIN,
            POLL_INTERVAL_MAX,
        )
    return merged


def _quote_desktop_arg(arg: str) -> str:
    """Quote a command argument according to the freedesktop Desktop Entry Spec."""
    if arg and not any(ch in _DESKTOP_SPECIAL_CHARS for ch in arg):
        return arg
    escaped = (
        arg.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return f'"{escaped}"'


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically to path via a temporary file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
        tmp_path.replace(path)
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def resolve_autostart_command(
    start_minimized: bool = False,
    local_bin: Optional[Path] = None,
    python_executable: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> tuple[str, Optional[Path]]:
    """Resolve the Exec command line and optional working directory for autostart."""
    launcher = Path(local_bin) if local_bin is not None else (Path.home() / ".local" / "bin" / "l-hub")
    if launcher.is_file() and os.access(launcher, os.X_OK):
        args = [str(launcher)]
        workdir: Optional[Path] = None
    else:
        py = python_executable or sys.executable or shutil.which("python3") or "python3"
        args = [py, "-m", "lhub"]
        workdir = Path(project_root) if project_root is not None else Path(__file__).resolve().parent.parent

    if start_minimized:
        args.append("--minimized")

    exec_line = " ".join(_quote_desktop_arg(arg) for arg in args)
    return exec_line, workdir


def build_autostart_desktop_entry(
    start_minimized: bool = False,
    local_bin: Optional[Path] = None,
    python_executable: Optional[str] = None,
    project_root: Optional[Path] = None,
) -> str:
    """Build the freedesktop .desktop file contents for L-Hub autostart."""
    exec_line, workdir = resolve_autostart_command(
        start_minimized=start_minimized,
        local_bin=local_bin,
        python_executable=python_executable,
        project_root=project_root,
    )
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=L-Hub",
        "Comment=Logitech and Peripheral Hub for Linux",
        f"Exec={exec_line}",
    ]
    if workdir is not None:
        lines.append(f"Path={workdir}")
    lines.extend([
        f"Icon={APP_ID}",
        "Terminal=false",
        "Categories=Utility;HardwareSettings;Settings;",
        f"StartupNotify={'false' if start_minimized else 'true'}",
        f"StartupWMClass={APP_ID}",
        "X-GNOME-Autostart-enabled=true",
    ])
    return "\n".join(lines) + "\n"


class SettingsManager:
    """Manages application-level settings persisted in ~/.config/lhub/settings.json."""

    def __init__(
        self,
        config_file: Optional[Path] = None,
        autostart_dir: Optional[Path] = None,
        local_bin: Optional[Path] = None,
    ):
        xdg_base = _xdg_config_home()
        self._file = Path(config_file) if config_file is not None else (xdg_base / "lhub" / "settings.json")
        self._autostart_file = (
            Path(autostart_dir) if autostart_dir is not None else (xdg_base / "autostart")
        ) / AUTOSTART_FILENAME
        self._local_bin = Path(local_bin) if local_bin is not None else None

        self._data: Dict[str, Any] = DEFAULT_SETTINGS.copy()
        self._load()

    @property
    def config_file(self) -> Path:
        return self._file

    @property
    def autostart_file(self) -> Path:
        return self._autostart_file

    @property
    def autostart(self) -> bool:
        return bool(self._data["autostart"])

    @property
    def start_minimized(self) -> bool:
        return bool(self._data["start_minimized"])

    @property
    def low_battery_threshold(self) -> int:
        return int(self._data["low_battery_threshold"])

    @property
    def notify_low_battery(self) -> bool:
        return bool(self._data["notify_low_battery"])

    @property
    def notify_profile_change(self) -> bool:
        return bool(self._data["notify_profile_change"])

    @property
    def poll_interval_sec(self) -> int:
        return int(self._data["poll_interval_sec"])

    def as_dict(self) -> Dict[str, Any]:
        return self._data.copy()

    def _load(self) -> None:
        if not self._file.exists():
            return
        try:
            with open(self._file, "r", encoding="utf-8") as handle:
                content = json.load(handle)
            if not isinstance(content, dict):
                logger.warning("Failed to load settings from %s: expected a JSON object", self._file)
                self._data = DEFAULT_SETTINGS.copy()
                return
            self._data = _validate_settings(content, base=DEFAULT_SETTINGS)
        except Exception as exc:
            logger.warning("Failed to load settings from %s: %s", self._file, exc)
            self._data = DEFAULT_SETTINGS.copy()

    def _save(self) -> bool:
        try:
            payload = json.dumps(self._data, indent=2, ensure_ascii=False) + "\n"
            _atomic_write_text(self._file, payload)
            return True
        except Exception as exc:
            logger.error("Failed to save settings to %s: %s", self._file, exc)
            return False

    def sync_autostart(self) -> bool:
        """Create, update, or remove the XDG autostart .desktop entry."""
        try:
            if self.autostart:
                content = build_autostart_desktop_entry(
                    start_minimized=self.start_minimized,
                    local_bin=self._local_bin,
                )
                _atomic_write_text(self._autostart_file, content)
                os.chmod(self._autostart_file, 0o644)
            else:
                self._autostart_file.unlink(missing_ok=True)
            return True
        except OSError as exc:
            logger.error("Failed to update autostart entry %s: %s", self._autostart_file, exc)
            return False

    def update(self, changes: Dict[str, Any]) -> bool:
        """Validate and persist a partial or full settings update."""
        if not isinstance(changes, dict):
            return False
        self._data = _validate_settings(changes, base=self._data)
        saved = self._save()
        synced = True
        if "autostart" in changes or "start_minimized" in changes:
            synced = self.sync_autostart()
        return saved and synced

    def set(self, key: str, value: Any) -> bool:
        """Update a single setting key and persist changes."""
        return self.update({key: value})

    def reset_defaults(self) -> bool:
        """Restore all settings to defaults, persist, and sync autostart."""
        return self.update(DEFAULT_SETTINGS.copy())
