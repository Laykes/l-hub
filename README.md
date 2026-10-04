# L-Hub

Eine schlanke, modulare Peripherie-Zentrale für Linux (KDE Plasma & Kirigami).

Verwaltet Gaming-Mäuse, Headsets, Tastaturen und Controller über eine gemeinsame Oberfläche mit nativer KDE-System-Tray-Integration.

## Features
- **Headset-Verwaltung** (über `headsetcontrol`): Akkustand in Prozent und verbleibender Laufzeit, Sidetone (Mithörton) regeln, automatisches Abschalten (Inactive Timeout).
- **Maus-Verwaltung** (über `libratbag` / `ratbagd`): DPI-Stufen, Tastenbelegung, Profilüberwachung.
- **Akkustand & Tray-Icon**: Integriertes KDE-Systray-Symbol mit Batteriestands-Warnung bei niedrigem Ladestand.
- **Herstellerübergreifend**: Nutzt universelle Linux-Dienste für Logitech, SteelSeries, Razer, Corsair und weitere.

## Installation der Systemvoraussetzungen

Unter Arch / CachyOS:
```bash
sudo pacman -S libratbag headsetcontrol kirigami qqc2-desktop-style pyside6
sudo systemctl enable --now ratbagd
```

## Starten
```bash
python3 -m lhub
```
