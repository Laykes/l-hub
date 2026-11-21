import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

QQC2.Popup {
    id: root

    property bool draftAutostart: false
    property bool draftStartMinimized: false
    property int draftLowBatteryThreshold: 20
    property bool draftNotifyLowBattery: true
    property bool draftNotifyProfileChange: true
    property int draftPollIntervalSec: 30

    signal settingsSaved()

    readonly property Theme theme: Theme {}
    readonly property bool hasDeviceManager: typeof deviceManager !== "undefined" && deviceManager !== null

    anchors.centerIn: QQC2.Overlay.overlay
    width: Math.min(parent ? parent.width - 48 : 540, 540)
    height: Math.min(parent ? parent.height - 48 : 580, 580)
    modal: true
    focus: true
    closePolicy: QQC2.Popup.CloseOnEscape | QQC2.Popup.CloseOnPressOutside
    padding: 0

    QQC2.Overlay.modal: Rectangle {
        color: "#b005080d"
    }

    background: Rectangle {
        radius: theme.radiusLg
        color: theme.bgDialog
        border.color: theme.borderStrong
        border.width: 1
    }

    component SettingToggle: QQC2.AbstractButton {
        id: toggleCtrl
        property bool active: false
        readonly property Theme theme: Theme {}

        implicitWidth: 44
        implicitHeight: 24
        hoverEnabled: true
        checkable: false

        background: Item {}

        contentItem: Rectangle {
            radius: 12
            color: toggleCtrl.active
                   ? (toggleCtrl.hovered ? toggleCtrl.theme.accentHover : toggleCtrl.theme.accent)
                   : (toggleCtrl.hovered ? toggleCtrl.theme.bgSurfaceHover : toggleCtrl.theme.bgControl)
            border.width: 1
            border.color: toggleCtrl.active
                          ? "transparent"
                          : (toggleCtrl.hovered ? toggleCtrl.theme.borderHover : toggleCtrl.theme.borderStrong)

            Behavior on color { ColorAnimation { duration: 120 } }

            Rectangle {
                width: 18
                height: 18
                radius: 9
                y: 3
                x: toggleCtrl.active ? parent.width - width - 3 : 3
                color: toggleCtrl.active ? toggleCtrl.theme.accentText : toggleCtrl.theme.textPrimary

                Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
            }
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.NoButton
            cursorShape: toggleCtrl.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        }
    }

    component SettingSlider: QQC2.Slider {
        id: sliderCtrl
        readonly property Theme theme: Theme {}

        implicitHeight: 28

        background: Rectangle {
            x: sliderCtrl.leftPadding
            y: sliderCtrl.topPadding + sliderCtrl.availableHeight / 2 - height / 2
            width: sliderCtrl.availableWidth
            height: 6
            radius: 3
            color: sliderCtrl.theme.bgControl
            border.color: sliderCtrl.theme.borderSubtle
            border.width: 1

            Rectangle {
                width: sliderCtrl.visualPosition * parent.width
                height: parent.height
                radius: 3
                color: sliderCtrl.theme.accent
            }
        }

        handle: Rectangle {
            x: sliderCtrl.leftPadding + sliderCtrl.visualPosition * (sliderCtrl.availableWidth - width)
            y: sliderCtrl.topPadding + sliderCtrl.availableHeight / 2 - height / 2
            width: 18
            height: 18
            radius: 9
            color: sliderCtrl.pressed ? sliderCtrl.theme.accentHover : sliderCtrl.theme.textPrimary
            border.color: sliderCtrl.theme.accent
            border.width: sliderCtrl.hovered || sliderCtrl.pressed ? 3 : 2

            Behavior on border.width { NumberAnimation { duration: 100 } }
        }
    }

    function syncSliders() {
        batteryThresholdSlider.value = draftLowBatteryThreshold
        pollIntervalSlider.value = draftPollIntervalSec
    }

    function loadFromManager() {
        if (hasDeviceManager) {
            draftAutostart = Boolean(deviceManager.autostart)
            draftStartMinimized = Boolean(deviceManager.startMinimized)
            draftLowBatteryThreshold = deviceManager.lowBatteryThreshold !== undefined ? deviceManager.lowBatteryThreshold : 20
            draftNotifyLowBattery = deviceManager.notifyLowBattery !== undefined ? Boolean(deviceManager.notifyLowBattery) : true
            draftNotifyProfileChange = deviceManager.notifyProfileChange !== undefined ? Boolean(deviceManager.notifyProfileChange) : true
            draftPollIntervalSec = deviceManager.pollIntervalSec !== undefined ? deviceManager.pollIntervalSec : 30
        } else {
            draftAutostart = false
            draftStartMinimized = false
            draftLowBatteryThreshold = 20
            draftNotifyLowBattery = true
            draftNotifyProfileChange = true
            draftPollIntervalSec = 30
        }
        syncSliders()
    }

    function restoreDefaults() {
        draftAutostart = false
        draftStartMinimized = false
        draftLowBatteryThreshold = 20
        draftNotifyLowBattery = true
        draftNotifyProfileChange = true
        draftPollIntervalSec = 30
        syncSliders()
    }

    function saveSettings() {
        if (hasDeviceManager) {
            deviceManager.updateSettings({
                autostart: draftAutostart,
                startMinimized: draftStartMinimized,
                lowBatteryThreshold: draftLowBatteryThreshold,
                notifyLowBattery: draftNotifyLowBattery,
                notifyProfileChange: draftNotifyProfileChange,
                pollIntervalSec: draftPollIntervalSec
            })
        }
        settingsSaved()
        root.close()
    }

    onOpened: loadFromManager()

    contentItem: ColumnLayout {
        spacing: 0

        // Top Header Bar
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: headerRow.implicitHeight + 28
            color: theme.bgSurface
            radius: theme.radiusLg

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: theme.radiusLg
                color: theme.bgSurface
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: theme.borderSubtle
            }

            RowLayout {
                id: headerRow
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12

                Rectangle {
                    width: 40
                    height: 40
                    radius: 12
                    color: theme.accentSoft
                    border.color: theme.accentBorder
                    border.width: 1

                    Kirigami.Icon {
                        anchors.centerIn: parent
                        source: "preferences-system-symbolic"
                        width: 20
                        height: 20
                        isMask: true
                        color: theme.accent
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        text: "Application Settings"
                        color: theme.textPrimary
                        font.pixelSize: 16
                        font.weight: Font.Bold
                    }

                    Text {
                        text: "Startup, desktop notifications, and polling"
                        color: theme.textSecondary
                        font.pixelSize: 12
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }

                UiButton {
                    variant: "subtle"
                    compact: true
                    iconName: "window-close-symbolic"
                    toolTipText: "Close"
                    onClicked: root.close()
                }
            }
        }

        // Scrollable Settings Body
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: bodyCol.implicitHeight + 36
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            QQC2.ScrollBar.vertical: QQC2.ScrollBar {
                policy: QQC2.ScrollBar.AsNeeded
                width: 8
                contentItem: Rectangle {
                    implicitWidth: 6
                    radius: 3
                    color: parent.pressed ? theme.borderStrong : theme.borderHover
                    opacity: parent.active ? 0.9 : 0.35
                }
                background: Item {}
            }

            ColumnLayout {
                id: bodyCol
                x: 18
                y: 18
                width: parent.width - 36
                spacing: 14

                // Section 1: Startup & System Tray
                Rectangle {
                    Layout.fillWidth: true
                    radius: theme.radiusMd
                    color: theme.bgSurface
                    border.color: theme.borderSubtle
                    border.width: 1
                    implicitHeight: startupCol.implicitHeight + 28

                    ColumnLayout {
                        id: startupCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 14
                        spacing: 12

                        Text {
                            text: "STARTUP & SYSTEM TRAY"
                            color: theme.textMuted
                            font.pixelSize: 11
                            font.weight: Font.Bold
                            font.letterSpacing: 0.8
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    text: "Start at Login"
                                    color: theme.textPrimary
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                }

                                Text {
                                    text: "Manage ~/.config/autostart/io.github.lhub.LHub.desktop automatically."
                                    color: theme.textSecondary
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }

                            SettingToggle {
                                active: root.draftAutostart
                                onClicked: root.draftAutostart = !root.draftAutostart
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            height: 1
                            color: theme.borderSubtle
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    text: "Start Minimized to Tray"
                                    color: theme.textPrimary
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                }

                                Text {
                                    text: "Passes --minimized to autostart so L-Hub starts hidden in the system tray."
                                    color: theme.textSecondary
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }

                            SettingToggle {
                                active: root.draftStartMinimized
                                onClicked: root.draftStartMinimized = !root.draftStartMinimized
                            }
                        }
                    }
                }

                // Section 2: Notifications
                Rectangle {
                    Layout.fillWidth: true
                    radius: theme.radiusMd
                    color: theme.bgSurface
                    border.color: theme.borderSubtle
                    border.width: 1
                    implicitHeight: notifyCol.implicitHeight + 28

                    ColumnLayout {
                        id: notifyCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 14
                        spacing: 12

                        Text {
                            text: "NOTIFICATIONS"
                            color: theme.textMuted
                            font.pixelSize: 11
                            font.weight: Font.Bold
                            font.letterSpacing: 0.8
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    text: "Low Battery Alerts"
                                    color: theme.textPrimary
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                }

                                Text {
                                    text: "Show a notification when a wireless device battery reaches the threshold."
                                    color: theme.textSecondary
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }

                            SettingToggle {
                                active: root.draftNotifyLowBattery
                                onClicked: root.draftNotifyLowBattery = !root.draftNotifyLowBattery
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            height: 1
                            color: theme.borderSubtle
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        text: "Low Battery Threshold"
                                        color: theme.textPrimary
                                        font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                    }

                                    Text {
                                        text: "Warning trigger level when discharging (5%–50%)."
                                        color: theme.textSecondary
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }
                                }

                                Rectangle {
                                    radius: theme.radiusPill
                                    color: theme.accentSoft
                                    border.color: theme.accentBorder
                                    border.width: 1
                                    implicitWidth: thresholdValLbl.implicitWidth + 20
                                    implicitHeight: 28

                                    Text {
                                        id: thresholdValLbl
                                        anchors.centerIn: parent
                                        text: root.draftLowBatteryThreshold + "%"
                                        color: theme.accent
                                        font.pixelSize: 12
                                        font.weight: Font.Bold
                                    }
                                }
                            }

                            SettingSlider {
                                id: batteryThresholdSlider
                                Layout.fillWidth: true
                                from: 5
                                to: 50
                                stepSize: 1
                                snapMode: QQC2.Slider.SnapAlways
                                onMoved: root.draftLowBatteryThreshold = Math.round(value)
                            }

                            RowLayout {
                                Layout.fillWidth: true

                                Text {
                                    text: "5%"
                                    color: theme.textMuted
                                    font.pixelSize: 11
                                }
                                Item { Layout.fillWidth: true }
                                Text {
                                    text: "25%"
                                    color: theme.textMuted
                                    font.pixelSize: 11
                                }
                                Item { Layout.fillWidth: true }
                                Text {
                                    text: "50%"
                                    color: theme.textMuted
                                    font.pixelSize: 11
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            height: 1
                            color: theme.borderSubtle
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    text: "On-Board Profile Changes"
                                    color: theme.textPrimary
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                }

                                Text {
                                    text: "Notify when switching profiles directly via a hardware mouse button."
                                    color: theme.textSecondary
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }

                            SettingToggle {
                                active: root.draftNotifyProfileChange
                                onClicked: root.draftNotifyProfileChange = !root.draftNotifyProfileChange
                            }
                        }
                    }
                }

                // Section 3: Background Polling
                Rectangle {
                    Layout.fillWidth: true
                    radius: theme.radiusMd
                    color: theme.bgSurface
                    border.color: theme.borderSubtle
                    border.width: 1
                    implicitHeight: pollCol.implicitHeight + 28

                    ColumnLayout {
                        id: pollCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 14
                        spacing: 10

                        Text {
                            text: "BACKGROUND POLLING"
                            color: theme.textMuted
                            font.pixelSize: 11
                            font.weight: Font.Bold
                            font.letterSpacing: 0.8
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    text: "Device Refresh Interval"
                                    color: theme.textPrimary
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                }

                                Text {
                                    text: "How often L-Hub polls battery and device state in the background (10–120 s)."
                                    color: theme.textSecondary
                                    font.pixelSize: 12
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }

                            Rectangle {
                                radius: theme.radiusPill
                                color: theme.accentSoft
                                border.color: theme.accentBorder
                                border.width: 1
                                implicitWidth: pollValLbl.implicitWidth + 20
                                implicitHeight: 28

                                Text {
                                    id: pollValLbl
                                    anchors.centerIn: parent
                                    text: root.draftPollIntervalSec + " s"
                                    color: theme.accent
                                    font.pixelSize: 12
                                    font.weight: Font.Bold
                                }
                            }
                        }

                        SettingSlider {
                            id: pollIntervalSlider
                            Layout.fillWidth: true
                            from: 10
                            to: 120
                            stepSize: 1
                            snapMode: QQC2.Slider.SnapAlways
                            onMoved: root.draftPollIntervalSec = Math.round(value)
                        }

                        RowLayout {
                            Layout.fillWidth: true

                            Text {
                                text: "10 s"
                                color: theme.textMuted
                                font.pixelSize: 11
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: "60 s"
                                color: theme.textMuted
                                font.pixelSize: 11
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: "120 s"
                                color: theme.textMuted
                                font.pixelSize: 11
                            }
                        }
                    }
                }
            }
        }

        // Bottom Action Footer
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: footerRow.implicitHeight + 24
            color: theme.bgSurface
            radius: theme.radiusLg

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: theme.radiusLg
                color: theme.bgSurface
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: theme.borderSubtle
            }

            RowLayout {
                id: footerRow
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8

                UiButton {
                    compact: true
                    text: "Restore Defaults"
                    iconName: "edit-undo-symbolic"
                    onClicked: root.restoreDefaults()
                }

                Item { Layout.fillWidth: true }

                UiButton {
                    text: "Cancel"
                    onClicked: root.close()
                }

                UiButton {
                    variant: "primary"
                    text: "Save"
                    onClicked: root.saveSettings()
                }
            }
        }
    }
}
