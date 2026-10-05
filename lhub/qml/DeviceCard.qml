import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.Card {
    id: root

    property var deviceData: ({})
    property string buttonFilterGroup: "all"
    signal dpiSelected(int dpi)
    signal sidetoneChanged(int level)
    signal buttonRemapRequested(int buttonIdx, string buttonName, string currentAction, string currentActionDisplay, string defaultAction, string buttonLocation)
    signal profileSelected(string profileName)
    signal saveProfileRequested(string profileName)
    signal newProfileRequested()
    signal deleteProfileRequested(string profileName)
    signal resetDefaultRequested()


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
                text: deviceData.name || "Device"
                font.bold: true
                font.pointSize: Kirigami.Theme.defaultFont.pointSize + 2
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            QQC2.Label {
                text: (deviceData.vendor || "Hardware") + " • via " + (deviceData.backend || "System")
                opacity: 0.7
                font.pointSize: Kirigami.Theme.smallFont.pointSize
            }
        }

        // Battery indicator
        ColumnLayout {
            visible: Boolean(deviceData.hasBattery) && (deviceData.batteryPercentage >= 0 || deviceData.isCharging)
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
                    text: {
                        if (deviceData.isCharging) {
                            return (deviceData.batteryPercentage >= 0) ? ("⚡ " + deviceData.batteryPercentage + "%") : "⚡ Charging"
                        }
                        return "🔋 " + deviceData.batteryPercentage + "%"
                    }
                    font.bold: true
                    color: {
                        if (deviceData.batteryPercentage > 50 || (deviceData.isCharging && deviceData.batteryPercentage < 0)) return Kirigami.Theme.positiveTextColor
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
                text: "DPI Resolution (Current: " + (deviceData.currentDpi || 800) + " DPI)"
                font.bold: true
            }

            QQC2.ButtonGroup {
                id: dpiGroup
            }

            RowLayout {
                spacing: Kirigami.Units.smallSpacing
                Repeater {
                    model: deviceData.dpiSteps || [400, 800, 1600, 3200]
                    QQC2.Button {
                        text: modelData + " DPI"
                        checkable: true
                        checked: modelData === (deviceData.currentDpi || 800)
                        QQC2.ButtonGroup.group: dpiGroup

                        Binding on checked {
                            value: modelData === (deviceData.currentDpi || 800)
                        }

                        onClicked: {
                            if (deviceData.currentDpi !== modelData) {
                                root.dpiSelected(modelData)
                            }
                        }
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
                    text: "Sidetone: " + Math.round(sidetoneSlider.value * 100 / 128) + "%"
                    font.bold: true
                    Layout.fillWidth: true
                }
            }

            QQC2.Label {
                text: "Plays your voice back through the headset so you can hear yourself speak."
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                opacity: 0.7
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
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


        // Profile Section
        ColumnLayout {
            visible: Boolean(deviceData.hasButtons)
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Separator {
                Layout.fillWidth: true
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: "document-properties"
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                }

                QQC2.Label {
                    text: "Profile:"
                    font.bold: true
                }

                QQC2.ComboBox {
                    id: profileCombo
                    Layout.fillWidth: true
                    model: deviceData.profiles || ["Default"]
                    currentIndex: {
                        var list = deviceData.profiles || []
                        var idx = list.indexOf(deviceData.activeProfile)
                        return idx >= 0 ? idx : 0
                    }
                    onActivated: function(index) {
                        var list = deviceData.profiles || []
                        if (index >= 0 && index < list.length) {
                            var pName = list[index]
                            if (pName && pName !== deviceData.activeProfile) {
                                root.profileSelected(pName)
                            }
                        }
                    }
                }

                QQC2.Button {
                    text: "Save"
                    icon.name: "document-save"
                    QQC2.ToolTip.text: "Save current button mapping to profile '" + (deviceData.activeProfile || "Default") + "'"
                    QQC2.ToolTip.visible: hovered
                    onClicked: root.saveProfileRequested(deviceData.activeProfile || "Default")
                }

                QQC2.Button {
                    text: "Reset to Default"
                    icon.name: "document-revert"
                    QQC2.ToolTip.text: "Restore factory default button mapping and settings"
                    QQC2.ToolTip.visible: hovered
                    onClicked: root.resetDefaultRequested()
                }

                QQC2.Button {
                    text: "New..."
                    icon.name: "list-add"
                    QQC2.ToolTip.text: "Create new profile"
                    QQC2.ToolTip.visible: hovered
                    onClicked: root.newProfileRequested()
                }

                QQC2.Button {
                    icon.name: "edit-delete"
                    enabled: Boolean(deviceData.profiles && deviceData.profiles.length > 1 && deviceData.activeProfile !== "Default" && deviceData.activeProfile !== "Standard")
                    QQC2.ToolTip.text: "Delete active profile"
                    QQC2.ToolTip.visible: hovered
                    onClicked: root.deleteProfileRequested(deviceData.activeProfile)
                }
            }
        }

        // Buttons Section
        ColumnLayout {
            visible: Boolean(deviceData.hasButtons) && Boolean(deviceData.buttons) && (deviceData.buttons.length > 0)
            Layout.fillWidth: true
            spacing: Kirigami.Units.mediumSpacing

            // Section Header with Identify Button
            RowLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                QQC2.Label {
                    text: "Button Mapping"
                    font.bold: true
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize + 1
                }

                Rectangle {
                    color: Kirigami.Theme.alternateBackgroundColor
                    border.color: Kirigami.Theme.separatorColor
                    border.width: 1
                    radius: 4
                    implicitWidth: countLbl.implicitWidth + 10
                    implicitHeight: countLbl.implicitHeight + 4

                    QQC2.Label {
                        id: countLbl
                        anchors.centerIn: parent
                        text: (deviceData.buttons ? deviceData.buttons.length : 0) + " Buttons"
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                        opacity: 0.8
                    }
                }

                Item {
                    Layout.fillWidth: true
                }

                QQC2.Button {
                    id: testButton
                    text: (deviceManager.isTestingButton && deviceManager.testingDeviceId === deviceData.id) ? "Waiting for click..." : "🎯 Identify Button"
                    icon.name: (deviceManager.isTestingButton && deviceManager.testingDeviceId === deviceData.id) ? "media-playback-pause" : "input-mouse"
                    highlighted: Boolean(deviceManager.isTestingButton && deviceManager.testingDeviceId === deviceData.id)
                    QQC2.ToolTip.text: "Click here and press any button on your mouse to highlight it in the list"
                    QQC2.ToolTip.visible: hovered
                    onClicked: {
                        if (deviceManager.isTestingButton && deviceManager.testingDeviceId === deviceData.id) {
                            deviceManager.stopButtonTest()
                        } else {
                            deviceManager.startButtonTest(deviceData.id)
                        }
                    }
                }
            }

            // Group Filter Tabs
            QQC2.TabBar {
                id: buttonFilterTabs
                visible: Boolean(deviceData.buttons && deviceData.buttons.length > 4)
                Layout.fillWidth: true
                currentIndex: 0

                QQC2.TabButton {
                    text: "All (" + (deviceData.buttons ? deviceData.buttons.length : 0) + ")"
                }
                QQC2.TabButton {
                    text: "🖱️ Main"
                }
                QQC2.TabButton {
                    text: "🎡 Wheel"
                }
                QQC2.TabButton {
                    text: "👈 Side"
                }
                QQC2.TabButton {
                    text: "⚡ DPI / Profile"
                }

                onCurrentIndexChanged: {
                    if (currentIndex === 0) root.buttonFilterGroup = "all"
                    else if (currentIndex === 1) root.buttonFilterGroup = "main"
                    else if (currentIndex === 2) root.buttonFilterGroup = "wheel"
                    else if (currentIndex === 3) root.buttonFilterGroup = "side"
                    else if (currentIndex === 4) root.buttonFilterGroup = "dpi"
                }
            }

            // Listening status banner
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                type: Kirigami.MessageType.Information
                visible: Boolean(deviceManager.isTestingButton && deviceManager.testingDeviceId === deviceData.id)
                text: "🎯 Waiting for button press... Press any button on your mouse now (e.g. right click, side button, scroll wheel). [Esc to cancel]"
                actions: [
                    Kirigami.Action {
                        text: "Cancel"
                        icon.name: "dialog-cancel"
                        onTriggered: deviceManager.stopButtonTest()
                    }
                ]
            }

            // Test result banner
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                type: (deviceManager.testedButtonResult && deviceManager.testedButtonResult.matchingIndices && deviceManager.testedButtonResult.matchingIndices.length > 0)
                      ? Kirigami.MessageType.Positive
                      : Kirigami.MessageType.Information
                visible: Boolean(
                    !deviceManager.isTestingButton &&
                    deviceManager.testedButtonResult &&
                    deviceManager.testedButtonResult.deviceId === deviceData.id &&
                    (deviceManager.testedButtonResult.detectedName || deviceManager.testedButtonResult.statusNote)
                )
                text: {
                    var res = deviceManager.testedButtonResult
                    if (!res) return ""
                    if (res.detectedName) {
                        var msg = "Detected button press: " + res.detectedName
                        if (res.matchingNames && res.matchingNames.length > 0) {
                            msg += " ➔ Corresponds to in L-Hub: " + res.matchingNames.join(", ")
                        } else {
                            msg += " (Currently not assigned to any mouse button in profile)"
                        }
                        return msg
                    } else if (res.statusNote) {
                        return res.statusNote
                    }
                    return ""
                }
                actions: [
                    Kirigami.Action {
                        visible: Boolean(
                            deviceManager.testedButtonResult &&
                            deviceManager.testedButtonResult.matchingIndices &&
                            deviceManager.testedButtonResult.matchingIndices.length > 0
                        )
                        text: {
                            var res = deviceManager.testedButtonResult
                            if (res && res.matchingNames && res.matchingNames.length > 0) {
                                return "Remap " + res.matchingNames[0]
                            }
                            return "Remap Button"
                        }
                        icon.name: "configure"
                        onTriggered: {
                            var res = deviceManager.testedButtonResult
                            if (res && res.matchingIndices && res.matchingIndices.length > 0) {
                                var idx = res.matchingIndices[0]
                                var bName = res.matchingNames[0]
                                var curAct = res.action || ""
                                var curDisp = res.detectedName || ""
                                var defAct = ""
                                var btnLoc = ""
                                if (deviceData.buttons) {
                                    for (var i = 0; i < deviceData.buttons.length; i++) {
                                        if (deviceData.buttons[i].index === idx) {
                                            curAct = deviceData.buttons[i].action
                                            curDisp = deviceData.buttons[i].actionDisplay || curAct
                                            defAct = deviceData.buttons[i].defaultAction || ""
                                            btnLoc = deviceData.buttons[i].location || ""
                                            break
                                        }
                                    }
                                }
                                root.buttonRemapRequested(idx, bName, curAct, curDisp, defAct, btnLoc)
                            }
                        }
                    },
                    Kirigami.Action {
                        text: "Close"
                        icon.name: "dialog-close"
                        onTriggered: deviceManager.clearTestResult()
                    }
                ]
            }

            // Responsive Card Grid
            Flow {
                id: buttonsFlow
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Repeater {
                    model: {
                        var all = deviceData.buttons || []
                        if (root.buttonFilterGroup === "all") return all
                        var filtered = []
                        for (var i = 0; i < all.length; i++) {
                            var b = all[i]
                            var grp = b.group || "main"
                            if (grp === root.buttonFilterGroup) {
                                filtered.push(b)
                            }
                        }
                        return filtered
                    }

                    Rectangle {
                        id: buttonCard
                        width: (buttonsFlow.width >= 560) ? Math.floor((buttonsFlow.width - Kirigami.Units.smallSpacing) / 2) : buttonsFlow.width
                        implicitHeight: Math.max(68, cardContent.implicitHeight + Kirigami.Units.smallSpacing * 2)
                        radius: 6

                        property bool isMatchingTest: Boolean(
                            deviceManager.testedButtonResult &&
                            deviceManager.testedButtonResult.deviceId === deviceData.id &&
                            deviceManager.testedButtonResult.matchingIndices &&
                            deviceManager.testedButtonResult.matchingIndices.indexOf(modelData.index) >= 0
                        )

                        color: isMatchingTest
                               ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g, Kirigami.Theme.highlightColor.b, 0.22)
                               : (cardMouseArea.containsMouse ? Kirigami.Theme.alternateBackgroundColor : Kirigami.Theme.backgroundColor)

                        border.color: isMatchingTest
                                      ? Kirigami.Theme.highlightColor
                                      : (cardMouseArea.containsMouse ? Kirigami.Theme.focusColor : Kirigami.Theme.separatorColor)
                        border.width: isMatchingTest ? 2 : 1

                        RowLayout {
                            id: cardContent
                            anchors.fill: parent
                            anchors.margins: Kirigami.Units.smallSpacing
                            spacing: Kirigami.Units.mediumSpacing

                            // Icon Container
                            Rectangle {
                                width: 36
                                height: 36
                                radius: 18
                                color: {
                                    if (modelData.group === "wheel") return Qt.rgba(0.2, 0.6, 0.8, 0.16)
                                    if (modelData.group === "side") return Qt.rgba(0.1, 0.7, 0.3, 0.16)
                                    if (modelData.group === "dpi") return Qt.rgba(0.9, 0.6, 0.1, 0.16)
                                    return Qt.rgba(0.2, 0.5, 0.9, 0.16)
                                }

                                Kirigami.Icon {
                                    anchors.centerIn: parent
                                    source: {
                                        if (modelData.group === "wheel") return "input-mouse"
                                        if (modelData.group === "side") {
                                            if (modelData.action && modelData.action.indexOf("resolution-alternate") >= 0) return "target"
                                            return "go-previous"
                                        }
                                        if (modelData.group === "dpi") {
                                            if (modelData.action && modelData.action.indexOf("up") >= 0) return "arrow-up"
                                            if (modelData.action && modelData.action.indexOf("down") >= 0) return "arrow-down"
                                            return "document-properties"
                                        }
                                        return "input-mouse"
                                    }
                                    width: Kirigami.Units.iconSizes.small
                                    height: Kirigami.Units.iconSizes.small
                                }
                            }

                            // Details
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                RowLayout {
                                    spacing: Kirigami.Units.smallSpacing

                                    QQC2.Label {
                                        text: modelData.name || ("Button " + (modelData.index + 1))
                                        font.bold: true
                                        elide: Text.ElideRight
                                    }

                                    Rectangle {
                                        visible: buttonCard.isMatchingTest
                                        color: Kirigami.Theme.highlightColor
                                        radius: 3
                                        implicitWidth: testBadge.implicitWidth + 8
                                        implicitHeight: testBadge.implicitHeight + 2

                                        QQC2.Label {
                                            id: testBadge
                                            anchors.centerIn: parent
                                            text: "🎯 DETECTED"
                                            color: Kirigami.Theme.highlightedTextColor
                                            font.pointSize: Kirigami.Theme.smallFont.pointSize - 1
                                            font.bold: true
                                        }
                                    }
                                }

                                RowLayout {
                                    spacing: Kirigami.Units.smallSpacing

                                    QQC2.Label {
                                        text: (modelData.location ? (modelData.location + " • ") : "") + "Button " + (modelData.index + 1)
                                        opacity: 0.6
                                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                                    }

                                    QQC2.Label {
                                        visible: Boolean(modelData.isCustomized)
                                        text: "• Custom"
                                        color: Kirigami.Theme.neutralTextColor
                                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                                        font.bold: true
                                    }
                                }

                                // Action Chip
                                Rectangle {
                                    radius: 4
                                    color: {
                                        var act = (modelData.action || "").toLowerCase()
                                        if (act === "disabled") return Qt.rgba(0.5, 0.5, 0.5, 0.2)
                                        if (act.indexOf("macro") >= 0 || act.indexOf("key ") >= 0) return Qt.rgba(0.55, 0.25, 0.85, 0.2)
                                        if (act.indexOf("special") >= 0) return Qt.rgba(0.9, 0.6, 0.1, 0.2)
                                        return Qt.rgba(0.1, 0.5, 0.9, 0.2)
                                    }
                                    implicitWidth: actionLbl.implicitWidth + 10
                                    implicitHeight: actionLbl.implicitHeight + 4

                                    QQC2.Label {
                                        id: actionLbl
                                        anchors.centerIn: parent
                                        text: modelData.actionDisplay || modelData.action || "Default"
                                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                                        font.bold: true
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            // Edit icon
                            Kirigami.Icon {
                                source: "document-edit"
                                width: Kirigami.Units.iconSizes.small
                                height: Kirigami.Units.iconSizes.small
                                opacity: cardMouseArea.containsMouse ? 0.9 : 0.25
                            }
                        }

                        MouseArea {
                            id: cardMouseArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.buttonRemapRequested(
                                modelData.index,
                                modelData.name,
                                modelData.action,
                                modelData.actionDisplay || modelData.action,
                                modelData.defaultAction || "",
                                modelData.location || ""
                            )
                        }
                    }
                }
            }
        }

    }
}
