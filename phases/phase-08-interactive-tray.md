# Phase 08: Interaktives System-Tray-Menü

## Ziel
Das bisher rein lesende System-Tray-Menü (`lhub/tray.py`) um schnelle, interaktive Aktionen pro Gerät erweitern (Profilwechsel, DPI-Stufe, Headset-Sidetone), damit häufige Anpassungen direkt per Rechtsklick möglich sind, ohne das Hauptfenster öffnen zu müssen.

## Voraussetzungen
- Empfohlen: Phase 02 & Phase 05.

## Relevante Dateien
- `lhub/tray.py`
- `lhub/manager.py`
- `tests/` (neuer Test `tests/test_tray.py`)

## Aufgaben
1. **Geräte-Untermenüs in `LHubTray._build_menu()`**
   - Statt deaktivierter Textzeilen pro Gerät mit konfigurierbaren Capabilities ein eigenes `QMenu`-Untermenü anzeigen (Statuszeile mit Akku/Profil weiterhin direkt sichtbar im Titel oder als erster Eintrag).
   - Nur-Akku-Geräte (z. B. UPower-Fallback) bleiben kompakte Status-Einträge.
2. **Schnellaktionen pro Gerätetyp**
   - **Mäuse:**
     - **Profile**: Checkable `QAction`-Liste aller gespeicherten Profile des Geräts (aktives Profil mit Häkchen) – Klick ruft `manager.switch_profile(...)` auf.
     - **DPI-Stufen**: Checkable `QAction`-Liste der verfügbaren DPI-Schritte (z. B. 400 / 800 / 1600 / 3200) – Klick ruft `manager.set_dpi(...)` auf.
   - **Headsets:**
     - **Sidetone**: Schnellauswahl (z. B. Aus / Niedrig / Mittel / Hoch oder gespeicherter Wert) – Klick ruft `manager.set_sidetone(...)` auf.
3. **Menü-Stabilität & Refresh-Schutz**
   - Sicherstellen, dass Hintergrund-Refreshes das geöffnete Tray-Menü nicht schließen oder kaputtmachen (bestehender `isVisible()`-Check sauber mit verzögertem Rebuild beim Schließen kombinieren).
   - Optional: „Refresh Devices“-Aktion im Hauptmenü ergänzen.
4. **Tests**
   - Unit-Tests in `tests/test_tray.py` für Menü-Aufbau (Maus mit Profilen/DPI, Headset mit Sidetone, reines Batterie-Gerät, keine Geräte) und Triggering der Manager-Slots.

## Akzeptanzkriterien & Verifikation
- Per Rechtsklick aufs Tray-Icon lassen sich Profile, DPI-Stufen und Headset-Sidetone direkt umschalten.
- Aktive Auswahl wird im Tray-Menü korrekt markiert und bleibt mit dem Hauptfenster synchron.
- `python3 -m unittest discover -s tests` läuft komplett grün.
- Nach Abschluss in `phases/README.md` diese Phase von **Phases to do** nach **Phases done** verschieben.
