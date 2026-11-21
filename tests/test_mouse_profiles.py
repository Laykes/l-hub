import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lhub.profiles import ProfileManager
from lhub.backends.ratbag import (
    RATBAG_BUTTON_IFACE,
    RATBAG_DEVICE_IFACE,
    RATBAG_SERVICE,
    RatbagActionSpecial,
    RatbagActionType,
    RatbagBackend,
    RatbagMacroEvent,
    decode_dbus_button_mapping,
    encode_dbus_button_mapping,
    parse_button_action,
)


class TestMouseProfiles(unittest.TestCase):
    def test_profile_manager_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            conf = Path(td) / "profiles.json"
            pm = ProfileManager(config_file=conf)
            dev_key = "046d:c099"

            # Initially default profile is Default
            self.assertEqual(pm.get_profiles(dev_key), ["Default"])
            self.assertEqual(pm.get_active_profile(dev_key), "Default")

            # Ensure default profile initializes
            pm.ensure_default_profile(dev_key, {4: "button 1", 5: "button 2", 8: "special resolution-alternate"}, 800)
            self.assertEqual(
                pm.get_profile_data(dev_key, "Default"),
                {
                    "buttons": {"4": "button 1", "5": "button 2", "8": "special resolution-alternate"},
                    "dpi": 800,
                },
            )

            # Create new profile
            pm.save_profile(dev_key, "Gaming", {4: "button 1", 5: "button 2", 8: "special doubleclick"}, 1600)
            self.assertEqual(pm.get_profiles(dev_key), ["Default", "Gaming"])
            self.assertEqual(pm.get_active_profile(dev_key), "Gaming")

            # Update button in active profile
            pm.update_active_button(dev_key, 8, "key KEY_SPACE")
            gaming_data = pm.get_profile_data(dev_key, "Gaming")
            self.assertEqual(gaming_data["buttons"]["8"], "key KEY_SPACE")

            # Switch active profile
            pm.set_active_profile(dev_key, "Default")
            self.assertEqual(pm.get_active_profile(dev_key), "Default")

            # Delete profile
            self.assertTrue(pm.delete_profile(dev_key, "Gaming"))
            self.assertEqual(pm.get_profiles(dev_key), ["Default"])

            # Default cannot be deleted
            self.assertFalse(pm.delete_profile(dev_key, "Default"))

            # Test reset_to_default
            pm.reset_to_default(dev_key, {0: "button 1", 1: "button 2", 4: "special resolution-alternate"}, 1600)
            def_data = pm.get_profile_data(dev_key, "Default")
            self.assertEqual(def_data["buttons"]["0"], "button 1")
            self.assertEqual(def_data["buttons"]["1"], "button 2")
            self.assertEqual(def_data["buttons"]["4"], "special resolution-alternate")
            self.assertEqual(def_data["dpi"], 1600)
            self.assertEqual(pm.get_active_profile(dev_key), "Default")

    def test_parse_button_action(self):
        act, disp = parse_button_action("'button 1'")
        self.assertEqual(act, "button 1")
        self.assertEqual(disp, "Left Click")

        act, disp = parse_button_action("resolution-alternate")
        self.assertEqual(act, "special resolution-alternate")
        self.assertEqual(disp, "DPI Shift (Sniper)")

        act, disp = parse_button_action("second-mode")
        self.assertEqual(act, "special second-mode")
        self.assertEqual(disp, "G-Shift (Secondary Mode)")

        act, disp = parse_button_action("key 'KEY_SPACE'")
        self.assertEqual(act, "key KEY_SPACE")
        self.assertEqual(disp, "Key: Space")

        act, disp = parse_button_action("none")
        self.assertEqual(act, "disabled")
        self.assertEqual(disp, "Disabled")

        act, disp = parse_button_action("UNKNOWN")
        self.assertEqual(act, "unknown")
        self.assertEqual(disp, "Default / Unknown")

        act, disp = parse_button_action("unknown")
        self.assertEqual(act, "unknown")
        self.assertEqual(disp, "Default / Unknown")

        # Macro parsing
        act, disp = parse_button_action("macro '↓KEY_LEFTCTRL ↕KEY_C ↑KEY_LEFTCTRL'")
        self.assertEqual(act, "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL")
        self.assertEqual(disp, "Copy (Ctrl+C)")

        act, disp = parse_button_action("macro +KEY_LEFTCTRL KEY_V -KEY_LEFTCTRL")
        self.assertEqual(act, "macro +KEY_LEFTCTRL KEY_V -KEY_LEFTCTRL")
        self.assertEqual(disp, "Paste (Ctrl+V)")

        # Custom multi-modifier macro strips quotes & normalizes ratbagctl arrows
        act, disp = parse_button_action("macro '↓KEY_LEFTCTRL ↓KEY_LEFTSHIFT ↕KEY_C ↑KEY_LEFTSHIFT ↑KEY_LEFTCTRL'")
        self.assertEqual(act, "macro +KEY_LEFTCTRL +KEY_LEFTSHIFT KEY_C -KEY_LEFTSHIFT -KEY_LEFTCTRL")
        self.assertNotIn("Copy", disp)

        # Substring keys like KEY_F5 / KEY_SPACE / KEY_TAB must not match Ctrl+F / Ctrl+S / Ctrl+T
        act, disp = parse_button_action("macro '↓KEY_LEFTCTRL ↕KEY_F5 ↑KEY_LEFTCTRL'")
        self.assertEqual(act, "macro +KEY_LEFTCTRL KEY_F5 -KEY_LEFTCTRL")
        self.assertNotIn("Find", disp)

        act, disp = parse_button_action("macro '↓KEY_LEFTCTRL ↕KEY_SPACE ↑KEY_LEFTCTRL'")
        self.assertEqual(act, "macro +KEY_LEFTCTRL KEY_SPACE -KEY_LEFTCTRL")
        self.assertNotIn("Save", disp)

        act, disp = parse_button_action("macro '↓KEY_LEFTCTRL ↕KEY_TAB ↑KEY_LEFTCTRL'")
        self.assertEqual(act, "macro +KEY_LEFTCTRL KEY_TAB -KEY_LEFTCTRL")
        self.assertNotIn("New Tab", disp)

    def test_button_metadata(self):
        from lhub.backends.ratbag import get_button_metadata
        # Test G502 metadata
        meta = get_button_metadata("Logitech G502 X", "046d", "c099", 4, "resolution-alternate", 11)
        self.assertIn("Sniper", meta["name"])
        self.assertEqual(meta["group"], "side")
        self.assertEqual(meta["default"], "special resolution-alternate")

        meta0 = get_button_metadata("Logitech G502 X", "046d", "c099", 0, "button 1", 11)
        self.assertIn("Left Click", meta0["name"])
        self.assertEqual(meta0["group"], "main")

    def test_dbus_button_mapping_roundtrip_codecs(self):
        # NONE
        enc_none = encode_dbus_button_mapping("disabled")
        self.assertEqual(enc_none, (int(RatbagActionType.NONE), ("u", 0)))
        self.assertEqual(decode_dbus_button_mapping(enc_none), ("disabled", "Disabled"))

        # BUTTON
        enc_btn = encode_dbus_button_mapping("button 4")
        self.assertEqual(enc_btn, (int(RatbagActionType.BUTTON), ("u", 4)))
        self.assertEqual(decode_dbus_button_mapping(enc_btn), ("button 4", "Back (Button 4)"))

        # SPECIAL
        enc_spec = encode_dbus_button_mapping("special resolution-alternate")
        self.assertEqual(
            enc_spec,
            (int(RatbagActionType.SPECIAL), ("u", int(RatbagActionSpecial.RESOLUTION_ALTERNATE))),
        )
        self.assertEqual(
            decode_dbus_button_mapping(enc_spec),
            ("special resolution-alternate", "DPI Shift (Sniper)"),
        )

        # KEY
        enc_key = encode_dbus_button_mapping("key KEY_SPACE")
        self.assertEqual(enc_key, (int(RatbagActionType.KEY), ("u", 57)))
        self.assertEqual(decode_dbus_button_mapping(enc_key), ("key KEY_SPACE", "Key: Space"))

        # MACRO with press/release + wait
        enc_macro = encode_dbus_button_mapping("macro +KEY_LEFTCTRL KEY_C t10ms -KEY_LEFTCTRL")
        self.assertEqual(
            enc_macro,
            (
                int(RatbagActionType.MACRO),
                (
                    "a(uu)",
                    [
                        (int(RatbagMacroEvent.KEY_PRESS), 29),
                        (int(RatbagMacroEvent.KEY_PRESS), 46),
                        (int(RatbagMacroEvent.KEY_RELEASE), 46),
                        (int(RatbagMacroEvent.WAIT), 10),
                        (int(RatbagMacroEvent.KEY_RELEASE), 29),
                    ],
                ),
            ),
        )
        act, disp = decode_dbus_button_mapping(enc_macro)
        self.assertEqual(act, "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL")
        self.assertEqual(disp, "Copy (Ctrl+C)")

    def test_batch_remap_buttons_commits_once_via_dbus(self):
        dev_path = "/org/freedesktop/ratbag1/device/mouse"
        dbus = MagicMock()
        dbus.is_bus_available.return_value = True
        dbus.has_name_owner.return_value = True
        dbus.call_method.return_value = (0,)

        backend = RatbagBackend(dbus_client=dbus)
        backend._device_paths["mouse"] = dev_path
        backend._active_profiles["mouse"] = 0
        backend._profile_paths["mouse"] = {0: "/org/freedesktop/ratbag1/profile/mouse/p0"}
        backend._resolution_paths["mouse"] = {0: {}}
        backend._resolution_is_xy["mouse"] = {0: {}}
        backend._button_paths["mouse"] = {
            0: {
                3: "/org/freedesktop/ratbag1/button/mouse/p0/b3",
                4: "/org/freedesktop/ratbag1/button/mouse/p0/b4",
            }
        }

        ok = backend.batch_remap_buttons(
            "mouse",
            {
                3: "key KEY_F5",
                4: "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL",
            },
        )
        self.assertTrue(ok)
        self.assertEqual(dbus.set_property.call_count, 2)
        dbus.set_property.assert_any_call(
            RATBAG_SERVICE,
            "/org/freedesktop/ratbag1/button/mouse/p0/b3",
            RATBAG_BUTTON_IFACE,
            "Mapping",
            "(uv)",
            (int(RatbagActionType.KEY), ("u", 63)),
        )
        dbus.call_method.assert_called_once_with(RATBAG_SERVICE, dev_path, RATBAG_DEVICE_IFACE, "Commit")

    def test_encode_key_prefers_macro_for_non_modifiers_when_enabled(self):
        # Non-modifier keys become a press+release macro so libratbag hidpp20 zeroes modifier_flags
        enc_f5 = encode_dbus_button_mapping("key KEY_F5", prefer_macro_for_keys=True)
        self.assertEqual(
            enc_f5,
            (
                int(RatbagActionType.MACRO),
                (
                    "a(uu)",
                    [
                        (int(RatbagMacroEvent.KEY_PRESS), 63),
                        (int(RatbagMacroEvent.KEY_RELEASE), 63),
                    ],
                ),
            ),
        )
        # Standalone modifier keys must remain ActionType.KEY because libratbag's
        # ratbag_action_keycode_from_macro does not accept modifier-only macros.
        enc_meta = encode_dbus_button_mapping("key KEY_LEFTMETA", prefer_macro_for_keys=True)
        self.assertEqual(enc_meta, (int(RatbagActionType.KEY), ("u", 125)))

    @patch("lhub.backends.ratbag.time.sleep")
    @patch("lhub.backends.ratbag.hidpp.set_onboard_profile", return_value=True)
    @patch("lhub.backends.ratbag.hidpp.get_onboard_profile", return_value=0x0002)
    def test_remap_button_logitech_uses_macro_for_f5_and_verifies_commit(
        self, _mock_get_prof, mock_set_prof, _mock_sleep
    ):
        dev_path = "/org/freedesktop/ratbag1/device/hidraw6"
        prof_path = "/org/freedesktop/ratbag1/profile/hidraw6/p1"
        btn_path = "/org/freedesktop/ratbag1/button/hidraw6/p1/b7"
        dbus = MagicMock()
        dbus.is_bus_available.return_value = True
        dbus.has_name_owner.return_value = True
        dbus.call_method.return_value = (0,)
        # First Commit attempt leaves profile dirty (e.g. transient USB timeout), retry clears it
        dbus.get_property.side_effect = [True, True, True, True, True, True, False]

        backend = RatbagBackend(dbus_client=dbus)
        backend._usb_ids["ratbag_hidraw6"] = ("046d", "c099")
        backend._device_paths["ratbag_hidraw6"] = dev_path
        backend._profile_paths["ratbag_hidraw6"] = {1: prof_path}
        backend._button_paths["ratbag_hidraw6"] = {1: {7: btn_path}}
        backend._resolution_paths["ratbag_hidraw6"] = {1: {}}
        backend._resolution_is_xy["ratbag_hidraw6"] = {1: {}}

        ok = backend.remap_button("ratbag_hidraw6", 7, "key KEY_F5")
        self.assertTrue(ok)
        dbus.set_property.assert_called_once_with(
            RATBAG_SERVICE,
            btn_path,
            RATBAG_BUTTON_IFACE,
            "Mapping",
            "(uv)",
            (
                int(RatbagActionType.MACRO),
                (
                    "a(uu)",
                    [
                        (int(RatbagMacroEvent.KEY_PRESS), 63),
                        (int(RatbagMacroEvent.KEY_RELEASE), 63),
                    ],
                ),
            ),
        )
        self.assertEqual(dbus.call_method.call_count, 2)
        mock_set_prof.assert_called_once_with("046d", "c099", 0x0002)

    @patch("lhub.backends.ratbag.time.sleep")
    @patch("lhub.backends.ratbag.hidpp.set_onboard_profile", return_value=True)
    @patch("lhub.backends.ratbag.hidpp.get_onboard_profile", return_value=0x0002)
    def test_remap_button_returns_false_when_profile_stays_dirty(
        self, _mock_get_prof, mock_set_prof, _mock_sleep
    ):
        dev_path = "/org/freedesktop/ratbag1/device/hidraw6"
        prof_path = "/org/freedesktop/ratbag1/profile/hidraw6/p1"
        btn_path = "/org/freedesktop/ratbag1/button/hidraw6/p1/b7"
        dbus = MagicMock()
        dbus.is_bus_available.return_value = True
        dbus.has_name_owner.return_value = True
        dbus.call_method.return_value = (0,)
        dbus.get_property.return_value = True

        backend = RatbagBackend(dbus_client=dbus)
        backend._usb_ids["ratbag_hidraw6"] = ("046d", "c099")
        backend._device_paths["ratbag_hidraw6"] = dev_path
        backend._profile_paths["ratbag_hidraw6"] = {1: prof_path}
        backend._button_paths["ratbag_hidraw6"] = {1: {7: btn_path}}
        backend._resolution_paths["ratbag_hidraw6"] = {1: {}}
        backend._resolution_is_xy["ratbag_hidraw6"] = {1: {}}

        ok = backend.remap_button("ratbag_hidraw6", 7, "key KEY_F5")
        self.assertFalse(ok)
        mock_set_prof.assert_not_called()


if __name__ == "__main__":
    unittest.main()
