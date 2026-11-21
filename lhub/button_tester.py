"""Button-tester controller combining raw hidraw input and Qt fallback events."""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal

from .backends import Device, hid_input
from .backends.ratbag import actions_match, format_key_combo
from .keymap import (
    _QT_MODIFIER_KEYS,
    _qt_modifiers_to_linux,
    map_key_event,
    map_mouse_button,
)

logger = logging.getLogger(__name__)


class ButtonTesterController(QObject):
    """Coordinates live mouse-button identification via hidraw and Qt window events."""

    testStateChanged = Signal()
    testResultChanged = Signal()
    _hidInputEvent = Signal(str, str)

    def __init__(
        self,
        device_lookup: Callable[[str], Optional[Device]],
        parent: Optional[QObject] = None,
        timeout_ms: int = 15000,
    ):
        super().__init__(parent)
        self._device_lookup = device_lookup
        self._timeout_ms = timeout_ms

        self._is_testing_button = False
        self._testing_device_id = ""
        self._tested_button_result: Dict[str, Any] = {}
        self._hid_input_monitor: Optional[hid_input.HidInputMonitor] = None
        self._pending_qt_mods: List[str] = []
        self._pending_mod_timer = QTimer(self)
        self._pending_mod_timer.setSingleShot(True)
        self._pending_mod_timer.setInterval(int(hid_input.MODIFIER_HOLD_TIMEOUT * 1000))
        self._pending_mod_timer.timeout.connect(self._on_pending_mod_timeout)
        self._suppress_qt_until: float = 0.0
        self._suppress_qt_action: str = ""
        self._test_timer = QTimer(self)
        self._test_timer.setSingleShot(True)
        self._test_timer.setInterval(self._timeout_ms)
        self._test_timer.timeout.connect(self._on_test_timeout)

        self._hidInputEvent.connect(self.handle_hid_input)

    @property
    def is_testing(self) -> bool:
        return self._is_testing_button

    @property
    def testing_device_id(self) -> str:
        return self._testing_device_id

    @property
    def tested_button_result(self) -> Dict[str, Any]:
        return self._tested_button_result

    def _stop_hid_input_monitor(self) -> None:
        mon = self._hid_input_monitor
        self._hid_input_monitor = None
        if mon is not None:
            mon.stop()

    def _clear_pending_qt_mods(self) -> None:
        self._pending_qt_mods.clear()
        self._pending_mod_timer.stop()

    def start(self, device_id: str) -> None:
        """Start listening for a physical button press on the given device."""
        self._stop_hid_input_monitor()
        self._clear_pending_qt_mods()
        self._suppress_qt_until = 0.0
        self._suppress_qt_action = ""
        self._is_testing_button = True
        self._testing_device_id = device_id
        self._tested_button_result = {}
        self._test_timer.start(self._timeout_ms)

        dev = self._device_lookup(device_id)
        if dev and dev.usb_vid and dev.usb_pid:
            mon = hid_input.HidInputMonitor(
                dev.usb_vid,
                dev.usb_pid,
                on_input=lambda act, name: self._hidInputEvent.emit(act, name),
            )
            if mon.start():
                self._hid_input_monitor = mon
            else:
                logger.debug("Raw hidraw monitor unavailable for %s; using Qt events", device_id)

        self.testResultChanged.emit()
        self.testStateChanged.emit()

    def stop(self) -> None:
        """Cancel an active button-identification session."""
        self._stop_hid_input_monitor()
        self._clear_pending_qt_mods()
        if self._is_testing_button:
            self._is_testing_button = False
            self._test_timer.stop()
            self.testStateChanged.emit()

    def clear_result(self) -> None:
        """Clear the last button-identification result."""
        self._tested_button_result = {}
        self.testResultChanged.emit()

    def cleanup(self) -> None:
        """Stop background monitors and timers during application shutdown."""
        self._stop_hid_input_monitor()
        self._clear_pending_qt_mods()
        self._test_timer.stop()

    def _on_test_timeout(self) -> None:
        self._stop_hid_input_monitor()
        self._clear_pending_qt_mods()
        if self._is_testing_button:
            self._is_testing_button = False
            self._tested_button_result = {
                "deviceId": self._testing_device_id,
                "detectedName": "",
                "statusNote": "No button press detected within 15 seconds.",
                "matchingIndices": [],
                "matchingNames": [],
            }
            self.testStateChanged.emit()
            self.testResultChanged.emit()

    def _on_pending_mod_timeout(self) -> None:
        if not self._is_testing_button or not self._pending_qt_mods:
            return
        mods = list(self._pending_qt_mods)
        self._clear_pending_qt_mods()
        action, detected_name = format_key_combo(mods, None)
        if action and detected_name:
            self._handle_detected_button(action, detected_name, relaxed_modifiers=True)

    def handle_hid_input(self, action: str, detected_name: str) -> None:
        """Process an input action captured from the raw hidraw monitor."""
        if not self._is_testing_button:
            return
        self._suppress_qt_until = time.monotonic() + 0.15
        self._suppress_qt_action = action
        self._handle_detected_button(action, detected_name, relaxed_modifiers=False)

    def _should_suppress_trailing_qt_event(self, ev_type: QEvent.Type) -> bool:
        if not self._suppress_qt_action or time.monotonic() >= self._suppress_qt_until:
            return False
        if ev_type == QEvent.Type.MouseButtonPress and self._suppress_qt_action.startswith("button "):
            self._suppress_qt_until = 0.0
            self._suppress_qt_action = ""
            return True
        if ev_type == QEvent.Type.Wheel and self._suppress_qt_action in (
            "special wheel-left",
            "special wheel-right",
        ):
            self._suppress_qt_until = 0.0
            self._suppress_qt_action = ""
            return True
        if ev_type == QEvent.Type.KeyPress and (
            self._suppress_qt_action.startswith("key ") or self._suppress_qt_action.startswith("macro ")
        ):
            return True
        return False

    def eventFilter(self, watched, event) -> bool:
        """Intercept Qt input events during testing and suppress hidraw duplicates."""
        ev_type = event.type()

        if not self._is_testing_button:
            if self._should_suppress_trailing_qt_event(ev_type):
                return True
            return super().eventFilter(watched, event)

        action: Optional[str] = None
        detected_name: Optional[str] = None
        relaxed_modifiers = False

        if ev_type == QEvent.Type.MouseButtonPress:
            action, detected_name = map_mouse_button(event.button())
        elif ev_type == QEvent.Type.Wheel:
            dx = event.angleDelta().x()
            if event.inverted():
                dx = -dx
            if dx > 0:
                action, detected_name = "special wheel-left", "Scroll Wheel Left"
            elif dx < 0:
                action, detected_name = "special wheel-right", "Scroll Wheel Right"
            else:
                return super().eventFilter(watched, event)
        elif ev_type == QEvent.Type.KeyPress:
            if event.isAutoRepeat():
                return True
            key = event.key()
            mods = _qt_modifiers_to_linux(event.modifiers())
            if key == Qt.Key.Key_Escape and not mods and not self._pending_qt_mods:
                self.stop()
                return True
            if key in _QT_MODIFIER_KEYS:
                mod_name = _QT_MODIFIER_KEYS[key]
                if mod_name not in self._pending_qt_mods:
                    self._pending_qt_mods.append(mod_name)
                self._pending_mod_timer.start()
                return True
            merged_mods = list(dict.fromkeys(self._pending_qt_mods + mods))
            self._clear_pending_qt_mods()
            action, detected_name = map_key_event(event, extra_modifiers=merged_mods)
            relaxed_modifiers = True
        elif ev_type == QEvent.Type.KeyRelease:
            if event.isAutoRepeat():
                return True
            if self._pending_qt_mods and event.key() in _QT_MODIFIER_KEYS:
                released_mod = _QT_MODIFIER_KEYS[event.key()]
                remaining = [m for m in _qt_modifiers_to_linux(event.modifiers()) if m != released_mod]
                if not remaining:
                    mods = list(self._pending_qt_mods)
                    self._clear_pending_qt_mods()
                    action, detected_name = format_key_combo(mods, None)
                    relaxed_modifiers = True

        if action and detected_name:
            self._handle_detected_button(action, detected_name, relaxed_modifiers=relaxed_modifiers)
            return True

        return super().eventFilter(watched, event)

    def _handle_detected_button(
        self,
        action: str,
        detected_name: str,
        relaxed_modifiers: bool = False,
    ) -> None:
        self._stop_hid_input_monitor()
        self._clear_pending_qt_mods()
        dev = self._device_lookup(self._testing_device_id)
        matching_indices = []
        matching_names = []

        if dev and dev.buttons:
            exact_matches = [
                btn for btn in dev.buttons
                if actions_match(btn.action_value, action, relaxed_modifiers=False)
            ]
            matches = exact_matches
            if not matches and relaxed_modifiers:
                matches = [
                    btn for btn in dev.buttons
                    if actions_match(btn.action_value, action, relaxed_modifiers=True)
                ]
            matching_indices = [btn.index for btn in matches]
            matching_names = [btn.name for btn in matches]

        self._tested_button_result = {
            "deviceId": self._testing_device_id,
            "detectedName": detected_name,
            "action": action,
            "matchingIndices": matching_indices,
            "matchingNames": matching_names,
            "timestamp": time.time(),
        }
        self._is_testing_button = False
        self._test_timer.stop()
        self.testStateChanged.emit()
        self.testResultChanged.emit()
