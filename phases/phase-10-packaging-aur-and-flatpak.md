# Phase 10: Packaging, Releases, AUR & Flatpak

## Ziel
L-Hub für eine breite Linux-Nutzerschaft sauber paketieren und auslieferbar machen: saubere Release-Metadaten, AUR `PKGBUILD` für Arch-basierte Distros sowie ein Flatpak-Manifest für Immutable-/Nicht-Arch-Distros.

## Voraussetzungen
- Empfohlen: Phase 01 (Health-Check für Host-Abhängigkeiten), Phase 04 (direktes D-Bus vereinfacht Flatpak erheblich), Phase 05 & Phase 06.

## Relevante Dateien
- `pyproject.toml`
- `io.github.lhub.LHub.desktop`
- `install.sh`
- `README.md`
- Neu: `io.github.lhub.LHub.metainfo.xml`, `packaging/aur/PKGBUILD`, `packaging/flatpak/io.github.lhub.LHub.yml`, `CHANGELOG.md`

## Aufgaben
1. **AppStream-Metadaten & Release-Grundlagen**
   - `io.github.lhub.LHub.metainfo.xml` nach FreeDesktop/Flathub-Spezifikation erstellen (Beschreibung, Lizenz `GPL-3.0-or-later`, Screenshots, Release-Historie) und mit `appstreamcli validate` prüfen.
   - `CHANGELOG.md` und einheitliche Versionierung in `pyproject.toml` / `lhub/__init__.py` einführen.
   - Hilfsdokumentation (und ggf. Beispiel-udev-Regeln) für `headsetcontrol` und `/dev/hidraw*` ergänzen.
2. **AUR `PKGBUILD` (`packaging/aur/PKGBUILD`)**
   - Sauberes `PKGBUILD` (für stabile Releases und/oder `-git`) erstellen:
     - `depends`: `python`, `python-pyside6`, `kirigami`, `qqc2-desktop-style`
     - `optdepends`: `libratbag`, `headsetcontrol`, `upower`
     - Installiert Python-Paket, `/usr/bin/l-hub`, Icon, `.desktop` und `.metainfo.xml`.
   - Lokal mit `makepkg -si` (bzw. `namcap`) testen und verifizieren.
3. **Flatpak-Manifest (`packaging/flatpak/io.github.lhub.LHub.yml`)**
   - Basis: `org.kde.Platform` / `org.kde.Sdk` (KF6 / Qt 6).
   - PySide6/Shiboken passend zur Qt-Version der KDE-Runtime integrieren (BaseApp oder Build-Modul prüfen, damit Kirigami-QML sauber lädt).
   - `headsetcontrol` im Manifest mitbundeln; `ratbagd` & `UPower` über D-Bus-Talk-Permissions ansprechen:
     - `--system-talk-name=org.freedesktop.ratbag1`
     - `--system-talk-name=org.freedesktop.UPower`
     - `--talk-name=org.kde.StatusNotifierWatcher`
     - `--device=all` (für USB-Headsets & `/dev/hidraw*`)
   - Lokal mit `flatpak-builder` bauen und testen; Host-Voraussetzungen (`ratbagd`, udev-Regeln) klar in `README.md` dokumentieren.
4. **CI-Workflow (`.github/workflows/ci.yml`)**
   - Automatische Ausführung von `python3 -m unittest discover -s tests` und optional Metainfo-Validierung bei Push/PR.

## Akzeptanzkriterien & Verifikation
- `appstreamcli validate io.github.lhub.LHub.metainfo.xml` meldet keine Fehler.
- AUR-Paket baut sauber und startet L-Hub korrekt inkl. Startmenü-Eintrag und Icon.
- Flatpak-Build startet erfolgreich mit funktionierendem Kirigami-UI, Tray und D-Bus-Verbindung zu `ratbagd`/`UPower`.
- `README.md` dokumentiert die neuen Installationswege (AUR, Flatpak, Source).
- Nach Abschluss in `phases/README.md` diese Phase von **Phases to do** nach **Phases done** verschieben.
