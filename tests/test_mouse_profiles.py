import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lhub.profiles import ProfileManager
from lhub.backends.ratbag import parse_button_action


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

        # Macro parsing
        act, disp = parse_button_action("macro '↓KEY_LEFTCTRL ↕KEY_C ↑KEY_LEFTCTRL'")
        self.assertEqual(act, "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL")
        self.assertEqual(disp, "Copy (Ctrl+C)")

        act, disp = parse_button_action("macro +KEY_LEFTCTRL KEY_V -KEY_LEFTCTRL")
        self.assertEqual(act, "macro +KEY_LEFTCTRL KEY_V -KEY_LEFTCTRL")
        self.assertEqual(disp, "Paste (Ctrl+V)")

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


if __name__ == "__main__":
    unittest.main()
