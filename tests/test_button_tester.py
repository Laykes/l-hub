import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, Qt, QPoint, QPointF
from PySide6.QtGui import QMouseEvent, QKeyEvent, QWheelEvent, QGuiApplication
from lhub.manager import DeviceManager
from lhub.backends.base import Device, DeviceType, Capability, ButtonMapping


# Ensure a QGuiApplication exists for event handling
_app = QGuiApplication.instance() or QGuiApplication(sys.argv)


class TestButtonTester(unittest.TestCase):
    def setUp(self):
        self.manager = DeviceManager()
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
        self.manager.startButtonTest("test-mouse")
        # Horizontal wheel event with negative x delta (tilt left)
        ev = QWheelEvent(
            QPointF(0, 0),
            QPointF(0, 0),
            QPoint(0, 0),
            QPoint(-120, 0),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        handled = self.manager.eventFilter(None, ev)
        self.assertTrue(handled)

        res = self.manager.testedButtonResult
        self.assertEqual(res["action"], "special wheel-left")
        self.assertEqual(res["matchingIndices"], [10])
        self.assertEqual(res["matchingNames"], ["Button 11"])

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


if __name__ == "__main__":
    unittest.main()
