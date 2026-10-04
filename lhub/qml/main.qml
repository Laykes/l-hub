import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root

    title: "L-Hub - Peripherie-Zentrale"
    width: 860
    height: 640
    minimumWidth: 640
    minimumHeight: 480

    pageStack.initialPage: Kirigami.ScrollablePage {
        title: "Meine Geräte"

        actions: [
            Kirigami.Action {
                text: "Aktualisieren"
                icon.name: "view-refresh"
                onTriggered: deviceManager.refresh_devices()
            }
        ]

        ColumnLayout {
            spacing: Kirigami.Units.largeSpacing
            Layout.fillWidth: true

            // Missing Backends Warning Banner
            Repeater {
                model: deviceManager.missingBackends
                Kirigami.InlineMessage {
                    Layout.fillWidth: true
                    type: Kirigami.MessageType.Warning
                    visible: true
                    text: modelData
                }
            }

            // No devices placeholder
            Kirigami.PlaceholderMessage {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignHCenter
                visible: deviceManager.devices.length === 0
                icon.name: "input-gaming"
                text: "Keine kompatiblen Geräte erkannt"
                explanation: "Stelle sicher, dass Headsets eingeschaltet und die nötigen Dienste aktiv sind."
            }

            // Cards for connected devices
            Repeater {
                model: deviceManager.devices

                DeviceCard {
                    Layout.fillWidth: true
                    deviceData: modelData

                    onDpiSelected: function(dpi) {
                        deviceManager.setDpi(modelData.id, dpi)
                    }

                    onSidetoneChanged: function(level) {
                        deviceManager.setSidetone(modelData.id, level)
                    }

                    onButtonRemapRequested: function(btnIdx) {
                        remapDialog.targetDeviceId = modelData.id
                        remapDialog.targetButtonIndex = btnIdx
                        remapDialog.open()
                    }
                }
            }
        }
    }

    // Dialog for remapping buttons
    Kirigami.PromptDialog {
        id: remapDialog
        property string targetDeviceId: ""
        property int targetButtonIndex: 0

        title: "Taste umbelegen"
        subtitle: "Wähle eine Standardfunktion für Taste " + (targetButtonIndex + 1)

        standardButtons: Kirigami.Dialog.Cancel

        customFooterActions: [
            Kirigami.Action {
                text: "Linksklick (1)"
                onTriggered: {
                    deviceManager.remapButton(remapDialog.targetDeviceId, remapDialog.targetButtonIndex, "button 1")
                    remapDialog.close()
                }
            },
            Kirigami.Action {
                text: "Rechtsklick (2)"
                onTriggered: {
                    deviceManager.remapButton(remapDialog.targetDeviceId, remapDialog.targetButtonIndex, "button 2")
                    remapDialog.close()
                }
            },
            Kirigami.Action {
                text: "Mittelklick (3)"
                onTriggered: {
                    deviceManager.remapButton(remapDialog.targetDeviceId, remapDialog.targetButtonIndex, "button 3")
                    remapDialog.close()
                }
            },
            Kirigami.Action {
                text: "Vorwärts (4)"
                onTriggered: {
                    deviceManager.remapButton(remapDialog.targetDeviceId, remapDialog.targetButtonIndex, "button 4")
                    remapDialog.close()
                }
            },
            Kirigami.Action {
                text: "Zurück (5)"
                onTriggered: {
                    deviceManager.remapButton(remapDialog.targetDeviceId, remapDialog.targetButtonIndex, "button 5")
                    remapDialog.close()
                }
            }
        ]
    }
}
