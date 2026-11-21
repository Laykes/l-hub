# Phase 04: Direktes D-Bus für `ratbagd` & `UPower` + Echtes Hotplugging

## Ziel
`RatbagBackend` und `UPowerBackend` von langsamem CLI-Parsing (`ratbagctl` / `upower` per `subprocess`) auf direkte D-Bus-Kommunikation umstellen und echtes Event-getriebenes Hotplugging statt reinem 30-Sekunden-Polling einführen.

## Voraussetzungen
- Empfohlen: Phase 01 (Logging) & Phase 02 (aufgeräumter `DeviceManager`).

## Relevante Dateien
- `lhub/backends/ratbag.py`
- `lhub/backends/upower.py`
- `lhub/backends/base.py`
- `lhub/manager.py`
- `pyproject.toml`
- `tests/test_battery.py`
- `tests/test_dpi.py`
- `tests/test_mouse_profiles.py`

## Aufgaben
1. **D-Bus-Stack festlegen**
   - Prüfen, ob `PySide6.QtDBus` (bereits Teil von PySide6, integriert sich direkt in die Qt-Event-Loop ohne zusätzliche Dependency!) sauber alle benötigten Typen (`org.freedesktop.ratbag1` & `org.freedesktop.UPower`) abbildet.
   - Falls `QtDBus` für bestimmte D-Bus-Signaturen unhandlich ist, begründet eine schlanke Alternative evaluieren – bevorzugt keine unnötigen neuen System-Dependencies.
2. **`UPowerBackend` auf D-Bus umstellen**
   - Direkt `org.freedesktop.UPower` (`EnumerateDevices`, Properties `Model`, `Vendor`, `Percentage`, `State`, `TimeToEmpty`, `TimeToFull`, `NativePath`) abfragen.
   - D-Bus-Signale (`DeviceAdded`, `DeviceRemoved`, `PropertiesChanged`) abonnieren, sodass Akku-Änderungen und neue Bluetooth-/Wireless-Geräte sofort aktualisiert werden.
3. **`RatbagBackend` auf D-Bus umstellen**
   - Direkt mit `org.freedesktop.ratbag1` (`Manager`, `Device`, `Profile`, `Resolution`, `Button`, `Commit`) sprechen.
   - Alle bestehenden Funktionen beibehalten: DPI lesen/setzen, Button-Mappings lesen/schreiben, Makros, Batch-Remap, Commit + HID++-Fallback.
   - D-Bus-Signale für Geräte-Hinzufügen/-Entfernen und Profil-/Auflösungsänderungen nutzen.
4. **Hotplugging & Polling-Reduktion im `DeviceManager`**
   - `BaseBackend` um optionale Callback-/Signal-Hooks für Geräte-Events erweitern.
   - Bei D-Bus-Events debounced `refresh_devices()` auslösen (z. B. 300–500 ms Debounce).
   - Den Timer im `DeviceManager` nur noch als schlanken Fallback für reine CLI-Backends (`headsetcontrol`) nutzen.
5. **Tests**
   - D-Bus-Client-Layer mockbar kapseln, damit Unit-Tests ohne laufenden System-D-Bus laufen.
   - Bestehende Tests (`test_dpi.py`, `test_battery.py`, `test_mouse_profiles.py`) aktualisieren und Hotplug-Tests ergänzen.

## Akzeptanzkriterien & Verifikation
- Weder `ratbagctl` noch `upower`-CLI werden im Normalbetrieb noch per `subprocess` aufgerufen.
- An-/Abstecken einer Maus oder Ändern des Akkustands über UPower aktualisiert UI und Tray innerhalb ~1 Sekunde.
- Spürbar schnellerer Scan/Startup-Zyklus ohne Subprocess-Spikes.
- `python3 -m unittest discover -s tests` läuft komplett grün.
- Nach Abschluss in `phases/README.md` diese Phase von **Phases to do** nach **Phases done** verschieben.
