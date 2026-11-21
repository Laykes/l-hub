import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

QQC2.Popup {
    id: root

    property string targetDeviceId: ""
    property int targetButtonIndex: 0
    property string targetButtonName: ""
    property string currentAction: ""
    property string currentActionDisplay: ""
    property string defaultAction: ""
    property string buttonLocation: ""

    property string searchFilter: ""
    property int activeTab: 0
    property bool isRecordingKey: false
    property string recordedAction: ""
    property string recordedDisplay: ""

    signal remapConfirmed(string deviceId, int buttonIndex, string action)

    readonly property Theme theme: Theme {}

    anchors.centerIn: QQC2.Overlay.overlay
    width: Math.min(parent ? parent.width - 48 : 680, 680)
    height: Math.min(parent ? parent.height - 48 : 560, 560)
    modal: true
    focus: true
    closePolicy: isRecordingKey ? QQC2.Popup.CloseOnPressOutside : (QQC2.Popup.CloseOnEscape | QQC2.Popup.CloseOnPressOutside)
    padding: 0

    QQC2.Overlay.modal: Rectangle {
        color: "#b005080d"
    }

    background: Rectangle {
        radius: theme.radiusLg
        color: theme.bgDialog
        border.color: theme.borderStrong
        border.width: 1
    }

    function selectAction(action) {
        if (!action) return
        remapConfirmed(targetDeviceId, targetButtonIndex, action)
        root.close()
    }

    function resetToDefault() {
        if (defaultAction) {
            selectAction(defaultAction)
        }
    }

    function assignCustomKey() {
        var rawKey = customKeyInput.text.trim().toUpperCase()
        if (!rawKey) return
        if (!rawKey.startsWith("KEY_") && !rawKey.startsWith("macro ")) {
            rawKey = "KEY_" + rawKey
        }
        var act = rawKey.startsWith("macro ") ? rawKey : ("key " + rawKey)
        selectAction(act)
        customKeyInput.text = ""
    }

    onOpened: {
        searchFilter = ""
        searchInput.text = ""
        isRecordingKey = false
        recordedAction = ""
        recordedDisplay = ""
        activeTab = 0
    }

    readonly property var allActionCatalog: [
        // Shortcuts & Productivity
        { label: "Copy (Ctrl+C)", action: "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-copy-symbolic" },
        { label: "Paste (Ctrl+V)", action: "macro +KEY_LEFTCTRL KEY_V -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-paste-symbolic" },
        { label: "Cut (Ctrl+X)", action: "macro +KEY_LEFTCTRL KEY_X -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-cut-symbolic" },
        { label: "Undo (Ctrl+Z)", action: "macro +KEY_LEFTCTRL KEY_Z -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-undo-symbolic" },
        { label: "Redo (Ctrl+Y)", action: "macro +KEY_LEFTCTRL KEY_Y -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-redo-symbolic" },
        { label: "Select All (Ctrl+A)", action: "macro +KEY_LEFTCTRL KEY_A -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-select-all-symbolic" },
        { label: "Save (Ctrl+S)", action: "macro +KEY_LEFTCTRL KEY_S -KEY_LEFTCTRL", cat: "Shortcuts", icon: "document-save-symbolic" },
        { label: "Find (Ctrl+F)", action: "macro +KEY_LEFTCTRL KEY_F -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-find-symbolic" },
        { label: "New Tab (Ctrl+T)", action: "macro +KEY_LEFTCTRL KEY_T -KEY_LEFTCTRL", cat: "Shortcuts", icon: "tab-new-symbolic" },
        { label: "Close Tab (Ctrl+W)", action: "macro +KEY_LEFTCTRL KEY_W -KEY_LEFTCTRL", cat: "Shortcuts", icon: "window-close-symbolic" },
        { label: "Switch App (Alt+Tab)", action: "macro +KEY_LEFTALT KEY_TAB -KEY_LEFTALT", cat: "Shortcuts", icon: "window-duplicate" },
        { label: "Show Desktop / Super", action: "key KEY_LEFTMETA", cat: "Shortcuts", icon: "user-desktop-symbolic" },
        { label: "Refresh Page (F5)", action: "key KEY_F5", cat: "Shortcuts", icon: "view-refresh-symbolic" },
        { label: "Screenshot (Print)", action: "key KEY_PRINT", cat: "Shortcuts", icon: "camera-photo-symbolic" },

        // Mouse Clicks
        { label: "Left Click (1)", action: "button 1", cat: "Mouse", icon: "input-mouse-symbolic" },
        { label: "Right Click (2)", action: "button 2", cat: "Mouse", icon: "input-mouse-symbolic" },
        { label: "Middle Click (3)", action: "button 3", cat: "Mouse", icon: "input-mouse-symbolic" },
        { label: "Back (4)", action: "button 4", cat: "Mouse", icon: "go-previous-symbolic" },
        { label: "Forward (5)", action: "button 5", cat: "Mouse", icon: "go-next-symbolic" },
        { label: "Button 6", action: "button 6", cat: "Mouse", icon: "input-mouse-symbolic" },
        { label: "Button 7", action: "button 7", cat: "Mouse", icon: "input-mouse-symbolic" },
        { label: "Button 8", action: "button 8", cat: "Mouse", icon: "input-mouse-symbolic" },
        { label: "Double Click", action: "special doubleclick", cat: "Mouse", icon: "input-mouse-symbolic" },
        { label: "Wheel Tilt Left", action: "special wheel-left", cat: "Mouse", icon: "go-previous-symbolic" },
        { label: "Wheel Tilt Right", action: "special wheel-right", cat: "Mouse", icon: "go-next-symbolic" },

        // Special & DPI
        { label: "DPI Shift (Sniper)", action: "special resolution-alternate", cat: "DPI", icon: "crosshairs" },
        { label: "Increase DPI (+)", action: "special resolution-up", cat: "DPI", icon: "go-up-symbolic" },
        { label: "Decrease DPI (-)", action: "special resolution-down", cat: "DPI", icon: "go-down-symbolic" },
        { label: "Cycle DPI Presets", action: "special resolution-cycle-up", cat: "DPI", icon: "view-refresh-symbolic" },
        { label: "Cycle On-Board Profile", action: "special profile-cycle-up", cat: "DPI", icon: "document-properties-symbolic" },
        { label: "G-Shift (Secondary)", action: "special second-mode", cat: "DPI", icon: "changes-prevent-symbolic" },

        // Media
        { label: "Volume Up", action: "key KEY_VOLUMEUP", cat: "Media", icon: "audio-volume-high-symbolic" },
        { label: "Volume Down", action: "key KEY_VOLUMEDOWN", cat: "Media", icon: "audio-volume-low-symbolic" },
        { label: "Mute Audio", action: "key KEY_MUTE", cat: "Media", icon: "audio-volume-muted-symbolic" },
        { label: "Play / Pause", action: "key KEY_PLAYPAUSE", cat: "Media", icon: "media-playback-start-symbolic" },
        { label: "Next Track", action: "key KEY_NEXTSONG", cat: "Media", icon: "media-skip-forward-symbolic" },
        { label: "Previous Track", action: "key KEY_PREVIOUSSONG", cat: "Media", icon: "media-skip-backward-symbolic" },

        // Keyboard Keys
        { label: "Enter", action: "key KEY_ENTER", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "Space", action: "key KEY_SPACE", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "Escape", action: "key KEY_ESC", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "Tab", action: "key KEY_TAB", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "Backspace", action: "key KEY_BACKSPACE", cat: "Keyboard", icon: "edit-clear-symbolic" },
        { label: "Delete", action: "key KEY_DELETE", cat: "Keyboard", icon: "edit-delete-symbolic" },
        { label: "Left Shift", action: "key KEY_LEFTSHIFT", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "Left Ctrl", action: "key KEY_LEFTCTRL", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "Left Alt", action: "key KEY_LEFTALT", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "Super / Win", action: "key KEY_LEFTMETA", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F1", action: "key KEY_F1", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F2", action: "key KEY_F2", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F3", action: "key KEY_F3", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F4", action: "key KEY_F4", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F5", action: "key KEY_F5", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F6", action: "key KEY_F6", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F7", action: "key KEY_F7", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F8", action: "key KEY_F8", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F9", action: "key KEY_F9", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F10", action: "key KEY_F10", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F11", action: "key KEY_F11", cat: "Keyboard", icon: "input-keyboard-symbolic" },
        { label: "F12", action: "key KEY_F12", cat: "Keyboard", icon: "input-keyboard-symbolic" }
    ]

    function catalogForCategory(catName) {
        var list = []
        for (var i = 0; i < allActionCatalog.length; i++) {
            if (allActionCatalog[i].cat === catName) {
                list.push(allActionCatalog[i])
            }
        }
        return list
    }

    readonly property var searchResults: {
        var query = searchFilter.trim().toLowerCase()
        if (!query) return []
        var results = []
        for (var i = 0; i < allActionCatalog.length; i++) {
            var item = allActionCatalog[i]
            if (item.label.toLowerCase().indexOf(query) >= 0 ||
                item.cat.toLowerCase().indexOf(query) >= 0 ||
                item.action.toLowerCase().indexOf(query) >= 0) {
                results.push(item)
            }
        }
        return results
    }

    contentItem: ColumnLayout {
        spacing: 0

        // Top Header Bar
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: headerRow.implicitHeight + 28
            color: theme.bgSurface
            radius: theme.radiusLg

            // Square off bottom corners of header
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: theme.radiusLg
                color: theme.bgSurface
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: theme.borderSubtle
            }

            RowLayout {
                id: headerRow
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12

                Rectangle {
                    width: 42
                    height: 42
                    radius: 12
                    color: theme.accentSoft
                    border.color: theme.accentBorder
                    border.width: 1

                    Kirigami.Icon {
                        anchors.centerIn: parent
                        source: "input-mouse-symbolic"
                        width: 20
                        height: 20
                        isMask: true
                        color: theme.accent
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    RowLayout {
                        spacing: 8

                        Text {
                            text: targetButtonName || ("Button " + (targetButtonIndex + 1))
                            color: theme.textPrimary
                            font.pixelSize: 16
                            font.weight: Font.Bold
                        }

                        Rectangle {
                            visible: Boolean(buttonLocation)
                            color: theme.bgControl
                            border.color: theme.borderSubtle
                            border.width: 1
                            radius: theme.radiusXs
                            implicitWidth: locLbl.implicitWidth + 12
                            implicitHeight: 20

                            Text {
                                id: locLbl
                                anchors.centerIn: parent
                                text: buttonLocation
                                color: theme.textSecondary
                                font.pixelSize: 11
                                font.weight: Font.Medium
                            }
                        }
                    }

                    RowLayout {
                        spacing: 6

                        Text {
                            text: "Current:"
                            color: theme.textMuted
                            font.pixelSize: 12
                        }

                        Rectangle {
                            color: theme.accentSoft
                            radius: 5
                            implicitWidth: curLbl.implicitWidth + 12
                            implicitHeight: 20

                            Text {
                                id: curLbl
                                anchors.centerIn: parent
                                text: currentActionDisplay || "Default"
                                color: theme.accent
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                        }

                        Text {
                            visible: Boolean(defaultAction && currentAction && currentAction !== defaultAction)
                            text: "· Customized"
                            color: theme.warning
                            font.pixelSize: 11
                            font.weight: Font.Medium
                        }
                    }
                }

                UiButton {
                    visible: Boolean(defaultAction && currentAction && currentAction !== defaultAction)
                    text: "Reset"
                    iconName: "edit-undo-symbolic"
                    compact: true
                    onClicked: root.resetToDefault()
                }

                UiButton {
                    variant: "subtle"
                    iconName: "window-close-symbolic"
                    compact: true
                    implicitWidth: 32
                    implicitHeight: 32
                    toolTipText: "Close"
                    onClicked: root.close()
                }
            }
        }

        // Body Content
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 16
            spacing: 14

            // Styled Search Input
            Rectangle {
                Layout.fillWidth: true
                height: 40
                radius: theme.radiusSm
                color: theme.bgControl
                border.color: searchInput.activeFocus ? theme.accent : theme.borderSubtle
                border.width: 1

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 8
                    spacing: 8

                    Kirigami.Icon {
                        source: "edit-find-symbolic"
                        Layout.preferredWidth: 16
                        Layout.preferredHeight: 16
                        isMask: true
                        color: searchInput.activeFocus ? theme.accent : theme.textMuted
                    }

                    QQC2.TextField {
                        id: searchInput
                        Layout.fillWidth: true
                        placeholderText: "Search shortcuts, actions, keys (e.g. copy, mute, dpi, f5)..."
                        placeholderTextColor: theme.textMuted
                        color: theme.textPrimary
                        font.pixelSize: 13
                        background: Item {}
                        onTextChanged: root.searchFilter = text
                    }

                    UiButton {
                        visible: searchInput.text.length > 0
                        variant: "subtle"
                        compact: true
                        iconName: "edit-clear-symbolic"
                        implicitWidth: 28
                        implicitHeight: 28
                        onClicked: {
                            searchInput.text = ""
                            root.searchFilter = ""
                        }
                    }
                }
            }

            // Search Results View
            ColumnLayout {
                visible: root.searchFilter.trim().length > 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 10

                Text {
                    text: root.searchResults.length + " matching actions"
                    color: theme.textSecondary
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }

                Flickable {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: width
                    contentHeight: searchFlow.implicitHeight
                    clip: true

                    Flow {
                        id: searchFlow
                        width: parent.width
                        spacing: 8

                        Repeater {
                            model: root.searchResults

                            UiButton {
                                iconName: modelData.icon || "input-keyboard-symbolic"
                                text: modelData.label + " · " + modelData.cat
                                checked: modelData.action === root.currentAction
                                onClicked: root.selectAction(modelData.action)
                            }
                        }
                    }
                }
            }

            // Category Pills + Tab Content (when not searching)
            ColumnLayout {
                visible: root.searchFilter.trim().length === 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 14

                // Pill Tab Strip
                Rectangle {
                    Layout.fillWidth: true
                    radius: theme.radiusMd
                    color: theme.bgControl
                    border.color: theme.borderSubtle
                    border.width: 1
                    implicitHeight: catRow.implicitHeight + 8

                    RowLayout {
                        id: catRow
                        anchors.fill: parent
                        anchors.margins: 4
                        spacing: 4

                        Repeater {
                            model: ["Shortcuts", "Mouse", "DPI", "Media", "Keyboard", "Disable"]

                            Rectangle {
                                Layout.fillWidth: true
                                height: 30
                                radius: theme.radiusSm
                                color: root.activeTab === index
                                       ? (index === 5 ? theme.dangerSoft : theme.accentSoft)
                                       : (tabHover.containsMouse ? theme.bgSurfaceHover : "transparent")
                                border.color: root.activeTab === index
                                              ? (index === 5 ? theme.dangerBorder : theme.accentBorder)
                                              : "transparent"
                                border.width: 1

                                Text {
                                    anchors.centerIn: parent
                                    text: modelData
                                    color: root.activeTab === index
                                           ? (index === 5 ? theme.danger : theme.accent)
                                           : theme.textSecondary
                                    font.pixelSize: 12
                                    font.weight: root.activeTab === index ? Font.DemiBold : Font.Medium
                                }

                                MouseArea {
                                    id: tabHover
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.activeTab = index
                                }
                            }
                        }
                    }
                }

                // Tab Panels
                StackLayout {
                    currentIndex: root.activeTab
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    // Tab 0: Shortcuts
                    Flickable {
                        contentWidth: width
                        contentHeight: shortcutsCol.implicitHeight
                        clip: true

                        ColumnLayout {
                            id: shortcutsCol
                            width: parent.width
                            spacing: 10

                            Text {
                                text: "Common Productivity & System Shortcuts"
                                color: theme.textSecondary
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: 8

                                Repeater {
                                    model: root.catalogForCategory("Shortcuts")
                                    UiButton {
                                        iconName: modelData.icon
                                        text: modelData.label
                                        checked: modelData.action === root.currentAction
                                        onClicked: root.selectAction(modelData.action)
                                    }
                                }
                            }
                        }
                    }

                    // Tab 1: Mouse
                    Flickable {
                        contentWidth: width
                        contentHeight: mouseCol.implicitHeight
                        clip: true

                        ColumnLayout {
                            id: mouseCol
                            width: parent.width
                            spacing: 10

                            Text {
                                text: "Standard Mouse Functions"
                                color: theme.textSecondary
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: 8

                                Repeater {
                                    model: root.catalogForCategory("Mouse")
                                    UiButton {
                                        iconName: modelData.icon
                                        text: modelData.label
                                        checked: modelData.action === root.currentAction
                                        onClicked: root.selectAction(modelData.action)
                                    }
                                }
                            }
                        }
                    }

                    // Tab 2: DPI & Sensor
                    Flickable {
                        contentWidth: width
                        contentHeight: dpiCol.implicitHeight
                        clip: true

                        ColumnLayout {
                            id: dpiCol
                            width: parent.width
                            spacing: 10

                            Text {
                                text: "Sensor DPI & Profile Switching"
                                color: theme.textSecondary
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: 8

                                Repeater {
                                    model: root.catalogForCategory("DPI")
                                    UiButton {
                                        iconName: modelData.icon
                                        text: modelData.label
                                        checked: modelData.action === root.currentAction
                                        onClicked: root.selectAction(modelData.action)
                                    }
                                }
                            }
                        }
                    }

                    // Tab 3: Media
                    Flickable {
                        contentWidth: width
                        contentHeight: mediaCol.implicitHeight
                        clip: true

                        ColumnLayout {
                            id: mediaCol
                            width: parent.width
                            spacing: 10

                            Text {
                                text: "Media Playback & System Volume"
                                color: theme.textSecondary
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: 8

                                Repeater {
                                    model: root.catalogForCategory("Media")
                                    UiButton {
                                        iconName: modelData.icon
                                        text: modelData.label
                                        checked: modelData.action === root.currentAction
                                        onClicked: root.selectAction(modelData.action)
                                    }
                                }
                            }
                        }
                    }

                    // Tab 4: Keyboard & Live Recorder
                    Flickable {
                        contentWidth: width
                        contentHeight: kbCol.implicitHeight
                        clip: true

                        ColumnLayout {
                            id: kbCol
                            width: parent.width
                            spacing: 12

                            // Interactive Key Recorder Card (fixed: translucent tint, full-opacity text)
                            Rectangle {
                                id: recorderBox
                                Layout.fillWidth: true
                                implicitHeight: recRow.implicitHeight + 24
                                radius: theme.radiusMd
                                color: root.isRecordingKey ? theme.accentSoft : theme.bgSurface
                                border.color: root.isRecordingKey ? theme.accent : theme.borderSubtle
                                border.width: root.isRecordingKey ? 2 : 1
                                focus: true

                                Keys.onPressed: function(event) {
                                    if (root.isRecordingKey) {
                                        event.accepted = true
                                        var res = deviceManager.resolveKeyAction(event.key, event.modifiers)
                                        if (res && res.action) {
                                            root.recordedAction = res.action
                                            root.recordedDisplay = res.display || res.action
                                            root.isRecordingKey = false
                                        }
                                    }
                                }

                                RowLayout {
                                    id: recRow
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 12

                                    Rectangle {
                                        width: 40
                                        height: 40
                                        radius: 10
                                        color: root.isRecordingKey ? theme.accentMedium : theme.bgControl

                                        Kirigami.Icon {
                                            anchors.centerIn: parent
                                            source: "input-keyboard-symbolic"
                                            width: 20
                                            height: 20
                                            isMask: true
                                            color: root.isRecordingKey ? theme.accent : theme.textSecondary
                                        }
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 2

                                        Text {
                                            text: root.isRecordingKey
                                                  ? "Listening for key press..."
                                                  : (root.recordedDisplay ? ("Captured: " + root.recordedDisplay) : "Live Keyboard Capture")
                                            color: root.isRecordingKey ? theme.accent : theme.textPrimary
                                            font.pixelSize: 13
                                            font.weight: Font.DemiBold
                                        }

                                        Text {
                                            text: root.isRecordingKey
                                                  ? "Press any key or shortcut now (e.g. F5, Ctrl+C, Space, Esc)..."
                                                  : "Capture any physical key or modifier combo directly from your keyboard."
                                            color: theme.textSecondary
                                            font.pixelSize: 11
                                            wrapMode: Text.WordWrap
                                            Layout.fillWidth: true
                                        }
                                    }

                                    UiButton {
                                        variant: root.isRecordingKey ? "default" : "primary"
                                        compact: true
                                        text: root.isRecordingKey ? "Cancel" : "Record Key"
                                        iconName: root.isRecordingKey ? "dialog-cancel-symbolic" : "media-record-symbolic"
                                        onClicked: {
                                            root.isRecordingKey = !root.isRecordingKey
                                            if (root.isRecordingKey) {
                                                recorderBox.forceActiveFocus()
                                            }
                                        }
                                    }

                                    UiButton {
                                        visible: Boolean(root.recordedAction)
                                        variant: "primary"
                                        compact: true
                                        text: "Assign " + root.recordedDisplay
                                        onClicked: root.selectAction(root.recordedAction)
                                    }
                                }
                            }

                            Text {
                                text: "Common Keyboard Keys"
                                color: theme.textSecondary
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: 6

                                Repeater {
                                    model: root.catalogForCategory("Keyboard")
                                    UiButton {
                                        compact: true
                                        text: modelData.label
                                        checked: modelData.action === root.currentAction
                                        onClicked: root.selectAction(modelData.action)
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                height: 1
                                color: theme.borderSubtle
                            }

                            // Manual Keycode Input
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Rectangle {
                                    Layout.fillWidth: true
                                    height: 36
                                    radius: theme.radiusSm
                                    color: theme.bgControl
                                    border.color: customKeyInput.activeFocus ? theme.accent : theme.borderSubtle
                                    border.width: 1

                                    QQC2.TextField {
                                        id: customKeyInput
                                        anchors.fill: parent
                                        anchors.leftMargin: 10
                                        anchors.rightMargin: 10
                                        placeholderText: "Manual keycode (e.g. C, F11, or KEY_ENTER)..."
                                        placeholderTextColor: theme.textMuted
                                        color: theme.textPrimary
                                        font.pixelSize: 12
                                        background: Item {}
                                        onAccepted: root.assignCustomKey()
                                    }
                                }

                                UiButton {
                                    text: "Assign"
                                    variant: "primary"
                                    compact: true
                                    enabled: customKeyInput.text.trim().length > 0
                                    onClicked: root.assignCustomKey()
                                }
                            }
                        }
                    }

                    // Tab 5: Disable
                    Item {
                        ColumnLayout {
                            anchors.top: parent.top
                            anchors.left: parent.left
                            anchors.right: parent.right
                            spacing: 12

                            Rectangle {
                                Layout.fillWidth: true
                                radius: theme.radiusMd
                                color: theme.dangerSoft
                                border.color: theme.dangerBorder
                                border.width: 1
                                implicitHeight: disableCol.implicitHeight + 28

                                ColumnLayout {
                                    id: disableCol
                                    anchors.fill: parent
                                    anchors.margins: 14
                                    spacing: 8

                                    Text {
                                        text: "Disable This Button"
                                        color: theme.danger
                                        font.pixelSize: 14
                                        font.weight: Font.DemiBold
                                    }

                                    Text {
                                        text: "Pressing this button will send no click, key, or action to the system until remapped again."
                                        color: theme.textSecondary
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                        Layout.fillWidth: true
                                    }

                                    Item { height: 4 }

                                    UiButton {
                                        variant: "danger"
                                        text: "Disable Button"
                                        iconName: "dialog-cancel-symbolic"
                                        onClicked: root.selectAction("disabled")
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
