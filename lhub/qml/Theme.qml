import QtQuick

QtObject {
    // Core Obsidian Dark Palette
    readonly property color bgWindow: "#0d1117"
    readonly property color bgSidebar: "#11161f"
    readonly property color bgSurface: "#161c26"
    readonly property color bgSurfaceHover: "#1c2432"
    readonly property color bgSurfaceActive: "#1e293b"
    readonly property color bgControl: "#10151e"
    readonly property color bgDialog: "#131924"

    // Borders
    readonly property color borderSubtle: "#222c3c"
    readonly property color borderHover: "#33435c"
    readonly property color borderStrong: "#3b4e6b"

    // Brand Accent (matches L-Hub icon cyan)
    readonly property color accent: "#38bdf8"
    readonly property color accentHover: "#5ce1ff"
    readonly property color accentPressed: "#0ea5e9"
    readonly property color accentSoft: "#1a38bdf8"
    readonly property color accentMedium: "#2e38bdf8"
    readonly property color accentBorder: "#6638bdf8"
    readonly property color accentText: "#081421"

    // Typography
    readonly property color textPrimary: "#f1f5f9"
    readonly property color textSecondary: "#94a3b8"
    readonly property color textMuted: "#64748b"

    // Semantic Status Colors
    readonly property color positive: "#34d399"
    readonly property color positiveSoft: "#1f34d399"
    readonly property color warning: "#fbbf24"
    readonly property color warningSoft: "#1ffbbf24"
    readonly property color danger: "#f87171"
    readonly property color dangerSoft: "#22f87171"
    readonly property color dangerBorder: "#66f87171"
    readonly property color purple: "#a78bfa"
    readonly property color purpleSoft: "#22a78bfa"

    // Radii
    readonly property int radiusXs: 6
    readonly property int radiusSm: 8
    readonly property int radiusMd: 12
    readonly property int radiusLg: 16
    readonly property int radiusPill: 999
}
