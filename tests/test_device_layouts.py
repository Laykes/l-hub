import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication

from lhub.backends.base import ButtonMapping, Capability, Device, DeviceType, DpiInfo
from lhub.backends.ratbag import (
    RATBAG_BUTTON_IFACE,
    RATBAG_DEVICE_IFACE,
    RATBAG_MANAGER_IFACE,
    RATBAG_MANAGER_PATH,
    RATBAG_PROFILE_IFACE,
    RATBAG_RESOLUTION_IFACE,
    RatbagActionSpecial,
    RatbagActionType,
    RatbagBackend,
    get_button_metadata as ratbag_get_button_metadata,
    parse_button_action,
)
from lhub.device_layouts import (
    BUNDLED_DEVICES_DIR,
    DeviceLayoutRegistry,
    find_device_layout,
    get_button_metadata,
    get_factory_reset_defaults,
    get_user_devices_dir,
    load_layout_file,
    reload_layouts,
    validate_layout_data,
)
from lhub.manager import DeviceManager
from lhub.profiles import ProfileManager
from lhub.serializers import device_to_dict

_app = QGuiApplication.instance() or QGuiApplication(sys.argv)


def _make_sample_layout(**overrides):
    data = {
        "id": "custom_test_mouse",
        "name": "Custom Test Mouse",
        "vendor": "TestVendor",
        "vid": "1234",
        "pids": ["abcd"],
        "name_patterns": ["custom test"],
        "buttons": [
            {
                "index": 0,
                "name": "Left Click",
                "label": "Left",
                "location": "Primary Left",
                "group": "main",
                "default": "button 1",
            },
            {
                "index": 1,
                "name": "Right Click",
                "label": "Right",
                "location": "Primary Right",
                "group": "main",
                "default": "button 2",
            },
        ],
    }
    data.update(overrides)
    return data


def _read_package_data_lhub(pyproject_path: Path):
    try:
        import tomllib  # Python 3.11+

        with open(pyproject_path, "rb") as fh:
            parsed = tomllib.load(fh)
        return parsed["tool"]["setuptools"]["package-data"]["lhub"]
    except ModuleNotFoundError:
        text = pyproject_path.read_text(encoding="utf-8")
        m = re.search(r"\[tool\.setuptools\.package-data\][^\[]*?lhub\s*=\s*(\[[^\]]*\])", text, re.S)
        self_list = json.loads(m.group(1)) if m else []
        return self_list


class TestBundledDeviceLayouts(unittest.TestCase):
    def test_bundled_layouts_exist_and_validate(self):
        json_files = sorted(BUNDLED_DEVICES_DIR.glob("*.json"))
        names = {p.name for p in json_files}
        self.assertIn("logitech_g502.json", names)
        self.assertIn("logitech_g305.json", names)
        self.assertIn("logitech_g_pro_x_superlight.json", names)

        seen_ids = set()
        seen_vid_pids = set()
        for path in json_files:
            layout = load_layout_file(path)
            self.assertNotIn(layout.id, seen_ids, f"Duplicate layout id: {layout.id}")
            seen_ids.add(layout.id)

            for pid in layout.pids:
                pair = (layout.vid, pid)
                self.assertNotIn(pair, seen_vid_pids, f"Duplicate VID:PID {pair} in {path}")
                seen_vid_pids.add(pair)

            for idx, btn in layout.buttons.items():
                act_val, act_disp = parse_button_action(btn.default)
                self.assertNotEqual(act_val, "unknown", f"Unrecognized default action in {path} button {idx}")
                self.assertTrue(act_disp.strip(), f"Empty action display in {path} button {idx}")

    def test_logitech_g502_exact_migration(self):
        g502 = load_layout_file(BUNDLED_DEVICES_DIR / "logitech_g502.json")
        self.assertEqual(g502.id, "logitech_g502")
        self.assertEqual(g502.vendor, "Logitech")
        self.assertEqual(g502.vid, "046d")
        self.assertEqual(g502.pids, ("c099", "c092", "c07d", "c332", "c08b"))
        self.assertEqual(len(g502.buttons), 11)

        expected = {
            0: ("Left Click (LMB)", "Left Click", "Primary Left", "main", "button 1"),
            1: ("Right Click (RMB)", "Right Click", "Primary Right", "main", "button 2"),
            2: ("Middle Click (Wheel)", "Wheel Click", "Scroll Wheel", "wheel", "button 3"),
            3: ("Side Back (G4)", "Back", "Thumb Rest (Rear)", "side", "button 4"),
            4: ("DPI Shift / Sniper (G6)", "Sniper / Shift", "Thumb Tip (Front)", "side", "special resolution-alternate"),
            5: ("Side Forward (G5)", "Forward", "Thumb Rest (Front)", "side", "button 5"),
            6: ("Wheel Tilt Left", "Tilt Left", "Scroll Wheel", "wheel", "special wheel-left"),
            7: ("Wheel Tilt Right", "Tilt Right", "Scroll Wheel", "wheel", "special wheel-right"),
            8: ("Profile Switch (G9)", "Profile Switch", "Behind Wheel", "dpi", "special profile-cycle-up"),
            9: ("DPI Up (G8)", "DPI Up", "Left of LMB", "dpi", "special resolution-up"),
            10: ("DPI Down (G7)", "DPI Down", "Left of LMB", "dpi", "special resolution-down"),
        }
        for idx, (name, label, location, group, default) in expected.items():
            btn = g502.buttons[idx]
            self.assertEqual(btn.name, name)
            self.assertEqual(btn.label, label)
            self.assertEqual(btn.location, location)
            self.assertEqual(btn.group, group)
            self.assertEqual(btn.default, default)

    def test_pyproject_package_data_includes_device_layouts(self):
        pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
        package_data = _read_package_data_lhub(pyproject_path)
        for required in ("qml/*.qml", "qml/components/*.qml", "assets/*.svg", "data/devices/*.json"):
            self.assertIn(required, package_data)


class TestSchemaValidation(unittest.TestCase):
    def test_rejects_invalid_schemas(self):
        invalid_cases = [
            [],
            _make_sample_layout(id=""),
            _make_sample_layout(name="   "),
            _make_sample_layout(vendor=123),
            _make_sample_layout(vid="046"),
            _make_sample_layout(vid="zzzz"),
            _make_sample_layout(vid=46),
            _make_sample_layout(vid="", pids=["c099"]),
            _make_sample_layout(pids="c099"),
            _make_sample_layout(pids=["bad"]),
            _make_sample_layout(pids=["c099", "C099"]),
            _make_sample_layout(pids=[], name_patterns=[]),
            _make_sample_layout(name_patterns="g502"),
            _make_sample_layout(name_patterns=[""]),
            _make_sample_layout(name_patterns=["[unclosed"]),
            _make_sample_layout(buttons=[]),
            _make_sample_layout(buttons=["not-a-dict"]),
            _make_sample_layout(
                buttons=[
                    {
                        "index": True,
                        "name": "Left",
                        "label": "Left",
                        "location": "Primary Left",
                        "group": "main",
                        "default": "button 1",
                    }
                ]
            ),
            _make_sample_layout(
                buttons=[
                    {
                        "index": -1,
                        "name": "Left",
                        "label": "Left",
                        "location": "Primary Left",
                        "group": "main",
                        "default": "button 1",
                    }
                ]
            ),
            _make_sample_layout(
                buttons=[
                    {
                        "index": 0,
                        "name": "A",
                        "label": "A",
                        "location": "L",
                        "group": "main",
                        "default": "button 1",
                    },
                    {
                        "index": 0,
                        "name": "B",
                        "label": "B",
                        "location": "R",
                        "group": "main",
                        "default": "button 2",
                    },
                ]
            ),
            _make_sample_layout(
                buttons=[
                    {
                        "index": 0,
                        "name": "A",
                        "label": "A",
                        "location": "L",
                        "group": "thumb",
                        "default": "button 1",
                    }
                ]
            ),
            _make_sample_layout(
                buttons=[
                    {
                        "index": 0,
                        "name": "A",
                        "label": "A",
                        "location": "L",
                        "group": "main",
                        "default": "",
                    }
                ]
            ),
        ]
        for case in invalid_cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    validate_layout_data(case, source="test")


class TestMatchingAndFallbacks(unittest.TestCase):
    def setUp(self):
        self._empty_user = tempfile.TemporaryDirectory()
        self.registry = DeviceLayoutRegistry(user_dir=Path(self._empty_user.name))

    def tearDown(self):
        self._empty_user.cleanup()

    def test_vid_pid_matching_and_normalization(self):
        layout = self.registry.find_layout("Unknown Name", " 046D ", " C099 ")
        self.assertIsNotNone(layout)
        self.assertEqual(layout.id, "logitech_g502")

        g305 = self.registry.find_layout("Anything", "046d", "4074")
        self.assertIsNotNone(g305)
        self.assertEqual(g305.id, "logitech_g305")

        superlight = self.registry.find_layout("Anything", "046d", "4093")
        self.assertIsNotNone(superlight)
        self.assertEqual(superlight.id, "logitech_g_pro_x_superlight")

        # VID:PID takes priority over name_patterns
        by_id = self.registry.find_layout("Logitech G305", "046d", "c099")
        self.assertIsNotNone(by_id)
        self.assertEqual(by_id.id, "logitech_g502")

    def test_name_pattern_matching_without_vid_pid(self):
        self.assertEqual(self.registry.find_layout("Logitech G502 X", "", "").id, "logitech_g502")
        self.assertEqual(self.registry.find_layout("Logitech Gaming Mouse G305", "", "").id, "logitech_g305")
        self.assertEqual(
            self.registry.find_layout("Logitech G Pro X Wireless Superlight", "", "").id,
            "logitech_g_pro_x_superlight",
        )
        self.assertEqual(
            self.registry.find_layout("Logitech G Pro X Superlight 2", "", "").id,
            "logitech_g_pro_x_superlight",
        )
        self.assertIsNone(self.registry.find_layout("Unknown Brand Mouse", "9999", "0001"))

    def test_generic_fallback_and_copy_isolation(self):
        # Standard 5-button unknown mouse
        meta4 = self.registry.get_button_metadata("Unknown Mouse", "9999", "0001", 4, "button 5", 5)
        self.assertEqual(meta4["name"], "Side Forward (Button 5)")
        self.assertEqual(meta4["default"], "button 5")

        # >6 button unknown mouse does not assume index 4 is Forward unless action says button 5
        meta4_large = self.registry.get_button_metadata("Unknown MMO Mouse", "9999", "0001", 4, "key KEY_1", 12)
        self.assertEqual(meta4_large["name"], "Button 5")
        self.assertEqual(meta4_large["group"], "side")
        self.assertEqual(meta4_large["default"], "button 5")

        # Action-based inference
        tilt_l = self.registry.get_button_metadata("Unknown Mouse", "9999", "0001", 6, "special wheel-left", 10)
        self.assertEqual(tilt_l["name"], "Wheel Tilt Left")
        self.assertEqual(tilt_l["group"], "wheel")
        self.assertEqual(tilt_l["default"], "special wheel-left")

        dpi_cycle = self.registry.get_button_metadata("Unknown Mouse", "9999", "0001", 5, "special resolution-cycle-up", 8)
        self.assertEqual(dpi_cycle["name"], "Cycle DPI")
        self.assertEqual(dpi_cycle["group"], "dpi")

        # Out-of-range button index on matched layout falls back cleanly
        extra_g502 = self.registry.get_button_metadata("Logitech G502 X", "046d", "c099", 11, "unknown", 12)
        self.assertEqual(extra_g502["name"], "Button 12")
        self.assertEqual(extra_g502["group"], "dpi")

        # Returned dict must be a fresh copy
        meta_a = self.registry.get_button_metadata("Logitech G502 X", "046d", "c099", 0, "button 1", 11)
        meta_a["name"] = "Mutated"
        meta_b = self.registry.get_button_metadata("Logitech G502 X", "046d", "c099", 0, "button 1", 11)
        self.assertEqual(meta_b["name"], "Left Click (LMB)")

    def test_factory_reset_defaults(self):
        g502_defs = self.registry.get_factory_reset_defaults("Logitech G502 X", "046d", "c099", total_buttons=11)
        self.assertEqual(len(g502_defs), 11)
        self.assertEqual(g502_defs[4], "special resolution-alternate")
        self.assertEqual(g502_defs[10], "special resolution-down")

        g502_truncated = self.registry.get_factory_reset_defaults("Logitech G502 X", "046d", "c099", total_buttons=5)
        self.assertEqual(list(g502_truncated.keys()), [0, 1, 2, 3, 4])

        g305_defs = self.registry.get_factory_reset_defaults("Logitech G305", "046d", "4074", total_buttons=6)
        self.assertEqual(len(g305_defs), 6)
        self.assertEqual(g305_defs[4], "button 5")
        self.assertEqual(g305_defs[5], "special resolution-cycle-up")

        superlight_defs = self.registry.get_factory_reset_defaults(
            "Logitech G Pro X Wireless Superlight", "046d", "4093", total_buttons=5
        )
        self.assertEqual(
            superlight_defs,
            {0: "button 1", 1: "button 2", 2: "button 3", 3: "button 4", 4: "button 5"},
        )

        # Safe fallback for unknown devices never guesses extra buttons
        self.assertEqual(
            self.registry.get_factory_reset_defaults("Unknown", "1111", "2222", total_buttons=None),
            {0: "button 1", 1: "button 2", 2: "button 3"},
        )
        self.assertEqual(
            self.registry.get_factory_reset_defaults("Unknown", "1111", "2222", total_buttons=3),
            {0: "button 1", 1: "button 2", 2: "button 3"},
        )
        self.assertEqual(
            self.registry.get_factory_reset_defaults("Unknown", "1111", "2222", total_buttons=6),
            {0: "button 1", 1: "button 2", 2: "button 3", 3: "button 4", 4: "button 5"},
        )
        self.assertEqual(
            self.registry.get_factory_reset_defaults("Unknown MMO", "1111", "2222", total_buttons=12),
            {0: "button 1", 1: "button 2", 2: "button 3", 3: "button 4"},
        )


class TestUserOverridesAndXdgConfig(unittest.TestCase):
    def test_user_override_by_id_replaces_bundled(self):
        with tempfile.TemporaryDirectory() as user_dir:
            override = _make_sample_layout(
                id="logitech_g502",
                name="Custom G502",
                vendor="Logitech",
                vid="046d",
                pids=["c099"],
                name_patterns=["g502"],
                buttons=[
                    {
                        "index": 0,
                        "name": "Custom LMB",
                        "label": "LMB",
                        "location": "Primary Left",
                        "group": "main",
                        "default": "button 1",
                    }
                ],
            )
            (Path(user_dir) / "g502_custom.json").write_text(json.dumps(override), encoding="utf-8")

            reg = DeviceLayoutRegistry(user_dir=Path(user_dir))
            matched = reg.find_layout("Logitech G502 X", "046d", "c099")
            self.assertIsNotNone(matched)
            self.assertTrue(matched.is_user_override)
            self.assertEqual(matched.buttons[0].name, "Custom LMB")
            # Old bundled PIDs from the replaced ID are no longer registered
            self.assertIsNone(reg.find_layout("Unknown", "046d", "c08b"))

    def test_user_override_different_id_takes_priority_and_adds_new_device(self):
        with tempfile.TemporaryDirectory() as user_dir:
            override_g305 = _make_sample_layout(
                id="my_custom_g305",
                name="My G305 Override",
                vendor="Logitech",
                vid="046d",
                pids=["4074"],
                name_patterns=["g305"],
                buttons=[
                    {
                        "index": 5,
                        "name": "Custom Middle DPI",
                        "label": "DPI",
                        "location": "Top",
                        "group": "dpi",
                        "default": "special profile-cycle-up",
                    }
                ],
            )
            new_mouse = _make_sample_layout(
                id="acme_mouse",
                name="Acme Gaming Mouse",
                vendor="Acme",
                vid="1234",
                pids=["5678"],
                name_patterns=["acme gaming"],
            )
            (Path(user_dir) / "override_g305.json").write_text(json.dumps(override_g305), encoding="utf-8")
            (Path(user_dir) / "acme.json").write_text(json.dumps(new_mouse), encoding="utf-8")

            reg = DeviceLayoutRegistry(user_dir=Path(user_dir))
            meta_vid = reg.get_button_metadata("Logitech G305", "046d", "4074", 5, "unknown", 6)
            self.assertEqual(meta_vid["name"], "Custom Middle DPI")
            self.assertEqual(meta_vid["default"], "special profile-cycle-up")

            meta_pat = reg.get_button_metadata("Logitech G305", "", "", 5, "unknown", 6)
            self.assertEqual(meta_pat["name"], "Custom Middle DPI")

            acme_layout = reg.find_layout("Acme", "1234", "5678")
            self.assertIsNotNone(acme_layout)
            self.assertEqual(acme_layout.vendor, "Acme")

    def test_invalid_user_files_logged_and_skipped(self):
        with tempfile.TemporaryDirectory() as user_dir:
            (Path(user_dir) / "broken.json").write_text("{not valid json", encoding="utf-8")
            (Path(user_dir) / "bad_schema.json").write_text(json.dumps({"id": "bad"}), encoding="utf-8")
            valid_mouse = _make_sample_layout(id="valid_user_mouse", vid="cafe", pids=["0001"], name_patterns=[])
            (Path(user_dir) / "valid.json").write_text(json.dumps(valid_mouse), encoding="utf-8")

            with self.assertLogs("lhub.device_layouts", level="WARNING") as logs:
                reg = DeviceLayoutRegistry(user_dir=Path(user_dir))

            self.assertGreaterEqual(len(logs.output), 2)
            self.assertIsNotNone(reg.find_layout("Valid", "cafe", "0001"))
            self.assertIsNotNone(reg.find_layout("G502", "046d", "c099"))

    def test_xdg_config_home_env_respected(self):
        with tempfile.TemporaryDirectory() as xdg_dir:
            devices_dir = Path(xdg_dir) / "lhub" / "devices"
            devices_dir.mkdir(parents=True)
            custom = _make_sample_layout(
                id="xdg_mouse",
                name="XDG Mouse",
                vendor="XdgCorp",
                vid="dead",
                pids=["beef"],
                name_patterns=["xdg mouse"],
            )
            (devices_dir / "xdg_mouse.json").write_text(json.dumps(custom), encoding="utf-8")

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": xdg_dir}):
                self.assertEqual(get_user_devices_dir(), devices_dir)
                reload_layouts()
                self.assertEqual(find_device_layout("", "dead", "beef").vendor, "XdgCorp")
                meta = get_button_metadata("XDG Mouse", "dead", "beef", 0, "unknown", 2)
                self.assertEqual(meta["name"], "Left Click")
                self.assertEqual(
                    get_factory_reset_defaults("XDG Mouse", "dead", "beef"),
                    {0: "button 1", 1: "button 2"},
                )
        reload_layouts()


class TestRatbagAndManagerIntegration(unittest.TestCase):
    def test_ratbag_get_button_metadata_delegates(self):
        meta = ratbag_get_button_metadata("Logitech G305", "046d", "4074", 5, "unknown", 6)
        self.assertEqual(meta["name"], "DPI Cycle (G6)")
        self.assertEqual(meta["default"], "special resolution-cycle-up")

    @patch("lhub.backends.ratbag.time.sleep")
    @patch("lhub.backends.ratbag.hidpp.set_dpi", return_value=True)
    @patch("lhub.backends.ratbag.hidpp.set_onboard_profile", return_value=True)
    @patch("lhub.backends.ratbag.hidpp.get_onboard_profile", return_value=None)
    @patch("lhub.backends.ratbag.hidpp.get_dpi", return_value=None)
    def test_ratbag_reset_defaults_uses_layout_or_safe_fallback(
        self, mock_dpi, mock_get_prof, mock_set_prof, mock_set_dpi, mock_sleep
    ):
        def _build_props_map(title, vid, pid, count):
            dev_path = "/org/freedesktop/ratbag1/device/dev0"
            p0 = "/org/freedesktop/ratbag1/profile/dev0/p0"
            p1 = "/org/freedesktop/ratbag1/profile/dev0/p1"
            p0_buttons = [f"/org/freedesktop/ratbag1/button/dev0/p0/b{i}" for i in range(count)]
            p1_buttons = [f"/org/freedesktop/ratbag1/button/dev0/p1/b{i}" for i in range(count)]
            props = {
                (RATBAG_MANAGER_PATH, RATBAG_MANAGER_IFACE): {"Devices": [dev_path]},
                (dev_path, RATBAG_DEVICE_IFACE): {
                    "Name": title,
                    "Model": f"usb:{vid}:{pid}:0",
                    "DeviceType": 2,
                    "Profiles": [p0, p1],
                },
                (p0, RATBAG_PROFILE_IFACE): {
                    "Index": 0,
                    "Disabled": False,
                    "IsActive": False,
                    "Resolutions": ["/r0"],
                    "Buttons": p0_buttons,
                },
                (p1, RATBAG_PROFILE_IFACE): {
                    "Index": 1,
                    "Disabled": False,
                    "IsActive": True,
                    "Resolutions": ["/r1_0", "/r1_1"],
                    "Buttons": p1_buttons,
                },
                ("/r0", RATBAG_RESOLUTION_IFACE): {"Index": 0, "Resolution": ("u", 800), "IsActive": True},
                ("/r1_0", RATBAG_RESOLUTION_IFACE): {"Index": 0, "Resolution": ("u", 800), "IsActive": True},
                ("/r1_1", RATBAG_RESOLUTION_IFACE): {"Index": 1, "Resolution": ("u", 1600), "IsActive": False},
            }
            for i, bp in enumerate(p0_buttons):
                props[(bp, RATBAG_BUTTON_IFACE)] = {
                    "Index": i,
                    "Mapping": (int(RatbagActionType.BUTTON), ("u", 1))
                    if i == 0
                    else (int(RatbagActionType.KEY), ("u", 30)),
                }
            for i, bp in enumerate(p1_buttons):
                props[(bp, RATBAG_BUTTON_IFACE)] = {
                    "Index": i,
                    "Mapping": (int(RatbagActionType.KEY), ("u", 30)),
                }
            return props

        def _make_fake_dbus(props_map):
            dbus = MagicMock()
            dbus.is_bus_available.return_value = True
            dbus.has_name_owner.return_value = True
            dbus.get_all_properties.side_effect = lambda svc, path, iface: dict(props_map.get((path, iface), {}))
            dbus.get_property.side_effect = lambda svc, path, iface, prop: props_map.get((path, iface), {}).get(prop)
            dbus.call_method.return_value = (0,)
            return dbus

        def _extract_profile_button_writes(calls, prof_str):
            out = []
            for call in calls:
                _svc, path, iface, prop, _sig, val = call[0]
                if iface == RATBAG_BUTTON_IFACE and prop == "Mapping" and f"/{prof_str}/" in path:
                    btn_idx = path.rsplit("/b", 1)[-1]
                    out.append((btn_idx, val))
            return out

        # Case 1: Known Logitech G502 X -> resets all 11 G502 defaults
        dbus1 = _make_fake_dbus(_build_props_map("Logitech G502 X", "046d", "c099", 11))
        backend = RatbagBackend(dbus_client=dbus1)
        self.assertTrue(backend.reset_defaults("ratbag_dev0"))

        prof1_writes = _extract_profile_button_writes(dbus1.set_property.call_args_list, "p1")
        self.assertEqual([idx for idx, _ in prof1_writes], [str(i) for i in range(11)])
        self.assertEqual(
            prof1_writes[4][1],
            (int(RatbagActionType.SPECIAL), ("u", int(RatbagActionSpecial.RESOLUTION_ALTERNATE))),
        )

        prof0_writes = _extract_profile_button_writes(dbus1.set_property.call_args_list, "p0")
        self.assertEqual([idx for idx, _ in prof0_writes], [str(i) for i in range(11)])
        self.assertEqual(
            prof0_writes[4][1],
            (int(RatbagActionType.SPECIAL), ("u", int(RatbagActionSpecial.RESOLUTION_ALTERNATE))),
        )

        # Case 2: Unknown 11-button mouse -> resets only safe standard buttons 0..3
        dbus2 = _make_fake_dbus(_build_props_map("Mystery 11-Button Mouse", "1234", "5678", 11))
        backend2 = RatbagBackend(dbus_client=dbus2)
        self.assertTrue(backend2.reset_defaults("ratbag_dev0"))
        prof1_unknown = _extract_profile_button_writes(dbus2.set_property.call_args_list, "p1")
        self.assertEqual([idx for idx, _ in prof1_unknown], ["0", "1", "2", "3"])
        prof0_unknown = _extract_profile_button_writes(dbus2.set_property.call_args_list, "p0")
        self.assertEqual([idx for idx, _ in prof0_unknown], ["0", "1", "2", "3"])

    @patch("lhub.backends.ratbag.hidpp.get_onboard_profile", return_value=None)
    @patch("lhub.backends.ratbag.hidpp.get_dpi", return_value=None)
    def test_inspect_device_parses_name_and_uses_layout_vendor(self, mock_dpi, mock_prof):
        with tempfile.TemporaryDirectory() as xdg_dir:
            devices_dir = Path(xdg_dir) / "lhub" / "devices"
            devices_dir.mkdir(parents=True)
            custom = _make_sample_layout(
                id="custom_vendor_mouse",
                name="Custom Vendor Mouse",
                vendor="CustomVendor",
                vid="1234",
                pids=["5678"],
                name_patterns=["custom vendor"],
            )
            (devices_dir / "custom.json").write_text(json.dumps(custom), encoding="utf-8")

            dev_path = "/org/freedesktop/ratbag1/device/dev0"
            p0 = "/org/freedesktop/ratbag1/profile/dev0/p0"
            props_map = {
                (dev_path, RATBAG_DEVICE_IFACE): {
                    "Name": "Custom Vendor Mouse",
                    "Model": "usb:1234:5678:0",
                    "DeviceType": 2,
                    "Profiles": [p0],
                },
                (p0, RATBAG_PROFILE_IFACE): {
                    "Index": 0,
                    "Disabled": False,
                    "IsActive": True,
                    "Resolutions": ["/r0"],
                    "Buttons": ["/b0", "/b1"],
                },
                ("/r0", RATBAG_RESOLUTION_IFACE): {"Index": 0, "Resolution": ("u", 800), "IsActive": True},
                ("/b0", RATBAG_BUTTON_IFACE): {"Index": 0, "Mapping": (int(RatbagActionType.BUTTON), ("u", 1))},
                ("/b1", RATBAG_BUTTON_IFACE): {"Index": 1, "Mapping": (int(RatbagActionType.BUTTON), ("u", 2))},
            }
            dbus = MagicMock()
            dbus.is_bus_available.return_value = True
            dbus.has_name_owner.return_value = True
            dbus.get_all_properties.side_effect = lambda svc, path, iface: dict(props_map.get((path, iface), {}))

            with patch.dict(os.environ, {"XDG_CONFIG_HOME": xdg_dir}):
                reload_layouts()
                backend = RatbagBackend(dbus_client=dbus)
                dev = backend._inspect_device("ratbag_dev0", dev_path)
                self.assertIsNotNone(dev)
                self.assertEqual(dev.name, "Custom Vendor Mouse")
                self.assertEqual(dev.vendor, "CustomVendor")
                self.assertEqual(dev.buttons[0].name, "Left Click")
        reload_layouts()

    def test_manager_reset_device_to_default_uses_device_layout(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = DeviceManager(auto_refresh=False)
            mgr.profile_mgr = ProfileManager(config_file=Path(td) / "profiles.json")
            mgr.backends = []

            g305_buttons = [
                ButtonMapping(index=0, name="LMB", action_value="key KEY_A", action_display="Key: A", default_action="button 1"),
                ButtonMapping(index=1, name="RMB", action_value="button 2", action_display="Right Click", default_action="button 2"),
                ButtonMapping(index=2, name="Wheel", action_value="button 3", action_display="Middle Click", default_action="button 3"),
                ButtonMapping(index=3, name="Back", action_value="button 4", action_display="Back", default_action="button 4"),
                ButtonMapping(index=4, name="Forward", action_value="key KEY_B", action_display="Key: B", default_action="button 5"),
                ButtonMapping(
                    index=5,
                    name="DPI Cycle",
                    action_value="key KEY_C",
                    action_display="Key: C",
                    default_action="special resolution-cycle-up",
                ),
            ]
            g305 = Device(
                id="g305-dev",
                name="Logitech Gaming Mouse G305",
                vendor="Logitech",
                device_type=DeviceType.MOUSE,
                usb_vid="046d",
                usb_pid="4074",
                capabilities=[Capability.BUTTON_REMAP],
                dpi=DpiInfo(current=800, steps=[400, 800, 1600]),
                buttons=g305_buttons,
            )

            unknown_buttons = [
                ButtonMapping(index=i, name=f"Btn {i + 1}", action_value="key KEY_Z", action_display="Key: Z", default_action=f"button {i + 1}")
                for i in range(5)
            ]
            unknown_dev = Device(
                id="unknown-dev",
                name="Generic 5-Button Mouse",
                vendor="Generic",
                device_type=DeviceType.MOUSE,
                usb_vid="9999",
                usb_pid="0005",
                capabilities=[Capability.BUTTON_REMAP],
                buttons=unknown_buttons,
            )

            mgr._devices = [g305, unknown_dev]
            mgr._cached_dict_devices = [
                device_to_dict(g305, mgr.profile_mgr),
                device_to_dict(unknown_dev, mgr.profile_mgr),
            ]

            with patch("lhub.manager.threading.Thread") as mock_thread:
                self.assertTrue(mgr.resetDeviceToDefault("g305-dev"))
                self.assertTrue(mgr.resetDeviceToDefault("unknown-dev"))
                self.assertEqual(mock_thread.call_count, 2)

            g305_cached = {b["index"]: b for b in mgr._cached_dict_devices[0]["buttons"]}
            self.assertEqual(g305_cached[4]["action"], "button 5")
            self.assertEqual(g305_cached[5]["action"], "special resolution-cycle-up")
            self.assertFalse(g305_cached[5]["isCustomized"])

            unknown_cached = {b["index"]: b for b in mgr._cached_dict_devices[1]["buttons"]}
            self.assertEqual(unknown_cached[4]["action"], "button 5")
            self.assertFalse(unknown_cached[4]["isCustomized"])


if __name__ == "__main__":
    unittest.main()
