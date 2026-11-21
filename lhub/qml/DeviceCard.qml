import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import "components"

ColumnLayout {
    id: root

    property var deviceData: ({})
    property alias buttonFilterGroup: buttonGrid.buttonFilterGroup

    signal dpiSelected(int dpi)
    signal sidetoneChanged(int level)
    signal inactiveTimeChanged(int minutes)
    signal micVolumeChanged(int volume)
    signal micMutedToggled(bool muted)
    signal micEqEnabledToggled(bool enabled)
    signal micHighpassChanged(bool enabled, int freq)
    signal micEqBandChanged(string bandId, real gain)
    signal micPresetSelected(string presetName)
    signal micMonitoringToggled(bool enabled)
    signal micDefaultSourceRequested(bool useEqSource)
    signal buttonRemapRequested(int buttonIdx, string buttonName, string currentAction, string currentActionDisplay, string defaultAction, string buttonLocation)
    signal profileSelected(string profileName)
    signal saveProfileRequested(string profileName)
    signal newProfileRequested()
    signal deleteProfileRequested(string profileName)
    signal resetDefaultRequested()

    readonly property Theme theme: Theme {}
    readonly property bool hasDeviceManager: typeof deviceManager !== "undefined" && deviceManager !== null

    spacing: 16

    // 1. Hero Header Card
    BatteryHeader {
        Layout.fillWidth: true
        deviceData: root.deviceData
    }

    // Status Note Banner (e.g. disabled profile info)
    Rectangle {
        visible: Boolean(root.deviceData.statusNote)
        Layout.fillWidth: true
        radius: theme.radiusMd
        color: theme.accentSoft
        border.color: theme.accentBorder
        border.width: 1
        implicitHeight: noteRow.implicitHeight + 22

        RowLayout {
            id: noteRow
            anchors.fill: parent
            anchors.margins: 11
            spacing: 10

            Kirigami.Icon {
                source: "dialog-information"
                Layout.preferredWidth: 18
                Layout.preferredHeight: 18
                isMask: true
                color: theme.accent
            }

            Text {
                text: root.deviceData.statusNote || ""
                color: theme.textPrimary
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
    }

    // 2. DPI Sensitivity Panel
    DpiSection {
        Layout.fillWidth: true
        deviceData: root.deviceData
        onDpiSelected: function(dpi) {
            root.dpiSelected(dpi)
        }
    }

    // 3. Headset Controls Panel (Sidetone & Auto Shut-Off)
    HeadsetSection {
        Layout.fillWidth: true
        deviceData: root.deviceData
        onSidetoneChanged: function(level) {
            root.sidetoneChanged(level)
        }
        onInactiveTimeChanged: function(minutes) {
            root.inactiveTimeChanged(minutes)
        }
    }

    // 3b. USB Microphone Controls, Equalizer & Live Voice Test
    MicrophoneSection {
        Layout.fillWidth: true
        deviceData: root.deviceData
        onVolumeChanged: function(volume) {
            root.micVolumeChanged(volume)
        }
        onMutedToggled: function(muted) {
            root.micMutedToggled(muted)
        }
        onEqEnabledToggled: function(enabled) {
            root.micEqEnabledToggled(enabled)
        }
        onHighpassChanged: function(enabled, freq) {
            root.micHighpassChanged(enabled, freq)
        }
        onEqBandChanged: function(bandId, gain) {
            root.micEqBandChanged(bandId, gain)
        }
        onPresetSelected: function(presetName) {
            root.micPresetSelected(presetName)
        }
        onMonitoringToggled: function(enabled) {
            root.micMonitoringToggled(enabled)
        }
        onDefaultSourceRequested: function(useEqSource) {
            root.micDefaultSourceRequested(useEqSource)
        }
        onProfileSelected: function(profileName) {
            root.profileSelected(profileName)
        }
        onSaveProfileRequested: function(profileName) {
            root.saveProfileRequested(profileName)
        }
        onNewProfileRequested: root.newProfileRequested()
        onDeleteProfileRequested: function(profileName) {
            root.deleteProfileRequested(profileName)
        }
        onResetDefaultRequested: root.resetDefaultRequested()
    }

    // 4. Profiles & Button Mapping Panel
    Rectangle {
        visible: Boolean(root.deviceData.hasButtons)
        Layout.fillWidth: true
        radius: theme.radiusLg
        color: theme.bgSurface
        border.color: theme.borderSubtle
        border.width: 1
        implicitHeight: mappingContainer.implicitHeight + 36

        ColumnLayout {
            id: mappingContainer
            anchors.fill: parent
            anchors.margins: 18
            spacing: 16

            ProfileBar {
                Layout.fillWidth: true
                deviceData: root.deviceData
                onProfileSelected: function(profileName) {
                    root.profileSelected(profileName)
                }
                onSaveProfileRequested: function(profileName) {
                    root.saveProfileRequested(profileName)
                }
                onNewProfileRequested: root.newProfileRequested()
                onDeleteProfileRequested: function(profileName) {
                    root.deleteProfileRequested(profileName)
                }
                onResetDefaultRequested: root.resetDefaultRequested()
            }

            // Hairline Divider
            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: theme.borderSubtle
            }

            ButtonGrid {
                id: buttonGrid
                Layout.fillWidth: true
                deviceData: root.deviceData
                isTestingButton: Boolean(root.hasDeviceManager && deviceManager.isTestingButton)
                testingDeviceId: (root.hasDeviceManager && deviceManager.testingDeviceId) ? deviceManager.testingDeviceId : ""
                testedButtonResult: (root.hasDeviceManager && deviceManager.testedButtonResult) ? deviceManager.testedButtonResult : ({})

                onButtonRemapRequested: function(buttonIdx, buttonName, currentAction, currentActionDisplay, defaultAction, buttonLocation) {
                    root.buttonRemapRequested(buttonIdx, buttonName, currentAction, currentActionDisplay, defaultAction, buttonLocation)
                }
                onStartButtonTestRequested: function(deviceId) {
                    if (root.hasDeviceManager) {
                        deviceManager.startButtonTest(deviceId)
                    }
                }
                onStopButtonTestRequested: {
                    if (root.hasDeviceManager) {
                        deviceManager.stopButtonTest()
                    }
                }
                onClearTestResultRequested: {
                    if (root.hasDeviceManager) {
                        deviceManager.clearTestResult()
                    }
                }
            }
        }
    }
}
