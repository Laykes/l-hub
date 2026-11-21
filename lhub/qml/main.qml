import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

QQC2.ApplicationWindow {
    id: root

    readonly property Theme theme: Theme {}

    property string selectedDeviceId: ""
    property string toastMessage: ""
    property bool toastWarning: false

    readonly property var selectedDevice: {
        var devs = deviceManager.devices || []
        if (devs.length === 0) return null
        for (var i = 0; i < devs.length; i++) {
            if (devs[i].id === selectedDeviceId) {
                return devs[i]
            }
        }
        return devs[0]
    }

    title: "L-Hub"
    width: 1060
    height: 700
    minimumWidth: 740
    minimumHeight: 520
    visible: true
    color: theme.bgWindow

    function showToast(msg, isWarning) {
        toastMessage = msg
        toastWarning = Boolean(isWarning)
        toastTimer.interval = toastWarning ? 6000 : 3000
        toastTimer.restart()
    }

    function deviceBatteryColor(dev) {
        if (!dev) return theme.textSecondary
        var pct = dev.batteryPercentage
        if (dev.isCharging && pct < 0) return theme.positive
        if (pct > 50) return theme.positive
        if (pct > 20) return theme.warning
        return theme.danger
    }

    Timer {
        id: toastTimer
        interval: 3000
        onTriggered: root.toastMessage = ""
    }

    Connections {
        target: deviceManager

        function onOnboardProfileChanged(deviceName, profileLabel) {
            root.showToast(deviceName + ": " + profileLabel)
        }

        function onBatteryWarning(deviceName, percentage) {
            root.showToast("Low battery: " + deviceName + " (" + percentage + "%)", true)
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // =====================================================================
        // LEFT SIDEBAR
        // =====================================================================
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 264
            Layout.minimumWidth: 220
            color: theme.bgSidebar

            // Right hairline divider
            Rectangle {
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: parent.right
                width: 1
                color: theme.borderSubtle
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.rightMargin: 1
                spacing: 0

                // Brand Header
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 72

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 14
                        spacing: 12

                        Image {
                            source: Qt.resolvedUrl("../assets/io.github.lhub.LHub.svg")
                            Layout.preferredWidth: 34
                            Layout.preferredHeight: 34
                            sourceSize.width: 68
                            sourceSize.height: 68
                            smooth: true
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1

                            Text {
                                text: "L-Hub"
                                color: theme.textPrimary
                                font.pixelSize: 16
                                font.weight: Font.Bold
                            }

                            Text {
                                text: "Peripheral Hub"
                                color: theme.textMuted
                                font.pixelSize: 11
                                font.weight: Font.Medium
                            }
                        }

                        UiButton {
                            variant: "subtle"
                            compact: true
                            iconName: "view-refresh-symbolic"
                            implicitWidth: 32
                            implicitHeight: 32
                            toolTipText: "Refresh devices"
                            onClicked: {
                                deviceManager.refresh_devices()
                                root.showToast("Scanning for devices...")
                            }
                        }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: theme.borderSubtle
                    }
                }

                // Devices Section Label
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 18
                    Layout.rightMargin: 16
                    Layout.topMargin: 16
                    Layout.bottomMargin: 8

                    Text {
                        text: "DEVICES"
                        color: theme.textMuted
                        font.pixelSize: 11
                        font.weight: Font.Bold
                        font.letterSpacing: 1.0
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        text: (deviceManager.devices ? deviceManager.devices.length : 0).toString()
                        color: theme.textMuted
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                }

                // Device Navigation List
                Flickable {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: width
                    contentHeight: navList.implicitHeight + 16
                    clip: true

                    ColumnLayout {
                        id: navList
                        width: parent.width - 20
                        x: 10
                        spacing: 6

                        Repeater {
                            model: deviceManager.devices

                            Rectangle {
                                id: navItem
                                readonly property bool isSelected: root.selectedDevice && root.selectedDevice.id === modelData.id

                                Layout.fillWidth: true
                                height: 62
                                radius: theme.radiusMd
                                color: isSelected
                                       ? theme.bgSurfaceActive
                                       : (navHover.containsMouse ? theme.bgSurfaceHover : "transparent")
                                border.color: isSelected ? theme.accentBorder : "transparent"
                                border.width: 1

                                Behavior on color { ColorAnimation { duration: 110 } }

                                // Left active cyan indicator bar
                                Rectangle {
                                    visible: navItem.isSelected
                                    anchors.left: parent.left
                                    anchors.leftMargin: 4
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 3
                                    height: 26
                                    radius: 2
                                    color: theme.accent
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 14
                                    anchors.rightMargin: 12
                                    spacing: 11

                                    Rectangle {
                                        width: 36
                                        height: 36
                                        radius: 10
                                        color: navItem.isSelected ? theme.bgControl : theme.bgSurface
                                        border.color: navItem.isSelected ? theme.borderStrong : theme.borderSubtle
                                        border.width: 1

                                        Kirigami.Icon {
                                            anchors.centerIn: parent
                                            width: 22
                                            height: 22
                                            source: {
                                                if (modelData.type === "mouse") return "input-mouse"
                                                if (modelData.type === "headset") return "audio-headset"
                                                if (modelData.type === "keyboard") return "input-keyboard"
                                                return "input-gaming"
                                            }
                                        }
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 3

                                        Text {
                                            text: modelData.name || "Device"
                                            color: navItem.isSelected ? theme.textPrimary : "#cbd5e1"
                                            font.pixelSize: 13
                                            font.weight: navItem.isSelected ? Font.DemiBold : Font.Medium
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }

                                        RowLayout {
                                            spacing: 6

                                            // Battery status if available
                                            Rectangle {
                                                visible: Boolean(modelData.hasBattery) && (modelData.batteryPercentage >= 0 || modelData.isCharging)
                                                width: 6
                                                height: 6
                                                radius: 3
                                                color: root.deviceBatteryColor(modelData)
                                            }

                                            Text {
                                                visible: Boolean(modelData.hasBattery) && (modelData.batteryPercentage >= 0 || modelData.isCharging)
                                                text: {
                                                    if (modelData.isCharging) {
                                                        return modelData.batteryPercentage >= 0
                                                               ? (modelData.batteryPercentage + "% · Charging")
                                                               : "Charging"
                                                    }
                                                    return modelData.batteryPercentage + "%"
                                                }
                                                color: root.deviceBatteryColor(modelData)
                                                font.pixelSize: 11
                                                font.weight: Font.Medium
                                            }

                                            // Fallback subtitle when no battery
                                            Text {
                                                visible: !(Boolean(modelData.hasBattery) && (modelData.batteryPercentage >= 0 || modelData.isCharging))
                                                text: {
                                                    if (modelData.hasDpi && modelData.currentDpi) {
                                                        return modelData.currentDpi + " DPI"
                                                    }
                                                    return modelData.vendor || modelData.backend || "Connected"
                                                }
                                                color: theme.textMuted
                                                font.pixelSize: 11
                                                elide: Text.ElideRight
                                            }
                                        }
                                    }
                                }

                                MouseArea {
                                    id: navHover
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.selectedDeviceId = modelData.id
                                }
                            }
                        }

                        // Subtle sidebar empty note
                        Text {
                            visible: !deviceManager.devices || deviceManager.devices.length === 0
                            text: "No devices found"
                            color: theme.textMuted
                            font.pixelSize: 12
                            Layout.leftMargin: 8
                            Layout.topMargin: 4
                        }
                    }
                }

                // Sidebar Bottom Status Footer
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    color: "transparent"

                    Rectangle {
                        anchors.top: parent.top
                        anchors.left: parent.left
                        anchors.right: parent.right
                        height: 1
                        color: theme.borderSubtle
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        spacing: 8

                        Rectangle {
                            width: 7
                            height: 7
                            radius: 4
                            color: (deviceManager.devices && deviceManager.devices.length > 0) ? theme.positive : theme.textMuted
                        }

                        Text {
                            text: {
                                var count = deviceManager.devices ? deviceManager.devices.length : 0
                                if (count === 0) return "No devices connected"
                                return count === 1 ? "1 device connected" : (count + " devices connected")
                            }
                            color: theme.textSecondary
                            font.pixelSize: 11
                            font.weight: Font.Medium
                        }
                    }
                }
            }
        }

        // =====================================================================
        // MAIN WORKSPACE PANE
        // =====================================================================
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Flickable {
                id: mainFlickable
                anchors.fill: parent
                contentWidth: width
                contentHeight: contentColumn.implicitHeight + 48
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
                    id: contentColumn
                    width: Math.min(parent.width - 48, 860)
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 24
                    spacing: 16

                    // Missing Backends Warning Banners
                    Repeater {
                        model: deviceManager.missingBackends

                        Rectangle {
                            Layout.fillWidth: true
                            radius: theme.radiusMd
                            color: theme.warningSoft
                            border.color: theme.warning
                            border.width: 1
                            implicitHeight: warnRow.implicitHeight + 22

                            RowLayout {
                                id: warnRow
                                anchors.fill: parent
                                anchors.margins: 11
                                spacing: 10

                                Kirigami.Icon {
                                    source: "dialog-warning"
                                    Layout.preferredWidth: 18
                                    Layout.preferredHeight: 18
                                    isMask: true
                                    color: theme.warning
                                }

                                Text {
                                    text: modelData
                                    color: theme.textPrimary
                                    font.pixelSize: 13
                                    wrapMode: Text.WordWrap
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }

                    // Empty State when no devices detected
                    Rectangle {
                        visible: !deviceManager.devices || deviceManager.devices.length === 0
                        Layout.fillWidth: true
                        Layout.topMargin: 48
                        radius: theme.radiusLg
                        color: theme.bgSurface
                        border.color: theme.borderSubtle
                        border.width: 1
                        implicitHeight: emptyCol.implicitHeight + 72

                        ColumnLayout {
                            id: emptyCol
                            anchors.centerIn: parent
                            width: Math.min(parent.width - 48, 420)
                            spacing: 14

                            Rectangle {
                                Layout.alignment: Qt.AlignHCenter
                                width: 64
                                height: 64
                                radius: 18
                                color: theme.bgControl
                                border.color: theme.borderSubtle
                                border.width: 1

                                Kirigami.Icon {
                                    anchors.centerIn: parent
                                    width: 34
                                    height: 34
                                    source: "input-gaming"
                                }
                            }

                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: "No compatible devices detected"
                                color: theme.textPrimary
                                font.pixelSize: 17
                                font.weight: Font.Bold
                            }

                            Text {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                text: "Make sure your wireless headset, mouse, or controller is powered on and required services (ratbagd, headsetcontrol) are running."
                                color: theme.textSecondary
                                font.pixelSize: 13
                                wrapMode: Text.WordWrap
                            }

                            Item { height: 4 }

                            UiButton {
                                Layout.alignment: Qt.AlignHCenter
                                variant: "primary"
                                text: "Scan for Devices"
                                iconName: "view-refresh-symbolic"
                                onClicked: deviceManager.refresh_devices()
                            }
                        }
                    }

                    // Active Device Workspace
                    DeviceCard {
                        visible: root.selectedDevice !== null
                        Layout.fillWidth: true
                        deviceData: root.selectedDevice || ({})

                        onDpiSelected: function(dpi) {
                            if (root.selectedDevice) {
                                deviceManager.setDpi(root.selectedDevice.id, dpi)
                            }
                        }

                        onSidetoneChanged: function(level) {
                            if (root.selectedDevice) {
                                deviceManager.setSidetone(root.selectedDevice.id, level)
                            }
                        }

                        onButtonRemapRequested: function(btnIdx, btnName, curAct, curActDisp, defAct, btnLoc) {
                            if (!root.selectedDevice) return
                            remapDialog.targetDeviceId = root.selectedDevice.id
                            remapDialog.targetButtonIndex = btnIdx
                            remapDialog.targetButtonName = btnName
                            remapDialog.currentAction = curAct || ""
                            remapDialog.currentActionDisplay = curActDisp || ""
                            remapDialog.defaultAction = defAct || ""
                            remapDialog.buttonLocation = btnLoc || ""
                            remapDialog.open()
                        }

                        onProfileSelected: function(pName) {
                            if (!root.selectedDevice) return
                            deviceManager.applyProfile(root.selectedDevice.id, pName)
                            root.showToast("Applying profile '" + pName + "'...")
                        }

                        onSaveProfileRequested: function(pName) {
                            if (!root.selectedDevice) return
                            deviceManager.saveProfile(root.selectedDevice.id, pName)
                            root.showToast("Profile '" + pName + "' saved.")
                        }

                        onNewProfileRequested: function() {
                            if (!root.selectedDevice) return
                            newProfileDialog.targetDeviceId = root.selectedDevice.id
                            newProfileNameField.text = ""
                            newProfileDialog.open()
                            newProfileNameField.forceActiveFocus()
                        }

                        onDeleteProfileRequested: function(pName) {
                            if (!root.selectedDevice) return
                            deleteProfileDialog.targetDeviceId = root.selectedDevice.id
                            deleteProfileDialog.targetProfileName = pName
                            deleteProfileDialog.open()
                        }

                        onResetDefaultRequested: function() {
                            if (!root.selectedDevice) return
                            resetConfirmDialog.targetDeviceId = root.selectedDevice.id
                            resetConfirmDialog.targetDeviceName = root.selectedDevice.name || "Device"
                            resetConfirmDialog.open()
                        }
                    }
                }
            }

            // Floating Dark Toast Notification
            Rectangle {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 20
                visible: opacity > 0.01
                opacity: root.toastMessage.length > 0 ? 1.0 : 0.0
                radius: theme.radiusMd
                color: theme.bgDialog
                border.color: root.toastWarning ? theme.dangerBorder : theme.accentBorder
                border.width: 1
                implicitWidth: toastRow.implicitWidth + 28
                implicitHeight: 40

                Behavior on opacity { NumberAnimation { duration: 180 } }

                RowLayout {
                    id: toastRow
                    anchors.centerIn: parent
                    spacing: 10

                    Rectangle {
                        width: 8
                        height: 8
                        radius: 4
                        color: root.toastWarning ? theme.danger : theme.accent
                    }

                    Text {
                        text: root.toastMessage
                        color: theme.textPrimary
                        font.pixelSize: 13
                        font.weight: Font.Medium
                    }
                }
            }
        }
    }

    // =========================================================================
    // MODALS
    // =========================================================================
    RemapDialog {
        id: remapDialog

        onRemapConfirmed: function(devId, btnIdx, action) {
            deviceManager.remapButton(devId, btnIdx, action)
            root.showToast("Button remapped.")
        }
    }

    // Create New Profile Modal
    QQC2.Popup {
        id: newProfileDialog
        property string targetDeviceId: ""

        anchors.centerIn: QQC2.Overlay.overlay
        width: 400
        modal: true
        focus: true
        padding: 20

        QQC2.Overlay.modal: Rectangle { color: "#b005080d" }
        background: Rectangle {
            radius: theme.radiusLg
            color: theme.bgDialog
            border.color: theme.borderStrong
            border.width: 1
        }

        function submit() {
            var name = newProfileNameField.text.trim()
            if (name) {
                deviceManager.saveProfile(targetDeviceId, name)
                root.showToast("Profile '" + name + "' created.")
                close()
            }
        }

        contentItem: ColumnLayout {
            spacing: 14

            Text {
                text: "Create New Profile"
                color: theme.textPrimary
                font.pixelSize: 16
                font.weight: Font.Bold
            }

            Text {
                text: "Enter a name for the new profile (e.g. Gaming or Office):"
                color: theme.textSecondary
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Rectangle {
                Layout.fillWidth: true
                height: 38
                radius: theme.radiusSm
                color: theme.bgControl
                border.color: newProfileNameField.activeFocus ? theme.accent : theme.borderSubtle
                border.width: 1

                QQC2.TextField {
                    id: newProfileNameField
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    placeholderText: "Profile name..."
                    placeholderTextColor: theme.textMuted
                    color: theme.textPrimary
                    font.pixelSize: 13
                    background: Item {}
                    onAccepted: newProfileDialog.submit()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 8

                Item { Layout.fillWidth: true }

                UiButton {
                    text: "Cancel"
                    onClicked: newProfileDialog.close()
                }

                UiButton {
                    variant: "primary"
                    text: "Create Profile"
                    enabled: newProfileNameField.text.trim().length > 0
                    onClicked: newProfileDialog.submit()
                }
            }
        }
    }

    // Confirm Delete Profile Modal
    QQC2.Popup {
        id: deleteProfileDialog
        property string targetDeviceId: ""
        property string targetProfileName: ""

        anchors.centerIn: QQC2.Overlay.overlay
        width: 400
        modal: true
        focus: true
        padding: 20

        QQC2.Overlay.modal: Rectangle { color: "#b005080d" }
        background: Rectangle {
            radius: theme.radiusLg
            color: theme.bgDialog
            border.color: theme.borderStrong
            border.width: 1
        }

        contentItem: ColumnLayout {
            spacing: 14

            Text {
                text: "Delete Profile"
                color: theme.textPrimary
                font.pixelSize: 16
                font.weight: Font.Bold
            }

            Text {
                text: "Do you really want to delete profile '" + deleteProfileDialog.targetProfileName + "'?"
                color: theme.textSecondary
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 8

                Item { Layout.fillWidth: true }

                UiButton {
                    text: "Cancel"
                    onClicked: deleteProfileDialog.close()
                }

                UiButton {
                    variant: "danger"
                    text: "Delete Profile"
                    iconName: "edit-delete-symbolic"
                    onClicked: {
                        deviceManager.deleteProfile(deleteProfileDialog.targetDeviceId, deleteProfileDialog.targetProfileName)
                        root.showToast("Profile deleted.")
                        deleteProfileDialog.close()
                    }
                }
            }
        }
    }

    // Confirm Reset to Default Modal
    QQC2.Popup {
        id: resetConfirmDialog
        property string targetDeviceId: ""
        property string targetDeviceName: ""

        anchors.centerIn: QQC2.Overlay.overlay
        width: 420
        modal: true
        focus: true
        padding: 20

        QQC2.Overlay.modal: Rectangle { color: "#b005080d" }
        background: Rectangle {
            radius: theme.radiusLg
            color: theme.bgDialog
            border.color: theme.borderStrong
            border.width: 1
        }

        contentItem: ColumnLayout {
            spacing: 14

            Text {
                text: "Reset to Default"
                color: theme.textPrimary
                font.pixelSize: 16
                font.weight: Font.Bold
            }

            Text {
                text: "Restore factory default button assignments and settings for " + resetConfirmDialog.targetDeviceName + "?"
                color: theme.textSecondary
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 8

                Item { Layout.fillWidth: true }

                UiButton {
                    text: "Cancel"
                    onClicked: resetConfirmDialog.close()
                }

                UiButton {
                    variant: "primary"
                    text: "Reset to Default"
                    iconName: "edit-undo-symbolic"
                    onClicked: {
                        deviceManager.resetDeviceToDefault(resetConfirmDialog.targetDeviceId)
                        root.showToast("Default settings restored.")
                        resetConfirmDialog.close()
                    }
                }
            }
        }
    }
}
