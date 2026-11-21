import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

QQC2.AbstractButton {
    id: control

    property string variant: "default" // "default" | "primary" | "subtle" | "danger" | "pill"
    property string iconName: ""
    property string toolTipText: ""
    property bool compact: false

    readonly property Theme theme: Theme {}

    implicitHeight: compact ? 32 : 36
    implicitWidth: contentRow.implicitWidth + (compact ? 22 : 30)
    hoverEnabled: true
    opacity: enabled ? 1.0 : 0.42

    QQC2.ToolTip.visible: hovered && toolTipText.length > 0
    QQC2.ToolTip.text: toolTipText
    QQC2.ToolTip.delay: 400

    readonly property bool isActiveStyle: checked || variant === "primary"

    background: Rectangle {
        radius: control.variant === "pill" ? control.theme.radiusPill : control.theme.radiusSm
        color: {
            if (control.variant === "primary") {
                if (control.down) return control.theme.accentPressed
                if (control.hovered) return control.theme.accentHover
                return control.theme.accent
            }
            if (control.checked) {
                if (control.down) return control.theme.accentMedium
                return control.theme.accentSoft
            }
            if (control.variant === "danger") {
                if (control.down) return "#38f87171"
                if (control.hovered) return control.theme.dangerSoft
                return control.theme.bgControl
            }
            if (control.variant === "subtle") {
                if (control.down) return control.theme.bgSurfaceActive
                if (control.hovered) return control.theme.bgSurfaceHover
                return "transparent"
            }
            if (control.down) return control.theme.bgSurfaceActive
            if (control.hovered) return control.theme.bgSurfaceHover
            return control.theme.bgControl
        }
        border.width: (control.variant === "subtle" && !control.hovered && !control.checked) ? 0 : 1
        border.color: {
            if (control.variant === "primary") return "transparent"
            if (control.checked) return control.theme.accent
            if (control.variant === "danger") return control.hovered ? control.theme.danger : control.theme.borderSubtle
            return control.hovered ? control.theme.borderHover : control.theme.borderSubtle
        }

        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }

    contentItem: Item {
        implicitWidth: contentRow.implicitWidth
        implicitHeight: contentRow.implicitHeight

        RowLayout {
            id: contentRow
            anchors.centerIn: parent
            spacing: (control.iconName.length > 0 && control.text.length > 0) ? 7 : 0

            Kirigami.Icon {
                visible: control.iconName.length > 0
                source: control.iconName
                Layout.preferredWidth: control.compact ? 15 : 16
                Layout.preferredHeight: control.compact ? 15 : 16
                isMask: true
                color: {
                    if (control.variant === "primary") return control.theme.accentText
                    if (control.checked) return control.theme.accent
                    if (control.variant === "danger" && control.hovered) return control.theme.danger
                    return control.theme.textPrimary
                }
            }

            Text {
                visible: control.text.length > 0
                text: control.text
                font.pixelSize: control.compact ? 12 : 13
                font.weight: (control.variant === "primary" || control.checked) ? Font.DemiBold : Font.Medium
                color: {
                    if (control.variant === "primary") return control.theme.accentText
                    if (control.checked) return control.theme.accent
                    if (control.variant === "danger" && control.hovered) return control.theme.danger
                    return control.theme.textPrimary
                }
                elide: Text.ElideRight
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
    }
}
