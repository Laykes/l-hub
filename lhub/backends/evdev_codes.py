"""Linux evdev KEY_* event code lookup table for ratbagd D-Bus button mappings.

Values follow Linux UAPI ``<linux/input-event-codes.h>`` so button key and
macro mappings can be encoded/decoded cleanly without external dependencies,
with an optional fallback to ``evdev.ecodes`` when installed.
"""

from typing import Dict

try:
    from evdev import ecodes as _evdev_ecodes
except ImportError:  # pragma: no cover - optional runtime fallback
    _evdev_ecodes = None


KEY_NAME_TO_CODE: Dict[str, int] = {
    "KEY_ESC": 1,
    "KEY_1": 2,
    "KEY_2": 3,
    "KEY_3": 4,
    "KEY_4": 5,
    "KEY_5": 6,
    "KEY_6": 7,
    "KEY_7": 8,
    "KEY_8": 9,
    "KEY_9": 10,
    "KEY_0": 11,
    "KEY_MINUS": 12,
    "KEY_EQUAL": 13,
    "KEY_BACKSPACE": 14,
    "KEY_TAB": 15,
    "KEY_Q": 16,
    "KEY_W": 17,
    "KEY_E": 18,
    "KEY_R": 19,
    "KEY_T": 20,
    "KEY_Y": 21,
    "KEY_U": 22,
    "KEY_I": 23,
    "KEY_O": 24,
    "KEY_P": 25,
    "KEY_LEFTBRACE": 26,
    "KEY_RIGHTBRACE": 27,
    "KEY_ENTER": 28,
    "KEY_LEFTCTRL": 29,
    "KEY_A": 30,
    "KEY_S": 31,
    "KEY_D": 32,
    "KEY_F": 33,
    "KEY_G": 34,
    "KEY_H": 35,
    "KEY_J": 36,
    "KEY_K": 37,
    "KEY_L": 38,
    "KEY_SEMICOLON": 39,
    "KEY_APOSTROPHE": 40,
    "KEY_GRAVE": 41,
    "KEY_LEFTSHIFT": 42,
    "KEY_BACKSLASH": 43,
    "KEY_Z": 44,
    "KEY_X": 45,
    "KEY_C": 46,
    "KEY_V": 47,
    "KEY_B": 48,
    "KEY_N": 49,
    "KEY_M": 50,
    "KEY_COMMA": 51,
    "KEY_DOT": 52,
    "KEY_SLASH": 53,
    "KEY_RIGHTSHIFT": 54,
    "KEY_KPASTERISK": 55,
    "KEY_LEFTALT": 56,
    "KEY_SPACE": 57,
    "KEY_CAPSLOCK": 58,
    "KEY_F1": 59,
    "KEY_F2": 60,
    "KEY_F3": 61,
    "KEY_F4": 62,
    "KEY_F5": 63,
    "KEY_F6": 64,
    "KEY_F7": 65,
    "KEY_F8": 66,
    "KEY_F9": 67,
    "KEY_F10": 68,
    "KEY_NUMLOCK": 69,
    "KEY_SCROLLLOCK": 70,
    "KEY_KP7": 71,
    "KEY_KP8": 72,
    "KEY_KP9": 73,
    "KEY_KPMINUS": 74,
    "KEY_KP4": 75,
    "KEY_KP5": 76,
    "KEY_KP6": 77,
    "KEY_KPPLUS": 78,
    "KEY_KP1": 79,
    "KEY_KP2": 80,
    "KEY_KP3": 81,
    "KEY_KP0": 82,
    "KEY_KPDOT": 83,
    "KEY_102ND": 86,
    "KEY_F11": 87,
    "KEY_F12": 88,
    "KEY_KPENTER": 96,
    "KEY_RIGHTCTRL": 97,
    "KEY_KPSLASH": 98,
    "KEY_SYSRQ": 99,
    "KEY_RIGHTALT": 100,
    "KEY_HOME": 102,
    "KEY_UP": 103,
    "KEY_PAGEUP": 104,
    "KEY_LEFT": 105,
    "KEY_RIGHT": 106,
    "KEY_END": 107,
    "KEY_DOWN": 108,
    "KEY_PAGEDOWN": 109,
    "KEY_INSERT": 110,
    "KEY_DELETE": 111,
    "KEY_MUTE": 113,
    "KEY_VOLUMEDOWN": 114,
    "KEY_VOLUMEUP": 115,
    "KEY_POWER": 116,
    "KEY_KPEQUAL": 117,
    "KEY_PAUSE": 119,
    "KEY_KPCOMMA": 121,
    "KEY_LEFTMETA": 125,
    "KEY_RIGHTMETA": 126,
    "KEY_COMPOSE": 127,
    "KEY_STOP": 128,
    "KEY_CALC": 140,
    "KEY_FILE": 144,
    "KEY_MAIL": 155,
    "KEY_BACK": 158,
    "KEY_FORWARD": 159,
    "KEY_NEXTSONG": 163,
    "KEY_PLAYPAUSE": 164,
    "KEY_PREVIOUSSONG": 165,
    "KEY_STOPCD": 166,
    "KEY_CONFIG": 171,
    "KEY_HOMEPAGE": 172,
    "KEY_REFRESH": 173,
    "KEY_F13": 183,
    "KEY_F14": 184,
    "KEY_F15": 185,
    "KEY_F16": 186,
    "KEY_F17": 187,
    "KEY_F18": 188,
    "KEY_F19": 189,
    "KEY_F20": 190,
    "KEY_F21": 191,
    "KEY_F22": 192,
    "KEY_F23": 193,
    "KEY_F24": 194,
    "KEY_PRINT": 210,
    "KEY_SEARCH": 217,
    "KEY_MICMUTE": 248,
}

KEY_CODE_TO_NAME: Dict[int, str] = {}
for _key_name, _key_code in KEY_NAME_TO_CODE.items():
    KEY_CODE_TO_NAME.setdefault(_key_code, _key_name)


def key_name_to_evcode(name: str) -> int:
    """Resolve a Linux ``KEY_*`` name to its integer evdev event code."""
    clean = str(name or "").strip().strip("'\"").upper()
    if not clean:
        raise ValueError("Empty key name")
    if clean in KEY_NAME_TO_CODE:
        return KEY_NAME_TO_CODE[clean]
    if _evdev_ecodes is not None:
        code = _evdev_ecodes.ecodes.get(clean)
        if isinstance(code, int):
            return code
    raise ValueError(f"Unknown Linux key name: {name!r}")


def evcode_to_key_name(code: int) -> str:
    """Resolve an integer Linux evdev key code to its canonical ``KEY_*`` name."""
    int_code = int(code)
    if int_code in KEY_CODE_TO_NAME:
        return KEY_CODE_TO_NAME[int_code]
    if _evdev_ecodes is not None:
        val = _evdev_ecodes.keys.get(int_code)
        if isinstance(val, list) and val:
            return str(val[0])
        if isinstance(val, str):
            return val
    return f"KEY_{int_code}"
