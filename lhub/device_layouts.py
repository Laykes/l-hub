"""Data-driven mouse button layouts and safe factory-reset defaults."""

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Pattern, Tuple

logger = logging.getLogger(__name__)

BUNDLED_DEVICES_DIR = Path(__file__).resolve().parent / "data" / "devices"
VALID_GROUPS = frozenset({"main", "side", "wheel", "dpi"})
HEX_ID_RE = re.compile(r"^[0-9a-f]{4}$")

SAFE_STANDARD_DEFAULTS: Dict[int, str] = {
    0: "button 1",
    1: "button 2",
    2: "button 3",
    3: "button 4",
    4: "button 5",
}

_INDEX_FALLBACK_METADATA: Dict[int, Dict[str, str]] = {
    0: {
        "name": "Left Click",
        "label": "Left Click",
        "location": "Primary Left",
        "group": "main",
        "default": "button 1",
    },
    1: {
        "name": "Right Click",
        "label": "Right Click",
        "location": "Primary Right",
        "group": "main",
        "default": "button 2",
    },
    2: {
        "name": "Middle Click",
        "label": "Wheel Click",
        "location": "Scroll Wheel",
        "group": "wheel",
        "default": "button 3",
    },
    3: {
        "name": "Side Back (Button 4)",
        "label": "Back",
        "location": "Side Thumb",
        "group": "side",
        "default": "button 4",
    },
}

_BUTTON_4_FORWARD_METADATA: Dict[str, str] = {
    "name": "Side Forward (Button 5)",
    "label": "Forward",
    "location": "Side Thumb",
    "group": "side",
    "default": "button 5",
}

_ACTION_SUBSTRING_FALLBACKS: Tuple[Tuple[Tuple[str, ...], Dict[str, str]], ...] = (
    (
        ("wheel-left",),
        {
            "name": "Wheel Tilt Left",
            "label": "Tilt Left",
            "location": "Scroll Wheel",
            "group": "wheel",
            "default": "special wheel-left",
        },
    ),
    (
        ("wheel-right",),
        {
            "name": "Wheel Tilt Right",
            "label": "Tilt Right",
            "location": "Scroll Wheel",
            "group": "wheel",
            "default": "special wheel-right",
        },
    ),
    (
        ("resolution-alternate", "sniper"),
        {
            "name": "DPI Shift / Sniper",
            "label": "Sniper",
            "location": "Thumb Rest",
            "group": "side",
            "default": "special resolution-alternate",
        },
    ),
    (
        ("resolution-up",),
        {
            "name": "DPI Up",
            "label": "DPI Up",
            "location": "Top Controls",
            "group": "dpi",
            "default": "special resolution-up",
        },
    ),
    (
        ("resolution-down",),
        {
            "name": "DPI Down",
            "label": "DPI Down",
            "location": "Top Controls",
            "group": "dpi",
            "default": "special resolution-down",
        },
    ),
    (
        ("resolution-cycle",),
        {
            "name": "Cycle DPI",
            "label": "Cycle DPI",
            "location": "Top Controls",
            "group": "dpi",
            "default": "special resolution-cycle-up",
        },
    ),
    (
        ("profile-cycle",),
        {
            "name": "Cycle Profile",
            "label": "Cycle Profile",
            "location": "Top Controls",
            "group": "dpi",
            "default": "special profile-cycle-up",
        },
    ),
)


def get_user_devices_dir() -> Path:
    """Return the user override directory for custom device layout JSON files."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / "lhub" / "devices"


@dataclass(frozen=True)
class ButtonLayout:
    """Definition of a single physical device button and its factory default."""

    index: int
    name: str
    label: str
    location: str
    group: str
    default: str

    def to_metadata_dict(self) -> Dict[str, str]:
        """Return a fresh button metadata dict compatible with ratbag helpers."""
        return {
            "name": self.name,
            "label": self.label,
            "location": self.location,
            "group": self.group,
            "default": self.default,
        }


@dataclass(frozen=True)
class DeviceLayout:
    """Validated device layout definition loaded from a JSON file."""

    id: str
    name: str
    vendor: str
    vid: str
    pids: Tuple[str, ...]
    name_patterns: Tuple[str, ...]
    buttons: Dict[int, ButtonLayout]
    source_path: Optional[Path] = None
    is_user_override: bool = False


def _require_nonempty_str(obj: Dict[str, Any], key: str, ctx: str) -> str:
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"{ctx}: '{key}' must be a non-empty string")
    return val.strip()


def _parse_button_entry(entry: Any, idx_pos: int, ctx: str) -> ButtonLayout:
    btn_ctx = f"{ctx} button[{idx_pos}]"
    if not isinstance(entry, dict):
        raise ValueError(f"{btn_ctx}: must be a JSON object")

    b_idx = entry.get("index")
    if isinstance(b_idx, bool) or not isinstance(b_idx, int) or b_idx < 0:
        raise ValueError(f"{btn_ctx}: 'index' must be a non-negative integer")

    name = _require_nonempty_str(entry, "name", btn_ctx)
    label = _require_nonempty_str(entry, "label", btn_ctx)
    location = _require_nonempty_str(entry, "location", btn_ctx)
    group = _require_nonempty_str(entry, "group", btn_ctx)
    if group not in VALID_GROUPS:
        allowed = ", ".join(sorted(VALID_GROUPS))
        raise ValueError(f"{btn_ctx}: 'group' must be one of {allowed}, got '{group}'")
    default = _require_nonempty_str(entry, "default", btn_ctx)

    return ButtonLayout(
        index=b_idx,
        name=name,
        label=label,
        location=location,
        group=group,
        default=default,
    )


def validate_layout_data(
    data: Any,
    *,
    source: str = "<memory>",
    source_path: Optional[Path] = None,
    is_user_override: bool = False,
) -> DeviceLayout:
    """Validate raw JSON data and return a normalized DeviceLayout."""
    ctx = f"Device layout '{source}'"
    if not isinstance(data, dict):
        raise ValueError(f"{ctx}: root value must be a JSON object")

    layout_id = _require_nonempty_str(data, "id", ctx)
    name = _require_nonempty_str(data, "name", ctx)
    vendor = _require_nonempty_str(data, "vendor", ctx)

    vid_raw = data.get("vid")
    if not isinstance(vid_raw, str):
        raise ValueError(f"{ctx}: 'vid' must be a string")
    vid = vid_raw.strip().lower()
    if vid and not HEX_ID_RE.fullmatch(vid):
        raise ValueError(f"{ctx}: 'vid' must be a 4-digit hex string, got '{vid_raw}'")

    pids_raw = data.get("pids")
    if not isinstance(pids_raw, list):
        raise ValueError(f"{ctx}: 'pids' must be a list of strings")

    pids: List[str] = []
    seen_pids = set()
    for i, p_raw in enumerate(pids_raw):
        if not isinstance(p_raw, str):
            raise ValueError(f"{ctx}: pids[{i}] must be a string")
        pid = p_raw.strip().lower()
        if not HEX_ID_RE.fullmatch(pid):
            raise ValueError(f"{ctx}: pids[{i}] must be a 4-digit hex string, got '{p_raw}'")
        if pid in seen_pids:
            raise ValueError(f"{ctx}: duplicate pid '{pid}'")
        seen_pids.add(pid)
        pids.append(pid)

    if pids and not vid:
        raise ValueError(f"{ctx}: 'vid' must be non-empty when 'pids' are specified")

    patterns_raw = data.get("name_patterns", [])
    if not isinstance(patterns_raw, list):
        raise ValueError(f"{ctx}: 'name_patterns' must be a list of strings")
    patterns: List[str] = []
    for i, pat in enumerate(patterns_raw):
        if not isinstance(pat, str) or not pat.strip():
            raise ValueError(f"{ctx}: name_patterns[{i}] must be a non-empty string")
        try:
            re.compile(pat, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"{ctx}: invalid regex in name_patterns[{i}] ('{pat}'): {exc}") from exc
        patterns.append(pat)

    if not pids and not patterns:
        raise ValueError(f"{ctx}: at least one 'pids' entry or 'name_patterns' entry is required")

    buttons_raw = data.get("buttons")
    if not isinstance(buttons_raw, list) or not buttons_raw:
        raise ValueError(f"{ctx}: 'buttons' must be a non-empty list")

    buttons: Dict[int, ButtonLayout] = {}
    for pos, entry in enumerate(buttons_raw):
        btn = _parse_button_entry(entry, pos, ctx)
        if btn.index in buttons:
            raise ValueError(f"{ctx}: duplicate button index {btn.index}")
        buttons[btn.index] = btn

    return DeviceLayout(
        id=layout_id,
        name=name,
        vendor=vendor,
        vid=vid,
        pids=tuple(pids),
        name_patterns=tuple(patterns),
        buttons=buttons,
        source_path=source_path,
        is_user_override=is_user_override,
    )


def load_layout_file(path: Path, *, is_user_override: bool = False) -> DeviceLayout:
    """Load and validate a single device layout JSON file."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return validate_layout_data(
        data,
        source=str(path),
        source_path=path,
        is_user_override=is_user_override,
    )


def generic_button_metadata(b_idx: int, act_val: str, total_buttons: int) -> Dict[str, str]:
    """Return generic fallback button metadata when no device-specific layout entry applies."""
    if b_idx in _INDEX_FALLBACK_METADATA:
        return dict(_INDEX_FALLBACK_METADATA[b_idx])
    if b_idx == 4 and total_buttons <= 6:
        return dict(_BUTTON_4_FORWARD_METADATA)

    act_lower = (act_val or "").lower()
    for needles, meta in _ACTION_SUBSTRING_FALLBACKS:
        if any(needle in act_lower for needle in needles):
            return dict(meta)

    if act_lower == "button 4":
        return dict(_INDEX_FALLBACK_METADATA[3])
    if act_lower == "button 5":
        return dict(_BUTTON_4_FORWARD_METADATA)

    return {
        "name": f"Button {b_idx + 1}",
        "label": f"Button {b_idx + 1}",
        "location": "Mouse",
        "group": "main" if b_idx < 3 else ("side" if b_idx < 6 else "dpi"),
        "default": f"button {b_idx + 1}",
    }


class DeviceLayoutRegistry:
    """Registry that loads bundled and user device layouts and resolves button metadata."""

    def __init__(
        self,
        bundled_dir: Optional[Path] = None,
        user_dir: Optional[Path] = None,
    ):
        self._bundled_dir = Path(bundled_dir) if bundled_dir is not None else BUNDLED_DEVICES_DIR
        self._user_dir = Path(user_dir) if user_dir is not None else get_user_devices_dir()
        self._layouts_by_id: Dict[str, DeviceLayout] = {}
        self._vid_pid_index: Dict[Tuple[str, str], DeviceLayout] = {}
        self._compiled_patterns: List[Tuple[Pattern[str], DeviceLayout]] = []
        self.reload()

    @property
    def layouts(self) -> Tuple[DeviceLayout, ...]:
        """Return all active loaded device layouts."""
        return tuple(self._layouts_by_id.values())

    def _load_directory(
        self,
        directory: Path,
        *,
        is_user_override: bool,
        layouts_by_id: Dict[str, DeviceLayout],
    ) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.json")):
            try:
                layout = load_layout_file(path, is_user_override=is_user_override)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("Skipping invalid device layout %s: %s", path, exc)
                continue
            layouts_by_id[layout.id] = layout

    def reload(self) -> None:
        """Reload all bundled and user device layout definitions."""
        layouts_by_id: Dict[str, DeviceLayout] = {}
        self._load_directory(self._bundled_dir, is_user_override=False, layouts_by_id=layouts_by_id)
        self._load_directory(self._user_dir, is_user_override=True, layouts_by_id=layouts_by_id)

        bundled = [lay for lay in layouts_by_id.values() if not lay.is_user_override]
        overrides = [lay for lay in layouts_by_id.values() if lay.is_user_override]

        vid_pid_index: Dict[Tuple[str, str], DeviceLayout] = {}
        for lay in bundled + overrides:
            for pid in lay.pids:
                vid_pid_index[(lay.vid, pid)] = lay

        compiled_patterns: List[Tuple[Pattern[str], DeviceLayout]] = []
        for lay in overrides + bundled:
            for pat in lay.name_patterns:
                compiled_patterns.append((re.compile(pat, re.IGNORECASE), lay))

        self._layouts_by_id = layouts_by_id
        self._vid_pid_index = vid_pid_index
        self._compiled_patterns = compiled_patterns

    def find_layout(
        self,
        dev_name: str,
        vid: str = "",
        pid: str = "",
    ) -> Optional[DeviceLayout]:
        """Match a device layout by (vid, pid) first, then optional name_patterns."""
        norm_vid = (vid or "").strip().lower()
        norm_pid = (pid or "").strip().lower()
        if norm_vid and norm_pid:
            matched = self._vid_pid_index.get((norm_vid, norm_pid))
            if matched is not None:
                return matched

        if dev_name:
            for pattern, layout in self._compiled_patterns:
                if pattern.search(dev_name):
                    return layout
        return None

    def get_button_metadata(
        self,
        dev_name: str,
        vid: str,
        pid: str,
        b_idx: int,
        act_val: str,
        total_buttons: int,
    ) -> Dict[str, str]:
        """Return metadata for a button index using matched layout or generic fallback."""
        layout = self.find_layout(dev_name, vid, pid)
        if layout is not None and b_idx in layout.buttons:
            return layout.buttons[b_idx].to_metadata_dict()
        return generic_button_metadata(b_idx, act_val, total_buttons)

    def get_factory_reset_defaults(
        self,
        dev_name: str,
        vid: str = "",
        pid: str = "",
        total_buttons: Optional[int] = None,
    ) -> Dict[int, str]:
        """Return safe factory-reset default actions keyed by 0-based button index."""
        layout = self.find_layout(dev_name, vid, pid)
        if layout is not None:
            return {
                idx: btn.default
                for idx, btn in sorted(layout.buttons.items())
                if total_buttons is None or total_buttons <= 0 or idx < total_buttons
            }

        # No model layout: only reset well-known standard mouse buttons, never guess extras.
        if total_buttons is None or total_buttons <= 0:
            return {idx: SAFE_STANDARD_DEFAULTS[idx] for idx in (0, 1, 2)}
        if total_buttons <= 6:
            return {idx: SAFE_STANDARD_DEFAULTS[idx] for idx in range(min(total_buttons, 5))}
        return {idx: SAFE_STANDARD_DEFAULTS[idx] for idx in range(4)}


_default_registry: Optional[DeviceLayoutRegistry] = None
_default_registry_user_dir: Optional[Path] = None


def get_default_registry() -> DeviceLayoutRegistry:
    """Return the shared registry, refreshing if XDG_CONFIG_HOME changed."""
    global _default_registry, _default_registry_user_dir
    current_user_dir = get_user_devices_dir()
    if _default_registry is None or _default_registry_user_dir != current_user_dir:
        _default_registry = DeviceLayoutRegistry(user_dir=current_user_dir)
        _default_registry_user_dir = current_user_dir
    return _default_registry


def reload_layouts() -> DeviceLayoutRegistry:
    """Force a full reload of the shared device layout registry."""
    global _default_registry, _default_registry_user_dir
    current_user_dir = get_user_devices_dir()
    _default_registry = DeviceLayoutRegistry(user_dir=current_user_dir)
    _default_registry_user_dir = current_user_dir
    return _default_registry


def find_device_layout(
    dev_name: str,
    vid: str = "",
    pid: str = "",
) -> Optional[DeviceLayout]:
    """Convenience helper matching a device layout against the default registry."""
    return get_default_registry().find_layout(dev_name, vid, pid)


def get_button_metadata(
    dev_name: str,
    vid: str,
    pid: str,
    b_idx: int,
    act_val: str,
    total_buttons: int,
) -> Dict[str, str]:
    """Convenience helper resolving button metadata via the default registry."""
    return get_default_registry().get_button_metadata(dev_name, vid, pid, b_idx, act_val, total_buttons)


def get_factory_reset_defaults(
    dev_name: str,
    vid: str = "",
    pid: str = "",
    total_buttons: Optional[int] = None,
) -> Dict[int, str]:
    """Convenience helper resolving safe factory-reset defaults via the default registry."""
    return get_default_registry().get_factory_reset_defaults(dev_name, vid, pid, total_buttons)
