import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, Qt, QPoint, QPointF
from PySide6.QtGui import QMouseEvent, QKeyEvent, QWheelEvent, QGuiApplication
from lhub.manager import DeviceManager
from lhub.backends.base import Device, DeviceType, Capability, ButtonMapping
from lhub.backends.hid_input import parse_report_descriptor, HidReportTracker
from lhub.backends.ratbag import actions_match


# Ensure a QGuiApplication exists for event handling
_app = QGuiApplication.instance() or QGuiApplication(sys.argv)


class TestButtonTester(unittest.TestCase):
    def setUp(self):
        self.manager = DeviceManager(auto_refresh=False, enable_hotplug=False)
        self.manager.backends = []
        self.manager.refresh_devices = MagicMock()
        self.addCleanup(self.manager.cleanup)
        # Mock devices in manager
        test_buttons = [
            ButtonMapping(index=0, name="Button 1", action_value="button 1", action_display="Left Click"),
            ButtonMapping(index=1, name="Button 2", action_value="unknown", action_display="Default / Unknown"),
            ButtonMapping(index=2, name="Button 3", action_value="unknown", action_display="Default / Unknown"),
            ButtonMapping(index=3, name="Button 4", action_value="unknown", action_display="Default / Unknown"),
            ButtonMapping(index=4, name="Button 5", action_value="button 1", action_display="Left Click"),
            ButtonMapping(index=5, name="Button 6", action_value="button 2", action_display="Right Click"),
            ButtonMapping(index=6, name="Button 7", action_value="button 3", action_display="Middle Click"),
            ButtonMapping(index=7, name="Button 8", action_value="button 4", action_display="Back (Button 4)"),
            ButtonMapping(index=8, name="Button 9", action_value="key KEY_PLAYPAUSE", action_display="Key: Play/Pause"),
            ButtonMapping(index=9, name="Button 10", action_value="button 5", action_display="Forward (Button 5)"),
            ButtonMapping(index=10, name="Button 11", action_value="special wheel-left", action_display="Scroll Wheel Left"),
            ButtonMapping(index=11, name="Button 12", action_value="special wheel-right", action_display="Scroll Wheel Right"),
        ]
        self.test_dev = Device(
            id="test-mouse",
            name="Logitech G502 X",
            vendor="Logitech",
            device_type=DeviceType.MOUSE,
            capabilities=[Capability.BUTTON_REMAP],
            buttons=test_buttons,
        )
        self.manager._devices = [self.test_dev]

    def test_start_and_stop_button_test(self):
        self.assertFalse(self.manager.isTestingButton)
        self.manager.startButtonTest("test-mouse")
        self.assertTrue(self.manager.isTestingButton)
        self.assertEqual(self.manager.testingDeviceId, "test-mouse")

        self.manager.stopButtonTest()
        self.assertFalse(self.manager.isTestingButton)

    def test_detect_right_click(self):
        self.manager.startButtonTest("test-mouse")
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(0, 0),
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
        )
        handled = self.manager.eventFilter(None, ev)
        self.assertTrue(handled)
        self.assertFalse(self.manager.isTestingButton)

        res = self.manager.testedButtonResult
        self.assertEqual(res["deviceId"], "test-mouse")
        self.assertEqual(res["action"], "button 2")
        self.assertIn("Right Click", res["detectedName"])
        self.assertEqual(res["matchingIndices"], [5])
        self.assertEqual(res["matchingNames"], ["Button 6"])

    def test_detect_back_button(self):
        self.manager.startButtonTest("test-mouse")
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(0, 0),
            Qt.MouseButton.BackButton,
            Qt.MouseButton.BackButton,
            Qt.KeyboardModifier.NoModifier,
        )
        handled = self.manager.eventFilter(None, ev)
        self.assertTrue(handled)

        res = self.manager.testedButtonResult
        self.assertEqual(res["action"], "button 4")
        self.assertEqual(res["matchingIndices"], [7])
        self.assertEqual(res["matchingNames"], ["Button 8"])

    def test_detect_media_key(self):
        self.manager.startButtonTest("test-mouse")
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_MediaPlay, Qt.KeyboardModifier.NoModifier)
        handled = self.manager.eventFilter(None, ev)
        self.assertTrue(handled)

        res = self.manager.testedButtonResult
        self.assertEqual(res["action"], "key KEY_PLAYPAUSE")
        self.assertEqual(res["matchingIndices"], [8])
        self.assertEqual(res["matchingNames"], ["Button 9"])

    def test_detect_wheel_tilt(self):
        # In Qt, horizontal angleDelta().x() > 0 means scroll/tilt left
        self.manager.startButtonTest("test-mouse")
        ev_left = QWheelEvent(
            QPointF(0, 0),
            QPointF(0, 0),
            QPoint(0, 0),
            QPoint(120, 0),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        self.assertTrue(self.manager.eventFilter(None, ev_left))
        res = self.manager.testedButtonResult
        self.assertEqual(res["action"], "special wheel-left")
        self.assertEqual(res["matchingIndices"], [10])
        self.assertEqual(res["matchingNames"], ["Button 11"])

        # angleDelta().x() < 0 means scroll/tilt right
        self.manager.startButtonTest("test-mouse")
        ev_right = QWheelEvent(
            QPointF(0, 0),
            QPointF(0, 0),
            QPoint(0, 0),
            QPoint(-120, 0),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        self.assertTrue(self.manager.eventFilter(None, ev_right))
        res = self.manager.testedButtonResult
        self.assertEqual(res["action"], "special wheel-right")
        self.assertEqual(res["matchingIndices"], [11])
        self.assertEqual(res["matchingNames"], ["Button 12"])

        # Natural/inverted scroll flips angleDelta(), so inverted=True with -120 is tilt left
        self.manager.startButtonTest("test-mouse")
        ev_inverted_left = QWheelEvent(
            QPointF(0, 0),
            QPointF(0, 0),
            QPoint(0, 0),
            QPoint(-120, 0),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            True,
        )
        self.assertTrue(self.manager.eventFilter(None, ev_inverted_left))
        self.assertEqual(self.manager.testedButtonResult["action"], "special wheel-left")

    def test_escape_cancels_test(self):
        self.manager.startButtonTest("test-mouse")
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        handled = self.manager.eventFilter(None, ev)
        self.assertTrue(handled)
        self.assertFalse(self.manager.isTestingButton)
        self.assertEqual(self.manager.testedButtonResult, {})

    def test_clear_test_result(self):
        self.manager.startButtonTest("test-mouse")
        ev = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(0, 0),
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.MiddleButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.manager.eventFilter(None, ev)
        self.assertNotEqual(self.manager.testedButtonResult, {})
        self.manager.clearTestResult()
        self.assertEqual(self.manager.testedButtonResult, {})

    def test_reset_device_to_default(self):
        self.manager._cached_dict_devices = [self.manager._device_to_dict(self.test_dev)]
        res = self.manager.resetDeviceToDefault("test-mouse")
        self.assertTrue(res)
        # Verify local cache updated immediately
        cached = self.manager._cached_dict_devices[0]
        self.assertEqual(cached["activeProfile"], "Default")
        buttons = {b["index"]: b["action"] for b in cached["buttons"]}
        self.assertEqual(buttons[0], "button 1")
        self.assertEqual(buttons[1], "button 2")
        self.assertEqual(buttons[4], "special resolution-alternate")


    def test_reset_button_to_default(self):
        self.test_dev.buttons[4].default_action = "button 1"
        self.test_dev.buttons[4].action_value = "key KEY_F5"
        self.manager._cached_dict_devices = [self.manager._device_to_dict(self.test_dev)]
        res = self.manager.resetButtonToDefault("test-mouse", 4)
        self.assertTrue(res)
        cached = self.manager._cached_dict_devices[0]
        btn4 = [b for b in cached["buttons"] if b["index"] == 4][0]
        self.assertEqual(btn4["action"], "button 1")

    def test_resolve_key_action(self):
        # Single key
        f5 = self.manager.resolveKeyAction(Qt.Key.Key_F5, 0)
        self.assertEqual(f5["action"], "key KEY_F5")
        self.assertEqual(f5["display"], "Key: F5")

        space = self.manager.resolveKeyAction(Qt.Key.Key_Space, 0)
        self.assertEqual(space["action"], "key KEY_SPACE")

        # Shortcut combos
        ctrl_c = self.manager.resolveKeyAction(Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier.value)
        self.assertEqual(ctrl_c["action"], "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL")
        self.assertEqual(ctrl_c["display"], "Copy (Ctrl+C)")

        alt_tab = self.manager.resolveKeyAction(Qt.Key.Key_Tab, Qt.KeyboardModifier.AltModifier.value)
        self.assertEqual(alt_tab["action"], "macro +KEY_LEFTALT KEY_TAB -KEY_LEFTALT")
        self.assertEqual(alt_tab["display"], "Switch App (Alt+Tab)")

    def test_detect_macro_shortcut_via_qt(self):
        self.test_dev.buttons[1].action_value = "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL"
        self.test_dev.buttons[1].action_display = "Copy (Ctrl+C)"
        self.manager.startButtonTest("test-mouse")

        # Mouse macro presses Ctrl first, then C with Ctrl modifier
        ev_ctrl = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.manager.eventFilter(None, ev_ctrl))
        self.assertTrue(self.manager.isTestingButton)

        ev_c = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.manager.eventFilter(None, ev_c))
        self.assertFalse(self.manager.isTestingButton)

        res = self.manager.testedButtonResult
        self.assertEqual(res["action"], "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL")
        self.assertEqual(res["matchingIndices"], [1])
        self.assertEqual(res["matchingNames"], ["Button 2"])

    def test_detect_multi_modifier_macro_via_qt(self):
        # Configured with different release order and delay token
        self.test_dev.buttons[2].action_value = "macro +KEY_LEFTSHIFT +KEY_LEFTCTRL t10ms +KEY_T -KEY_T -KEY_LEFTCTRL -KEY_LEFTSHIFT"
        self.manager.startButtonTest("test-mouse")

        self.manager.eventFilter(None, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier))
        self.manager.eventFilter(None, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        self.assertTrue(self.manager.isTestingButton)

        self.manager.eventFilter(None, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        self.assertFalse(self.manager.isTestingButton)

        res = self.manager.testedButtonResult
        self.assertEqual(res["matchingIndices"], [2])

    def test_detect_standalone_modifier_key_on_release_via_qt(self):
        self.test_dev.buttons[3].action_value = "key KEY_LEFTSHIFT"
        self.manager.startButtonTest("test-mouse")

        self.manager.eventFilter(None, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier))
        self.assertTrue(self.manager.isTestingButton)

        self.manager.eventFilter(None, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Shift, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(self.manager.isTestingButton)

        res = self.manager.testedButtonResult
        self.assertEqual(res["action"], "key KEY_LEFTSHIFT")
        self.assertEqual(res["matchingIndices"], [3])

    def test_detect_extended_keys_via_qt(self):
        self.test_dev.buttons[1].action_value = "key KEY_PAGEUP"
        self.test_dev.buttons[2].action_value = "key KEY_F13"
        self.test_dev.buttons[3].action_value = "key KEY_INSERT"

        for qt_key, expected_idx, expected_act in [
            (Qt.Key.Key_PageUp, 1, "key KEY_PAGEUP"),
            (Qt.Key.Key_F13, 2, "key KEY_F13"),
            (Qt.Key.Key_Insert, 3, "key KEY_INSERT"),
        ]:
            self.manager.startButtonTest("test-mouse")
            self.manager.eventFilter(None, QKeyEvent(QEvent.Type.KeyPress, qt_key, Qt.KeyboardModifier.NoModifier))
            res = self.manager.testedButtonResult
            self.assertEqual(res["action"], expected_act)
            self.assertEqual(res["matchingIndices"], [expected_idx])

    def test_hid_input_event_matches_custom_binds_and_suppresses_trailing_qt_event(self):
        self.test_dev.buttons[1].action_value = "key KEY_PRINT"
        self.manager.startButtonTest("test-mouse")

        # HID keyboard sends KEY_SYSRQ for PrintScreen -> matches KEY_PRINT
        self.manager._on_hid_input_event("key KEY_SYSRQ", "Key: Screenshot (PrintScreen)")
        self.assertFalse(self.manager.isTestingButton)
        self.assertEqual(self.manager.testedButtonResult["matchingIndices"], [1])

        # Trailing Qt KeyPress right after hidraw detection is swallowed
        trailing = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Print, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(self.manager.eventFilter(None, trailing))

        # Trailing Qt MouseButtonPress right after hidraw button detection is swallowed
        self.manager.startButtonTest("test-mouse")
        self.manager._on_hid_input_event("button 2", "Right Click (Button 2)")
        trailing_click = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(0, 0),
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.assertTrue(self.manager.eventFilter(None, trailing_click))

    def test_remap_button_immediately_updates_device_for_identify(self):
        self.manager._cached_dict_devices = [self.manager._device_to_dict(self.test_dev)]
        self.manager.backends = []
        self.manager.remapButton("test-mouse", 1, "key KEY_F5")

        self.manager.startButtonTest("test-mouse")
        self.manager.eventFilter(None, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F5, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(self.manager.testedButtonResult["matchingIndices"], [1])

    def test_actions_match_equivalences(self):
        self.assertTrue(actions_match("key KEY_F5", "macro +KEY_F5 -KEY_F5"))
        self.assertTrue(actions_match("macro KEY_F5", "key KEY_F5"))
        self.assertTrue(actions_match("key KEY_PRINT", "key KEY_SYSRQ"))
        self.assertTrue(actions_match(
            "macro +KEY_LEFTCTRL +KEY_LEFTSHIFT KEY_T -KEY_LEFTCTRL -KEY_LEFTSHIFT",
            "macro +KEY_LEFTSHIFT +KEY_LEFTCTRL KEY_T -KEY_LEFTSHIFT -KEY_LEFTCTRL",
        ))
        self.assertFalse(actions_match("key KEY_LEFTCTRL", "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL"))
        self.assertFalse(actions_match("key KEY_RIGHTCTRL", "key KEY_LEFTCTRL", relaxed_modifiers=False))
        self.assertTrue(actions_match("key KEY_RIGHTCTRL", "key KEY_LEFTCTRL", relaxed_modifiers=True))


class TestHidInputParser(unittest.TestCase):
    # Real Logitech G502 X HID report descriptors (mouse + keyboard/consumer/HID++)
    G502X_MOUSE_DESC = bytes.fromhex(
        "05 01 09 02 a1 01 09 01 a1 00 05 09 19 01 29 10 15 00 25 01 95 10 75 01 81 02 "
        "05 01 16 01 80 26 ff 7f 75 10 95 02 09 30 09 31 81 06 15 81 25 7f 75 08 95 01 "
        "09 38 81 06 05 0c 0a 38 02 95 01 81 06 c0 06 00 ff 09 f1 75 08 95 05 15 00 26 "
        "ff 00 81 00 c0"
    )
    G502X_KB_DESC = bytes.fromhex(
        "05 01 09 06 a1 01 85 01 05 07 19 e0 29 e7 15 00 25 01 75 01 95 08 81 02 81 03 "
        "95 06 75 08 15 00 26 ff 00 19 00 2a ff 00 81 00 c0 05 0c 09 01 a1 01 85 03 75 "
        "10 95 02 15 01 26 8c 02 19 01 2a 8c 02 81 00 c0 05 01 09 80 a1 01 85 04 75 02 "
        "95 01 15 01 25 03 09 82 09 81 09 83 81 60 75 06 81 03 c0 06 00 ff 09 01 a1 01 "
        "85 10 75 08 95 06 15 00 26 ff 00 09 01 81 00 09 01 91 00 c0 06 00 ff 09 02 a1 "
        "01 85 11 75 08 95 13 15 00 26 ff 00 09 02 81 00 09 02 91 00 c0"
    )

    def test_g502x_mouse_reports(self):
        layouts = parse_report_descriptor(self.G502X_MOUSE_DESC)
        self.assertIn(0, layouts)
        tracker = HidReportTracker(layouts)

        # Pure cursor movement produces nothing
        self.assertIsNone(tracker.process_report(bytes([0x00, 0x00, 0x05, 0x00, 0xFB, 0xFF, 0x00, 0x00, 0, 0, 0, 0, 0])))

        # Back button (button 4 -> bit 3 = 0x08)
        self.assertEqual(
            tracker.process_report(bytes([0x08, 0x00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])),
            ("button 4", "Back (Button 4)"),
        )
        # Holding button 4 while moving does not re-fire; releasing does not fire
        self.assertIsNone(tracker.process_report(bytes([0x08, 0x00, 0x01, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])))
        self.assertIsNone(tracker.process_report(bytes([0x00, 0x00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])))

        # Horizontal wheel tilt left (-1 = 0xFF at byte 7) and right (+1 = 0x01)
        self.assertEqual(
            tracker.process_report(bytes([0, 0, 0, 0, 0, 0, 0, 0xFF, 0, 0, 0, 0, 0])),
            ("special wheel-left", "Scroll Wheel Left"),
        )
        self.assertEqual(
            tracker.process_report(bytes([0, 0, 0, 0, 0, 0, 0, 0x01, 0, 0, 0, 0, 0])),
            ("special wheel-right", "Scroll Wheel Right"),
        )

    def test_g502x_consumer_media_keys(self):
        layouts = parse_report_descriptor(self.G502X_KB_DESC)
        self.assertIn(1, layouts)
        self.assertIn(3, layouts)
        self.assertNotIn(0x10, layouts)
        self.assertNotIn(0x11, layouts)
        tracker = HidReportTracker(layouts)

        # HID++ packets are ignored
        self.assertIsNone(tracker.process_report(bytes([0x11, 0xFF, 0x14, 0x00, 0x00, 0x02]) + bytes(14)))

        # Report ID 3: Play/Pause (Consumer Usage 0x00CD, little-endian)
        self.assertEqual(
            tracker.process_report(bytes([0x03, 0xCD, 0x00, 0x00, 0x00])),
            ("key KEY_PLAYPAUSE", "Key: Play/Pause"),
        )
        self.assertIsNone(tracker.process_report(bytes([0x03, 0x00, 0x00, 0x00, 0x00])))

        # Volume Up (0x00E9)
        self.assertEqual(
            tracker.process_report(bytes([0x03, 0xE9, 0x00, 0x00, 0x00])),
            ("key KEY_VOLUMEUP", "Key: Volume Up"),
        )

    def test_g502x_keyboard_keys_and_macros(self):
        layouts = parse_report_descriptor(self.G502X_KB_DESC)
        tracker = HidReportTracker(layouts)

        # Single key: HID 0x1D is always KEY_Z regardless of OS keyboard layout
        self.assertEqual(
            tracker.process_report(bytes([0x01, 0x00, 0x00, 0x1D, 0, 0, 0, 0, 0]), now=1.0),
            ("key KEY_Z", "Key: Z"),
        )
        self.assertIsNone(tracker.process_report(bytes([0x01, 0, 0, 0, 0, 0, 0, 0, 0]), now=1.05))

        # Macro: Left Ctrl down, then C down -> Copy (Ctrl+C)
        self.assertIsNone(tracker.process_report(bytes([0x01, 0x01, 0, 0, 0, 0, 0, 0, 0]), now=2.0))
        self.assertTrue(tracker.has_pending_modifier)
        self.assertEqual(
            tracker.process_report(bytes([0x01, 0x01, 0, 0x06, 0, 0, 0, 0, 0]), now=2.01),
            ("macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL", "Copy (Ctrl+C)"),
        )
        self.assertFalse(tracker.has_pending_modifier)
        self.assertIsNone(tracker.process_report(bytes([0x01, 0, 0, 0, 0, 0, 0, 0, 0]), now=2.02))

        # Standalone modifier tap (Left Shift down then up)
        self.assertIsNone(tracker.process_report(bytes([0x01, 0x02, 0, 0, 0, 0, 0, 0, 0]), now=3.0))
        self.assertEqual(
            tracker.process_report(bytes([0x01, 0x00, 0, 0, 0, 0, 0, 0, 0]), now=3.05),
            ("key KEY_LEFTSHIFT", "Key: Left Shift"),
        )

        # Standalone modifier hold timeout (Left Meta held >= 0.35s)
        self.assertIsNone(tracker.process_report(bytes([0x01, 0x08, 0, 0, 0, 0, 0, 0, 0]), now=4.0))
        self.assertIsNone(tracker.poll_pending(now=4.2))
        self.assertEqual(
            tracker.poll_pending(now=4.4),
            ("key KEY_LEFTMETA", "Key: Super / Win"),
        )


if __name__ == "__main__":
    unittest.main()
