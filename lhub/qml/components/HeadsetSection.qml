import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property var deviceData: ({})

    signal sidetoneChanged(int level)

    readonly property Theme theme: Theme {}

    visible: Boolean(root.deviceData.hasSidetone)
    radius: theme.radiusLg
    color: theme.bgSurface
    border.color: theme.borderSubtle
    border.width: 1
    implicitHeight: sidetoneLayout.implicitHeight + 36

    ColumnLayout {
        id: sidetoneLayout
        anchors.fill: parent
        anchors.margins: 18
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
            value: root.deviceData.sidetone || 0
            onMoved: root.sidetoneChanged(Math.round(value))

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
}
