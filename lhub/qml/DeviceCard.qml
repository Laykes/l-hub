import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

ColumnLayout {
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

    readonly property Theme theme: Theme {}

    spacing: 16

    // Reset filter tab if switching to a device with <= 4 buttons
    onDeviceDataChanged: {
        if (!deviceData.buttons || deviceData.buttons.length <= 4) {
            buttonFilterGroup = "all"
        }
    }

    function batteryColor() {
        var pct = deviceData.batteryPercentage
        if (deviceData.isCharging && pct < 0) return theme.positive
        if (pct > 50) return theme.positive
        if (pct > 20) return theme.warning
        return theme.danger
    }

    // =========================================================================
    // 1. HERO HEADER CARD
    // =========================================================================
    Rectangle {
        Layout.fillWidth: true
        radius: theme.radiusLg
        color: theme.bgSurface
        border.color: theme.borderSubtle
        border.width: 1
        implicitHeight: heroLayout.implicitHeight + 36

        RowLayout {
            id: heroLayout
            anchors.fill: parent
            anchors.margins: 18
            spacing: 16

            // Device Icon Tile
            Rectangle {
                width: 54
                height: 54
                radius: 14
                color: theme.bgControl
                border.color: theme.borderSubtle
                border.width: 1

                Kirigami.Icon {
                    anchors.centerIn: parent
                    width: 34
                    height: 34
                    source: {
                        if (deviceData.type === "mouse") return "input-mouse"
                        if (deviceData.type === "headset") return "audio-headset"
                        if (deviceData.type === "keyboard") return "input-keyboard"
                        return "input-gaming"
                    }
                }
            }

            // Title & Vendor Metadata
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5

                Text {
                    text: deviceData.name || "Device"
                    color: theme.textPrimary
                    font.pixelSize: 19
                    font.weight: Font.Bold
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                RowLayout {
                    spacing: 8

                    Text {
                        text: deviceData.vendor || "Hardware"
                        color: theme.textSecondary
                        font.pixelSize: 12
                        font.weight: Font.Medium
                    }

                    Rectangle {
                        width: 3
                        height: 3
                        radius: 2
                        color: theme.textMuted
                    }

                    Rectangle {
                        radius: theme.radiusXs
                        color: theme.bgControl
                        border.color: theme.borderSubtle
                        border.width: 1
                        implicitWidth: backendLbl.implicitWidth + 14
                        implicitHeight: 20

                        Text {
                            id: backendLbl
                            anchors.centerIn: parent
                            text: deviceData.backend || "system"
                            color: theme.textSecondary
                            font.pixelSize: 11
                            font.weight: Font.Medium
                        }
                    }
                }
            }

            // Live Hardware Onboard Profile Pill
            Rectangle {
                visible: Boolean(deviceData.hasOnboardProfile)
                Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                color: theme.accentSoft
                border.color: theme.accentBorder
                border.width: 1
                radius: theme.radiusPill
                implicitWidth: onboardRow.implicitWidth + 20
                implicitHeight: 32

                RowLayout {
                    id: onboardRow
                    anchors.centerIn: parent
                    spacing: 6

                    Rectangle {
                        width: 7
                        height: 7
                        radius: 4
                        color: theme.accent
                    }

                    Text {
                        text: "Onboard: " + (deviceData.onboardProfile || "")
                        color: theme.accent
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }

                QQC2.ToolTip.visible: onboardHover.containsMouse
                QQC2.ToolTip.text: "Active hardware on-board profile (updates live)"

                MouseArea {
                    id: onboardHover
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                }
            }

            // Rich Battery Status Pill
            Rectangle {
                visible: Boolean(deviceData.hasBattery) && (deviceData.batteryPercentage >= 0 || deviceData.isCharging)
                Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                radius: theme.radiusMd
                color: theme.bgControl
                border.color: theme.borderSubtle
                border.width: 1
                implicitWidth: Math.max(132, batteryCol.implicitWidth + 24)
                implicitHeight: batteryCol.implicitHeight + 16

                ColumnLayout {
                    id: batteryCol
                    anchors.centerIn: parent
                    spacing: 5

                    RowLayout {
                        Layout.alignment: Qt.AlignRight
                        spacing: 6

                        Kirigami.Icon {
                            source: deviceData.isCharging ? "battery-full-charging-symbolic" : "battery-full-symbolic"
                            Layout.preferredWidth: 15
                            Layout.preferredHeight: 15
                            isMask: true
                            color: root.batteryColor()
                        }

                        Text {
                            text: {
                                if (deviceData.isCharging) {
                                    return (deviceData.batteryPercentage >= 0) ? (deviceData.batteryPercentage + "% · Charging") : "Charging"
                                }
                                return deviceData.batteryPercentage + "%"
                            }
                            color: root.batteryColor()
                            font.pixelSize: 13
                            font.weight: Font.Bold
                        }
                    }

                    // Visual Battery Bar
                    Rectangle {
                        visible: deviceData.batteryPercentage >= 0
                        Layout.fillWidth: true
                        Layout.minimumWidth: 100
                        height: 5
                        radius: 3
                        color: theme.borderSubtle

                        Rectangle {
                            width: parent.width * Math.max(0, Math.min(100, deviceData.batteryPercentage || 0)) / 100
                            height: parent.height
                            radius: 3
                            color: root.batteryColor()

                            Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                        }
                    }

                    Text {
                        visible: Boolean(deviceData.batteryTimeRemaining)
                        text: deviceData.batteryTimeRemaining || ""
                        color: theme.textSecondary
                        font.pixelSize: 11
                        Layout.alignment: Qt.AlignRight
                    }
                }
            }
        }
    }

    // =========================================================================
    // STATUS NOTE BANNER (e.g. disabled profile info)
    // =========================================================================
    Rectangle {
        visible: Boolean(deviceData.statusNote)
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
                text: deviceData.statusNote || ""
                color: theme.textPrimary
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
    }

    // =========================================================================
    // 2. DPI SENSITIVITY PANEL
    // =========================================================================
    Rectangle {
        visible: Boolean(deviceData.hasDpi) && !deviceData.isDpiDisabled
        Layout.fillWidth: true
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
                        text: (deviceData.currentDpi || 800) + " DPI"
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
                    model: deviceData.dpiSteps || [400, 800, 1600, 3200]

                    UiButton {
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
    }

    // =========================================================================
    // 3. SIDETONE PANEL (Headset)
    // =========================================================================
    Rectangle {
        visible: Boolean(deviceData.hasSidetone)
        Layout.fillWidth: true
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
                value: deviceData.sidetone || 0
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

    // =========================================================================
    // 4. PROFILES & BUTTON MAPPING PANEL
    // =========================================================================
    Rectangle {
        visible: Boolean(deviceData.hasButtons)
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

            // --- Profile Toolbar ---
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "Profile"
                    color: theme.textSecondary
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }

                // Styled Dark ComboBox
                QQC2.ComboBox {
                    id: profileCombo
                    Layout.fillWidth: true
                    Layout.minimumWidth: 140
                    implicitHeight: 36
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

                    background: Rectangle {
                        radius: theme.radiusSm
                        color: profileCombo.hovered ? theme.bgSurfaceHover : theme.bgControl
                        border.color: profileCombo.popup.visible ? theme.accent : (profileCombo.hovered ? theme.borderHover : theme.borderSubtle)
                        border.width: 1
                    }

                    contentItem: Text {
                        leftPadding: 12
                        rightPadding: 28
                        text: profileCombo.displayText
                        font.pixelSize: 13
                        font.weight: Font.Medium
                        color: theme.textPrimary
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }

                    indicator: Kirigami.Icon {
                        x: profileCombo.width - width - 10
                        y: (profileCombo.height - height) / 2
                        width: 14
                        height: 14
                        source: "arrow-down"
                        isMask: true
                        color: theme.textSecondary
                    }

                    delegate: QQC2.ItemDelegate {
                        width: profileCombo.width
                        height: 34
                        highlighted: profileCombo.highlightedIndex === index

                        background: Rectangle {
                            radius: 6
                            color: highlighted ? theme.accentSoft : "transparent"
                        }

                        contentItem: Text {
                            text: modelData
                            color: highlighted ? theme.accent : theme.textPrimary
                            font.pixelSize: 13
                            font.weight: highlighted ? Font.DemiBold : Font.Normal
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 8
                        }
                    }

                    popup: QQC2.Popup {
                        y: profileCombo.height + 4
                        width: profileCombo.width
                        padding: 4

                        background: Rectangle {
                            radius: theme.radiusSm
                            color: theme.bgDialog
                            border.color: theme.borderStrong
                            border.width: 1
                        }

                        contentItem: ListView {
                            clip: true
                            implicitHeight: contentHeight
                            model: profileCombo.popup.visible ? profileCombo.delegateModel : null
                            currentIndex: profileCombo.highlightedIndex
                        }
                    }
                }

                UiButton {
                    text: "Save"
                    iconName: "document-save-symbolic"
                    toolTipText: "Save current button mapping to profile '" + (deviceData.activeProfile || "Default") + "'"
                    onClicked: root.saveProfileRequested(deviceData.activeProfile || "Default")
                }

                UiButton {
                    text: "New"
                    iconName: "list-add-symbolic"
                    toolTipText: "Create new profile"
                    onClicked: root.newProfileRequested()
                }

                UiButton {
                    text: "Reset"
                    iconName: "edit-undo-symbolic"
                    toolTipText: "Restore factory default button mapping and settings"
                    onClicked: root.resetDefaultRequested()
                }

                UiButton {
                    variant: "danger"
                    iconName: "edit-delete-symbolic"
                    compact: true
                    implicitWidth: 36
                    implicitHeight: 36
                    enabled: Boolean(deviceData.profiles && deviceData.profiles.length > 1 && deviceData.activeProfile !== "Default" && deviceData.activeProfile !== "Standard")
                    toolTipText: "Delete active profile"
                    onClicked: root.deleteProfileRequested(deviceData.activeProfile)
                }
            }

            // Hairline Divider
            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: theme.borderSubtle
            }

            // --- Button Mapping Header & Identify Action ---
            ColumnLayout {
                visible: Boolean(deviceData.buttons) && (deviceData.buttons.length > 0)
                Layout.fillWidth: true
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Text {
                        text: "Button Mapping"
                        color: theme.textPrimary
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }

                    Rectangle {
                        radius: theme.radiusPill
                        color: theme.bgControl
                        border.color: theme.borderSubtle
                        border.width: 1
                        implicitWidth: countLbl.implicitWidth + 16
                        implicitHeight: 22

                        Text {
                            id: countLbl
                            anchors.centerIn: parent
                            text: (deviceData.buttons ? deviceData.buttons.length : 0) + " buttons"
                            color: theme.textSecondary
                            font.pixelSize: 11
                            font.weight: Font.Medium
                        }
                    }

                    Item { Layout.fillWidth: true }

                    UiButton {
                        id: testButton
                        property bool isListening: Boolean(deviceManager.isTestingButton && deviceManager.testingDeviceId === deviceData.id)
                        variant: isListening ? "primary" : "default"
                        text: isListening ? "Waiting for click..." : "Identify Button"
                        iconName: isListening ? "media-playback-pause-symbolic" : "crosshairs"
                        toolTipText: "Click here and press any button on your mouse to highlight it"
                        onClicked: {
                            if (isListening) {
                                deviceManager.stopButtonTest()
                            } else {
                                deviceManager.startButtonTest(deviceData.id)
                            }
                        }
                    }
                }

                // Segmented Pill Filter Bar
                Rectangle {
                    visible: Boolean(deviceData.buttons && deviceData.buttons.length > 4)
                    Layout.fillWidth: true
                    radius: theme.radiusMd
                    color: theme.bgControl
                    border.color: theme.borderSubtle
                    border.width: 1
                    implicitHeight: filterRow.implicitHeight + 8

                    RowLayout {
                        id: filterRow
                        anchors.fill: parent
                        anchors.margins: 4
                        spacing: 4

                        Repeater {
                            model: [
                                { id: "all", label: "All (" + (deviceData.buttons ? deviceData.buttons.length : 0) + ")" },
                                { id: "main", label: "Main" },
                                { id: "wheel", label: "Wheel" },
                                { id: "side", label: "Side" },
                                { id: "dpi", label: "DPI & Profile" }
                            ]

                            Rectangle {
                                Layout.fillWidth: true
                                height: 30
                                radius: theme.radiusSm
                                color: root.buttonFilterGroup === modelData.id
                                       ? theme.accentSoft
                                       : (filterMouse.containsMouse ? theme.bgSurfaceHover : "transparent")
                                border.color: root.buttonFilterGroup === modelData.id ? theme.accentBorder : "transparent"
                                border.width: 1

                                Behavior on color { ColorAnimation { duration: 110 } }

                                Text {
                                    anchors.centerIn: parent
                                    text: modelData.label
                                    color: root.buttonFilterGroup === modelData.id ? theme.accent : theme.textSecondary
                                    font.pixelSize: 12
                                    font.weight: root.buttonFilterGroup === modelData.id ? Font.DemiBold : Font.Medium
                                }

                                MouseArea {
                                    id: filterMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.buttonFilterGroup = modelData.id
                                }
                            }
                        }
                    }
                }

                // Listening Status Banner
                Rectangle {
                    visible: Boolean(deviceManager.isTestingButton && deviceManager.testingDeviceId === deviceData.id)
                    Layout.fillWidth: true
                    radius: theme.radiusMd
                    color: theme.accentSoft
                    border.color: theme.accent
                    border.width: 1
                    implicitHeight: listenRow.implicitHeight + 24

                    RowLayout {
                        id: listenRow
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 12

                        Rectangle {
                            width: 10
                            height: 10
                            radius: 5
                            color: theme.accent
                        }

                        Text {
                            text: "Press any button on your mouse now to identify it (Esc to cancel)."
                            color: theme.textPrimary
                            font.pixelSize: 13
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }

                        UiButton {
                            text: "Cancel"
                            compact: true
                            onClicked: deviceManager.stopButtonTest()
                        }
                    }
                }

                // Test Result Banner
                Rectangle {
                    property bool hasMatch: Boolean(
                        deviceManager.testedButtonResult &&
                        deviceManager.testedButtonResult.matchingIndices &&
                        deviceManager.testedButtonResult.matchingIndices.length > 0
                    )

                    visible: Boolean(
                        !deviceManager.isTestingButton &&
                        deviceManager.testedButtonResult &&
                        deviceManager.testedButtonResult.deviceId === deviceData.id &&
                        (deviceManager.testedButtonResult.detectedName || deviceManager.testedButtonResult.statusNote)
                    )
                    Layout.fillWidth: true
                    radius: theme.radiusMd
                    color: hasMatch ? theme.positiveSoft : theme.accentSoft
                    border.color: hasMatch ? theme.positive : theme.accentBorder
                    border.width: 1
                    implicitHeight: resultRow.implicitHeight + 24

                    RowLayout {
                        id: resultRow
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 10

                        Kirigami.Icon {
                            source: parent.parent.hasMatch ? "emblem-checked" : "dialog-information"
                            Layout.preferredWidth: 18
                            Layout.preferredHeight: 18
                            isMask: true
                            color: parent.parent.hasMatch ? theme.positive : theme.accent
                        }

                        Text {
                            text: {
                                var res = deviceManager.testedButtonResult
                                if (!res) return ""
                                if (res.detectedName) {
                                    var msg = "Detected: " + res.detectedName
                                    if (res.matchingNames && res.matchingNames.length > 0) {
                                        msg += "  →  " + res.matchingNames.join(", ")
                                    } else {
                                        msg += " (not assigned to a mouse button in this profile)"
                                    }
                                    return msg
                                } else if (res.statusNote) {
                                    return res.statusNote
                                }
                                return ""
                            }
                            color: theme.textPrimary
                            font.pixelSize: 13
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }

                        UiButton {
                            visible: parent.parent.hasMatch
                            variant: "primary"
                            compact: true
                            text: {
                                var res = deviceManager.testedButtonResult
                                if (res && res.matchingNames && res.matchingNames.length > 0) {
                                    return "Remap " + res.matchingNames[0]
                                }
                                return "Remap"
                            }
                            onClicked: {
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
                        }

                        UiButton {
                            variant: "subtle"
                            compact: true
                            iconName: "window-close-symbolic"
                            implicitWidth: 30
                            toolTipText: "Dismiss"
                            onClicked: deviceManager.clearTestResult()
                        }
                    }
                }

                // Responsive 2-Column Button Grid
                Flow {
                    id: buttonsFlow
                    Layout.fillWidth: true
                    spacing: 10

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
                            width: (buttonsFlow.width >= 520) ? Math.floor((buttonsFlow.width - 10) / 2) : buttonsFlow.width
                            implicitHeight: Math.max(76, cardContent.implicitHeight + 22)
                            radius: theme.radiusMd

                            property bool isMatchingTest: Boolean(
                                deviceManager.testedButtonResult &&
                                deviceManager.testedButtonResult.deviceId === deviceData.id &&
                                deviceManager.testedButtonResult.matchingIndices &&
                                deviceManager.testedButtonResult.matchingIndices.indexOf(modelData.index) >= 0
                            )

                            color: isMatchingTest
                                   ? theme.accentSoft
                                   : (cardMouseArea.containsMouse ? theme.bgSurfaceHover : theme.bgControl)
                            border.color: isMatchingTest
                                          ? theme.accent
                                          : (cardMouseArea.containsMouse ? theme.borderStrong : theme.borderSubtle)
                            border.width: isMatchingTest ? 2 : 1

                            Behavior on color { ColorAnimation { duration: 110 } }
                            Behavior on border.color { ColorAnimation { duration: 110 } }

                            RowLayout {
                                id: cardContent
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 12

                                // Category Icon Badge
                                Rectangle {
                                    width: 38
                                    height: 38
                                    radius: 10
                                    color: {
                                        if (modelData.group === "wheel") return theme.accentSoft
                                        if (modelData.group === "side") return theme.positiveSoft
                                        if (modelData.group === "dpi") return theme.warningSoft
                                        return "#1f60a5fa"
                                    }

                                    Kirigami.Icon {
                                        anchors.centerIn: parent
                                        width: 18
                                        height: 18
                                        isMask: true
                                        color: {
                                            if (modelData.group === "wheel") return theme.accent
                                            if (modelData.group === "side") return theme.positive
                                            if (modelData.group === "dpi") return theme.warning
                                            return "#60a5fa"
                                        }
                                        source: {
                                            if (modelData.group === "wheel") return "input-mouse-symbolic"
                                            if (modelData.group === "side") {
                                                if (modelData.action && modelData.action.indexOf("resolution-alternate") >= 0) return "crosshairs"
                                                return "go-previous-symbolic"
                                            }
                                            if (modelData.group === "dpi") {
                                                if (modelData.action && modelData.action.indexOf("up") >= 0) return "go-up-symbolic"
                                                if (modelData.action && modelData.action.indexOf("down") >= 0) return "go-down-symbolic"
                                                return "view-refresh-symbolic"
                                            }
                                            return "input-mouse-symbolic"
                                        }
                                    }
                                }

                                // Details Column
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 4

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 6

                                        Text {
                                            text: modelData.name || ("Button " + (modelData.index + 1))
                                            color: theme.textPrimary
                                            font.pixelSize: 13
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                            Layout.fillWidth: true
                                        }

                                        Rectangle {
                                            visible: buttonCard.isMatchingTest
                                            color: theme.accent
                                            radius: theme.radiusPill
                                            implicitWidth: testBadge.implicitWidth + 12
                                            implicitHeight: 18

                                            Text {
                                                id: testBadge
                                                anchors.centerIn: parent
                                                text: "DETECTED"
                                                color: theme.accentText
                                                font.pixelSize: 10
                                                font.weight: Font.Bold
                                            }
                                        }
                                    }

                                    RowLayout {
                                        spacing: 6

                                        Text {
                                            text: (modelData.location ? (modelData.location + " · ") : "") + "Button " + (modelData.index + 1)
                                            color: theme.textMuted
                                            font.pixelSize: 11
                                        }

                                        Rectangle {
                                            visible: Boolean(modelData.isCustomized)
                                            radius: theme.radiusPill
                                            color: theme.warningSoft
                                            implicitWidth: customLbl.implicitWidth + 10
                                            implicitHeight: 16

                                            Text {
                                                id: customLbl
                                                anchors.centerIn: parent
                                                text: "Custom"
                                                color: theme.warning
                                                font.pixelSize: 10
                                                font.weight: Font.DemiBold
                                            }
                                        }
                                    }

                                    // Color-coded Action Chip
                                    Rectangle {
                                        property string actLower: (modelData.action || "").toLowerCase()
                                        radius: 6
                                        color: {
                                            if (actLower === "disabled") return "#1f64748b"
                                            if (actLower.indexOf("macro") >= 0 || actLower.indexOf("key ") >= 0) return theme.purpleSoft
                                            if (actLower.indexOf("special") >= 0) return theme.warningSoft
                                            return theme.accentSoft
                                        }
                                        implicitWidth: Math.min(actionLbl.implicitWidth + 14, parent.width)
                                        implicitHeight: 22

                                        Text {
                                            id: actionLbl
                                            anchors.centerIn: parent
                                            width: Math.min(implicitWidth, parent.width - 10)
                                            text: modelData.actionDisplay || modelData.action || "Default"
                                            color: {
                                                var act = parent.actLower
                                                if (act === "disabled") return theme.textMuted
                                                if (act.indexOf("macro") >= 0 || act.indexOf("key ") >= 0) return theme.purple
                                                if (act.indexOf("special") >= 0) return theme.warning
                                                return theme.accent
                                            }
                                            font.pixelSize: 11
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                        }
                                    }
                                }

                                // Edit Indicator
                                Kirigami.Icon {
                                    source: "document-edit-symbolic"
                                    Layout.preferredWidth: 15
                                    Layout.preferredHeight: 15
                                    isMask: true
                                    color: cardMouseArea.containsMouse ? theme.accent : theme.textMuted
                                    opacity: cardMouseArea.containsMouse ? 1.0 : 0.45

                                    Behavior on opacity { NumberAnimation { duration: 110 } }
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
}
