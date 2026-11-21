"""Qt-to-Linux key, modifier, and mouse button mapping helpers."""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QKeySequence

from .backends.ratbag import format_key_combo

logger = logging.getLogger(__name__)

_QT_MODIFIER_KEYS: Dict[int, str] = {
    Qt.Key.Key_Shift: "KEY_LEFTSHIFT",
    Qt.Key.Key_Control: "KEY_LEFTCTRL",
    Qt.Key.Key_Meta: "KEY_LEFTMETA",
    Qt.Key.Key_Alt: "KEY_LEFTALT",
    Qt.Key.Key_AltGr: "KEY_RIGHTALT",
}

_QT_TO_LINUX_KEY: Dict[int, str] = {
    Qt.Key.Key_Escape: "KEY_ESC",
    Qt.Key.Key_Tab: "KEY_TAB",
    Qt.Key.Key_Backtab: "KEY_TAB",
    Qt.Key.Key_Backspace: "KEY_BACKSPACE",
    Qt.Key.Key_Return: "KEY_ENTER",
    Qt.Key.Key_Enter: "KEY_ENTER",
    Qt.Key.Key_Insert: "KEY_INSERT",
    Qt.Key.Key_Delete: "KEY_DELETE",
    Qt.Key.Key_Pause: "KEY_PAUSE",
    Qt.Key.Key_Print: "KEY_PRINT",
    Qt.Key.Key_Home: "KEY_HOME",
    Qt.Key.Key_End: "KEY_END",
    Qt.Key.Key_Left: "KEY_LEFT",
    Qt.Key.Key_Up: "KEY_UP",
    Qt.Key.Key_Right: "KEY_RIGHT",
    Qt.Key.Key_Down: "KEY_DOWN",
    Qt.Key.Key_PageUp: "KEY_PAGEUP",
    Qt.Key.Key_PageDown: "KEY_PAGEDOWN",
    Qt.Key.Key_CapsLock: "KEY_CAPSLOCK",
    Qt.Key.Key_NumLock: "KEY_NUMLOCK",
    Qt.Key.Key_ScrollLock: "KEY_SCROLLLOCK",
    Qt.Key.Key_Space: "KEY_SPACE",
    Qt.Key.Key_Minus: "KEY_MINUS",
    Qt.Key.Key_Equal: "KEY_EQUAL",
    Qt.Key.Key_BracketLeft: "KEY_LEFTBRACE",
    Qt.Key.Key_BracketRight: "KEY_RIGHTBRACE",
    Qt.Key.Key_Semicolon: "KEY_SEMICOLON",
    Qt.Key.Key_Apostrophe: "KEY_APOSTROPHE",
    Qt.Key.Key_QuoteLeft: "KEY_GRAVE",
    Qt.Key.Key_Backslash: "KEY_BACKSLASH",
    Qt.Key.Key_Comma: "KEY_COMMA",
    Qt.Key.Key_Period: "KEY_DOT",
    Qt.Key.Key_Slash: "KEY_SLASH",
    Qt.Key.Key_VolumeUp: "KEY_VOLUMEUP",
    Qt.Key.Key_VolumeDown: "KEY_VOLUMEDOWN",
    Qt.Key.Key_VolumeMute: "KEY_MUTE",
    Qt.Key.Key_MediaPlay: "KEY_PLAYPAUSE",
    Qt.Key.Key_MediaPause: "KEY_PLAYPAUSE",
    Qt.Key.Key_MediaTogglePlayPause: "KEY_PLAYPAUSE",
    Qt.Key.Key_MediaNext: "KEY_NEXTSONG",
    Qt.Key.Key_MediaPrevious: "KEY_PREVIOUSSONG",
    Qt.Key.Key_MediaStop: "KEY_STOPCD",
    **_QT_MODIFIER_KEYS,
}
for _i in range(1, 25):
    _QT_TO_LINUX_KEY[getattr(Qt.Key, f"Key_F{_i}")] = f"KEY_F{_i}"

QT_MODIFIER_KEYS = _QT_MODIFIER_KEYS
QT_TO_LINUX_KEY = _QT_TO_LINUX_KEY

_MOUSE_BUTTON_ACTIONS: Dict[Qt.MouseButton, Tuple[str, str]] = {
    Qt.MouseButton.LeftButton: ("button 1", "Left Click (Button 1)"),
    Qt.MouseButton.RightButton: ("button 2", "Right Click (Button 2)"),
    Qt.MouseButton.MiddleButton: ("button 3", "Middle Click (Button 3)"),
    Qt.MouseButton.BackButton: ("button 4", "Back (Button 4)"),
    Qt.MouseButton.ForwardButton: ("button 5", "Forward (Button 5)"),
    Qt.MouseButton.TaskButton: ("button 6", "Button 6"),
    Qt.MouseButton.ExtraButton4: ("button 7", "Button 7"),
    Qt.MouseButton.ExtraButton5: ("button 8", "Button 8"),
    Qt.MouseButton.ExtraButton6: ("button 9", "Button 9"),
    Qt.MouseButton.ExtraButton7: ("button 10", "Button 10"),
    Qt.MouseButton.ExtraButton8: ("button 11", "Button 11"),
    Qt.MouseButton.ExtraButton9: ("button 12", "Button 12"),
}


def _qt_key_to_linux(key: int) -> Optional[str]:
    """Translate a Qt key code to its Linux evdev KEY_* name, if supported."""
    if key in _QT_TO_LINUX_KEY:
        return _QT_TO_LINUX_KEY[key]
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return f"KEY_{chr(key)}"
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return f"KEY_{chr(key)}"
    return None


def _qt_modifiers_to_linux(modifiers) -> List[str]:
    """Translate Qt keyboard modifier flags to an ordered list of Linux modifier keys."""
    mod_val = int(modifiers.value) if hasattr(modifiers, "value") else int(modifiers)
    mods: List[str] = []
    if mod_val & int(Qt.KeyboardModifier.ControlModifier.value):
        mods.append("KEY_LEFTCTRL")
    if mod_val & int(Qt.KeyboardModifier.AltModifier.value):
        mods.append("KEY_LEFTALT")
    if mod_val & int(Qt.KeyboardModifier.ShiftModifier.value):
        mods.append("KEY_LEFTSHIFT")
    if mod_val & int(Qt.KeyboardModifier.MetaModifier.value):
        mods.append("KEY_LEFTMETA")
    return mods


qt_key_to_linux = _qt_key_to_linux
qt_modifiers_to_linux = _qt_modifiers_to_linux


def resolve_key_action(key: int, modifiers: int) -> Dict[str, Any]:
    """Resolve a Qt key + modifiers pair into a ratbag action and display label."""
    linux_key = _qt_key_to_linux(key)
    if not linux_key:
        return {}

    if key in _QT_MODIFIER_KEYS:
        act, disp = format_key_combo([linux_key], None)
    else:
        mods = _qt_modifiers_to_linux(modifiers)
        act, disp = format_key_combo(mods, linux_key)
    return {"action": act, "display": disp} if act else {}


def map_mouse_button(btn: Qt.MouseButton) -> Tuple[str, str]:
    """Map a Qt.MouseButton enum value to a (ratbag action, display name) tuple."""
    if btn in _MOUSE_BUTTON_ACTIONS:
        return _MOUSE_BUTTON_ACTIONS[btn]

    try:
        val = int(btn.value) if hasattr(btn, "value") else int(btn)
        if val > 0:
            btn_num = int(math.log2(val)) + 1
            return f"button {btn_num}", f"Button {btn_num}"
    except Exception as exc:
        logger.debug("Could not map Qt mouse button %r: %s", btn, exc)
    return "unknown", "Unknown Mouse Button"


def map_key_event(
    event: QKeyEvent,
    extra_modifiers: Optional[List[str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Map a Qt key event (with optional buffered modifiers) to (action, display)."""
    key = event.key()
    mods = list(dict.fromkeys((extra_modifiers or []) + _qt_modifiers_to_linux(event.modifiers())))
    linux_key = _qt_key_to_linux(key)
    if linux_key:
        if key in _QT_MODIFIER_KEYS:
            act, disp = format_key_combo([linux_key], None)
        else:
            act, disp = format_key_combo(mods, linux_key)
        return (act, disp) if act else (None, None)

    seq = QKeySequence(key).toString()
    if seq:
        clean_k = seq.upper().replace(" ", "_")
        fallback_key = f"KEY_{clean_k}"
        if mods:
            act, disp = format_key_combo(mods, fallback_key)
            return (act, disp) if act else (None, None)
        return f"key {fallback_key}", f"Key: {seq}"
    return None, None
