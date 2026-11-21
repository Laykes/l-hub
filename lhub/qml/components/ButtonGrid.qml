import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import ".."

ColumnLayout {
    id: root

    property var deviceData: ({})
    property string buttonFilterGroup: "all"
    property bool isTestingButton: false
    property string testingDeviceId: ""
    property var testedButtonResult: ({})

    signal buttonRemapRequested(int buttonIdx, string buttonName, string currentAction, string currentActionDisplay, string defaultAction, string buttonLocation)
    signal startButtonTestRequested(string deviceId)
    signal stopButtonTestRequested()
    signal clearTestResultRequested()

    readonly property Theme theme: Theme {}

    visible: Boolean(root.deviceData.buttons) && (root.deviceData.buttons.length > 0)
    spacing: 14

    // Reset filter tab if switching to a device with <= 4 buttons
    onDeviceDataChanged: {
        if (!deviceData || !deviceData.buttons || deviceData.buttons.length <= 4) {
            buttonFilterGroup = "all"
        }
    }

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
                text: (root.deviceData.buttons ? root.deviceData.buttons.length : 0) + " buttons"
                color: theme.textSecondary
                font.pixelSize: 11
                font.weight: Font.Medium
            }
        }

        Item { Layout.fillWidth: true }

        UiButton {
            id: testButton
            property bool isListening: Boolean(root.isTestingButton && root.deviceData.id && root.testingDeviceId === root.deviceData.id)
            variant: isListening ? "primary" : "default"
            text: isListening ? "Waiting for click..." : "Identify Button"
            iconName: isListening ? "media-playback-pause-symbolic" : "crosshairs"
            toolTipText: "Click here and press any button on your mouse to highlight it"
            onClicked: {
                if (isListening) {
                    root.stopButtonTestRequested()
                } else {
                    root.startButtonTestRequested(root.deviceData.id || "")
                }
            }
        }
    }

    // Segmented Pill Filter Bar
    Rectangle {
        visible: Boolean(root.deviceData.buttons && root.deviceData.buttons.length > 4)
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
                    { id: "all", label: "All (" + (root.deviceData.buttons ? root.deviceData.buttons.length : 0) + ")" },
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
        visible: Boolean(root.isTestingButton && root.deviceData.id && root.testingDeviceId === root.deviceData.id)
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
                onClicked: root.stopButtonTestRequested()
            }
        }
    }

    // Test Result Banner
    Rectangle {
        id: testResultBanner

        property bool hasMatch: Boolean(
            root.testedButtonResult &&
            root.testedButtonResult.matchingIndices &&
            root.testedButtonResult.matchingIndices.length > 0
        )

        visible: Boolean(
            !root.isTestingButton &&
            root.deviceData.id &&
            root.testedButtonResult &&
            root.testedButtonResult.deviceId === root.deviceData.id &&
            (root.testedButtonResult.detectedName || root.testedButtonResult.statusNote)
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
                source: testResultBanner.hasMatch ? "emblem-checked" : "dialog-information"
                Layout.preferredWidth: 18
                Layout.preferredHeight: 18
                isMask: true
                color: testResultBanner.hasMatch ? theme.positive : theme.accent
            }

            Text {
                text: {
                    var res = root.testedButtonResult
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
                visible: testResultBanner.hasMatch
                variant: "primary"
                compact: true
                text: {
                    var res = root.testedButtonResult
                    if (res && res.matchingNames && res.matchingNames.length > 0) {
                        return "Remap " + res.matchingNames[0]
                    }
                    return "Remap"
                }
                onClicked: {
                    var res = root.testedButtonResult
                    if (res && res.matchingIndices && res.matchingIndices.length > 0) {
                        var idx = res.matchingIndices[0]
                        var bName = res.matchingNames[0]
                        var curAct = res.action || ""
                        var curDisp = res.detectedName || ""
                        var defAct = ""
                        var btnLoc = ""
                        if (root.deviceData.buttons) {
                            for (var i = 0; i < root.deviceData.buttons.length; i++) {
                                if (root.deviceData.buttons[i].index === idx) {
                                    curAct = root.deviceData.buttons[i].action
                                    curDisp = root.deviceData.buttons[i].actionDisplay || curAct
                                    defAct = root.deviceData.buttons[i].defaultAction || ""
                                    btnLoc = root.deviceData.buttons[i].location || ""
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
                onClicked: root.clearTestResultRequested()
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
                var all = root.deviceData.buttons || []
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
                    root.testedButtonResult &&
                    root.deviceData.id &&
                    root.testedButtonResult.deviceId === root.deviceData.id &&
                    root.testedButtonResult.matchingIndices &&
                    root.testedButtonResult.matchingIndices.indexOf(modelData.index) >= 0
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
                            id: actionChip
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
                                    var act = actionChip.actLower
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
