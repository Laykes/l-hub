"""Unit tests for the PipeWire USB microphone backend, profiles, serialization, and manager."""

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

from lhub.backends.base import Capability, Device, DeviceType, MicrophoneInfo
from lhub.backends.microphone import (
    BUILTIN_EQ_PRESETS,
    HPF_BYPASS_FREQ,
    PipeWireMicBackend,
    build_filter_chain_config,
    build_pw_cli_eq_params,
    clamp_eq_gain,
    clamp_hpf_freq,
    clamp_mic_volume,
    create_default_eq_bands,
    linear_volume_to_percent,
    mic_info_to_config,
)
from lhub.health import _discover_relevant_hidraw_nodes
from lhub.manager import DeviceManager
from lhub.profiles import ProfileManager
from lhub.serializers import device_to_dict
from lhub.settings import SettingsManager


def _sample_pw_dump(
    default_source: str = "alsa_input.usb-USB_Microphone_USB_Microphone-00.analog-stereo",
    include_virtual: bool = False,
    mic_volume_linear: float = 1.0,
    mic_muted: bool = False,
    mic_channels: int = 2,
) -> list:
    objs = [
        {
            "id": 31,
            "type": "PipeWire:Interface:Metadata",
            "props": {"metadata.name": "default"},
            "metadata": [
                {
                    "subject": 0,
                    "key": "default.audio.source",
                    "type": "Spa:String:JSON",
                    "value": {"name": default_source},
                }
            ],
        },
        {
            "id": 45,
            "type": "PipeWire:Interface:Device",
            "info": {
                "props": {
                    "media.class": "Audio/Device",
                    "device.bus": "usb",
                    "device.vendor.id": "0x17a0",
                    "device.product.id": "0x0002",
                    "device.vendor.name": "Samson Technologies Corp.",
                    "device.product.name": "Q1U dynamic microphone",
                    "device.description": "Q1U dynamic microphone",
                    "device.form-factor": "microphone",
                }
            },
        },
        {
            "id": 46,
            "type": "PipeWire:Interface:Device",
            "info": {
                "props": {
                    "media.class": "Audio/Device",
                    "device.bus": "usb",
                    "device.vendor.id": "0x054c",
                    "device.product.id": "0x09cc",
                    "device.vendor.name": "Sony Corp.",
                    "device.product.name": "DualShock 4 [CUH-ZCT2x]",
                    "device.form-factor": "controller",
                }
            },
        },
        {
            "id": 44,
            "type": "PipeWire:Interface:Device",
            "info": {
                "props": {
                    "media.class": "Audio/Device",
                    "device.bus": "usb",
                    "device.vendor.id": "0x046d",
                    "device.product.id": "0x0aba",
                    "device.vendor.name": "Logitech, Inc.",
                    "device.product.name": "PRO X Wireless Gaming Headset",
                    "device.form-factor": "headset",
                }
            },
        },
        {
            "id": 48,
            "type": "PipeWire:Interface:Device",
            "info": {
                "props": {
                    "media.class": "Audio/Device",
                    "device.bus": "pci",
                    "device.vendor.name": "AMD",
                    "device.product.name": "Ryzen HD Audio Controller",
                }
            },
        },
        # Valid USB Microphone
        {
            "id": 59,
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Source",
                    "factory.name": "api.alsa.pcm.source",
                    "node.name": "alsa_input.usb-USB_Microphone_USB_Microphone-00.analog-stereo",
                    "node.description": "MICROPHONE",
                    "device.bus": "usb",
                    "device.form-factor": "microphone",
                    "device.id": 45,
                    "audio.channels": mic_channels,
                },
                "params": {
                    "Props": [
                        {
                            "volume": mic_volume_linear,
                            "mute": mic_muted,
                            "channelVolumes": [mic_volume_linear] * mic_channels,
                        }
                    ]
                },
            },
        },
        # DualShock 4 controller mic (must be filtered out)
        {
            "id": 61,
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Source",
                    "factory.name": "api.alsa.pcm.source",
                    "node.name": "alsa_input.usb-Sony_Interactive_Entertainment_Wireless_Controller-00.mono-fallback",
                    "node.description": "DualShock 4 Mono",
                    "device.bus": "usb",
                    "device.form-factor": "controller",
                    "device.id": 46,
                    "audio.channels": 1,
                }
            },
        },
        # Headset mic (must be filtered out)
        {
            "id": 62,
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Source",
                    "factory.name": "api.alsa.pcm.source",
                    "node.name": "alsa_input.usb-Logitech_PRO_X-00.mono-fallback",
                    "node.description": "PRO X Wireless Gaming Headset",
                    "device.bus": "usb",
                    "device.form-factor": "headset",
                    "device.id": 44,
                    "audio.channels": 1,
                }
            },
        },
        # Onboard PCI mic (must be filtered out)
        {
            "id": 64,
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Source",
                    "factory.name": "api.alsa.pcm.source",
                    "node.name": "alsa_input.pci-0000_11_00.6.analog-stereo",
                    "node.description": "Ryzen HD Audio",
                    "device.bus": "pci",
                    "device.id": 48,
                    "audio.channels": 2,
                }
            },
        },
        # EasyEffects virtual source (must be filtered out)
        {
            "id": 98,
            "type": "PipeWire:Interface:Node",
            "info": {
                "props": {
                    "media.class": "Audio/Source",
                    "node.name": "easyeffects_source",
                    "device.bus": "usb",
                }
            },
        },
    ]

    if include_virtual:
        objs.extend([
            {
                "id": 320,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "media.class": "Stream/Input/Audio",
                        "node.name": "lhub_eq_capture.17a0_0002",
                    }
                },
            },
            {
                "id": 321,
                "type": "PipeWire:Interface:Node",
                "info": {
                    "props": {
                        "media.class": "Audio/Source",
                        "node.name": "lhub_eq_source.17a0_0002",
                    }
                },
            },
        ])
    return objs


def _make_fake_proc(poll_value=None) -> MagicMock:
    proc = MagicMock()
    proc.poll.return_value = poll_value
    return proc


class TestMicrophoneHelpers(unittest.TestCase):
    def test_clamping_and_volume_conversion(self):
        self.assertEqual(clamp_mic_volume(-10), 0)
        self.assertEqual(clamp_mic_volume(200), 150)
        self.assertEqual(clamp_mic_volume(85.4), 85)

        self.assertEqual(clamp_eq_gain(15.0), 12.0)
        self.assertEqual(clamp_eq_gain(-15.0), -12.0)
        self.assertEqual(clamp_eq_gain(2.3), 2.5)

        self.assertEqual(clamp_hpf_freq(10), 40)
        self.assertEqual(clamp_hpf_freq(500), 250)
        self.assertEqual(clamp_hpf_freq(80), 80)

        self.assertEqual(linear_volume_to_percent(0.0), 0)
        self.assertEqual(linear_volume_to_percent(1.0), 100)
        self.assertEqual(linear_volume_to_percent(0.125), 50)

    def test_filter_chain_config_and_pw_cli_params(self):
        mic = MicrophoneInfo(
            source_name="alsa_input.usb-USB_Microphone-00.analog-stereo",
            channels=2,
            eq_enabled=True,
            highpass_enabled=True,
            highpass_freq=95,
            bands=create_default_eq_bands({"eq_band_1": 3.0, "eq_band_3": -2.5, "eq_band_5": 4.0}),
            virtual_source_name="lhub_eq_source.17a0_0002",
            virtual_source_description='L-Hub: Q1U "Studio" Mic',
        )

        conf = build_filter_chain_config(mic, "lhub_eq_capture.17a0_0002")
        self.assertIn("libpipewire-module-filter-chain", conf)
        self.assertIn("label = bq_highpass", conf)
        self.assertIn('"Freq" = 95.0', conf)
        self.assertIn('"Gain" = 3.0', conf)
        self.assertIn('"Gain" = -2.5', conf)
        self.assertIn('"Gain" = 4.0', conf)
        self.assertIn('media.class      = Audio/Source', conf)
        self.assertIn('target.object    = "alsa_input.usb-USB_Microphone-00.analog-stereo"', conf)
        self.assertIn('L-Hub: Q1U \\"Studio\\" Mic', conf)
        self.assertIn("audio.channels = 2", conf)
        self.assertIn("audio.position = [ FL FR ]", conf)

        params_active = build_pw_cli_eq_params(mic)
        self.assertIn('"hpf:Freq" 95.0', params_active)
        self.assertIn('"eq_band_1:Gain" 3.0', params_active)
        self.assertIn('"eq_band_3:Gain" -2.5', params_active)

        # Bypass zeroes every band and sets HPF to transparent bypass frequency
        mic.eq_enabled = False
        params_bypass = build_pw_cli_eq_params(mic)
        self.assertIn(f'"hpf:Freq" {HPF_BYPASS_FREQ:.1f}', params_bypass)
        self.assertIn('"eq_band_1:Gain" 0.0', params_bypass)
        self.assertIn('"eq_band_3:Gain" 0.0', params_bypass)
        self.assertIn('"eq_band_5:Gain" 0.0', params_bypass)

    def test_mono_filter_chain_config(self):
        mic = MicrophoneInfo(
            source_name="alsa_input.usb-MonoMic-00.mono",
            channels=1,
            bands=create_default_eq_bands(),
            virtual_source_name="lhub_eq_source.1234_5678",
            virtual_source_description="L-Hub: MonoMic",
        )
        conf = build_filter_chain_config(mic, "lhub_eq_capture.1234_5678")
        self.assertIn("audio.channels = 1", conf)
        self.assertIn("audio.position = [ MONO ]", conf)


class TestPipeWireMicBackend(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.backend = PipeWireMicBackend(config_dir=Path(self._tmpdir.name))

    def tearDown(self):
        self.backend.cleanup()
        self._tmpdir.cleanup()

    def test_scan_discovers_only_usb_microphones(self):
        dump_data = _sample_pw_dump(
            default_source="lhub_eq_source.17a0_0002",
            include_virtual=True,
            mic_volume_linear=0.512,  # 80%
            mic_muted=True,
        )
        with patch.object(self.backend, "_run_pw_dump", return_value=dump_data):
            devices = self.backend.scan_devices()

        self.assertEqual(len(devices), 1)
        dev = devices[0]
        self.assertEqual(dev.id, "mic_17a0_0002")
        self.assertEqual(dev.name, "Q1U dynamic microphone")
        self.assertEqual(dev.vendor, "Samson Technologies Corp.")
        self.assertEqual(dev.device_type, DeviceType.MICROPHONE)
        self.assertEqual(dev.usb_vid, "17a0")
        self.assertEqual(dev.usb_pid, "0002")
        self.assertIn(Capability.EQUALIZER, dev.capabilities)
        self.assertIn(Capability.MIC_MONITOR, dev.capabilities)
        self.assertIsNotNone(dev.microphone)
        assert dev.microphone is not None
        self.assertEqual(dev.microphone.volume, 80)
        self.assertTrue(dev.microphone.muted)
        self.assertTrue(dev.microphone.virtual_source_active)
        self.assertTrue(dev.microphone.is_eq_default_source)
        self.assertFalse(dev.microphone.is_raw_default_source)
        self.assertEqual(len(dev.microphone.bands), 6)

    def test_apply_eq_spawns_filter_chain_and_pushes_pw_cli(self):
        initial_dump = _sample_pw_dump(include_virtual=False)
        after_spawn_dump = _sample_pw_dump(include_virtual=True)

        fake_fc_proc = _make_fake_proc(poll_value=None)

        with patch.object(self.backend, "_run_pw_dump", side_effect=[initial_dump, initial_dump, after_spawn_dump]):
            devices = self.backend.scan_devices()
            mic = devices[0].microphone
            assert mic is not None
            mic.highpass_enabled = True
            mic.highpass_freq = 100
            mic.bands[0].gain = 3.5

            with (
                patch("lhub.backends.microphone.subprocess.Popen", return_value=fake_fc_proc) as mock_popen,
                patch("lhub.backends.microphone.subprocess.run") as mock_run,
            ):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                ok = self.backend.apply_eq("mic_17a0_0002", mic)

        self.assertTrue(ok)
        mock_popen.assert_called_once()
        spawn_cmd = mock_popen.call_args[0][0]
        self.assertEqual(spawn_cmd[0], "pipewire")
        self.assertEqual(spawn_cmd[1], "-c")
        self.assertTrue(Path(spawn_cmd[2]).exists())

        mock_run.assert_called_once()
        pw_cli_cmd = mock_run.call_args[0][0]
        self.assertEqual(pw_cli_cmd[:4], ["pw-cli", "set-param", "320", "Props"])
        self.assertIn('"hpf:Freq" 100.0', pw_cli_cmd[4])
        self.assertIn('"eq_band_1:Gain" 3.5', pw_cli_cmd[4])

    def test_volume_mute_default_and_monitoring_lifecycle(self):
        dump_with_virtual = _sample_pw_dump(include_virtual=True)
        fake_lb_proc = _make_fake_proc(poll_value=None)

        with patch.object(self.backend, "_run_pw_dump", return_value=dump_with_virtual):
            self.backend.scan_devices()

            with (
                patch("lhub.backends.microphone.subprocess.run") as mock_run,
                patch("lhub.backends.microphone.subprocess.Popen", return_value=fake_lb_proc) as mock_popen,
                patch("lhub.backends.microphone.shutil.which", return_value="/usr/bin/pw-loopback"),
            ):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

                self.assertTrue(self.backend.set_volume("mic_17a0_0002", 125))
                self.assertEqual(
                    mock_run.call_args[0][0],
                    [
                        "pactl",
                        "set-source-volume",
                        "alsa_input.usb-USB_Microphone_USB_Microphone-00.analog-stereo",
                        "125%",
                    ],
                )

                self.assertTrue(self.backend.set_mute("mic_17a0_0002", True))
                mute_cmds = [c[0][0] for c in mock_run.call_args_list[-2:]]
                self.assertIn(
                    [
                        "pactl",
                        "set-source-mute",
                        "alsa_input.usb-USB_Microphone_USB_Microphone-00.analog-stereo",
                        "1",
                    ],
                    mute_cmds,
                )
                self.assertIn(
                    ["pactl", "set-source-mute", "lhub_eq_source.17a0_0002", "1"],
                    mute_cmds,
                )

                self.assertTrue(self.backend.set_default_source("mic_17a0_0002", use_eq_source=True))
                self.assertEqual(
                    mock_run.call_args[0][0],
                    ["pactl", "set-default-source", "lhub_eq_source.17a0_0002"],
                )

                # Start live voice monitoring (pw-loopback targeting virtual EQ source)
                self.assertTrue(self.backend.set_monitoring("mic_17a0_0002", True))
                self.assertTrue(self.backend.is_monitoring("mic_17a0_0002"))
                lb_cmd = mock_popen.call_args[0][0]
                self.assertEqual(lb_cmd[0], "pw-loopback")
                self.assertIn("lhub_eq_source.17a0_0002", lb_cmd)

                # Stop live voice monitoring
                self.assertTrue(self.backend.set_monitoring("mic_17a0_0002", False))
                self.assertFalse(self.backend.is_monitoring("mic_17a0_0002"))
                fake_lb_proc.terminate.assert_called_once()

    def test_cleanup_restores_raw_default_and_stops_processes(self):
        dump_with_virtual = _sample_pw_dump(
            default_source="lhub_eq_source.17a0_0002",
            include_virtual=True,
        )
        fake_fc = _make_fake_proc(poll_value=None)
        fake_lb = _make_fake_proc(poll_value=None)

        with patch.object(self.backend, "_run_pw_dump", return_value=dump_with_virtual):
            self.backend.scan_devices()
        self.backend._filter_procs["mic_17a0_0002"] = fake_fc
        self.backend._monitor_proc = fake_lb
        self.backend._monitor_device_id = "mic_17a0_0002"

        with patch("lhub.backends.microphone.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            self.backend.cleanup()

        fake_lb.terminate.assert_called_once()
        fake_fc.terminate.assert_called_once()
        mock_run.assert_called_once()
        self.assertEqual(
            mock_run.call_args[0][0],
            [
                "pactl",
                "set-default-source",
                "alsa_input.usb-USB_Microphone_USB_Microphone-00.analog-stereo",
            ],
        )

    def test_hotplug_event_filtering(self):
        self.assertTrue(PipeWireMicBackend._should_trigger_hotplug("event 'new' on source #61"))
        self.assertTrue(PipeWireMicBackend._should_trigger_hotplug("event 'remove' on card #5"))
        self.assertTrue(PipeWireMicBackend._should_trigger_hotplug("event 'change' on server #0"))
        self.assertFalse(PipeWireMicBackend._should_trigger_hotplug("event 'change' on source #61"))
        self.assertFalse(PipeWireMicBackend._should_trigger_hotplug("event 'change' on sink #40"))


class TestMicrophoneProfilesAndManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.profiles_path = Path(self._tmpdir.name) / "profiles.json"
        self.settings_path = Path(self._tmpdir.name) / "settings.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_stub_mic_backend(self) -> PipeWireMicBackend:
        backend = PipeWireMicBackend(config_dir=Path(self._tmpdir.name) / "pw")
        backend.is_available = MagicMock(return_value=True)
        backend.apply_eq = MagicMock(return_value=True)
        backend.set_volume = MagicMock(return_value=True)
        backend.set_mute = MagicMock(return_value=True)
        backend.set_monitoring = MagicMock(return_value=True)
        backend.set_default_source = MagicMock(return_value=True)
        backend.cleanup = MagicMock()

        mic_info = MicrophoneInfo(
            source_name="alsa_input.usb-USB_Microphone_USB_Microphone-00.analog-stereo",
            channels=2,
            volume=100,
            muted=False,
            eq_enabled=True,
            highpass_enabled=False,
            highpass_freq=80,
            bands=create_default_eq_bands(),
            virtual_source_name="lhub_eq_source.17a0_0002",
            virtual_source_description="L-Hub: Q1U dynamic microphone",
            virtual_source_active=False,
        )
        dev = Device(
            id="mic_17a0_0002",
            name="Q1U dynamic microphone",
            vendor="Samson Technologies Corp.",
            device_type=DeviceType.MICROPHONE,
            usb_vid="17a0",
            usb_pid="0002",
            capabilities=[
                Capability.AUDIO_GAIN,
                Capability.AUDIO_MUTE,
                Capability.EQUALIZER,
                Capability.PROFILES,
                Capability.MIC_MONITOR,
            ],
            microphone=mic_info,
            backend_name="pipewire",
        )
        backend.scan_devices = MagicMock(return_value=[dev])
        return backend

    def test_profile_manager_roundtrip_and_serialization(self):
        pm = ProfileManager(config_file=self.profiles_path)
        default_cfg = {
            "volume": 100,
            "eq_enabled": True,
            "highpass_enabled": False,
            "highpass_freq": 80,
            "bands": {"eq_band_1": 0.0, "eq_band_2": 0.0},
        }
        pm.ensure_default_mic_profile("17a0:0002", default_cfg)
        self.assertEqual(pm.get_profiles("17a0:0002"), ["Default"])

        broadcast_cfg = {
            "volume": 110,
            "eq_enabled": True,
            "highpass_enabled": True,
            "highpass_freq": 85,
            "bands": {"eq_band_1": 3.0, "eq_band_2": 2.0},
        }
        pm.save_mic_profile("17a0:0002", "Broadcast", broadcast_cfg)
        self.assertEqual(pm.get_active_profile("17a0:0002"), "Broadcast")

        # Reload from disk
        pm2 = ProfileManager(config_file=self.profiles_path)
        self.assertEqual(pm2.get_profiles("17a0:0002"), ["Default", "Broadcast"])
        loaded = pm2.get_profile_data("17a0:0002", "Broadcast")
        self.assertEqual(loaded["microphone"]["highpass_freq"], 85)
        self.assertEqual(loaded["microphone"]["bands"]["eq_band_1"], 3.0)

        # Verify serializer fields
        mic = MicrophoneInfo(
            source_name="alsa_input.usb-test",
            bands=create_default_eq_bands({"eq_band_1": 3.0}),
            highpass_enabled=True,
            highpass_freq=85,
            monitoring=True,
            virtual_source_name="lhub_eq_source.17a0_0002",
            virtual_source_description="L-Hub: Q1U",
            virtual_source_active=True,
            is_eq_default_source=True,
        )
        dev = Device(
            id="mic_17a0_0002",
            name="Q1U",
            vendor="Samson",
            device_type=DeviceType.MICROPHONE,
            usb_vid="17a0",
            usb_pid="0002",
            capabilities=[Capability.EQUALIZER, Capability.MIC_MONITOR, Capability.PROFILES],
            microphone=mic,
            backend_name="pipewire",
        )
        data = device_to_dict(dev, pm2)
        self.assertTrue(data["hasMicrophone"])
        self.assertTrue(data["hasEqualizer"])
        self.assertTrue(data["hasMicMonitor"])
        self.assertTrue(data["micMonitoring"])
        self.assertTrue(data["micIsEqDefaultSource"])
        self.assertEqual(data["micHighpassFreq"], 85)
        self.assertEqual(len(data["micEqBands"]), 6)
        self.assertEqual(data["micEqBands"][0]["gain"], 3.0)
        self.assertEqual(len(data["micPresets"]), len(BUILTIN_EQ_PRESETS))

    def test_manager_mic_controls_presets_profiles_and_monitoring(self):
        backend = self._make_stub_mic_backend()
        settings_mgr = SettingsManager(config_file=self.settings_path)
        mgr = DeviceManager(
            auto_refresh=False,
            backends=[backend],
            enable_hotplug=False,
            settings_mgr=settings_mgr,
        )
        mgr.profile_mgr = ProfileManager(config_file=self.profiles_path)

        try:
            with patch("lhub.manager.run_health_checks", return_value=[]):
                mgr._scan_worker()

            self.assertEqual(len(mgr.devices), 1)
            self.assertEqual(mgr.devices[0]["id"], "mic_17a0_0002")
            backend.apply_eq.assert_called()

            # Adjust EQ band
            self.assertTrue(mgr.setMicEqBand("mic_17a0_0002", "eq_band_1", 4.5))
            self.assertEqual(mgr.devices[0]["micEqBands"][0]["gain"], 4.5)

            # Toggle High-Pass
            self.assertTrue(mgr.setMicHighpass("mic_17a0_0002", True, 110))
            self.assertTrue(mgr.devices[0]["micHighpassEnabled"])
            self.assertEqual(mgr.devices[0]["micHighpassFreq"], 110)

            # Save custom profile, apply preset, then switch back to custom profile
            self.assertTrue(mgr.saveProfile("mic_17a0_0002", "My Voice"))
            self.assertIn("My Voice", mgr.devices[0]["profiles"])

            self.assertTrue(mgr.applyMicPreset("mic_17a0_0002", "Radio"))
            self.assertEqual(mgr.devices[0]["micEqBands"][0]["gain"], -8.0)
            self.assertEqual(mgr.devices[0]["micHighpassFreq"], 180)

            # Save Radio as another profile, then restore Default via reset
            self.assertTrue(mgr.saveProfile("mic_17a0_0002", "Radio Custom"))
            self.assertTrue(mgr.applyProfile("mic_17a0_0002", "Default"))
            self.assertEqual(mgr.devices[0]["activeProfile"], "Default")

            # Toggle Live Voice Test monitoring
            self.assertTrue(mgr.setMicMonitoring("mic_17a0_0002", True))
            self.assertTrue(mgr.devices[0]["micMonitoring"])

            # Toggle mute & volume & default source
            self.assertTrue(mgr.setMicMuted("mic_17a0_0002", True))
            self.assertTrue(mgr.devices[0]["micMuted"])
            self.assertTrue(mgr.setMicVolume("mic_17a0_0002", 120))
            self.assertEqual(mgr.devices[0]["micVolume"], 120)
            self.assertTrue(mgr.setMicAsDefault("mic_17a0_0002", True))

            # Reset to default flat
            self.assertTrue(mgr.resetDeviceToDefault("mic_17a0_0002"))
            self.assertEqual(mgr.devices[0]["micEqBands"][0]["gain"], 0.0)
            self.assertFalse(mgr.devices[0]["micHighpassEnabled"])
            self.assertEqual(mgr.devices[0]["micVolume"], 100)

            # Wait briefly for daemon worker threads to finish
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and not backend.set_default_source.called:
                time.sleep(0.02)

            backend.set_monitoring.assert_called_with("mic_17a0_0002", True)
            backend.set_mute.assert_called_with("mic_17a0_0002", True)
            backend.set_default_source.assert_called_with("mic_17a0_0002", use_eq_source=True)
        finally:
            mgr.cleanup()
            backend.cleanup.assert_called_once()

    def test_health_hidraw_skips_microphone_devices(self):
        mic_dev = Device(
            id="mic_17a0_0002",
            name="Q1U dynamic microphone",
            vendor="Samson",
            device_type=DeviceType.MICROPHONE,
            usb_vid="17a0",
            usb_pid="0002",
            backend_name="pipewire",
        )
        with (
            patch("lhub.health.glob.glob", return_value=["/sys/class/hidraw/hidraw9"]),
            patch("builtins.open", unittest.mock.mock_open(read_data="HID_ID=0003:000017A0:00000002\nHID_NAME=Samson Q1U\n")),
        ):
            nodes = _discover_relevant_hidraw_nodes([mic_dev])
        self.assertEqual(nodes, [])

    def test_qml_microphone_section_compiles(self):
        engine = QQmlEngine()
        qml_dir = Path(__file__).resolve().parent.parent / "lhub" / "qml"
        for rel in ("components/MicrophoneSection.qml", "DeviceCard.qml"):
            comp = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_dir / rel)))
            self.assertFalse(
                comp.isError(),
                f"QML error in {rel}: {[e.toString() for e in comp.errors()]}",
            )


if __name__ == "__main__":
    unittest.main()
