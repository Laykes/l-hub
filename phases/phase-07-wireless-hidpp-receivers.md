# Phase 07: Wireless HID++ 2.0 Support (Lightspeed / Unifying / Bolt)

## Ziel
Das bisher auf kabelgebundene Logitech-Mäuse (`_DEVICE_INDEX = 0xFF`) beschränkte HID++-Modul auf drahtlose Logitech-Empfänger (Lightspeed, Unifying, Bolt) erweitern, sodass auch kabellose Mäuse Live-DPI und Onboard-Profilwechsel unterstützen.

## Voraussetzungen
- Empfohlen: Phase 01 (Logging für HID++-Debugging).

## Relevante Dateien
- `lhub/backends/hidpp.py`
- `lhub/backends/hid_input.py`
- `lhub/backends/ratbag.py`
- `lhub/manager.py`
- `tests/test_hidpp.py`

## Aufgaben
1. **Receiver- & Device-Index-Erkennung in `lhub/backends/hidpp.py`**
   - Statt hardcoded `_DEVICE_INDEX = 0xFF` sowohl direkte USB-Geräte (`0xFF`) als auch gepairte Receiver-Slots (`1..6`) unterstützen.
   - Bekannte Logitech-Receiver-PIDs (Unifying, Lightspeed, Bolt) erkennen und über HID++ 2.0 (`IRoot` / `DeviceName` `0x0005` bzw. `DeviceType` / WPID) das richtige gepairte Gerät dem `ratbagd`-Device zuordnen.
   - Cache-Schlüssel von `(vid, pid, feature_id)` sauber auf `(device_key, feature_id)` mit gespeichertem `(hidraw_path, device_index, feature_idx)` erweitern.
2. **Sleep / Wake & Reconnect-Verhalten absichern**
   - Wireless-Mäuse gehen regelmäßig in den Tiefschlaf und liefern dann HID++-Fehler (`0x08` / `ResourceError` / Timeout) statt Antworten.
   - Fehler sauber abfangen, Cache nicht dauerhaft vergiften und beim Aufwachen automatisch neu verbinden/synchronisieren (z. B. beim Empfang von Receiver-Connection-Notifications oder beim nächsten Request).
3. **`OnboardProfileMonitor` für Receiver-Slots**
   - Events nach `device_index` filtern, damit bei mehreren Geräten am selben Dongle (z. B. Maus + Tastatur an einem Bolt/Unifying-Receiver) keine Events verwechselt werden.
4. **Raw HID Input Monitor (`hid_input.py`) prüfen**
   - Prüfen, ob das Matching über VID:PID im Button-Tester bei Receiver-Dongles sauber funktioniert (Receiver teilt sich ggf. eine VID:PID für mehrere Interfaces) und ggf. gezielt auf Mouse-/Keyboard-Report-Interfaces filtern.
5. **Tests**
   - `tests/test_hidpp.py` um Tests für Receiver-Index-Enumeration (`1..6`), Multi-Device-Filterung am selben Dongle und Sleep/Wake-Fehlerbehandlung erweitern.

## Akzeptanzkriterien & Verifikation
- Kabelgebundene Logitech-Mäuse (`0xFF`) funktionieren unverändert weiter.
- Kabellose Logitech-Mäuse über Lightspeed/Unifying/Bolt werden am korrekten Device-Index erkannt; Runtime-DPI und Onboard-Profilwechsel funktionieren stabil.
- Tiefschlaf/Aufwachen der Maus führt nicht zu Abstürzen, hängenden Threads oder dauerhaftem Verlust der HID++-Funktion.
- `python3 -m unittest discover -s tests` läuft komplett grün.
- Nach Abschluss in `phases/README.md` diese Phase von **Phases to do** nach **Phases done** verschieben.
