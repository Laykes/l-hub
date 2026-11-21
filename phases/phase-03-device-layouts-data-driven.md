# Phase 03: Datengetriebene Geräte-Layouts statt Hardcoding

## Ziel
Die aktuell im Python-Code fest verdrahteten Button-Layouts und Factory-Reset-Defaults (derzeit speziell für die Logitech G502-Serie) in erweiterbare JSON-Gerätedefinitionen auslagern.

## Voraussetzungen
- Empfohlen: Phase 02, aber auch unabhängig umsetzbar.

## Relevante Dateien
- `lhub/backends/ratbag.py` (`get_button_metadata`, Factory-Reset-Logik)
- `pyproject.toml` (`[tool.setuptools.package-data]`)
- `tests/test_mouse_profiles.py`
- `tests/test_button_tester.py`

## Aufgaben
1. **Gerätedefinitions-Schema entwerfen**
   - Verzeichnis `lhub/data/devices/` anlegen.
   - Klares JSON-Schema für Maus-Layouts definieren:
     - `id`, `name`, `vendor`, `vid`, `pids` (Liste unterstützter PIDs), optional `name_patterns`
     - `buttons`: Liste/Map mit `index`, `name`, `label`, `location`, `group` (`main`, `side`, `wheel`, `dpi`, ...), `default` (Default-ratbag-Action für sicheren Factory-Reset)
2. **Loader-Modul (`lhub/device_layouts.py`)**
   - Lädt alle JSON-Dateien aus `lhub/data/devices/` (optional auch benutzerdefinierte Overrides aus `~/.config/lhub/devices/`).
   - Matcht zuerst exakt über `(vid, pid)`, danach optional über `name_patterns`, und fällt sonst sauber auf generische Button-Metadaten zurück.
   - Bietet eine Hilfsfunktion für sichere Factory-Reset-Defaults (wenn kein Modell-Layout existiert, wird für unbekannte Buttons ein sicherer Fallback genutzt bzw. nur bekannte Standard-Buttons zurückgesetzt).
3. **Bestehende G502-Definition migrieren & weitere verbreitete Modelle anlegen**
   - `lhub/data/devices/logitech_g502.json` mit den bestehenden 11-Button-Metadaten und PIDs erstellen.
   - Optional 2–3 weitere verbreitete Mäuse als Beispiele anlegen (z. B. generische 5-Tasten-Maus / Logitech G Pro / G305) – nur verifizierte Layouts, nichts raten.
   - `ratbag.py` auf den neuen Loader umstellen.
   - `pyproject.toml` so aktualisieren, dass `data/devices/*.json` als Package-Data enthalten ist.
4. **Tests**
   - Unit-Tests für JSON-Validierung aller mitgelieferten Layouts, VID:PID-Matching, Fallback-Verhalten und User-Override in `tests/test_device_layouts.py`.

## Akzeptanzkriterien & Verifikation
- Keine modellspezifischen Button-Tabellen mehr hartkodiert in `lhub/backends/ratbag.py`.
- Logitech G502 funktioniert exakt wie zuvor; andere Mäuse fallen sauber auf generische Namen zurück.
- `python3 -m unittest discover -s tests` läuft komplett grün.
- Nach Abschluss in `phases/README.md` diese Phase von **Phases to do** nach **Phases done** verschieben.
