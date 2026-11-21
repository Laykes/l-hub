# Phase 02: Architektur-Entzerrung (`DeviceManager` & QML-Komponenten)

## Ziel
Die stark gewachsenen Kern-Dateien (`lhub/manager.py` und die QML-Views) in kleine, klar abgegrenzte Module und Komponenten zerlegen, ohne bestehendes Verhalten zu verändern.

## Voraussetzungen
- Empfohlen: Phase 01 (Logging), aber auch unabhängig machbar.

## Relevante Dateien
- `lhub/manager.py` (~935 Zeilen)
- `lhub/qml/main.qml` (~33 KB)
- `lhub/qml/DeviceCard.qml` (~48 KB)
- `lhub/qml/RemapDialog.qml` (~38 KB)
- `lhub/qml/Theme.qml`
- `lhub/qml/UiButton.qml`
- `tests/` (insb. `tests/test_button_tester.py`, `tests/test_battery.py`, `tests/test_mouse_profiles.py`)

## Aufgaben
1. **`lhub/manager.py` modularisieren**
   - Qt-Key-Mapping (`_QT_MODIFIER_KEYS`, `_QT_TO_LINUX_KEY`, `_qt_key_to_linux`, `_qt_modifiers_to_linux`) in `lhub/keymap.py` auslagern.
   - Button-Tester-Logik (HID-Input-Monitor, Qt-Event-Filter, Modifier-Debounce, Timeout, Match-Auswertung) in eine eigene Klasse `ButtonTesterController` (z. B. `lhub/button_tester.py`) auslagern.
   - Device-to-QML-Dict-Serialisierung in ein eigenes Helper-Modul (`lhub/serializers.py`) auslagern.
   - `DeviceManager` als schlanken Koordinator behalten, der weiterhin die bestehende QML-API (Properties, Signals, Slots) stabil bedient.
2. **QML-Komponenten aufteilen**
   - `DeviceCard.qml` in klare Unterkomponenten pro Capability zerlegen, z. B.:
     - `lhub/qml/components/BatteryHeader.qml`
     - `lhub/qml/components/DpiSection.qml`
     - `lhub/qml/components/ProfileBar.qml`
     - `lhub/qml/components/ButtonGrid.qml`
     - `lhub/qml/components/HeadsetSection.qml`
   - Wiederverwendbare Bausteine aus `RemapDialog.qml` (z. B. Live-Key-Capture-Bereich, Preset-Auswahl) sinnvoll extrahieren, wenn es die Lesbarkeit deutlich verbessert.
3. **Verhalten & Tests absichern**
   - Bestehende Imports/Methoden, die in Tests genutzt werden, kompatibel halten oder Tests sauber mit anpassen.
   - Keine neuen Features in dieser Phase mischen (reines Refactoring).

## Akzeptanzkriterien & Verifikation
- Keine bestehende Funktionalität (DPI, Remapping, Button-Tester, Profile, Headset, Tray) geht verloren.
- `lhub/manager.py` und `lhub/qml/DeviceCard.qml` sind deutlich kompakter und übersichtlicher.
- `python3 -m unittest discover -s tests` läuft vor und nach dem Refactoring komplett grün.
- App lässt sich starten (`python3 -m lhub`) ohne QML-Warnings/Fehler auf `stderr`.
- Nach Abschluss in `phases/README.md` diese Phase von **Phases to do** nach **Phases done** verschieben.
