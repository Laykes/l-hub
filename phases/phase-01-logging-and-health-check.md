# Phase 01: Logging & System-Health-Diagnose

## Ziel
Stille Fehler (`except Exception: pass`) und verstreute `print(...)`-Aufrufe durch strukturiertes Logging ersetzen sowie eine zentrale System-Health-Prüfung bauen, die fehlende Daemons, Tools oder Geräte-Rechte klar in der UI meldet.

## Voraussetzungen
- Keine (kann sofort als erste Phase umgesetzt werden).

## Relevante Dateien
- `lhub/main.py`
- `lhub/manager.py`
- `lhub/profiles.py`
- `lhub/backends/base.py`
- `lhub/backends/ratbag.py`
- `lhub/backends/headset.py`
- `lhub/backends/hidpp.py`
- `lhub/backends/hid_input.py`
- `lhub/backends/upower.py`
- `lhub/qml/main.qml`
- `tests/`

## Aufgaben
1. **Zentrales Logging-Modul (`lhub/logging_config.py`)**
   - Python `logging` mit sauberem Format konfigurieren (`WARNING`/`INFO` als Standard).
   - CLI-Argumente in `lhub/main.py` via `argparse` unterstützen, mindestens `--debug` (schaltet `DEBUG`-Logging ein).
   - Bestehende `print(...)`-Statements und stille `except Exception: pass` in den Backends, `manager.py` und `profiles.py` auf `logger.debug/warning/error` umstellen.
2. **System-Health-Check (`lhub/health.py` oder Methode im `DeviceManager`)**
   - Prüfen und strukturierte Statusmeldungen (Severity: `ok` / `warning` / `error`, Titel, Beschreibung, Lösungshinweis) liefern für:
     - `ratbagd` läuft / erreichbar (inkl. Hinweis `sudo systemctl enable --now ratbagd`)
     - `headsetcontrol` installiert und ausführbar
     - `/dev/hidraw*`-Zugriffsrechte für erkannte Logitech-Geräte / Headsets (Hinweis auf udev-Regeln, wenn `PermissionError` auftritt)
     - `upower` verfügbar (optional, nur als Info/Fallback)
3. **UI-Integration**
   - Health-Ergebnisse als QML-Property über `DeviceManager` bereitstellen.
   - In `lhub/qml/main.qml` nur dann einen kompakten Hinweis-/Diagnose-Banner (oder aufklappbaren Status-Dialog) anzeigen, wenn relevante Warnungen/Fehler vorliegen – mit konkretem Kopier-/Fix-Hinweis.
4. **Tests**
   - Unit-Tests für den Health-Check (fehlender Daemon, fehlende Binary, PermissionError auf `/dev/hidraw*`, alles OK) unter `tests/test_health.py` ergänzen.

## Akzeptanzkriterien & Verifikation
- `python3 -m lhub --debug` startet sauber und schreibt strukturierte Logs.
- Fehlender `ratbagd` oder fehlende `/dev/hidraw*`-Rechte werden nicht mehr still verschluckt, sondern verständlich geloggt und in der UI angezeigt.
- `python3 -m unittest discover -s tests` läuft komplett grün.
- Nach Abschluss in `phases/README.md` diese Phase von **Phases to do** nach **Phases done** verschieben.
