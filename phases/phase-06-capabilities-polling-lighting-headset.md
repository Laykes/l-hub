# Phase 06: Hardware-Capabilities ausbauen (Polling Rate, RGB/LEDs, Headset Sleep & EQ)

## Ziel
Die bereits in `lhub/backends/base.py` modellierten Capabilities (`POLLING_RATE`, `LIGHTING`, `INACTIVE_TIME`, `EQUALIZER`) vollständig in den Backends, im `DeviceManager` und in der QML-UI verdrahten.

## Voraussetzungen
- Empfohlen: Phase 02 (modulare QML-Komponenten) & Phase 04 (D-Bus für `ratbagd`).

## Relevante Dateien
- `lhub/backends/base.py`
- `lhub/backends/ratbag.py`
- `lhub/backends/headset.py`
- `lhub/manager.py` (bzw. `lhub/serializers.py`)
- `lhub/qml/DeviceCard.qml` (bzw. die extrahierten Section-Komponenten)
- `tests/test_headset.py`, `tests/test_dpi.py`

## Aufgaben
1. **Polling Rate (`POLLING_RATE`) für Mäuse**
   - `Device`-Datenmodell um `polling_rate` und `supported_polling_rates` (z. B. `[125, 250, 500, 1000]`) erweitern.
   - In `RatbagBackend` aktuelle und unterstützte Report-Rates lesen und setzen (`set_polling_rate`).
   - Kompakte Auswahl (Button-Row / Chips) in der Maus-UI anzeigen, wenn `Capability.POLLING_RATE` vorhanden ist.
2. **Beleuchtung / RGB (`LIGHTING`)**
   - Schlankes `LightingInfo`-Datenmodell (`leds`: Modus wie `off`/`on`/`breathing`/`cycle`, Farbe als Hex `#RRGGBB`, Helligkeit, Geschwindigkeit) in `base.py` definieren.
   - `RatbagBackend`: LED-Konfiguration lesen & setzen (inkl. Commit).
   - `HeadsetBackend`: LED-Toggle (`headsetcontrol -l 0|1`) für Headsets mit `lights`/`leds`-Capability unterstützen.
   - UI-Sektion für Beleuchtung (On/Off, Modus, Farbauswahl/Presets, Helligkeit) nur anzeigen, wenn das Gerät `Capability.LIGHTING` unterstützt.
3. **Headset Sleep-Timer (`INACTIVE_TIME`) & Equalizer (`EQUALIZER`)**
   - `INACTIVE_TIME` ist in `headset.py` bereits teilweise vorhanden (`set_inactive_time`): sauber in `DeviceManager` und der Headset-UI verdrahten (Slider/Auswahl 0–90 Min, `0 = Aus`).
   - `EQUALIZER`: über `headsetcontrol` verfügbare EQ-Presets (falls im JSON-Output gemeldet) auslesen und umschalten (`-p <preset>`).
4. **Tests**
   - Unit-Tests für Parsing & Setzen von Polling Rate, LED-Konfiguration, Inactive Time und EQ-Presets ergänzen.

## Akzeptanzkriterien & Verifikation
- UI-Elemente erscheinen nur dynamisch für Capabilities, die das jeweilige Gerät tatsächlich unterstützt.
- Polling Rate, Beleuchtung, Sleep-Timer und EQ-Presets lassen sich ohne UI-Freeze ändern und aktualisieren den Zustand korrekt.
- `python3 -m unittest discover -s tests` läuft komplett grün.
- Nach Abschluss in `phases/README.md` diese Phase von **Phases to do** nach **Phases done** verschieben.
