#!/usr/bin/env bash
set -euo pipefail

APP_ID="io.github.lhub.LHub"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BIN_DIR="${HOME}/.local/bin"
BIN_PATH="${BIN_DIR}/l-hub"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
ICON_PATH="${ICON_DIR}/${APP_ID}.svg"
DESKTOP_DIR="${HOME}/.local/share/applications"
DESKTOP_PATH="${DESKTOP_DIR}/${APP_ID}.desktop"
AUTOSTART_PATH="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart/${APP_ID}.desktop"

refresh_caches() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "${DESKTOP_DIR}" 2>/dev/null || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
    fi
    if command -v kbuildsycoca6 >/dev/null 2>&1; then
        kbuildsycoca6 --noincremental 2>/dev/null || true
    fi
}

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "${BIN_PATH}" "${ICON_PATH}" "${DESKTOP_PATH}" "${AUTOSTART_PATH}"
    refresh_caches
    echo "L-Hub wurde aus ~/.local entfernt."
    exit 0
fi

mkdir -p "${BIN_DIR}" "${ICON_DIR}" "${DESKTOP_DIR}"

cat > "${BIN_PATH}" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${SCRIPT_DIR}\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m lhub "\$@"
EOF
chmod +x "${BIN_PATH}"

cp "${SCRIPT_DIR}/lhub/assets/${APP_ID}.svg" "${ICON_PATH}"

sed "s|^Exec=.*|Exec=${BIN_PATH}|" "${SCRIPT_DIR}/${APP_ID}.desktop" > "${DESKTOP_PATH}"
chmod 644 "${DESKTOP_PATH}"

refresh_caches

echo "L-Hub wurde installiert:"
echo "  Launcher: ${BIN_PATH}"
echo "  Icon:     ${ICON_PATH}"
echo "  Desktop:  ${DESKTOP_PATH}"
