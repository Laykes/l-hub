import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property var deviceData: ({})
    property string _lastDeviceId: ""

    signal sidetoneChanged(int level)
    signal inactiveTimeChanged(int minutes)

    readonly property Theme theme: Theme {}
    readonly property bool hasSidetone: Boolean(root.deviceData.hasSidetone)
    readonly property bool hasInactiveTime: Boolean(root.deviceData.hasInactiveTime)

    visible: root.hasSidetone || root.hasInactiveTime
    radius: theme.radiusLg
    color: theme.bgSurface
    border.color: theme.borderSubtle
    border.width: 1
    implicitHeight: headsetLayout.implicitHeight + 36

    onDeviceDataChanged: {
        var nextId = root.deviceData && root.deviceData.id ? String(root.deviceData.id) : ""
        if (nextId !== root._lastDeviceId) {
            sidetoneDebounce.stop()
            inactiveDebounce.stop()
            root._lastDeviceId = nextId
        }
    }

    Timer {
        id: sidetoneDebounce
        interval: 120
        repeat: false
        onTriggered: root.sidetoneChanged(Math.round(sidetoneSlider.value))
    }

    Timer {
        id: inactiveDebounce
        interval: 120
        repeat: false
        onTriggered: root.inactiveTimeChanged(Math.round(inactiveSlider.value))
    }

    ColumnLayout {
        id: headsetLayout
        anchors.fill: parent
        anchors.margins: 18
        spacing: 16

        // 1. Microphone Sidetone
        ColumnLayout {
            visible: root.hasSidetone
            Layout.fillWidth: true
            spacing: 12

            RowLayout {
                Layout.fillWidth: true

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        text: "Microphone Sidetone"
                        color: theme.textPrimary
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }

                    Text {
                        text: "Plays your voice back through the headset so you can hear yourself speak."
                        color: theme.textSecondary
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }

                Rectangle {
                    radius: theme.radiusPill
                    color: sidetoneSlider.value > 0 ? theme.accentSoft : theme.bgControl
                    border.color: sidetoneSlider.value > 0 ? theme.accentBorder : theme.borderSubtle
                    border.width: 1
                    implicitWidth: sidetoneValLbl.implicitWidth + 22
                    implicitHeight: 30

                    Text {
                        id: sidetoneValLbl
                        anchors.centerIn: parent
                        text: Math.round(sidetoneSlider.value * 100 / 128) + "%"
                        color: sidetoneSlider.value > 0 ? theme.accent : theme.textSecondary
                        font.pixelSize: 13
                        font.weight: Font.Bold
                    }
                }
            }

            // Custom sleek dark slider (no cluttered tick marks)
            QQC2.Slider {
                id: sidetoneSlider
                Layout.fillWidth: true
                implicitHeight: 28
                from: 0
                to: 128
                stepSize: 1

                Binding {
                    target: sidetoneSlider
                    property: "value"
                    value: root.deviceData.sidetone !== undefined ? root.deviceData.sidetone : 0
                    when: !sidetoneSlider.pressed && !sidetoneDebounce.running
                }

                onMoved: {
                    if (pressed) {
                        sidetoneDebounce.restart()
                    } else {
                        sidetoneDebounce.stop()
                        root.sidetoneChanged(Math.round(value))
                    }
                }

                onPressedChanged: {
                    if (!pressed && sidetoneDebounce.running) {
                        sidetoneDebounce.stop()
                        root.sidetoneChanged(Math.round(value))
                    }
                }

                background: Rectangle {
                    x: sidetoneSlider.leftPadding
                    y: sidetoneSlider.topPadding + sidetoneSlider.availableHeight / 2 - height / 2
                    width: sidetoneSlider.availableWidth
                    height: 6
                    radius: 3
                    color: theme.bgControl
                    border.color: theme.borderSubtle
                    border.width: 1

                    Rectangle {
                        width: sidetoneSlider.visualPosition * parent.width
                        height: parent.height
                        radius: 3
                        color: theme.accent
                    }
                }

                handle: Rectangle {
                    x: sidetoneSlider.leftPadding + sidetoneSlider.visualPosition * (sidetoneSlider.availableWidth - width)
                    y: sidetoneSlider.topPadding + sidetoneSlider.availableHeight / 2 - height / 2
                    width: 18
                    height: 18
                    radius: 9
                    color: sidetoneSlider.pressed ? theme.accentHover : theme.textPrimary
                    border.color: theme.accent
                    border.width: sidetoneSlider.hovered || sidetoneSlider.pressed ? 3 : 2

                    Behavior on border.width { NumberAnimation { duration: 100 } }
                }
            }

            RowLayout {
                Layout.fillWidth: true

                Text {
                    text: "Off"
                    color: theme.textMuted
                    font.pixelSize: 11
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: "50%"
                    color: theme.textMuted
                    font.pixelSize: 11
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: "Max"
                    color: theme.textMuted
                    font.pixelSize: 11
                }
            }
        }

        // Hairline Divider when both controls are visible
        Rectangle {
            visible: root.hasSidetone && root.hasInactiveTime
            Layout.fillWidth: true
            height: 1
            color: theme.borderSubtle
        }

        // 2. Auto Shut-Off (Inactive Time)
        ColumnLayout {
            visible: root.hasInactiveTime
            Layout.fillWidth: true
            spacing: 12

            RowLayout {
                Layout.fillWidth: true

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        text: "Auto Shut-Off"
                        color: theme.textPrimary
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }

                    Text {
                        text: "Automatically powers off the headset after inactivity to save battery."
                        color: theme.textSecondary
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }

                Rectangle {
                    radius: theme.radiusPill
                    color: Math.round(inactiveSlider.value) > 0 ? theme.accentSoft : theme.bgControl
                    border.color: Math.round(inactiveSlider.value) > 0 ? theme.accentBorder : theme.borderSubtle
                    border.width: 1
                    implicitWidth: inactiveValLbl.implicitWidth + 22
                    implicitHeight: 30

                    Text {
                        id: inactiveValLbl
                        anchors.centerIn: parent
                        text: Math.round(inactiveSlider.value) === 0 ? "Off" : Math.round(inactiveSlider.value) + " min"
                        color: Math.round(inactiveSlider.value) > 0 ? theme.accent : theme.textSecondary
                        font.pixelSize: 13
                        font.weight: Font.Bold
                    }
                }
            }

            QQC2.Slider {
                id: inactiveSlider
                Layout.fillWidth: true
                implicitHeight: 28
                from: 0
                to: 90
                stepSize: 1

                Binding {
                    target: inactiveSlider
                    property: "value"
                    value: root.deviceData.inactiveTime !== undefined ? root.deviceData.inactiveTime : 15
                    when: !inactiveSlider.pressed && !inactiveDebounce.running
                }

                onMoved: {
                    if (pressed) {
                        inactiveDebounce.restart()
                    } else {
                        inactiveDebounce.stop()
                        root.inactiveTimeChanged(Math.round(value))
                    }
                }

                onPressedChanged: {
                    if (!pressed && inactiveDebounce.running) {
                        inactiveDebounce.stop()
                        root.inactiveTimeChanged(Math.round(value))
                    }
                }

                background: Rectangle {
                    x: inactiveSlider.leftPadding
                    y: inactiveSlider.topPadding + inactiveSlider.availableHeight / 2 - height / 2
                    width: inactiveSlider.availableWidth
                    height: 6
                    radius: 3
                    color: theme.bgControl
                    border.color: theme.borderSubtle
                    border.width: 1

                    Rectangle {
                        width: inactiveSlider.visualPosition * parent.width
                        height: parent.height
                        radius: 3
                        color: theme.accent
                    }
                }

                handle: Rectangle {
                    x: inactiveSlider.leftPadding + inactiveSlider.visualPosition * (inactiveSlider.availableWidth - width)
                    y: inactiveSlider.topPadding + inactiveSlider.availableHeight / 2 - height / 2
                    width: 18
                    height: 18
                    radius: 9
                    color: inactiveSlider.pressed ? theme.accentHover : theme.textPrimary
                    border.color: theme.accent
                    border.width: inactiveSlider.hovered || inactiveSlider.pressed ? 3 : 2

                    Behavior on border.width { NumberAnimation { duration: 100 } }
                }
            }

            RowLayout {
                Layout.fillWidth: true

                Text {
                    text: "Off"
                    color: theme.textMuted
                    font.pixelSize: 11
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: "45 min"
                    color: theme.textMuted
                    font.pixelSize: 11
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: "90 min"
                    color: theme.textMuted
                    font.pixelSize: 11
                }
            }

            Flow {
                Layout.fillWidth: true
                spacing: 8

                Repeater {
                    model: [0, 5, 10, 15, 30, 60]

                    UiButton {
                        text: modelData === 0 ? "Off" : modelData + " min"
                        checkable: true

                        Binding on checked {
                            value: Math.round(inactiveSlider.value) === modelData
                        }

                        onClicked: {
                            inactiveDebounce.stop()
                            inactiveSlider.value = modelData
                            root.inactiveTimeChanged(modelData)
                        }
                    }
                }
            }
        }
    }
}
