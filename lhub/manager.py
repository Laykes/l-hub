import math
import time
import threading
from typing import List, Dict, Any, Optional, Set, Tuple
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, QCoreApplication, QEvent, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence

from .backends import (
    Device,
    DeviceType,
    Capability,
    BaseBackend,
    RatbagBackend,
    HeadsetBackend,
    UPowerBackend,
)
from .backends.ratbag import parse_button_action, KEY_DISPLAY_NAMES
from .profiles import ProfileManager




class DeviceManager(QObject):
    devicesChanged = Signal()
    statusChanged = Signal()
    batteryWarning = Signal(str, int)  # device_name, percentage
    testStateChanged = Signal()
    testResultChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile_mgr = ProfileManager()
        self.backends: List[BaseBackend] = [
            HeadsetBackend(),
            RatbagBackend(),
            UPowerBackend(),
        ]
        self._devices: List[Device] = []
        self._cached_dict_devices: List[Dict[str, Any]] = []
        self._is_scanning = False
        self._warned_devices: Set[str] = set()

        # Button tester state
        self._is_testing_button = False
        self._testing_device_id = ""
        self._tested_button_result: Dict[str, Any] = {}
        self._test_timer = QTimer(self)
        self._test_timer.setSingleShot(True)
        self._test_timer.setInterval(15000)
        self._test_timer.timeout.connect(self._on_test_timeout)

        # Background refresh timer every 30 seconds
        self._timer = QTimer(self)
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self.refresh_devices)
        self._timer.start()

        # Initial scan
        self.refresh_devices()

    @Slot()
    def refresh_devices(self):
        if self._is_scanning:
            return
        self._is_scanning = True

        # Run scan in background thread to avoid freezing GUI
        thread = threading.Thread(target=self._scan_worker, daemon=True)
        thread.start()

    def _scan_worker(self):
        try:
            detected: List[Device] = []
            for b in self.backends:
                if b.is_available():
                    try:
                        devs = b.scan_devices()
                        detected.extend(devs)
                    except Exception:
                        pass

            merged = self._merge_devices(detected)

            # Ensure default profile for devices with configurable buttons
            for d in merged:
                if d.buttons:
                    dev_key = self._get_device_key(d)
                    b_map = {b.index: b.action_value for b in d.buttons}
                    dpi_val = d.dpi.current if (d.dpi and not d.dpi.is_disabled) else None
                    self.profile_mgr.ensure_default_profile(dev_key, b_map, dpi_val)


            # Check low battery warnings
            for d in merged:
                if d.battery and d.battery.percentage >= 0 and not d.battery.is_charging:
                    if d.battery.percentage <= 20 and d.id not in self._warned_devices:
                        self._warned_devices.add(d.id)
                        self.batteryWarning.emit(d.name, d.battery.percentage)
                    elif d.battery.percentage > 25 and d.id in self._warned_devices:
                        self._warned_devices.remove(d.id)

            dict_devs = [self._device_to_dict(d) for d in merged]

            # Update cache and notify in main thread safe manner
            self._devices = merged
            self._cached_dict_devices = dict_devs
            self.devicesChanged.emit()
            self.statusChanged.emit()
        finally:
            self._is_scanning = False

    def _merge_devices(self, raw_list: List[Device]) -> List[Device]:
        merged: List[Device] = []
        seen_keys = {}

        for dev in raw_list:
            # Build unique key: VID:PID or cleaned name
            key = ""
            if dev.usb_vid and dev.usb_pid:
                key = f"{dev.usb_vid}:{dev.usb_pid}"
            else:
                key = dev.name.lower().replace("-", " ").strip()

            if key not in seen_keys:
                seen_keys[key] = dev
                merged.append(dev)
            else:
                # Merge capabilities if existing backend has less info
                existing = seen_keys[key]
                if not existing.battery and dev.battery:
                    existing.battery = dev.battery
                elif existing.backend_name != "headsetcontrol" and dev.battery and dev.battery.percentage >= 0:
                    existing.battery = dev.battery

        return merged

    def _device_to_dict(self, dev: Device) -> Dict[str, Any]:
        time_str = ""
        if dev.battery:
            if dev.battery.is_charging:
                if dev.battery.time_to_full_min is not None:
                    if dev.battery.time_to_full_min == 0:
                        time_str = "Fully charged"
                    else:
                        hrs = dev.battery.time_to_full_min // 60
                        mins = dev.battery.time_to_full_min % 60
                        time_str = f"Full in ~{hrs} hr {mins} min" if hrs > 0 else f"Full in ~{mins} min"
                else:
                    time_str = ""
            elif dev.battery.time_to_empty_min:
                hrs = dev.battery.time_to_empty_min // 60
                mins = dev.battery.time_to_empty_min % 60
                time_str = f"~{hrs} hr {mins} min" if hrs > 0 else f"~{mins} min"

        dev_key = self._get_device_key(dev)
        profiles = self.profile_mgr.get_profiles(dev_key)
        active_profile = self.profile_mgr.get_active_profile(dev_key)

        return {
            "id": dev.id,
            "name": dev.name,
            "vendor": dev.vendor,
            "type": dev.device_type.value,
            "deviceKey": dev_key,
            "profiles": profiles,
            "activeProfile": active_profile,
            "capabilities": [c.value for c in dev.capabilities],
            "hasBattery": Capability.BATTERY in dev.capabilities and dev.battery is not None and dev.battery.is_supported,
            "batteryPercentage": dev.battery.percentage if dev.battery else -1,
            "isCharging": dev.battery.is_charging if dev.battery else False,
            "batteryStatusText": dev.battery.status_text if dev.battery else "",
            "batteryTimeRemaining": time_str,
            "hasDpi": Capability.DPI in dev.capabilities,
            "currentDpi": dev.dpi.current if dev.dpi else 800,
            "dpiSteps": dev.dpi.steps if dev.dpi else [400, 800, 1600, 3200],
            "isDpiDisabled": dev.dpi.is_disabled if dev.dpi else False,
            "hasSidetone": Capability.SIDETONE in dev.capabilities,
            "sidetone": dev.sidetone if dev.sidetone is not None else 0,
            "hasButtons": Capability.BUTTON_REMAP in dev.capabilities,
            "buttons": [
                {
                    "index": b.index,
                    "name": b.name,
                    "label": getattr(b, "label", "") or b.name,
                    "location": getattr(b, "location", ""),
                    "group": getattr(b, "group", "main"),
                    "defaultAction": getattr(b, "default_action", ""),
                    "action": b.action_value,
                    "actionDisplay": b.action_display or b.action_value,
                    "isCustomized": bool(getattr(b, "default_action", "") and b.action_value != getattr(b, "default_action", "")),
                }
                for b in dev.buttons
            ],
            "statusNote": dev.status_note,
            "backend": dev.backend_name,
        }

    def _get_device_key(self, dev: Device) -> str:
        if dev.usb_vid and dev.usb_pid:
            return f"{dev.usb_vid}:{dev.usb_pid}"
        return dev.name.lower().replace("-", " ").strip()

    def _get_device_by_id(self, device_id: str) -> Optional[Device]:
        for d in self._devices:
            if d.id == device_id:
                return d
        return None

    @Property("QVariantList", notify=devicesChanged)
    def devices(self) -> List[Dict[str, Any]]:
        return self._cached_dict_devices

    @Property("QVariantList", notify=statusChanged)
    def missingBackends(self) -> List[str]:
        missing = []
        for b in self.backends:
            if not b.is_available():
                msg = b.get_missing_reason()
                if msg:
                    missing.append(msg)
        return missing

    @Slot(str, int, result=bool)
    def setDpi(self, device_id: str, dpi: int) -> bool:
        dev = self._get_device_by_id(device_id)
        # Update local cache immediately for responsive UI
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                d["currentDpi"] = dpi
                self.devicesChanged.emit()
                break

        def _worker():
            for b in self.backends:
                if isinstance(b, RatbagBackend):
                    if b.set_dpi(device_id, dpi):
                        if dev:
                            if dev.dpi:
                                dev.dpi.current = dpi
                            dev_key = self._get_device_key(dev)
                            self.profile_mgr.update_active_dpi(dev_key, dpi)
                        break
            self.refresh_devices()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    @Slot(str, int)
    def setSidetone(self, device_id: str, level: int):
        # Update local cache immediately
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                d["sidetone"] = level
                self.devicesChanged.emit()
                break

        def _worker():
            for b in self.backends:
                if isinstance(b, HeadsetBackend):
                    b.set_sidetone(device_id, level)

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(str, int, str, result=bool)
    def remapButton(self, device_id: str, button_idx: int, action: str) -> bool:
        # Update local cache immediately for responsive UI
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                for btn in d.get("buttons", []):
                    if btn["index"] == button_idx:
                        btn["action"] = action
                        btn["actionDisplay"] = parse_button_action(action)[1]
                        break
                self.devicesChanged.emit()
                break

        dev = self._get_device_by_id(device_id)

        def _worker():
            for b in self.backends:
                if isinstance(b, RatbagBackend):
                    if b.remap_button(device_id, button_idx, action):
                        if dev:
                            dev_key = self._get_device_key(dev)
                            self.profile_mgr.update_active_button(dev_key, button_idx, action)
                        break
            self.refresh_devices()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    @Slot(str, int, result=bool)
    def resetButtonToDefault(self, device_id: str, button_idx: int) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or not dev.buttons:
            return False
        default_act = None
        for b in dev.buttons:
            if b.index == button_idx:
                default_act = getattr(b, "default_action", "")
                break
        if not default_act:
            return False
        return self.remapButton(device_id, button_idx, default_act)

    @Slot(int, int, result="QVariantMap")
    def resolveKeyAction(self, key: int, modifiers: int) -> Dict[str, Any]:
        mod_val = int(modifiers.value) if hasattr(modifiers, "value") else int(modifiers)
        has_ctrl = bool(mod_val & int(Qt.KeyboardModifier.ControlModifier.value))
        has_shift = bool(mod_val & int(Qt.KeyboardModifier.ShiftModifier.value))
        has_alt = bool(mod_val & int(Qt.KeyboardModifier.AltModifier.value))
        has_meta = bool(mod_val & int(Qt.KeyboardModifier.MetaModifier.value))

        qt_to_linux = {
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
            Qt.Key.Key_Shift: "KEY_LEFTSHIFT",
            Qt.Key.Key_Control: "KEY_LEFTCTRL",
            Qt.Key.Key_Meta: "KEY_LEFTMETA",
            Qt.Key.Key_Alt: "KEY_LEFTALT",
            Qt.Key.Key_CapsLock: "KEY_CAPSLOCK",
            Qt.Key.Key_NumLock: "KEY_NUMLOCK",
            Qt.Key.Key_ScrollLock: "KEY_SCROLLLOCK",
            Qt.Key.Key_Space: "KEY_SPACE",
            Qt.Key.Key_VolumeUp: "KEY_VOLUMEUP",
            Qt.Key.Key_VolumeDown: "KEY_VOLUMEDOWN",
            Qt.Key.Key_VolumeMute: "KEY_MUTE",
            Qt.Key.Key_MediaPlay: "KEY_PLAYPAUSE",
            Qt.Key.Key_MediaPause: "KEY_PLAYPAUSE",
            Qt.Key.Key_MediaNext: "KEY_NEXTSONG",
            Qt.Key.Key_MediaPrevious: "KEY_PREVIOUSSONG",
        }
        for i in range(1, 25):
            qt_to_linux[getattr(Qt.Key, f"Key_F{i}")] = f"KEY_F{i}"

        linux_key = None
        if key in qt_to_linux:
            linux_key = qt_to_linux[key]
        elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            linux_key = f"KEY_{chr(key)}"
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            linux_key = f"KEY_{chr(key)}"

        if not linux_key:
            return {}

        is_mod_key = key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta)

        if not is_mod_key and (has_ctrl or has_alt or has_meta or has_shift):
            if has_ctrl and not has_alt and not has_meta and not has_shift:
                if linux_key == "KEY_C":
                    return {"action": "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL", "display": "Copy (Ctrl+C)"}
                if linux_key == "KEY_V":
                    return {"action": "macro +KEY_LEFTCTRL KEY_V -KEY_LEFTCTRL", "display": "Paste (Ctrl+V)"}
                if linux_key == "KEY_X":
                    return {"action": "macro +KEY_LEFTCTRL KEY_X -KEY_LEFTCTRL", "display": "Cut (Ctrl+X)"}
                if linux_key == "KEY_Z":
                    return {"action": "macro +KEY_LEFTCTRL KEY_Z -KEY_LEFTCTRL", "display": "Undo (Ctrl+Z)"}
                if linux_key == "KEY_Y":
                    return {"action": "macro +KEY_LEFTCTRL KEY_Y -KEY_LEFTCTRL", "display": "Redo (Ctrl+Y)"}
                if linux_key == "KEY_A":
                    return {"action": "macro +KEY_LEFTCTRL KEY_A -KEY_LEFTCTRL", "display": "Select All (Ctrl+A)"}
                if linux_key == "KEY_S":
                    return {"action": "macro +KEY_LEFTCTRL KEY_S -KEY_LEFTCTRL", "display": "Save (Ctrl+S)"}
                if linux_key == "KEY_F":
                    return {"action": "macro +KEY_LEFTCTRL KEY_F -KEY_LEFTCTRL", "display": "Find (Ctrl+F)"}
                if linux_key == "KEY_T":
                    return {"action": "macro +KEY_LEFTCTRL KEY_T -KEY_LEFTCTRL", "display": "New Tab (Ctrl+T)"}
                if linux_key == "KEY_W":
                    return {"action": "macro +KEY_LEFTCTRL KEY_W -KEY_LEFTCTRL", "display": "Close Tab (Ctrl+W)"}
            if has_alt and not has_ctrl and not has_shift and not has_meta and linux_key == "KEY_TAB":
                return {"action": "macro +KEY_LEFTALT KEY_TAB -KEY_LEFTALT", "display": "Switch App (Alt+Tab)"}

            macro_parts = []
            display_parts = []
            if has_ctrl:
                macro_parts.append("+KEY_LEFTCTRL")
                display_parts.append("Ctrl")
            if has_alt:
                macro_parts.append("+KEY_LEFTALT")
                display_parts.append("Alt")
            if has_shift:
                macro_parts.append("+KEY_LEFTSHIFT")
                display_parts.append("Shift")
            if has_meta:
                macro_parts.append("+KEY_LEFTMETA")
                display_parts.append("Super")

            macro_parts.append(linux_key)
            k_disp = KEY_DISPLAY_NAMES.get(linux_key, linux_key.replace("KEY_", ""))
            display_parts.append(k_disp)

            if has_meta:
                macro_parts.append("-KEY_LEFTMETA")
            if has_shift:
                macro_parts.append("-KEY_LEFTSHIFT")
            if has_alt:
                macro_parts.append("-KEY_LEFTALT")
            if has_ctrl:
                macro_parts.append("-KEY_LEFTCTRL")

            return {
                "action": "macro " + " ".join(macro_parts),
                "display": " + ".join(display_parts),
            }

        k_disp = KEY_DISPLAY_NAMES.get(linux_key, linux_key.replace("KEY_", ""))
        return {
            "action": f"key {linux_key}",
            "display": f"Key: {k_disp}",
        }

    @Slot(str, str, result=bool)
    def applyProfile(self, device_id: str, profile_name: str) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev:
            return False
        dev_key = self._get_device_key(dev)
        prof_data = self.profile_mgr.get_profile_data(dev_key, profile_name)
        if not prof_data:
            return False

        self.profile_mgr.set_active_profile(dev_key, profile_name)

        # Update local cache immediately
        buttons_data = prof_data.get("buttons", {})
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                d["activeProfile"] = profile_name
                for btn in d.get("buttons", []):
                    idx_str = str(btn["index"])
                    if idx_str in buttons_data:
                        act = buttons_data[idx_str]
                        btn["action"] = act
                        btn["actionDisplay"] = parse_button_action(act)[1]
                if "dpi" in prof_data:
                    d["currentDpi"] = prof_data["dpi"]
                self.devicesChanged.emit()
                break

        def _worker():
            buttons = {int(k): v for k, v in prof_data.get("buttons", {}).items()}
            dpi = prof_data.get("dpi")
            for b in self.backends:
                if isinstance(b, RatbagBackend):
                    if buttons:
                        b.batch_remap_buttons(device_id, buttons)
                    if dpi and dev.dpi and not dev.dpi.is_disabled:
                        b.set_dpi(device_id, int(dpi))
            self.refresh_devices()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    @Slot(str, str, result=bool)
    def saveProfile(self, device_id: str, profile_name: str) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or not profile_name.strip():
            return False
        dev_key = self._get_device_key(dev)
        buttons = {b.index: b.action_value for b in dev.buttons}
        dpi = dev.dpi.current if (dev.dpi and not dev.dpi.is_disabled) else None
        self.profile_mgr.save_profile(dev_key, profile_name.strip(), buttons, dpi)

        # Update local cache immediately
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                if profile_name.strip() not in d.get("profiles", []):
                    d["profiles"].append(profile_name.strip())
                d["activeProfile"] = profile_name.strip()
                self.devicesChanged.emit()
                break

        self.refresh_devices()
        return True

    @Slot(str, str, result=bool)
    def deleteProfile(self, device_id: str, profile_name: str) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev or not profile_name:
            return False
        dev_key = self._get_device_key(dev)
        if self.profile_mgr.delete_profile(dev_key, profile_name):
            active = self.profile_mgr.get_active_profile(dev_key)

            # Update local cache immediately
            for d in self._cached_dict_devices:
                if d["id"] == device_id:
                    if profile_name in d.get("profiles", []):
                        d["profiles"].remove(profile_name)
                    self.devicesChanged.emit()
                    break

            self.applyProfile(device_id, active)
            return True
        return False

    @Slot(str, result=bool)
    def resetDeviceToDefault(self, device_id: str) -> bool:
        dev = self._get_device_by_id(device_id)
        if not dev:
            return False
        dev_key = self._get_device_key(dev)

        defaults_map = {
            0: ("button 1", "Left Click"),
            1: ("button 2", "Right Click"),
            2: ("button 3", "Middle Click"),
            3: ("button 4", "Back (Button 4)"),
            4: ("special resolution-alternate", "DPI Shift (Sniper)"),
            5: ("button 5", "Forward (Button 5)"),
            6: ("special wheel-left", "Scroll Wheel Left"),
            7: ("special wheel-right", "Scroll Wheel Right"),
            8: ("special profile-cycle-up", "Cycle Profile"),
            9: ("special resolution-up", "DPI +"),
            10: ("special resolution-down", "DPI -"),
        }

        # Update local cache immediately
        for d in self._cached_dict_devices:
            if d["id"] == device_id:
                d["activeProfile"] = "Default"
                for btn in d.get("buttons", []):
                    if btn["index"] in defaults_map:
                        btn["action"] = defaults_map[btn["index"]][0]
                        btn["actionDisplay"] = defaults_map[btn["index"]][1]
                self.devicesChanged.emit()
                break

        def _worker():
            for b in self.backends:
                if isinstance(b, RatbagBackend):
                    b.reset_defaults(device_id)
                    updated = b.scan_devices()
                    for ud in updated:
                        if ud.id == device_id or self._get_device_key(ud) == dev_key:
                            b_map = {btn.index: btn.action_value for btn in ud.buttons}
                            dpi_val = ud.dpi.current if (ud.dpi and not ud.dpi.is_disabled) else 800
                            self.profile_mgr.reset_to_default(dev_key, b_map, dpi_val)
                            break
            self.refresh_devices()

        threading.Thread(target=_worker, daemon=True).start()
        return True

    @Property(bool, notify=testStateChanged)
    def isTestingButton(self) -> bool:
        return self._is_testing_button

    @Property(str, notify=testStateChanged)
    def testingDeviceId(self) -> str:
        return self._testing_device_id

    @Property("QVariantMap", notify=testResultChanged)
    def testedButtonResult(self) -> Dict[str, Any]:
        return self._tested_button_result

    @Slot(str)
    def startButtonTest(self, device_id: str):
        self._is_testing_button = True
        self._testing_device_id = device_id
        self._tested_button_result = {}
        self._test_timer.start(15000)
        self.testResultChanged.emit()
        self.testStateChanged.emit()

    @Slot()
    def stopButtonTest(self):
        if self._is_testing_button:
            self._is_testing_button = False
            self._test_timer.stop()
            self.testStateChanged.emit()

    @Slot()
    def clearTestResult(self):
        self._tested_button_result = {}
        self.testResultChanged.emit()

    def _on_test_timeout(self):
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

    def eventFilter(self, watched, event):
        if not self._is_testing_button:
            return super().eventFilter(watched, event)

        ev_type = event.type()
        action = None
        detected_name = None

        if ev_type == QEvent.Type.MouseButtonPress:
            action, detected_name = self._map_mouse_button(event.button())
        elif ev_type == QEvent.Type.Wheel:
            dx = event.angleDelta().x()
            if dx < 0:
                action, detected_name = "special wheel-left", "Scroll Wheel Left"
            elif dx > 0:
                action, detected_name = "special wheel-right", "Scroll Wheel Right"
            else:
                return super().eventFilter(watched, event)
        elif ev_type == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.stopButtonTest()
                return True
            action, detected_name = self._map_key_event(event)

        if action and detected_name:
            self._handle_detected_button(action, detected_name)
            return True

        return super().eventFilter(watched, event)

    def _map_mouse_button(self, btn: Qt.MouseButton) -> Tuple[str, str]:
        mouse_button_actions = {
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
        if btn in mouse_button_actions:
            return mouse_button_actions[btn]

        try:
            val = int(btn.value) if hasattr(btn, "value") else int(btn)
            if val > 0:
                btn_num = int(math.log2(val)) + 1
                return f"button {btn_num}", f"Button {btn_num}"
        except Exception:
            pass
        return "unknown", "Unknown Mouse Button"

    def _map_key_event(self, event: QKeyEvent) -> Tuple[Optional[str], Optional[str]]:
        key = event.key()
        qt_key_map = {
            Qt.Key.Key_MediaPlay: "KEY_PLAYPAUSE",
            Qt.Key.Key_MediaPause: "KEY_PLAYPAUSE",
            Qt.Key.Key_MediaTogglePlayPause: "KEY_PLAYPAUSE",
            Qt.Key.Key_MediaNext: "KEY_NEXTSONG",
            Qt.Key.Key_MediaPrevious: "KEY_PREVIOUSSONG",
            Qt.Key.Key_VolumeUp: "KEY_VOLUMEUP",
            Qt.Key.Key_VolumeDown: "KEY_VOLUMEDOWN",
            Qt.Key.Key_VolumeMute: "KEY_MUTE",
            Qt.Key.Key_Return: "KEY_ENTER",
            Qt.Key.Key_Enter: "KEY_ENTER",
            Qt.Key.Key_Space: "KEY_SPACE",
            Qt.Key.Key_Tab: "KEY_TAB",
            Qt.Key.Key_Backspace: "KEY_BACKSPACE",
            Qt.Key.Key_Delete: "KEY_DELETE",
            Qt.Key.Key_Shift: "KEY_LEFTSHIFT",
            Qt.Key.Key_Control: "KEY_LEFTCTRL",
            Qt.Key.Key_Alt: "KEY_LEFTALT",
            Qt.Key.Key_Meta: "KEY_LEFTMETA",
            Qt.Key.Key_F1: "KEY_F1",
            Qt.Key.Key_F2: "KEY_F2",
            Qt.Key.Key_F3: "KEY_F3",
            Qt.Key.Key_F4: "KEY_F4",
            Qt.Key.Key_F5: "KEY_F5",
            Qt.Key.Key_F6: "KEY_F6",
            Qt.Key.Key_F7: "KEY_F7",
            Qt.Key.Key_F8: "KEY_F8",
            Qt.Key.Key_F9: "KEY_F9",
            Qt.Key.Key_F10: "KEY_F10",
            Qt.Key.Key_F11: "KEY_F11",
            Qt.Key.Key_F12: "KEY_F12",
        }
        if key in qt_key_map:
            linux_key = qt_key_map[key]
            disp = KEY_DISPLAY_NAMES.get(linux_key, linux_key.replace("KEY_", ""))
            return f"key {linux_key}", f"Key: {disp}"

        seq = QKeySequence(key).toString()
        if seq:
            clean_k = seq.upper().replace(" ", "_")
            return f"key KEY_{clean_k}", f"Key: {seq}"
        return None, None

    def _handle_detected_button(self, action: str, detected_name: str):
        dev = self._get_device_by_id(self._testing_device_id)
        matching_indices = []
        matching_names = []

        if dev and dev.buttons:
            for btn in dev.buttons:
                if btn.action_value == action:
                    matching_indices.append(btn.index)
                    matching_names.append(btn.name)

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


