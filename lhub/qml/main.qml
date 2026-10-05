import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root

    title: "L-Hub - Peripheral Control Center"
    width: 860
    height: 640
    minimumWidth: 640
    minimumHeight: 480

    pageStack.initialPage: Kirigami.ScrollablePage {
        title: "My Devices"

        actions: [
            Kirigami.Action {
                text: "Refresh"
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
                text: "No compatible devices detected"
                explanation: "Make sure headsets are powered on and required services are running."
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

                    onButtonRemapRequested: function(btnIdx, btnName, curAct, curActDisp, defAct, btnLoc) {
                        remapDialog.targetDeviceId = modelData.id
                        remapDialog.targetButtonIndex = btnIdx
                        remapDialog.targetButtonName = btnName
                        remapDialog.currentAction = curAct || ""
                        remapDialog.currentActionDisplay = curActDisp || ""
                        remapDialog.defaultAction = defAct || ""
                        remapDialog.buttonLocation = btnLoc || ""
                        remapDialog.open()
                    }

                    onProfileSelected: function(pName) {
                        deviceManager.applyProfile(modelData.id, pName)
                        root.showPassiveNotification("Applying profile '" + pName + "'...")
                    }

                    onSaveProfileRequested: function(pName) {
                        deviceManager.saveProfile(modelData.id, pName)
                        root.showPassiveNotification("Profile '" + pName + "' saved.")
                    }

                    onNewProfileRequested: function() {
                        newProfileDialog.targetDeviceId = modelData.id
                        newProfileNameField.text = ""
                        newProfileDialog.open()
                    }

                    onDeleteProfileRequested: function(pName) {
                        deleteProfileDialog.targetDeviceId = modelData.id
                        deleteProfileDialog.targetProfileName = pName
                        deleteProfileDialog.open()
                    }

                    onResetDefaultRequested: function() {
                        resetConfirmDialog.targetDeviceId = modelData.id
                        resetConfirmDialog.targetDeviceName = modelData.name || "Device"
                        resetConfirmDialog.open()
                    }
                }
            }
        }
    }

    // Dialog for remapping buttons
    RemapDialog {
        id: remapDialog

        onRemapConfirmed: function(devId, btnIdx, action) {
            deviceManager.remapButton(devId, btnIdx, action)
            root.showPassiveNotification("Button remapped.")
        }
    }

    // Dialog for creating a new profile
    Kirigami.Dialog {
        id: newProfileDialog
        property string targetDeviceId: ""

        title: "Create New Profile"
        preferredWidth: Kirigami.Units.gridUnit * 22
        standardButtons: Kirigami.Dialog.Ok | Kirigami.Dialog.Cancel

        ColumnLayout {
            spacing: Kirigami.Units.mediumSpacing
            Layout.fillWidth: true

            QQC2.Label {
                text: "Enter a name for the new profile (e.g. 'Gaming' or 'Office'):"
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            QQC2.TextField {
                id: newProfileNameField
                Layout.fillWidth: true
                placeholderText: "Profile name..."
                onAccepted: {
                    if (text.trim().length > 0) {
                        newProfileDialog.accept()
                    }
                }
            }
        }

        onAccepted: {
            var name = newProfileNameField.text.trim()
            if (name) {
                deviceManager.saveProfile(targetDeviceId, name)
                root.showPassiveNotification("Profile '" + name + "' created.")
            }
        }
    }

    // Dialog for confirming profile deletion
    Kirigami.PromptDialog {
        id: deleteProfileDialog
        property string targetDeviceId: ""
        property string targetProfileName: ""

        title: "Delete Profile"
        subtitle: "Do you really want to delete profile '" + targetProfileName + "'?"
        standardButtons: Kirigami.Dialog.Cancel

        customFooterActions: [
            Kirigami.Action {
                text: "Delete Profile"
                icon.name: "edit-delete"
                onTriggered: {
                    deviceManager.deleteProfile(deleteProfileDialog.targetDeviceId, deleteProfileDialog.targetProfileName)
                    root.showPassiveNotification("Profile deleted.")
                    deleteProfileDialog.close()
                }
            }
        ]
    }

    // Dialog for confirming default reset
    Kirigami.PromptDialog {
        id: resetConfirmDialog
        property string targetDeviceId: ""
        property string targetDeviceName: ""

        title: "Reset to Default"
        subtitle: "Restore default button assignments and settings for " + targetDeviceName + "?"
        standardButtons: Kirigami.Dialog.Cancel

        customFooterActions: [
            Kirigami.Action {
                text: "Reset to Default"
                icon.name: "document-revert"
                onTriggered: {
                    deviceManager.resetDeviceToDefault(resetConfirmDialog.targetDeviceId)
                    root.showPassiveNotification("Default settings restored.")
                    resetConfirmDialog.close()
                }
            }
        ]
    }
}

