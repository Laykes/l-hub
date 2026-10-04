import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.Card {
    id: root

    property var deviceData: ({})
    signal dpiSelected(int dpi)
    signal sidetoneChanged(int level)
    signal buttonRemapRequested(int buttonIdx)

    header: RowLayout {
        spacing: Kirigami.Units.mediumSpacing

        Kirigami.Icon {
            source: {
                if (deviceData.type === "mouse") return "input-mouse"
                if (deviceData.type === "headset") return "audio-headset"
                if (deviceData.type === "keyboard") return "input-keyboard"
                return "input-gaming"
            }
            Layout.preferredWidth: Kirigami.Units.iconSizes.large
            Layout.preferredHeight: Kirigami.Units.iconSizes.large
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2

            QQC2.Label {
                text: deviceData.name || "Gerät"
                font.bold: true
                font.pointSize: Kirigami.Theme.defaultFont.pointSize + 2
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            QQC2.Label {
                text: (deviceData.vendor || "Hardware") + " • über " + (deviceData.backend || "System")
                opacity: 0.7
                font.pointSize: Kirigami.Theme.smallFont.pointSize
            }
        }

        // Battery indicator
        ColumnLayout {
            visible: Boolean(deviceData.hasBattery) && (deviceData.batteryPercentage >= 0)
            Layout.alignment: Qt.AlignRight
            spacing: 2

            RowLayout {
                spacing: Kirigami.Units.smallSpacing
                Layout.alignment: Qt.AlignRight

                Kirigami.Icon {
                    source: deviceData.isCharging ? "battery-charging" : "battery"
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                }

                QQC2.Label {
                    text: (deviceData.isCharging ? "⚡ " : "🔋 ") + deviceData.batteryPercentage + "%"
                    font.bold: true
                    color: {
                        if (deviceData.batteryPercentage > 50) return Kirigami.Theme.positiveTextColor
                        if (deviceData.batteryPercentage > 20) return Kirigami.Theme.neutralTextColor
                        return Kirigami.Theme.negativeTextColor
                    }
                }
            }

            QQC2.Label {
                visible: Boolean(deviceData.batteryTimeRemaining)
                text: deviceData.batteryTimeRemaining || ""
                opacity: 0.8
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                Layout.alignment: Qt.AlignRight
            }
        }
    }

    contentItem: ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        // Status note (e.g. disabled profile)
        Kirigami.InlineMessage {
            visible: Boolean(deviceData.statusNote)
            type: Kirigami.MessageType.Information
            text: deviceData.statusNote || ""
            Layout.fillWidth: true
        }

        // DPI Section
        ColumnLayout {
            visible: Boolean(deviceData.hasDpi) && !deviceData.isDpiDisabled
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                text: "DPI-Auflösung (Aktuell: " + (deviceData.currentDpi || 800) + " DPI)"
                font.bold: true
            }

            RowLayout {
                spacing: Kirigami.Units.smallSpacing
                Repeater {
                    model: deviceData.dpiSteps || [400, 800, 1600, 3200]
                    QQC2.Button {
                        text: modelData + " DPI"
                        checkable: true
                        checked: modelData === deviceData.currentDpi
                        onClicked: root.dpiSelected(modelData)
                    }
                }
            }
        }

        // Sidetone Section (Headset)
        ColumnLayout {
            visible: Boolean(deviceData.hasSidetone)
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            RowLayout {
                Layout.fillWidth: true
                QQC2.Label {
                    text: "Mithörton (Sidetone): " + Math.round(sidetoneSlider.value * 100 / 128) + "%"
                    font.bold: true
                    Layout.fillWidth: true
                }
            }

            QQC2.Slider {
                id: sidetoneSlider
                Layout.fillWidth: true
                from: 0
                to: 128
                stepSize: 1
                value: deviceData.sidetone || 0
                onMoved: root.sidetoneChanged(Math.round(value))
            }
        }


        // Buttons Section
        ColumnLayout {
            visible: Boolean(deviceData.hasButtons) && Boolean(deviceData.buttons) && (deviceData.buttons.length > 0)
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                text: "Tastenbelegung (" + (deviceData.buttons ? deviceData.buttons.length : 0) + " Tasten)"
                font.bold: true
            }

            Flow {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: deviceData.buttons || []
                    QQC2.Button {
                        text: modelData.name + (modelData.action ? ": " + modelData.action : "")
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                        onClicked: root.buttonRemapRequested(modelData.index)
                    }
                }
            }
        }
    }
}
