# Phase 09: Erweiterter Makro-Editor, Profil-Import/Export & App-Auto-Profile

## Ziel
Die Profil- und Remapping-Funktionen auf das Niveau moderner Peripherie-Suiten heben: mehrstufige Makros, Profil-Export/-Import sowie (optional) automatischer Profilwechsel je nach aktivem Fenster/Spiel.

## Voraussetzungen
- Empfohlen: Phase 02 (aufgeräumter `RemapDialog.qml`), Phase 03 & Phase 05 (Settings).

## Relevante Dateien
- `lhub/profiles.py`
- `lhub/backends/ratbag.py` (`parse_macro`, Makro-Formatierung)
- `lhub/manager.py`
- `lhub/qml/RemapDialog.qml`
- `lhub/qml/main.qml`
- `tests/test_mouse_profiles.py`

## Aufgaben
1. **Mehrstufiger Makro-Editor**
   - Datenmodell und Parser/Serializer für `libratbag`-Makro-Syntax (`+KEY_...`, `-KEY_...`, `t<ms>` Delays) sauber kapseln und testen.
   - Im Remap-Dialog einen eigenen Tab/Bereich „Macro“ ergänzen:
     - Schritte hinzufügen (Taste drücken/aufnehmen, Press/Release oder Tap, Delay in ms)
     - Schritte umsortieren und löschen
     - Validierung gegen `libratbag`-Längenlimits mit verständlicher Fehlermeldung
2. **Profil-Import & -Export**
   - In `ProfileManager` Methoden zum Exportieren einzelner oder aller Profile eines Geräts als JSON (inkl. Schema-Version & Geräte-Metadaten) sowie validierten Import (Konfliktbehandlung bei gleichem Namen).
   - Export-/Import-Buttons in der Profil-Leiste mit nativem Qt-`FileDialog`.
3. **Automatischer Profilwechsel pro Anwendung (KDE Plasma / optional aktivierbar)**
   - Pro Profil optional eine Liste von Fensterklassen / Prozessnamen (z. B. `cs2`, `blender`, `firefox`) hinterlegen können.
   - Leichtgewichtigen Window-Watcher für KDE Plasma/Wayland (und X11-Fallback) entwerfen – sauber optional, per Setting an-/abschaltbar und ohne Polling-Overhead (z. B. über KWin-D-Bus / Script-Hook oder klar gekapselten Provider).
   - Beim Wechsel auf ein nicht gematchtes Fenster sauber auf das Standard-Profil zurückfallen.
4. **Tests**
   - Unit-Tests für Makro-Serialisierung/-Parsing, Längen-Validierung, Profil-Import/Export (inkl. fehlerhafter JSON-Dateien) und App-Matching-Logik.

## Akzeptanzkriterien & Verifikation
- Mehrstufige Makros (inkl. Delays) können erstellt, gespeichert, an die Maus übertragen und korrekt wieder ausgelesen werden.
- Profile lassen sich als JSON exportieren und ohne Datenverlust wieder importieren.
- Auto-Profilwechsel (wenn aktiviert) schaltet sauber um und fällt bei Fensterwechsel zurück.
- `python3 -m unittest discover -s tests` läuft komplett grün.
- Nach Abschluss in `phases/README.md` diese Phase von **Phases to do** nach **Phases done** verschieben.
