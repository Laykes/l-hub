"""PipeWire USB microphone backend with native filter-chain EQ and live voice monitoring."""

from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import BaseBackend, Capability, Device, DeviceType, EqBand, MicrophoneInfo

logger = logging.getLogger(__name__)

MIC_VOLUME_MIN = 0
MIC_VOLUME_MAX = 150
EQ_GAIN_MIN = -12.0
EQ_GAIN_MAX = 12.0
HPF_FREQ_MIN = 40
HPF_FREQ_MAX = 250
HPF_BYPASS_FREQ = 10.0

EXCLUDED_FORM_FACTORS = frozenset({
    "controller",
    "gamepad",
    "joystick",
    "headset",
    "handset",
    "webcam",
})

EXCLUDED_NAME_KEYWORDS = (
    "dualshock",
    "dualsense",
    "wireless controller",
    "xbox",
    "headset",
    "webcam",
)

# 6 classic vocal EQ bands covering rumble/warmth/mud/vocal/presence/air
DEFAULT_EQ_BAND_SPECS: Tuple[Tuple[str, str, float, str, str, float], ...] = (
    ("eq_band_1", "Bass", 80.0, "80 Hz", "bq_lowshelf", 0.707),
    ("eq_band_2", "Warmth", 200.0, "200 Hz", "bq_peaking", 1.0),
    ("eq_band_3", "Low-Mid", 500.0, "500 Hz", "bq_peaking", 1.0),
    ("eq_band_4", "Vocal", 1500.0, "1.5 kHz", "bq_peaking", 1.0),
    ("eq_band_5", "Presence", 4000.0, "4 kHz", "bq_peaking", 1.0),
    ("eq_band_6", "Air", 10000.0, "10 kHz", "bq_highshelf", 0.707),
)

BUILTIN_EQ_PRESETS: Tuple[Dict[str, Any], ...] = (
    {
        "name": "Flat",
        "description": "Neutral response with all bands at 0 dB",
        "highpass_enabled": False,
        "highpass_freq": 80,
        "bands": {
            "eq_band_1": 0.0,
            "eq_band_2": 0.0,
            "eq_band_3": 0.0,
            "eq_band_4": 0.0,
            "eq_band_5": 0.0,
            "eq_band_6": 0.0,
        },
    },
    {
        "name": "Broadcast",
        "description": "Full studio voice with clean low-mid cut and crisp presence",
        "highpass_enabled": True,
        "highpass_freq": 80,
        "bands": {
            "eq_band_1": 3.0,
            "eq_band_2": 2.0,
            "eq_band_3": -3.0,
            "eq_band_4": 1.0,
            "eq_band_5": 3.5,
            "eq_band_6": 2.0,
        },
    },
    {
        "name": "Discord",
        "description": "Clear, punchy voice chat optimized for speech intelligibility",
        "highpass_enabled": True,
        "highpass_freq": 100,
        "bands": {
            "eq_band_1": -2.0,
            "eq_band_2": -1.0,
            "eq_band_3": -2.5,
            "eq_band_4": 2.0,
            "eq_band_5": 4.0,
            "eq_band_6": 2.5,
        },
    },
    {
        "name": "Warm Voice",
        "description": "Rich low end and smooth highs for podcasting",
        "highpass_enabled": True,
        "highpass_freq": 70,
        "bands": {
            "eq_band_1": 4.0,
            "eq_band_2": 3.0,
            "eq_band_3": -2.0,
            "eq_band_4": -0.5,
            "eq_band_5": 2.0,
            "eq_band_6": 1.0,
        },
    },
    {
        "name": "Radio",
        "description": "Classic mid-focused communications / vintage radio tone",
        "highpass_enabled": True,
        "highpass_freq": 180,
        "bands": {
            "eq_band_1": -8.0,
            "eq_band_2": -4.0,
            "eq_band_3": 3.0,
            "eq_band_4": 5.5,
            "eq_band_5": 2.0,
            "eq_band_6": -6.0,
        },
    },
)


def _c_locale_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LC_NUMERIC"] = "C"
    return env


def clamp_mic_volume(volume: Any) -> int:
    try:
        val = int(round(float(volume)))
    except (TypeError, ValueError):
        return 100
    return max(MIC_VOLUME_MIN, min(MIC_VOLUME_MAX, val))


def clamp_eq_gain(gain: Any) -> float:
    try:
        val = float(gain)
    except (TypeError, ValueError):
        return 0.0
    val = max(EQ_GAIN_MIN, min(EQ_GAIN_MAX, val))
    return round(val * 2.0) / 2.0  # 0.5 dB precision


def clamp_hpf_freq(freq: Any) -> int:
    try:
        val = int(round(float(freq)))
    except (TypeError, ValueError):
        return 80
    return max(HPF_FREQ_MIN, min(HPF_FREQ_MAX, val))


def create_default_eq_bands(gains: Optional[Dict[str, float]] = None) -> List[EqBand]:
    gain_map = gains or {}
    return [
        EqBand(
            id=band_id,
            label=label,
            freq=freq,
            freq_label=freq_label,
            filter_type=filter_type,
            q=q,
            gain=clamp_eq_gain(gain_map.get(band_id, 0.0)),
        )
        for band_id, label, freq, freq_label, filter_type, q in DEFAULT_EQ_BAND_SPECS
    ]


def get_builtin_eq_preset(preset_name: str) -> Optional[Dict[str, Any]]:
    target = (preset_name or "").strip().lower()
    for preset in BUILTIN_EQ_PRESETS:
        if preset["name"].lower() == target:
            return preset
    return None


def mic_info_to_config(mic: MicrophoneInfo) -> Dict[str, Any]:
    """Serialize MicrophoneInfo tuning settings for profile persistence."""
    bands = mic.bands if mic.bands else create_default_eq_bands()
    return {
        "volume": clamp_mic_volume(mic.volume),
        "eq_enabled": bool(mic.eq_enabled),
        "highpass_enabled": bool(mic.highpass_enabled),
        "highpass_freq": clamp_hpf_freq(mic.highpass_freq),
        "bands": {b.id: clamp_eq_gain(b.gain) for b in bands},
    }


def apply_config_to_mic_info(mic: MicrophoneInfo, config: Dict[str, Any]) -> None:
    """Apply a stored microphone profile dict onto a MicrophoneInfo instance."""
    if not isinstance(config, dict):
        return
    if "volume" in config:
        mic.volume = clamp_mic_volume(config["volume"])
    if "eq_enabled" in config:
        mic.eq_enabled = bool(config["eq_enabled"])
    if "highpass_enabled" in config:
        mic.highpass_enabled = bool(config["highpass_enabled"])
    if "highpass_freq" in config:
        mic.highpass_freq = clamp_hpf_freq(config["highpass_freq"])
    if not mic.bands:
        mic.bands = create_default_eq_bands()
    raw_bands = config.get("bands")
    if isinstance(raw_bands, dict):
        for band in mic.bands:
            if band.id in raw_bands:
                band.gain = clamp_eq_gain(raw_bands[band.id])


def normalize_hex_usb_id(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text or not all(c in "0123456789abcdef" for c in text):
        return None
    return text[-4:].zfill(4)


def linear_volume_to_percent(linear: float) -> int:
    """Convert PipeWire cubic channel volume (0.0..3.375) to percentage (0..150)."""
    if linear <= 0.0:
        return 0
    return clamp_mic_volume(round((linear ** (1.0 / 3.0)) * 100.0))


def _sanitize_node_token(raw: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_]+", "_", raw.strip().lower()).strip("_")
    return token or "usb_mic"


def _escape_pw_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def build_filter_chain_config(mic: MicrophoneInfo, capture_node_name: str) -> str:
    """Render a standalone PipeWire filter-chain configuration for a USB microphone."""
    hpf_freq = float(clamp_hpf_freq(mic.highpass_freq)) if (mic.eq_enabled and mic.highpass_enabled) else HPF_BYPASS_FREQ
    bands = mic.bands if mic.bands else create_default_eq_bands()

    node_entries: List[str] = [
        (
            "                    {\n"
            "                        type  = builtin\n"
            "                        name  = hpf\n"
            "                        label = bq_highpass\n"
            f'                        control = {{ "Freq" = {hpf_freq:.1f} "Q" = 0.707 "Gain" = 0.0 }}\n'
            "                    }"
        )
    ]

    for band in bands:
        eff_gain = float(clamp_eq_gain(band.gain)) if mic.eq_enabled else 0.0
        node_entries.append(
            "                    {\n"
            "                        type  = builtin\n"
            f"                        name  = {band.id}\n"
            f"                        label = {band.filter_type}\n"
            f'                        control = {{ "Freq" = {band.freq:.1f} "Q" = {band.q:.3f} "Gain" = {eff_gain:.1f} }}\n'
            "                    }"
        )

    chain_names = ["hpf"] + [band.id for band in bands]
    link_entries = [
        f'                    {{ output = "{chain_names[i]}:Out" input = "{chain_names[i + 1]}:In" }}'
        for i in range(len(chain_names) - 1)
    ]

    channels = 1 if mic.channels == 1 else 2
    position = "[ MONO ]" if channels == 1 else "[ FL FR ]"
    desc = _escape_pw_string(mic.virtual_source_description or "L-Hub Mic EQ")
    target_source = _escape_pw_string(mic.source_name)
    cap_name = _escape_pw_string(capture_node_name)
    virt_name = _escape_pw_string(mic.virtual_source_name)

    nodes_block = "\n".join(node_entries)
    links_block = "\n".join(link_entries)

    return (
        "# Generated by L-Hub — PipeWire native microphone equalizer filter-chain\n"
        "context.properties = {\n"
        "    log.level = 0\n"
        "}\n"
        "\n"
        "context.spa-libs = {\n"
        "    audio.convert.* = audioconvert/libspa-audioconvert\n"
        "    support.*       = support/libspa-support\n"
        "}\n"
        "\n"
        "context.modules = [\n"
        "    { name = libpipewire-module-rt\n"
        "        flags = [ ifexists nofail ]\n"
        "    }\n"
        "    { name = libpipewire-module-protocol-native }\n"
        "    { name = libpipewire-module-client-node }\n"
        "    { name = libpipewire-module-adapter }\n"
        "    { name = libpipewire-module-filter-chain\n"
        "        args = {\n"
        f'            node.description = "{desc}"\n'
        f'            media.name       = "{desc}"\n'
        "            filter.graph = {\n"
        "                nodes = [\n"
        f"{nodes_block}\n"
        "                ]\n"
        "                links = [\n"
        f"{links_block}\n"
        "                ]\n"
        "            }\n"
        f"            audio.channels = {channels}\n"
        f"            audio.position = {position}\n"
        "            capture.props = {\n"
        f'                node.name        = "{cap_name}"\n'
        f'                node.description = "{desc} Input"\n'
        "                node.passive     = true\n"
        f'                target.object    = "{target_source}"\n'
        "            }\n"
        "            playback.props = {\n"
        f'                node.name        = "{virt_name}"\n'
        f'                node.description = "{desc}"\n'
        "                media.class      = Audio/Source\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "]\n"
    )


def build_pw_cli_eq_params(mic: MicrophoneInfo) -> str:
    """Build SPA JSON Props payload for live pw-cli EQ parameter updates."""
    hpf_freq = float(clamp_hpf_freq(mic.highpass_freq)) if (mic.eq_enabled and mic.highpass_enabled) else HPF_BYPASS_FREQ
    bands = mic.bands if mic.bands else create_default_eq_bands()
    parts = [f'"hpf:Freq" {hpf_freq:.1f}']
    for band in bands:
        eff_gain = float(clamp_eq_gain(band.gain)) if mic.eq_enabled else 0.0
        parts.append(f'"{band.id}:Gain" {eff_gain:.1f}')
    return "{ params = [ " + " ".join(parts) + " ] }"


class PipeWireMicBackend(BaseBackend):
    """Discovers USB microphones via PipeWire and manages native EQ filter-chains & live monitoring."""

    def __init__(self, config_dir: Optional[Path] = None):
        super().__init__("pipewire")
        if config_dir is not None:
            self._config_dir = Path(config_dir)
        else:
            xdg_config = os.environ.get("XDG_CONFIG_HOME")
            base = Path(xdg_config) if xdg_config else Path.home() / ".config"
            self._config_dir = base / "lhub" / "pipewire"

        self._lock = threading.RLock()
        self._mics: Dict[str, MicrophoneInfo] = {}
        self._capture_node_names: Dict[str, str] = {}
        self._capture_node_ids: Dict[str, int] = {}
        self._filter_procs: Dict[str, subprocess.Popen] = {}
        self._monitor_proc: Optional[subprocess.Popen] = None
        self._monitor_device_id: Optional[str] = None

        self._sub_proc: Optional[subprocess.Popen] = None
        self._sub_thread: Optional[threading.Thread] = None
        self._sub_stop = threading.Event()

    def is_available(self) -> bool:
        return all(
            shutil.which(cmd) is not None
            for cmd in ("pw-dump", "pw-cli", "pipewire", "pactl")
        )

    def get_missing_reason(self) -> str:
        return ""

    @property
    def supports_hotplug(self) -> bool:
        return shutil.which("pactl") is not None

    def start_monitoring(self, on_change: Callable[[], None]) -> bool:
        if not self.supports_hotplug:
            return False
        self.stop_monitoring()
        self._sub_stop.clear()
        try:
            proc = subprocess.Popen(
                ["pactl", "subscribe"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                text=True,
                env=_c_locale_env(),
            )
        except OSError as exc:
            logger.debug("Failed to start pactl subscribe: %s", exc)
            return False

        self._sub_proc = proc

        def _reader() -> None:
            try:
                assert proc.stdout is not None
                for raw_line in proc.stdout:
                    if self._sub_stop.is_set():
                        break
                    line = raw_line.strip().lower()
                    if self._should_trigger_hotplug(line):
                        on_change()
            except Exception as exc:
                logger.debug("pactl subscribe loop ended: %s", exc)

        thread = threading.Thread(target=_reader, name="lhub-pw-hotplug", daemon=True)
        self._sub_thread = thread
        thread.start()
        return True

    @staticmethod
    def _should_trigger_hotplug(line: str) -> bool:
        if not line:
            return False
        if "on card" in line and ("'new'" in line or "'remove'" in line):
            return True
        if "on source" in line and ("'new'" in line or "'remove'" in line):
            return True
        if "'change'" in line and "on server" in line:
            return True
        return False

    def stop_monitoring(self) -> None:
        self._sub_stop.set()
        proc = self._sub_proc
        self._sub_proc = None
        if proc is not None:
            self._terminate_process(proc)
        thread = self._sub_thread
        self._sub_thread = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _run_pw_dump(self, obj_id: Optional[int] = None) -> List[Dict[str, Any]]:
        cmd = ["pw-dump"]
        if obj_id is not None:
            cmd.append(str(obj_id))
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3.0,
                env=_c_locale_env(),
            )
            if res.returncode != 0 or not res.stdout.strip():
                return []
            data = json.loads(res.stdout)
            return data if isinstance(data, list) else []
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            logger.debug("pw-dump failed: %s", exc)
            return []

    @staticmethod
    def _extract_default_source(objects: List[Dict[str, Any]]) -> str:
        for obj in objects:
            if obj.get("type") != "PipeWire:Interface:Metadata":
                continue
            props = obj.get("props") or {}
            if props.get("metadata.name") != "default":
                continue
            for entry in obj.get("metadata") or []:
                if entry.get("key") == "default.audio.source":
                    val = entry.get("value")
                    if isinstance(val, dict) and isinstance(val.get("name"), str):
                        return val["name"]
                    if isinstance(val, str):
                        try:
                            parsed = json.loads(val)
                            if isinstance(parsed, dict) and isinstance(parsed.get("name"), str):
                                return parsed["name"]
                        except json.JSONDecodeError:
                            return val
        return ""

    @staticmethod
    def _extract_volume_and_mute(node_obj: Dict[str, Any]) -> Tuple[int, bool]:
        props_list = (node_obj.get("info") or {}).get("params", {}).get("Props") or []
        volume_pct = 100
        muted = False
        for entry in props_list:
            if not isinstance(entry, dict):
                continue
            if "mute" in entry:
                muted = bool(entry["mute"])
            ch_vols = entry.get("channelVolumes")
            if isinstance(ch_vols, list) and ch_vols:
                try:
                    avg_linear = sum(float(v) for v in ch_vols) / len(ch_vols)
                    volume_pct = linear_volume_to_percent(avg_linear)
                except (TypeError, ValueError):
                    pass
            elif "volume" in entry:
                try:
                    volume_pct = linear_volume_to_percent(float(entry["volume"]))
                except (TypeError, ValueError):
                    pass
        return volume_pct, muted

    @staticmethod
    def _is_usb_microphone(node_props: Dict[str, Any], dev_props: Dict[str, Any]) -> bool:
        node_name = str(node_props.get("node.name") or "")
        if not node_name:
            return False
        if (
            node_name.startswith("lhub_eq_")
            or node_name.startswith("easyeffects_")
            or node_name.startswith("effect_")
            or ".monitor" in node_name
        ):
            return False

        factory = str(node_props.get("factory.name") or "")
        if factory and factory != "api.alsa.pcm.source":
            return False

        bus = str(node_props.get("device.bus") or dev_props.get("device.bus") or "").lower()
        if bus != "usb":
            return False

        form_factor = str(
            node_props.get("device.form-factor")
            or dev_props.get("device.form-factor")
            or ""
        ).lower()
        if form_factor in EXCLUDED_FORM_FACTORS:
            return False

        if form_factor == "microphone":
            return True

        combined_text = " ".join(
            str(x or "")
            for x in (
                dev_props.get("device.product.name"),
                dev_props.get("device.description"),
                dev_props.get("device.nick"),
                node_props.get("node.description"),
                node_props.get("api.alsa.card.name"),
            )
        ).lower()

        if any(keyword in combined_text for keyword in EXCLUDED_NAME_KEYWORDS):
            return False

        return True

    def scan_devices(self) -> List[Device]:
        objects = self._run_pw_dump()
        if not objects:
            return []

        default_source = self._extract_default_source(objects)
        audio_devices: Dict[int, Dict[str, Any]] = {}
        live_nodes_by_name: Dict[str, int] = {}

        for obj in objects:
            obj_type = obj.get("type")
            obj_id = obj.get("id")
            props = (obj.get("info") or {}).get("props") or {}
            if obj_type == "PipeWire:Interface:Device" and props.get("media.class") == "Audio/Device":
                if isinstance(obj_id, int):
                    audio_devices[obj_id] = props
            elif obj_type == "PipeWire:Interface:Node":
                n_name = props.get("node.name")
                if isinstance(n_name, str) and isinstance(obj_id, int):
                    live_nodes_by_name[n_name] = obj_id

        discovered: List[Device] = []
        active_ids: set[str] = set()

        with self._lock:
            # Reap monitor process if it exited on its own
            if self._monitor_proc is not None and self._monitor_proc.poll() is not None:
                self._monitor_proc = None
                self._monitor_device_id = None

            for obj in objects:
                if obj.get("type") != "PipeWire:Interface:Node":
                    continue
                node_props = (obj.get("info") or {}).get("props") or {}
                if node_props.get("media.class") != "Audio/Source":
                    continue

                parent_dev_id = node_props.get("device.id")
                dev_props = audio_devices.get(parent_dev_id, {}) if isinstance(parent_dev_id, int) else {}

                if not self._is_usb_microphone(node_props, dev_props):
                    continue

                source_name = str(node_props.get("node.name") or "")
                usb_vid = normalize_hex_usb_id(
                    dev_props.get("device.vendor.id") or node_props.get("device.vendor.id")
                )
                usb_pid = normalize_hex_usb_id(
                    dev_props.get("device.product.id") or node_props.get("device.product.id")
                )
                vendor = str(
                    dev_props.get("device.vendor.name")
                    or node_props.get("device.vendor.name")
                    or "USB Audio"
                ).strip()
                name = str(
                    dev_props.get("device.product.name")
                    or dev_props.get("device.description")
                    or node_props.get("node.description")
                    or node_props.get("api.alsa.card.name")
                    or "USB Microphone"
                ).strip()

                if usb_vid and usb_pid:
                    safe_key = f"{usb_vid}_{usb_pid}"
                else:
                    safe_key = _sanitize_node_token(source_name)

                device_id = f"mic_{safe_key}"
                if device_id in active_ids:
                    # Handle rare duplicate USB mics with identical VID:PID
                    safe_key = _sanitize_node_token(source_name)
                    device_id = f"mic_{safe_key}"
                active_ids.add(device_id)

                capture_node_name = f"lhub_eq_capture.{safe_key}"
                virtual_source_name = f"lhub_eq_source.{safe_key}"
                virtual_desc = f"L-Hub: {name}"

                volume, muted = self._extract_volume_and_mute(obj)
                channels_raw = node_props.get("audio.channels", 2)
                try:
                    channels = int(channels_raw)
                except (TypeError, ValueError):
                    channels = 2
                channel_position = "[ MONO ]" if channels == 1 else "[ FL FR ]"

                # Check live filter-chain status
                fc_proc = self._filter_procs.get(device_id)
                if fc_proc is not None and fc_proc.poll() is not None:
                    self._filter_procs.pop(device_id, None)
                cap_node_id = live_nodes_by_name.get(capture_node_name)
                if cap_node_id is not None:
                    self._capture_node_ids[device_id] = cap_node_id
                else:
                    self._capture_node_ids.pop(device_id, None)
                virtual_active = virtual_source_name in live_nodes_by_name

                existing = self._mics.get(device_id)
                if existing is not None:
                    bands = [replace(b) for b in existing.bands] if existing.bands else create_default_eq_bands()
                    eq_enabled = existing.eq_enabled
                    highpass_enabled = existing.highpass_enabled
                    highpass_freq = existing.highpass_freq
                else:
                    bands = create_default_eq_bands()
                    eq_enabled = True
                    highpass_enabled = False
                    highpass_freq = 80

                mic_info = MicrophoneInfo(
                    source_name=source_name,
                    source_node_id=obj.get("id") if isinstance(obj.get("id"), int) else None,
                    channels=channels,
                    channel_position=channel_position,
                    volume=volume,
                    muted=muted,
                    eq_enabled=eq_enabled,
                    highpass_enabled=highpass_enabled,
                    highpass_freq=highpass_freq,
                    bands=bands,
                    virtual_source_name=virtual_source_name,
                    virtual_source_description=virtual_desc,
                    virtual_source_active=virtual_active,
                    is_eq_default_source=(default_source == virtual_source_name),
                    is_raw_default_source=(default_source == source_name),
                    monitoring=(self._monitor_device_id == device_id and self._monitor_proc is not None),
                )

                self._mics[device_id] = mic_info
                self._capture_node_names[device_id] = capture_node_name

                discovered.append(
                    Device(
                        id=device_id,
                        name=name,
                        vendor=vendor,
                        device_type=DeviceType.MICROPHONE,
                        usb_vid=usb_vid,
                        usb_pid=usb_pid,
                        capabilities=[
                            Capability.AUDIO_GAIN,
                            Capability.AUDIO_MUTE,
                            Capability.EQUALIZER,
                            Capability.PROFILES,
                            Capability.MIC_MONITOR,
                        ],
                        microphone=self._clone_mic_info(mic_info),
                        backend_name=self.name,
                    )
                )

            # Clean up processes for disconnected microphones
            stale_ids = [did for did in list(self._filter_procs.keys()) if did not in active_ids]
            for stale_id in stale_ids:
                self._stop_filter_chain_locked(stale_id)
            if self._monitor_device_id and self._monitor_device_id not in active_ids:
                self._stop_monitoring_locked()

        return discovered

    @staticmethod
    def _clone_mic_info(mic: MicrophoneInfo) -> MicrophoneInfo:
        return replace(mic, bands=[replace(b) for b in mic.bands])

    def get_microphone_info(self, device_id: str) -> Optional[MicrophoneInfo]:
        with self._lock:
            mic = self._mics.get(device_id)
            return self._clone_mic_info(mic) if mic is not None else None

    def _find_capture_node_id(self, capture_node_name: str) -> Optional[int]:
        for obj in self._run_pw_dump():
            if obj.get("type") != "PipeWire:Interface:Node":
                continue
            props = (obj.get("info") or {}).get("props") or {}
            if props.get("node.name") == capture_node_name and isinstance(obj.get("id"), int):
                return obj["id"]
        return None

    def ensure_filter_chain(self, device_id: str) -> bool:
        """Start the PipeWire filter-chain process for this microphone if not already live."""
        with self._lock:
            mic = self._mics.get(device_id)
            capture_node_name = self._capture_node_names.get(device_id)
            if mic is None or not capture_node_name:
                return False

            proc = self._filter_procs.get(device_id)
            if proc is not None and proc.poll() is None:
                if device_id in self._capture_node_ids:
                    mic.virtual_source_active = True
                    return True
                found_id = self._find_capture_node_id(capture_node_name)
                if found_id is not None:
                    self._capture_node_ids[device_id] = found_id
                    mic.virtual_source_active = True
                    return True

            # Reuse already-running PipeWire node if present from an external session
            existing_id = self._find_capture_node_id(capture_node_name)
            if existing_id is not None:
                self._capture_node_ids[device_id] = existing_id
                mic.virtual_source_active = True
                return True

            try:
                self._config_dir.mkdir(parents=True, exist_ok=True)
                safe_file = _sanitize_node_token(device_id)
                conf_path = self._config_dir / f"{safe_file}.conf"
                conf_text = build_filter_chain_config(mic, capture_node_name)
                temp_path = conf_path.with_suffix(".tmp")
                temp_path.write_text(conf_text, encoding="utf-8")
                temp_path.replace(conf_path)
            except OSError as exc:
                logger.warning("Failed to write PipeWire EQ config for %s: %s", device_id, exc)
                return False

            try:
                new_proc = subprocess.Popen(
                    ["pipewire", "-c", str(conf_path)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=_c_locale_env(),
                )
            except OSError as exc:
                logger.warning("Failed to start PipeWire filter-chain for %s: %s", device_id, exc)
                return False

            self._filter_procs[device_id] = new_proc

        # Wait briefly (off-lock) for PipeWire to register the capture node
        deadline = time.monotonic() + 1.5
        cap_id: Optional[int] = None
        while time.monotonic() < deadline:
            if new_proc.poll() is not None:
                break
            cap_id = self._find_capture_node_id(capture_node_name)
            if cap_id is not None:
                break
            time.sleep(0.1)

        with self._lock:
            if cap_id is not None:
                self._capture_node_ids[device_id] = cap_id
                if device_id in self._mics:
                    self._mics[device_id].virtual_source_active = True
                return True
            logger.warning("PipeWire filter-chain node %s did not appear in time", capture_node_name)
            self._stop_filter_chain_locked(device_id)
            return False

    def apply_eq(self, device_id: str, mic_state: Optional[MicrophoneInfo] = None) -> bool:
        """Apply current EQ/HPF/bypass parameters live to the PipeWire filter-chain."""
        with self._lock:
            if mic_state is not None:
                if device_id in self._mics:
                    stored = self._mics[device_id]
                    stored.eq_enabled = bool(mic_state.eq_enabled)
                    stored.highpass_enabled = bool(mic_state.highpass_enabled)
                    stored.highpass_freq = clamp_hpf_freq(mic_state.highpass_freq)
                    stored.bands = [replace(b, gain=clamp_eq_gain(b.gain)) for b in mic_state.bands]
                else:
                    self._mics[device_id] = self._clone_mic_info(mic_state)
            mic = self._mics.get(device_id)
            capture_node_name = self._capture_node_names.get(device_id)
            if mic is None or not capture_node_name:
                return False
            snapshot = self._clone_mic_info(mic)

        if not self.ensure_filter_chain(device_id):
            return False

        payload = build_pw_cli_eq_params(snapshot)
        with self._lock:
            cap_id = self._capture_node_ids.get(device_id)

        if cap_id is None:
            return False

        for attempt in range(2):
            try:
                res = subprocess.run(
                    ["pw-cli", "set-param", str(cap_id), "Props", payload],
                    capture_output=True,
                    text=True,
                    timeout=3.0,
                    env=_c_locale_env(),
                )
                if res.returncode == 0:
                    return True
                logger.debug("pw-cli set-param attempt %d failed: %s", attempt + 1, res.stderr.strip())
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("pw-cli set-param error for %s: %s", device_id, exc)
                return False

            # Node ID may have changed; re-resolve once
            refreshed_id = self._find_capture_node_id(capture_node_name)
            if refreshed_id is None or refreshed_id == cap_id:
                break
            cap_id = refreshed_id
            with self._lock:
                self._capture_node_ids[device_id] = cap_id

        return False

    def set_volume(self, device_id: str, volume_percent: int) -> bool:
        clamped = clamp_mic_volume(volume_percent)
        with self._lock:
            mic = self._mics.get(device_id)
            if mic is None:
                return False
            source_name = mic.source_name

        try:
            res = subprocess.run(
                ["pactl", "set-source-volume", source_name, f"{clamped}%"],
                capture_output=True,
                text=True,
                timeout=3.0,
                env=_c_locale_env(),
            )
            if res.returncode == 0:
                with self._lock:
                    if device_id in self._mics:
                        self._mics[device_id].volume = clamped
                return True
            logger.warning("pactl set-source-volume failed for %s: %s", device_id, res.stderr.strip())
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("pactl set-source-volume error for %s: %s", device_id, exc)
        return False

    def set_mute(self, device_id: str, muted: bool) -> bool:
        with self._lock:
            mic = self._mics.get(device_id)
            if mic is None:
                return False
            source_name = mic.source_name
            virt_name = mic.virtual_source_name if mic.virtual_source_active else ""

        flag = "1" if muted else "0"
        try:
            res = subprocess.run(
                ["pactl", "set-source-mute", source_name, flag],
                capture_output=True,
                text=True,
                timeout=3.0,
                env=_c_locale_env(),
            )
            if res.returncode == 0:
                if virt_name:
                    subprocess.run(
                        ["pactl", "set-source-mute", virt_name, flag],
                        capture_output=True,
                        text=True,
                        timeout=3.0,
                        env=_c_locale_env(),
                    )
                with self._lock:
                    if device_id in self._mics:
                        self._mics[device_id].muted = bool(muted)
                return True
            logger.warning("pactl set-source-mute failed for %s: %s", device_id, res.stderr.strip())
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("pactl set-source-mute error for %s: %s", device_id, exc)
        return False

    def set_default_source(self, device_id: str, use_eq_source: bool = True) -> bool:
        with self._lock:
            mic = self._mics.get(device_id)
            if mic is None:
                return False
            raw_name = mic.source_name
            virt_name = mic.virtual_source_name

        target_name = raw_name
        if use_eq_source:
            if not self.ensure_filter_chain(device_id):
                return False
            target_name = virt_name

        try:
            res = subprocess.run(
                ["pactl", "set-default-source", target_name],
                capture_output=True,
                text=True,
                timeout=3.0,
                env=_c_locale_env(),
            )
            if res.returncode == 0:
                with self._lock:
                    if device_id in self._mics:
                        self._mics[device_id].is_eq_default_source = (target_name == virt_name)
                        self._mics[device_id].is_raw_default_source = (target_name == raw_name)
                return True
            logger.warning("pactl set-default-source failed for %s: %s", device_id, res.stderr.strip())
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("pactl set-default-source error for %s: %s", device_id, exc)
        return False

    def set_monitoring(self, device_id: str, enabled: bool) -> bool:
        """Toggle real-time voice loopback so the user hears their processed microphone live."""
        if not enabled:
            with self._lock:
                self._stop_monitoring_locked()
            return True

        with self._lock:
            mic = self._mics.get(device_id)
            if mic is None:
                return False
            raw_source = mic.source_name
            virt_source = mic.virtual_source_name

        # Ensure the EQ filter-chain is running so live EQ changes are heard immediately
        fc_ok = self.ensure_filter_chain(device_id)
        capture_target = virt_source if fc_ok else raw_source

        if shutil.which("pw-loopback") is None:
            logger.warning("pw-loopback not found; cannot start live mic monitor")
            return False

        with self._lock:
            self._stop_monitoring_locked()
            try:
                proc = subprocess.Popen(
                    [
                        "pw-loopback",
                        "-n",
                        "lhub-mic-monitor",
                        "--latency",
                        "15",
                        "-c",
                        "2",
                        "-m",
                        "[ FL FR ]",
                        "-C",
                        capture_target,
                        "-i",
                        "node.description='L-Hub Mic Monitor'",
                        "-o",
                        "node.description='L-Hub Mic Monitor'",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=_c_locale_env(),
                )
            except OSError as exc:
                logger.warning("Failed to start pw-loopback for %s: %s", device_id, exc)
                return False

            self._monitor_proc = proc
            self._monitor_device_id = device_id
            if device_id in self._mics:
                self._mics[device_id].monitoring = True
            return True

    def is_monitoring(self, device_id: Optional[str] = None) -> bool:
        with self._lock:
            if self._monitor_proc is None or self._monitor_proc.poll() is not None:
                self._monitor_proc = None
                self._monitor_device_id = None
                return False
            if device_id is None:
                return True
            return self._monitor_device_id == device_id

    @staticmethod
    def _terminate_process(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass
        except Exception:
            pass

    def _stop_monitoring_locked(self) -> None:
        prev_id = self._monitor_device_id
        proc = self._monitor_proc
        self._monitor_proc = None
        self._monitor_device_id = None
        if prev_id and prev_id in self._mics:
            self._mics[prev_id].monitoring = False
        if proc is not None:
            self._terminate_process(proc)

    def _stop_filter_chain_locked(self, device_id: str) -> None:
        proc = self._filter_procs.pop(device_id, None)
        self._capture_node_ids.pop(device_id, None)
        mic = self._mics.get(device_id)
        if mic is not None:
            mic.virtual_source_active = False
        if proc is not None:
            self._terminate_process(proc)

    def cleanup(self) -> None:
        """Stop monitoring, hotplug watcher, and managed filter-chain processes cleanly."""
        self.stop_monitoring()
        with self._lock:
            self._stop_monitoring_locked()
            # If our virtual EQ source is currently the system default, restore the raw hardware mic
            for device_id in list(self._filter_procs.keys()):
                mic = self._mics.get(device_id)
                if mic is not None and mic.is_eq_default_source and mic.source_name:
                    try:
                        subprocess.run(
                            ["pactl", "set-default-source", mic.source_name],
                            capture_output=True,
                            text=True,
                            timeout=2.0,
                            env=_c_locale_env(),
                        )
                    except (OSError, subprocess.SubprocessError):
                        pass
                self._stop_filter_chain_locked(device_id)
