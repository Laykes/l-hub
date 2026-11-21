import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property var deviceData: ({})

    signal dpiSelected(int dpi)

    readonly property Theme theme: Theme {}

    visible: Boolean(root.deviceData.hasDpi) && !root.deviceData.isDpiDisabled
    radius: theme.radiusLg
    color: theme.bgSurface
    border.color: theme.borderSubtle
    border.width: 1
    implicitHeight: dpiLayout.implicitHeight + 36

    ColumnLayout {
        id: dpiLayout
        anchors.fill: parent
        anchors.margins: 18
        spacing: 14

        RowLayout {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Text {
                    text: "DPI Sensitivity"
                    color: theme.textPrimary
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }

                Text {
                    text: "Select active hardware resolution step"
                    color: theme.textSecondary
                    font.pixelSize: 12
                    Layout.fillWidth: true
                }
            }

            Item { Layout.fillWidth: true }

            Rectangle {
                radius: theme.radiusPill
                color: theme.accentSoft
                border.color: theme.accentBorder
                border.width: 1
                implicitWidth: activeDpiLbl.implicitWidth + 22
                implicitHeight: 30

                Text {
                    id: activeDpiLbl
                    anchors.centerIn: parent
                    text: (root.deviceData.currentDpi || 800) + " DPI"
                    color: theme.accent
                    font.pixelSize: 13
                    font.weight: Font.Bold
                }
            }
        }

        QQC2.ButtonGroup {
            id: dpiGroup
        }

        Flow {
            Layout.fillWidth: true
            spacing: 8

            Repeater {
                model: root.deviceData.dpiSteps || [400, 800, 1600, 3200]

                UiButton {
                    text: modelData + " DPI"
                    checkable: true
                    checked: modelData === (root.deviceData.currentDpi || 800)
                    QQC2.ButtonGroup.group: dpiGroup

                    Binding on checked {
                        value: modelData === (root.deviceData.currentDpi || 800)
                    }

                    onClicked: {
                        if (root.deviceData.currentDpi !== modelData) {
                            root.dpiSelected(modelData)
                        }
                    }
                }
            }
        }
    }
}
