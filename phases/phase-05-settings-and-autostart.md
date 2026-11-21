# Phase 05: App-Einstellungen & Autostart

## Ziel
Eine persistente Konfigurationsschicht (`settings.json`) inkl. Einstellungs-UI in L-Hub einführen – mit Autostart beim Login, Start minimiert ins System-Tray und konfigurierbaren Benachrichtigungen.

## Voraussetzungen
- Empfohlen: Phase 01 & Phase 02.

## Relevante Dateien
- `lhub/main.py`
- `lhub/manager.py`
- `lhub/profiles.py` (Vorlage für atomares JSON-Speichern unter `~/.config/lhub/`)
- `lhub/tray.py`
- `lhub/qml/main.qml`
- `io.github.lhub.LHub.desktop`
- `install.sh`

## Aufgaben
1. **`SettingsManager` (`lhub/settings.py`)**
   - Atomare JSON-Speicherung unter `~/.config/lhub/settings.json` (respektiert `XDG_CONFIG_HOME`, analog zu `ProfileManager`).
   - Sinnvolle Defaults:
     - `autostart`: `false`
     - `start_minimized`: `false`
     - `low_battery_threshold`: `20` (int, 5–50)
     - `notify_low_battery`: `true`
     - `notify_profile_change`: `true`
     - `poll_interval_sec`: `30` (int, z. B. 10–120)
2. **Autostart-Verwaltung & `--minimized`-Flag**
   - CLI-Flag `--minimized` in `lhub/main.py`: startet L-Hub direkt im Tray ohne das Hauptfenster anzuzeigen (Single-Instance-Aktivierung öffnet das Fenster aber weiterhin normal).
   - Beim Aktivieren von `autostart` eine `.desktop`-Datei unter `~/.config/autostart/io.github.lhub.LHub.desktop` anlegen (inkl. `--minimized`, wenn `start_minimized` aktiv ist); beim Deaktivieren sauber entfernen.
   - `Exec=` dynamisch sinnvoll auflösen (`~/.local/bin/l-hub` falls vorhanden, sonst `python3 -m lhub` mit aktuellem Pfad).
3. **Einstellungen im `DeviceManager` & `LHubTray` anwenden**
   - Hardcoded `LOW_BATTERY_THRESHOLD = 20` und `30000 ms` Timer durch Werte aus `SettingsManager` ersetzen (Live-Aktualisierung ohne Neustart).
   - Benachrichtigungen für Low Battery und Onboard-Profilwechsel nur auslösen, wenn das jeweilige Setting aktiviert ist.
4. **Settings-Dialog / -Seite in QML**
   - Sauberer Einstellungs-Button in der Header-Bar von `main.qml` + kompakter Dialog (`lhub/qml/SettingsDialog.qml`) im bestehenden dunklen Kirigami-Stil (`Theme.qml`).
5. **Tests**
   - Unit-Tests in `tests/test_settings.py` für Laden/Speichern/Defaults, Autostart-Desktop-Datei erstellen/aktualisieren/löschen und Threshold-/Notification-Logik.

## Akzeptanzkriterien & Verifikation
- `python3 -m lhub --minimized` startet ohne sichtbares Fenster direkt ins Tray; erneutes Starten oder Klick aufs Tray öffnet das Fenster.
- Änderungen in den Einstellungen bleiben über Neustarts hinweg erhalten und greifen sofort.
- Autostart-Toggle erstellt/entfernt `~/.config/autostart/io.github.lhub.LHub.desktop` korrekt.
- `python3 -m unittest discover -s tests` läuft komplett grün.
- Nach Abschluss in `phases/README.md` diese Phase von **Phases to do** nach **Phases done** verschieben.
