import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import ".."

Rectangle {
    id: root

    property var deviceData: ({})

    readonly property Theme theme: Theme {}

    radius: theme.radiusLg
    color: theme.bgSurface
    border.color: theme.borderSubtle
    border.width: 1
    implicitHeight: heroLayout.implicitHeight + 36

    function batteryColor() {
        var pct = deviceData.batteryPercentage
        var threshold = (typeof deviceManager !== "undefined" && deviceManager && deviceManager.lowBatteryThreshold !== undefined)
                        ? deviceManager.lowBatteryThreshold
                        : 20
        if (deviceData.isCharging && pct < 0) return theme.positive
        if (pct > 50) return theme.positive
        if (pct > threshold) return theme.warning
        return theme.danger
    }

    RowLayout {
        id: heroLayout
        anchors.fill: parent
        anchors.margins: 18
        spacing: 16

        // Device Icon Tile
        Rectangle {
            width: 54
            height: 54
            radius: 14
            color: theme.bgControl
            border.color: theme.borderSubtle
            border.width: 1

            Kirigami.Icon {
                anchors.centerIn: parent
                width: 34
                height: 34
                source: {
                    if (root.deviceData.type === "mouse") return "input-mouse"
                    if (root.deviceData.type === "headset") return "audio-headset"
                    if (root.deviceData.type === "microphone") return "audio-input-microphone"
                    if (root.deviceData.type === "keyboard") return "input-keyboard"
                    return "input-gaming"
                }
            }
        }

        // Title & Vendor Metadata
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 5

            Text {
                text: root.deviceData.name || "Device"
                color: theme.textPrimary
                font.pixelSize: 19
                font.weight: Font.Bold
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            RowLayout {
                spacing: 8

                Text {
                    text: root.deviceData.vendor || "Hardware"
                    color: theme.textSecondary
                    font.pixelSize: 12
                    font.weight: Font.Medium
                }

                Rectangle {
                    width: 3
                    height: 3
                    radius: 2
                    color: theme.textMuted
                }

                Rectangle {
                    radius: theme.radiusXs
                    color: theme.bgControl
                    border.color: theme.borderSubtle
                    border.width: 1
                    implicitWidth: backendLbl.implicitWidth + 14
                    implicitHeight: 20

                    Text {
                        id: backendLbl
                        anchors.centerIn: parent
                        text: root.deviceData.backend || "system"
                        color: theme.textSecondary
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }
                }
            }
        }

        // Live Hardware Onboard Profile Pill
        Rectangle {
            visible: Boolean(root.deviceData.hasOnboardProfile)
            Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
            color: theme.accentSoft
            border.color: theme.accentBorder
            border.width: 1
            radius: theme.radiusPill
            implicitWidth: onboardRow.implicitWidth + 20
            implicitHeight: 32

            RowLayout {
                id: onboardRow
                anchors.centerIn: parent
                spacing: 6

                Rectangle {
                    width: 7
                    height: 7
                    radius: 4
                    color: theme.accent
                }

                Text {
                    text: "Onboard: " + (root.deviceData.onboardProfile || "")
                    color: theme.accent
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }

            QQC2.ToolTip.visible: onboardHover.containsMouse
            QQC2.ToolTip.text: "Active hardware on-board profile (updates live)"

            MouseArea {
                id: onboardHover
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }
        }

        // Microphone Live Status Pill
        Rectangle {
            visible: Boolean(root.deviceData.hasMicrophone)
            Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
            color: {
                if (root.deviceData.micMuted) return theme.dangerSoft
                if (root.deviceData.micMonitoring) return theme.positiveSoft
                if (root.deviceData.micEqEnabled) return theme.accentSoft
                return theme.bgControl
            }
            border.color: {
                if (root.deviceData.micMuted) return theme.dangerBorder
                if (root.deviceData.micMonitoring) return theme.positive
                if (root.deviceData.micEqEnabled) return theme.accentBorder
                return theme.borderSubtle
            }
            border.width: 1
            radius: theme.radiusPill
            implicitWidth: micStatusRow.implicitWidth + 20
            implicitHeight: 32

            RowLayout {
                id: micStatusRow
                anchors.centerIn: parent
                spacing: 6

                Rectangle {
                    width: 7
                    height: 7
                    radius: 4
                    color: {
                        if (root.deviceData.micMuted) return theme.danger
                        if (root.deviceData.micMonitoring) return theme.positive
                        if (root.deviceData.micEqEnabled) return theme.accent
                        return theme.textMuted
                    }
                }

                Text {
                    text: {
                        if (root.deviceData.micMuted) return "Muted"
                        if (root.deviceData.micMonitoring) return "Live Test"
                        if (root.deviceData.micEqEnabled) return "EQ Active"
                        return "EQ Bypassed"
                    }
                    color: {
                        if (root.deviceData.micMuted) return theme.danger
                        if (root.deviceData.micMonitoring) return theme.positive
                        if (root.deviceData.micEqEnabled) return theme.accent
                        return theme.textSecondary
                    }
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }
        }

        // Rich Battery Status Pill
        Rectangle {
            visible: Boolean(root.deviceData.hasBattery) && (root.deviceData.batteryPercentage >= 0 || root.deviceData.isCharging)
            Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
            radius: theme.radiusMd
            color: theme.bgControl
            border.color: theme.borderSubtle
            border.width: 1
            implicitWidth: Math.max(132, batteryCol.implicitWidth + 24)
            implicitHeight: batteryCol.implicitHeight + 16

            ColumnLayout {
                id: batteryCol
                anchors.centerIn: parent
                spacing: 5

                RowLayout {
                    Layout.alignment: Qt.AlignRight
                    spacing: 6

                    Kirigami.Icon {
                        source: root.deviceData.isCharging ? "battery-full-charging-symbolic" : "battery-full-symbolic"
                        Layout.preferredWidth: 15
                        Layout.preferredHeight: 15
                        isMask: true
                        color: root.batteryColor()
                    }

                    Text {
                        text: {
                            var pct = root.deviceData.batteryPercentage
                            if (root.deviceData.isCharging) {
                                return (pct >= 0) ? (pct + "% · Charging") : "Charging"
                            }
                            return (pct !== undefined ? pct : 0) + "%"
                        }
                        color: root.batteryColor()
                        font.pixelSize: 13
                        font.weight: Font.Bold
                    }
                }

                // Visual Battery Bar
                Rectangle {
                    visible: root.deviceData.batteryPercentage >= 0
                    Layout.fillWidth: true
                    Layout.minimumWidth: 100
                    height: 5
                    radius: 3
                    color: theme.borderSubtle

                    Rectangle {
                        width: parent.width * Math.max(0, Math.min(100, root.deviceData.batteryPercentage || 0)) / 100
                        height: parent.height
                        radius: 3
                        color: root.batteryColor()

                        Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                    }
                }

                Text {
                    visible: Boolean(root.deviceData.batteryTimeRemaining)
                    text: root.deviceData.batteryTimeRemaining || ""
                    color: theme.textSecondary
                    font.pixelSize: 11
                    Layout.alignment: Qt.AlignRight
                }
            }
        }
    }
}
