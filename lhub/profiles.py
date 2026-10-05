import os
import json
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any


DEFAULT_PROFILE = "Default"
PROTECTED_PROFILES = {"Default", "Standard"}


class ProfileManager:
    """Manages application-level device configuration profiles saved in ~/.config/lhub/profiles.json."""

    def __init__(self, config_file: Optional[Path] = None):
        if config_file:
            self._file = Path(config_file)
        else:
            xdg_config = os.environ.get("XDG_CONFIG_HOME")
            base = Path(xdg_config) if xdg_config else Path.home() / ".config"
            self._file = base / "lhub" / "profiles.json"

        self._data: Dict[str, Any] = {"active_profiles": {}, "profiles": {}}
        self._load()

    def _load(self):
        if not self._file.exists():
            return
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, dict):
                    self._data = {
                        "active_profiles": content.get("active_profiles", {}),
                        "profiles": content.get("profiles", {}),
                    }
        except Exception:
            self._data = {"active_profiles": {}, "profiles": {}}

    def _save(self):
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            # Write to temporary file first for atomic write
            temp_file = self._file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            temp_file.replace(self._file)
        except Exception as e:
            print(f"Error saving profiles: {e}")

    def get_profiles(self, device_key: str) -> List[str]:
        dev_profiles = self._data["profiles"].get(device_key, {})
        names = list(dev_profiles.keys())
        if not names:
            return [DEFAULT_PROFILE]
        for def_name in [DEFAULT_PROFILE, "Standard"]:
            if def_name in names and names[0] != def_name:
                names.remove(def_name)
                names.insert(0, def_name)
                break
        return names

    def get_active_profile(self, device_key: str) -> str:
        active = self._data["active_profiles"].get(device_key)
        available = self.get_profiles(device_key)
        if active and active in available:
            return active
        return available[0] if available else DEFAULT_PROFILE

    def set_active_profile(self, device_key: str, profile_name: str):
        self._data["active_profiles"][device_key] = profile_name
        self._save()

    def get_profile_data(self, device_key: str, profile_name: str) -> Optional[Dict[str, Any]]:
        dev_profiles = self._data["profiles"].get(device_key, {})
        return dev_profiles.get(profile_name)

    def save_profile(
        self,
        device_key: str,
        profile_name: str,
        buttons: Dict[int, str],
        dpi: Optional[int] = None,
    ):
        profile_name = profile_name.strip()
        if not profile_name:
            return

        if device_key not in self._data["profiles"]:
            self._data["profiles"][device_key] = {}

        # Convert button keys to strings for JSON
        btn_dict = {str(k): v for k, v in buttons.items()}
        data: Dict[str, Any] = {"buttons": btn_dict}
        if dpi is not None and dpi > 0:
            data["dpi"] = dpi

        self._data["profiles"][device_key][profile_name] = data
        self._data["active_profiles"][device_key] = profile_name
        self._save()

    def delete_profile(self, device_key: str, profile_name: str) -> bool:
        dev_profiles = self._data["profiles"].get(device_key, {})
        if profile_name in dev_profiles and profile_name not in PROTECTED_PROFILES:
            del dev_profiles[profile_name]
            if self.get_active_profile(device_key) == profile_name:
                remaining = self.get_profiles(device_key)
                self._data["active_profiles"][device_key] = remaining[0] if remaining else DEFAULT_PROFILE
            self._save()
            return True
        return False

    def update_active_button(self, device_key: str, button_idx: int, action: str):
        active = self.get_active_profile(device_key)
        dev_profiles = self._data["profiles"].setdefault(device_key, {})
        prof_data = dev_profiles.setdefault(active, {"buttons": {}})
        prof_data.setdefault("buttons", {})[str(button_idx)] = action
        self._save()

    def update_active_dpi(self, device_key: str, dpi: int):
        active = self.get_active_profile(device_key)
        dev_profiles = self._data["profiles"].setdefault(device_key, {})
        prof_data = dev_profiles.setdefault(active, {"buttons": {}})
        prof_data["dpi"] = dpi
        self._save()

    def ensure_default_profile(
        self,
        device_key: str,
        buttons: Dict[int, str],
        dpi: Optional[int] = None,
    ):
        dev_profiles = self._data["profiles"].get(device_key, {})
        if not any(p in dev_profiles for p in PROTECTED_PROFILES) and buttons:
            btn_dict = {str(k): v for k, v in buttons.items()}
            data: Dict[str, Any] = {"buttons": btn_dict}
            if dpi is not None and dpi > 0:
                data["dpi"] = dpi
            self._data["profiles"].setdefault(device_key, {})[DEFAULT_PROFILE] = data
            if device_key not in self._data["active_profiles"]:
                self._data["active_profiles"][device_key] = DEFAULT_PROFILE
            self._save()

    def reset_to_default(
        self,
        device_key: str,
        buttons: Dict[int, str],
        dpi: Optional[int] = None,
    ):
        btn_dict = {str(k): v for k, v in buttons.items()}
        data: Dict[str, Any] = {"buttons": btn_dict}
        if dpi is not None and dpi > 0:
            data["dpi"] = dpi

        dev_profiles = self._data["profiles"].setdefault(device_key, {})
        dev_profiles[DEFAULT_PROFILE] = data
        if "Standard" in dev_profiles:
            dev_profiles["Standard"] = data.copy()
        self._data["active_profiles"][device_key] = DEFAULT_PROFILE
        self._save()
