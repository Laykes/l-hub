import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent, QWheelEvent

from lhub.backends.base import (
    BatteryInfo,
    ButtonMapping,
    Capability,
    Device,
    DeviceType,
    DpiInfo,
)
from lhub.button_tester import ButtonTesterController
from lhub.keymap import (
    _QT_MODIFIER_KEYS,
    _QT_TO_LINUX_KEY,
    _qt_key_to_linux,
    _qt_modifiers_to_linux,
    map_key_event,
    map_mouse_button,
    resolve_key_action,
)
from lhub.profiles import ProfileManager
from lhub.serializers import (
    button_to_dict,
    device_to_dict,
    format_battery_time_remaining,
    get_device_key,
)

_app = QGuiApplication.instance() or QGuiApplication(sys.argv)


class TestKeymap(unittest.TestCase):
    def test_qt_key_to_linux_variants(self):
        self.assertEqual(_qt_key_to_linux(Qt.Key.Key_Space), "KEY_SPACE")
        self.assertEqual(_qt_key_to_linux(Qt.Key.Key_MediaPlay), "KEY_PLAYPAUSE")
        self.assertEqual(_qt_key_to_linux(Qt.Key.Key_F1), "KEY_F1")
        self.assertEqual(_qt_key_to_linux(Qt.Key.Key_F24), "KEY_F24")
        self.assertEqual(_qt_key_to_linux(Qt.Key.Key_A), "KEY_A")
        self.assertEqual(_qt_key_to_linux(Qt.Key.Key_Z), "KEY_Z")
        self.assertEqual(_qt_key_to_linux(Qt.Key.Key_0), "KEY_0")
        self.assertEqual(_qt_key_to_linux(Qt.Key.Key_9), "KEY_9")
        self.assertIsNone(_qt_key_to_linux(Qt.Key.Key_unknown))
        self.assertIn(Qt.Key.Key_Shift, _QT_MODIFIER_KEYS)
        self.assertIn(Qt.Key.Key_F12, _QT_TO_LINUX_KEY)

    def test_qt_modifiers_to_linux_order(self):
        mods = _qt_modifiers_to_linux(
            Qt.KeyboardModifier.ShiftModifier
            | Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        self.assertEqual(
            mods,
            ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_LEFTSHIFT", "KEY_LEFTMETA"],
        )
        self.assertEqual(_qt_modifiers_to_linux(0), [])

    def test_resolve_key_action_single_modifier_and_unknown(self):
        shift_res = resolve_key_action(Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier.value)
        self.assertEqual(shift_res["action"], "key KEY_LEFTSHIFT")

        combo_res = resolve_key_action(Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier.value)
        self.assertEqual(combo_res["action"], "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL")
        self.assertEqual(combo_res["display"], "Copy (Ctrl+C)")

        self.assertEqual(resolve_key_action(Qt.Key.Key_unknown, 0), {})

    def test_map_mouse_button_standard_extra_and_fallback(self):
        self.assertEqual(map_mouse_button(Qt.MouseButton.LeftButton), ("button 1", "Left Click (Button 1)"))
        self.assertEqual(map_mouse_button(Qt.MouseButton.ExtraButton9), ("button 12", "Button 12"))
        # Raw bitmask outside named enum values falls back to log2 mapping
        self.assertEqual(map_mouse_button(1 << 15), ("button 16", "Button 16"))
        self.assertEqual(map_mouse_button(Qt.MouseButton.NoButton), ("unknown", "Unknown Mouse Button"))

    def test_map_key_event_with_extra_modifiers_and_fallback(self):
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.NoModifier)
        act, disp = map_key_event(ev, extra_modifiers=["KEY_LEFTCTRL"])
        self.assertEqual(act, "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL")
        self.assertEqual(disp, "Copy (Ctrl+C)")

        ev_mod = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(map_key_event(ev_mod), ("key KEY_LEFTCTRL", "Key: Left Ctrl"))


class TestSerializers(unittest.TestCase):
    def test_get_device_key(self):
        usb_dev = Device(
            id="d1",
            name="Logitech G502 X",
            vendor="Logitech",
            device_type=DeviceType.MOUSE,
            usb_vid="046d",
            usb_pid="c099",
        )
        self.assertEqual(get_device_key(usb_dev), "046d:c099")

        fallback_dev = Device(
            id="d2",
            name="Test-Headset  Pro",
            vendor="Vendor",
            device_type=DeviceType.HEADSET,
        )
        self.assertEqual(get_device_key(fallback_dev), "test headset  pro")

    def test_format_battery_time_remaining(self):
        self.assertEqual(format_battery_time_remaining(None), "")
        self.assertEqual(
            format_battery_time_remaining(BatteryInfo(percentage=100, is_charging=True, time_to_full_min=0)),
            "Fully charged",
        )
        self.assertEqual(
            format_battery_time_remaining(BatteryInfo(percentage=50, is_charging=True, time_to_full_min=95)),
            "Full in ~1 hr 35 min",
        )
        self.assertEqual(
            format_battery_time_remaining(BatteryInfo(percentage=80, is_charging=True, time_to_full_min=25)),
            "Full in ~25 min",
        )
        self.assertEqual(
            format_battery_time_remaining(BatteryInfo(percentage=40, is_charging=True, time_to_full_min=None)),
            "",
        )
        self.assertEqual(
            format_battery_time_remaining(BatteryInfo(percentage=50, is_charging=False, time_to_empty_min=135)),
            "~2 hr 15 min",
        )
        self.assertEqual(
            format_battery_time_remaining(BatteryInfo(percentage=10, is_charging=False, time_to_empty_min=45)),
            "~45 min",
        )
        self.assertEqual(
            format_battery_time_remaining(BatteryInfo(percentage=10, is_charging=False, time_to_empty_min=None)),
            "",
        )

    def test_button_to_dict_customized_flag(self):
        default_btn = ButtonMapping(
            index=0,
            name="Left Click",
            action_value="button 1",
            action_display="Left Click",
            label="Primary",
            location="Top",
            group="main",
            default_action="button 1",
        )
        self.assertFalse(button_to_dict(default_btn)["isCustomized"])

        custom_btn = ButtonMapping(
            index=4,
            name="Sniper",
            action_value="key KEY_F5",
            action_display="Key: F5",
            default_action="special resolution-alternate",
        )
        serialized = button_to_dict(custom_btn)
        self.assertTrue(serialized["isCustomized"])
        self.assertEqual(serialized["label"], "Sniper")
        self.assertEqual(serialized["actionDisplay"], "Key: F5")

    def test_device_to_dict_with_and_without_profile_mgr(self):
        dev = Device(
            id="mouse1",
            name="Logitech G502 X",
            vendor="Logitech",
            device_type=DeviceType.MOUSE,
            usb_vid="046d",
            usb_pid="c099",
            capabilities=[Capability.BATTERY, Capability.DPI, Capability.BUTTON_REMAP],
            battery=BatteryInfo(percentage=80, is_charging=False, time_to_empty_min=120),
            dpi=DpiInfo(current=1600, steps=[800, 1600, 3200], is_disabled=False),
            buttons=[ButtonMapping(index=0, name="Left", action_value="button 1", action_display="Left Click")],
            onboard_profile="Profile 1",
            status_note="Note",
            backend_name="ratbag",
        )

        no_pm = device_to_dict(dev)
        self.assertEqual(no_pm["profiles"], ["Default"])
        self.assertEqual(no_pm["activeProfile"], "Default")
        self.assertEqual(no_pm["batteryTimeRemaining"], "~2 hr 0 min")
        self.assertEqual(no_pm["currentDpi"], 1600)
        self.assertTrue(no_pm["hasOnboardProfile"])

        with tempfile.TemporaryDirectory() as td:
            pm = ProfileManager(config_file=Path(td) / "profiles.json")
            pm.save_profile("046d:c099", "Gaming", {0: "button 1"}, 1600)
            with_pm = device_to_dict(dev, pm)
            self.assertIn("Gaming", with_pm["profiles"])
            self.assertEqual(with_pm["activeProfile"], "Gaming")


class TestButtonTesterControllerStandalone(unittest.TestCase):
    def setUp(self):
        self.dev = Device(
            id="dev-1",
            name="Test Mouse",
            vendor="Logitech",
            device_type=DeviceType.MOUSE,
            capabilities=[Capability.BUTTON_REMAP],
            buttons=[
                ButtonMapping(index=0, name="Left", action_value="button 1", action_display="Left Click"),
                ButtonMapping(index=1, name="Mute", action_value="key KEY_MUTE", action_display="Key: Mute"),
                ButtonMapping(index=2, name="TiltL", action_value="special wheel-left", action_display="Wheel Left"),
                ButtonMapping(index=3, name="Shift", action_value="key KEY_LEFTSHIFT", action_display="Left Shift"),
            ],
        )
        self.controller = ButtonTesterController(
            device_lookup=lambda dev_id: self.dev if dev_id == self.dev.id else None
        )
        self.addCleanup(self.controller.cleanup)

    def test_lifecycle_timeout_and_clear(self):
        states = []
        results = []
        self.controller.testStateChanged.connect(lambda: states.append(self.controller.is_testing))
        self.controller.testResultChanged.connect(lambda: results.append(dict(self.controller.tested_button_result)))

        self.controller.start("dev-1")
        self.assertTrue(self.controller.is_testing)
        self.assertEqual(self.controller.testing_device_id, "dev-1")

        self.controller._on_test_timeout()
        self.assertFalse(self.controller.is_testing)
        self.assertIn("15 seconds", self.controller.tested_button_result["statusNote"])

        self.controller.clear_result()
        self.assertEqual(self.controller.tested_button_result, {})
        self.assertEqual(states, [True, False])
        self.assertEqual(len(results), 3)

    def test_pending_mod_timeout_and_escape_stop(self):
        self.controller.start("dev-1")
        self.controller.eventFilter(
            None, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier)
        )
        self.assertTrue(self.controller.is_testing)
        self.controller._on_pending_mod_timeout()
        self.assertFalse(self.controller.is_testing)
        self.assertEqual(self.controller.tested_button_result["matchingIndices"], [3])

        self.controller.start("dev-1")
        self.assertTrue(
            self.controller.eventFilter(
                None, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
            )
        )
        self.assertFalse(self.controller.is_testing)

    def test_hid_input_and_wheel_mouse_events(self):
        self.controller.start("dev-1")
        self.controller.handle_hid_input("key KEY_MUTE", "Key: Mute")
        self.assertFalse(self.controller.is_testing)
        self.assertEqual(self.controller.tested_button_result["matchingIndices"], [1])

        # Trailing Qt KeyPress swallowed while suppression window is active
        self.assertTrue(
            self.controller.eventFilter(
                None, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_VolumeMute, Qt.KeyboardModifier.NoModifier)
            )
        )

        # Wheel tilt left match
        self.controller.start("dev-1")
        wheel_ev = QWheelEvent(
            QPointF(0, 0),
            QPointF(0, 0),
            QPoint(0, 0),
            QPoint(120, 0),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        self.assertTrue(self.controller.eventFilter(None, wheel_ev))
        self.assertEqual(self.controller.tested_button_result["matchingIndices"], [2])

        # Mouse click match
        self.controller.start("dev-1")
        mouse_ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(0, 0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.assertTrue(self.controller.eventFilter(None, mouse_ev))
        self.assertEqual(self.controller.tested_button_result["matchingIndices"], [0])


if __name__ == "__main__":
    unittest.main()
