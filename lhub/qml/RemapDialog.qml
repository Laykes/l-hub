import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Kirigami.Dialog {
    id: root

    property string targetDeviceId: ""
    property int targetButtonIndex: 0
    property string targetButtonName: ""
    property string currentAction: ""
    property string currentActionDisplay: ""
    property string defaultAction: ""
    property string buttonLocation: ""

    property string searchFilter: ""
    property bool isRecordingKey: false
    property string recordedAction: ""
    property string recordedDisplay: ""

    signal remapConfirmed(string deviceId, int buttonIndex, string action)

    title: "Remap Button: " + (targetButtonName || ("Button " + (targetButtonIndex + 1)))
    preferredWidth: Kirigami.Units.gridUnit * 36
    preferredHeight: Kirigami.Units.gridUnit * 28
    standardButtons: Kirigami.Dialog.Cancel

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
        categoryTabs.currentIndex = 0
    }

    // Master list of all predefined actions for search
    readonly property var allActionCatalog: [
        // Shortcuts & Productivity
        { label: "Copy (Ctrl+C)", action: "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-copy" },
        { label: "Paste (Ctrl+V)", action: "macro +KEY_LEFTCTRL KEY_V -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-paste" },
        { label: "Cut (Ctrl+X)", action: "macro +KEY_LEFTCTRL KEY_X -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-cut" },
        { label: "Undo (Ctrl+Z)", action: "macro +KEY_LEFTCTRL KEY_Z -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-undo" },
        { label: "Redo (Ctrl+Y)", action: "macro +KEY_LEFTCTRL KEY_Y -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-redo" },
        { label: "Select All (Ctrl+A)", action: "macro +KEY_LEFTCTRL KEY_A -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-select-all" },
        { label: "Save (Ctrl+S)", action: "macro +KEY_LEFTCTRL KEY_S -KEY_LEFTCTRL", cat: "Shortcuts", icon: "document-save" },
        { label: "Find (Ctrl+F)", action: "macro +KEY_LEFTCTRL KEY_F -KEY_LEFTCTRL", cat: "Shortcuts", icon: "edit-find" },
        { label: "New Tab (Ctrl+T)", action: "macro +KEY_LEFTCTRL KEY_T -KEY_LEFTCTRL", cat: "Shortcuts", icon: "tab-new" },
        { label: "Close Tab (Ctrl+W)", action: "macro +KEY_LEFTCTRL KEY_W -KEY_LEFTCTRL", cat: "Shortcuts", icon: "tab-close" },
        { label: "Switch App (Alt+Tab)", action: "macro +KEY_LEFTALT KEY_TAB -KEY_LEFTALT", cat: "Shortcuts", icon: "window-duplicate" },
        { label: "Show Desktop / Super", action: "key KEY_LEFTMETA", cat: "Shortcuts", icon: "user-desktop" },
        { label: "Refresh Page (F5)", action: "key KEY_F5", cat: "Shortcuts", icon: "view-refresh" },
        { label: "Screenshot (PrintScreen)", action: "key KEY_PRINT", cat: "Shortcuts", icon: "camera-photo" },

        // Mouse Clicks
        { label: "Left Click (1)", action: "button 1", cat: "Mouse", icon: "input-mouse" },
        { label: "Right Click (2)", action: "button 2", cat: "Mouse", icon: "input-mouse" },
        { label: "Middle Click (3)", action: "button 3", cat: "Mouse", icon: "input-mouse" },
        { label: "Back (4)", action: "button 4", cat: "Mouse", icon: "go-previous" },
        { label: "Forward (5)", action: "button 5", cat: "Mouse", icon: "go-next" },
        { label: "Button 6", action: "button 6", cat: "Mouse", icon: "input-mouse" },
        { label: "Button 7", action: "button 7", cat: "Mouse", icon: "input-mouse" },
        { label: "Button 8", action: "button 8", cat: "Mouse", icon: "input-mouse" },
        { label: "Double Click", action: "special doubleclick", cat: "Mouse", icon: "input-mouse" },
        { label: "Scroll Wheel Tilt Left", action: "special wheel-left", cat: "Mouse", icon: "arrow-left" },
        { label: "Scroll Wheel Tilt Right", action: "special wheel-right", cat: "Mouse", icon: "arrow-right" },

        // Special & DPI
        { label: "DPI Shift (Sniper Mode)", action: "special resolution-alternate", cat: "DPI", icon: "target" },
        { label: "Increase DPI (+)", action: "special resolution-up", cat: "DPI", icon: "arrow-up" },
        { label: "Decrease DPI (-)", action: "special resolution-down", cat: "DPI", icon: "arrow-down" },
        { label: "Cycle DPI Presets", action: "special resolution-cycle-up", cat: "DPI", icon: "view-refresh" },
        { label: "Cycle On-Board Profile", action: "special profile-cycle-up", cat: "DPI", icon: "document-properties" },
        { label: "G-Shift (Secondary Mode)", action: "special second-mode", cat: "DPI", icon: "dialog-password" },

        // Media
        { label: "Volume Up", action: "key KEY_VOLUMEUP", cat: "Media", icon: "audio-volume-high" },
        { label: "Volume Down", action: "key KEY_VOLUMEDOWN", cat: "Media", icon: "audio-volume-low" },
        { label: "Mute Audio", action: "key KEY_MUTE", cat: "Media", icon: "audio-volume-muted" },
        { label: "Play / Pause", action: "key KEY_PLAYPAUSE", cat: "Media", icon: "media-playback-start" },
        { label: "Next Track", action: "key KEY_NEXTSONG", cat: "Media", icon: "media-skip-forward" },
        { label: "Previous Track", action: "key KEY_PREVIOUSSONG", cat: "Media", icon: "media-skip-backward" },

        // Keyboard Keys
        { label: "Enter", action: "key KEY_ENTER", cat: "Keyboard", icon: "key-enter" },
        { label: "Space", action: "key KEY_SPACE", cat: "Keyboard", icon: "input-keyboard" },
        { label: "Escape", action: "key KEY_ESC", cat: "Keyboard", icon: "dialog-cancel" },
        { label: "Tab", action: "key KEY_TAB", cat: "Keyboard", icon: "input-keyboard" },
        { label: "Backspace", action: "key KEY_BACKSPACE", cat: "Keyboard", icon: "edit-clear" },
        { label: "Delete", action: "key KEY_DELETE", cat: "Keyboard", icon: "edit-delete" },
        { label: "Left Shift", action: "key KEY_LEFTSHIFT", cat: "Keyboard", icon: "input-keyboard" },
        { label: "Left Ctrl", action: "key KEY_LEFTCTRL", cat: "Keyboard", icon: "input-keyboard" },
        { label: "Left Alt", action: "key KEY_LEFTALT", cat: "Keyboard", icon: "input-keyboard" },
        { label: "F1", action: "key KEY_F1", cat: "Keyboard", icon: "input-keyboard" },
        { label: "F2", action: "key KEY_F2", cat: "Keyboard", icon: "input-keyboard" },
        { label: "F3", action: "key KEY_F3", cat: "Keyboard", icon: "input-keyboard" },
        { label: "F4", action: "key KEY_F4", cat: "Keyboard", icon: "input-keyboard" },
        { label: "F5", action: "key KEY_F5", cat: "Keyboard", icon: "view-refresh" },
        { label: "F6", action: "key KEY_F6", cat: "Keyboard", icon: "input-keyboard" },
        { label: "F7", action: "key KEY_F7", cat: "Keyboard", icon: "input-keyboard" },
        { label: "F8", action: "key KEY_F8", cat: "Keyboard", icon: "input-keyboard" },
        { label: "F9", action: "key KEY_F9", cat: "Keyboard", icon: "input-keyboard" },
        { label: "F10", action: "key KEY_F10", cat: "Keyboard", icon: "input-keyboard" },
        { label: "F11", action: "key KEY_F11", cat: "Keyboard", icon: "input-keyboard" },
        { label: "F12", action: "key KEY_F12", cat: "Keyboard", icon: "input-keyboard" }
    ]

    // Filtered actions when searching
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

    ColumnLayout {
        spacing: Kirigami.Units.mediumSpacing
        Layout.fillWidth: true

        // Header Card
        Rectangle {
            Layout.fillWidth: true
            color: Kirigami.Theme.alternateBackgroundColor
            radius: Kirigami.Units.smallSpacing
            border.color: Kirigami.Theme.separatorColor
            border.width: 1
            implicitHeight: headerLayout.implicitHeight + Kirigami.Units.mediumSpacing * 2

            RowLayout {
                id: headerLayout
                anchors.fill: parent
                anchors.margins: Kirigami.Units.mediumSpacing
                spacing: Kirigami.Units.mediumSpacing

                Rectangle {
                    width: Kirigami.Units.iconSizes.large
                    height: Kirigami.Units.iconSizes.large
                    radius: width / 2
                    color: Kirigami.Theme.highlightColor
                    opacity: 0.15

                    Kirigami.Icon {
                        anchors.centerIn: parent
                        source: "input-mouse"
                        width: Kirigami.Units.iconSizes.medium
                        height: Kirigami.Units.iconSizes.medium
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    RowLayout {
                        spacing: Kirigami.Units.smallSpacing

                        QQC2.Label {
                            text: targetButtonName || ("Button " + (targetButtonIndex + 1))
                            font.bold: true
                            font.pointSize: Kirigami.Theme.defaultFont.pointSize + 2
                        }

                        Rectangle {
                            visible: Boolean(buttonLocation)
                            color: Kirigami.Theme.focusColor
                            opacity: 0.2
                            radius: 4
                            implicitWidth: locLabel.implicitWidth + 8
                            implicitHeight: locLabel.implicitHeight + 4

                            QQC2.Label {
                                id: locLabel
                                anchors.centerIn: parent
                                text: buttonLocation
                                font.pointSize: Kirigami.Theme.smallFont.pointSize
                                font.bold: true
                            }
                        }
                    }

                    RowLayout {
                        spacing: Kirigami.Units.smallSpacing

                        QQC2.Label {
                            text: "Current: "
                            opacity: 0.7
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                        }

                        Rectangle {
                            color: Kirigami.Theme.highlightColor
                            radius: 4
                            implicitWidth: curActLbl.implicitWidth + 8
                            implicitHeight: curActLbl.implicitHeight + 4

                            QQC2.Label {
                                id: curActLbl
                                anchors.centerIn: parent
                                text: currentActionDisplay || "Default"
                                color: Kirigami.Theme.highlightedTextColor
                                font.pointSize: Kirigami.Theme.smallFont.pointSize
                                font.bold: true
                            }
                        }

                        QQC2.Label {
                            visible: Boolean(defaultAction && currentAction && currentAction !== defaultAction)
                            text: "• Customized"
                            color: Kirigami.Theme.neutralTextColor
                            font.pointSize: Kirigami.Theme.smallFont.pointSize
                        }
                    }
                }

                // Quick Reset to Default Button in Header
                QQC2.Button {
                    visible: Boolean(defaultAction && currentAction && currentAction !== defaultAction)
                    text: "Reset to Default"
                    icon.name: "document-revert"
                    onClicked: root.resetToDefault()
                }
            }
        }

        // Search Bar
        QQC2.TextField {
            id: searchInput
            Layout.fillWidth: true
            placeholderText: "🔍 Search all shortcuts, actions, keys (e.g. 'copy', 'mute', 'dpi', 'f5')..."
            onTextChanged: root.searchFilter = text
            rightPadding: clearSearchBtn.visible ? clearSearchBtn.width + Kirigami.Units.smallSpacing : Kirigami.Units.smallSpacing

            QQC2.ToolButton {
                id: clearSearchBtn
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                visible: searchInput.text.length > 0
                icon.name: "edit-clear"
                onClicked: {
                    searchInput.text = ""
                    root.searchFilter = ""
                }
            }
        }

        // When search query is active, show search results directly
        ColumnLayout {
            visible: root.searchFilter.trim().length > 0
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            QQC2.Label {
                text: "Search Results (" + root.searchResults.length + " matching actions):"
                font.bold: true
                opacity: 0.8
            }

            QQC2.ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: Kirigami.Units.gridUnit * 13
                clip: true

                Flow {
                    width: parent.width
                    spacing: Kirigami.Units.smallSpacing

                    Repeater {
                        model: root.searchResults
                        QQC2.Button {
                            icon.name: modelData.icon || "input-keyboard"
                            text: modelData.label + " [" + modelData.cat + "]"
                            onClicked: root.selectAction(modelData.action)
                        }
                    }
                }
            }
        }

        // Category TabBar & StackLayout (Shown when NOT searching)
        ColumnLayout {
            visible: root.searchFilter.trim().length === 0
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            QQC2.TabBar {
                id: categoryTabs
                Layout.fillWidth: true
                currentIndex: 0

                QQC2.TabButton {
                    text: "⚡ Shortcuts"
                }
                QQC2.TabButton {
                    text: "🖱️ Mouse"
                }
                QQC2.TabButton {
                    text: "🎯 DPI & Sensor"
                }
                QQC2.TabButton {
                    text: "🎵 Media"
                }
                QQC2.TabButton {
                    text: "⌨️ Keyboard"
                }
                QQC2.TabButton {
                    text: "🚫 Disable"
                }
            }

            StackLayout {
                id: tabContent
                currentIndex: categoryTabs.currentIndex
                Layout.fillWidth: true

                // Tab 0: Shortcuts & Productivity
                ColumnLayout {
                    spacing: Kirigami.Units.mediumSpacing
                    Layout.fillWidth: true

                    QQC2.Label {
                        text: "Common Productivity & System Shortcuts:"
                        font.bold: true
                        opacity: 0.8
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        Repeater {
                            model: [
                                { label: "Copy (Ctrl+C)", action: "macro +KEY_LEFTCTRL KEY_C -KEY_LEFTCTRL", icon: "edit-copy" },
                                { label: "Paste (Ctrl+V)", action: "macro +KEY_LEFTCTRL KEY_V -KEY_LEFTCTRL", icon: "edit-paste" },
                                { label: "Cut (Ctrl+X)", action: "macro +KEY_LEFTCTRL KEY_X -KEY_LEFTCTRL", icon: "edit-cut" },
                                { label: "Undo (Ctrl+Z)", action: "macro +KEY_LEFTCTRL KEY_Z -KEY_LEFTCTRL", icon: "edit-undo" },
                                { label: "Redo (Ctrl+Y)", action: "macro +KEY_LEFTCTRL KEY_Y -KEY_LEFTCTRL", icon: "edit-redo" },
                                { label: "Select All (Ctrl+A)", action: "macro +KEY_LEFTCTRL KEY_A -KEY_LEFTCTRL", icon: "edit-select-all" },
                                { label: "Save (Ctrl+S)", action: "macro +KEY_LEFTCTRL KEY_S -KEY_LEFTCTRL", icon: "document-save" },
                                { label: "Find (Ctrl+F)", action: "macro +KEY_LEFTCTRL KEY_F -KEY_LEFTCTRL", icon: "edit-find" },
                                { label: "New Tab (Ctrl+T)", action: "macro +KEY_LEFTCTRL KEY_T -KEY_LEFTCTRL", icon: "tab-new" },
                                { label: "Close Tab (Ctrl+W)", action: "macro +KEY_LEFTCTRL KEY_W -KEY_LEFTCTRL", icon: "tab-close" },
                                { label: "Switch App (Alt+Tab)", action: "macro +KEY_LEFTALT KEY_TAB -KEY_LEFTALT", icon: "window-duplicate" },
                                { label: "Show Desktop (Super)", action: "key KEY_LEFTMETA", icon: "user-desktop" },
                                { label: "Refresh (F5)", action: "key KEY_F5", icon: "view-refresh" },
                                { label: "Screenshot (Print)", action: "key KEY_PRINT", icon: "camera-photo" }
                            ]

                            QQC2.Button {
                                icon.name: modelData.icon
                                text: modelData.label
                                onClicked: root.selectAction(modelData.action)
                            }
                        }
                    }
                }

                // Tab 1: Mouse Clicks
                ColumnLayout {
                    spacing: Kirigami.Units.mediumSpacing
                    Layout.fillWidth: true

                    QQC2.Label {
                        text: "Standard Mouse Functions:"
                        font.bold: true
                        opacity: 0.8
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        Repeater {
                            model: [
                                { label: "Left Click (1)", action: "button 1", icon: "input-mouse" },
                                { label: "Right Click (2)", action: "button 2", icon: "input-mouse" },
                                { label: "Middle Click (3)", action: "button 3", icon: "input-mouse" },
                                { label: "Back (Button 4)", action: "button 4", icon: "go-previous" },
                                { label: "Forward (Button 5)", action: "button 5", icon: "go-next" },
                                { label: "Button 6", action: "button 6", icon: "input-mouse" },
                                { label: "Button 7", action: "button 7", icon: "input-mouse" },
                                { label: "Button 8", action: "button 8", icon: "input-mouse" },
                                { label: "Double Click", action: "special doubleclick", icon: "input-mouse" },
                                { label: "Wheel Tilt Left", action: "special wheel-left", icon: "arrow-left" },
                                { label: "Wheel Tilt Right", action: "special wheel-right", icon: "arrow-right" }
                            ]

                            QQC2.Button {
                                icon.name: modelData.icon
                                text: modelData.label
                                onClicked: root.selectAction(modelData.action)
                            }
                        }
                    }
                }

                // Tab 2: Special & DPI
                ColumnLayout {
                    spacing: Kirigami.Units.mediumSpacing
                    Layout.fillWidth: true

                    QQC2.Label {
                        text: "Sensor DPI & Profile Switching:"
                        font.bold: true
                        opacity: 0.8
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        Repeater {
                            model: [
                                { label: "🎯 DPI Shift (Sniper Mode)", action: "special resolution-alternate", icon: "target" },
                                { label: "⚡ Increase DPI (+)", action: "special resolution-up", icon: "arrow-up" },
                                { label: "⚡ Decrease DPI (-)", action: "special resolution-down", icon: "arrow-down" },
                                { label: "🔄 Cycle DPI Presets", action: "special resolution-cycle-up", icon: "view-refresh" },
                                { label: "📋 Cycle Profile", action: "special profile-cycle-up", icon: "document-properties" },
                                { label: "🛡️ G-Shift (Secondary Mode)", action: "special second-mode", icon: "dialog-password" }
                            ]

                            QQC2.Button {
                                icon.name: modelData.icon
                                text: modelData.label
                                onClicked: root.selectAction(modelData.action)
                            }
                        }
                    }
                }

                // Tab 3: Media & Audio
                ColumnLayout {
                    spacing: Kirigami.Units.mediumSpacing
                    Layout.fillWidth: true

                    QQC2.Label {
                        text: "Media Playback & System Volume:"
                        font.bold: true
                        opacity: 0.8
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        Repeater {
                            model: [
                                { label: "🔊 Volume Up", action: "key KEY_VOLUMEUP", icon: "audio-volume-high" },
                                { label: "🔉 Volume Down", action: "key KEY_VOLUMEDOWN", icon: "audio-volume-low" },
                                { label: "🔇 Mute Audio", action: "key KEY_MUTE", icon: "audio-volume-muted" },
                                { label: "⏯️ Play / Pause", action: "key KEY_PLAYPAUSE", icon: "media-playback-start" },
                                { label: "⏭️ Next Track", action: "key KEY_NEXTSONG", icon: "media-skip-forward" },
                                { label: "⏮️ Previous Track", action: "key KEY_PREVIOUSSONG", icon: "media-skip-backward" }
                            ]

                            QQC2.Button {
                                icon.name: modelData.icon
                                text: modelData.label
                                onClicked: root.selectAction(modelData.action)
                            }
                        }
                    }
                }

                // Tab 4: Keyboard Keys & Live Recorder
                ColumnLayout {
                    spacing: Kirigami.Units.mediumSpacing
                    Layout.fillWidth: true

                    // Interactive Key Recorder Box
                    Rectangle {
                        id: recorderBox
                        Layout.fillWidth: true
                        implicitHeight: Kirigami.Units.gridUnit * 5
                        color: root.isRecordingKey ? Kirigami.Theme.highlightColor : Kirigami.Theme.alternateBackgroundColor
                        opacity: root.isRecordingKey ? 0.25 : 1.0
                        radius: Kirigami.Units.smallSpacing
                        border.color: root.isRecordingKey ? Kirigami.Theme.highlightColor : Kirigami.Theme.separatorColor
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
                            anchors.fill: parent
                            anchors.margins: Kirigami.Units.mediumSpacing
                            spacing: Kirigami.Units.mediumSpacing

                            Kirigami.Icon {
                                source: "input-keyboard"
                                width: Kirigami.Units.iconSizes.large
                                height: Kirigami.Units.iconSizes.large
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                QQC2.Label {
                                    text: root.isRecordingKey ? "🎮 Listening for key press..." : (root.recordedDisplay ? ("Recorded: " + root.recordedDisplay) : "Live Keyboard Capture")
                                    font.bold: true
                                    font.pointSize: Kirigami.Theme.defaultFont.pointSize + 1
                                }

                                QQC2.Label {
                                    text: root.isRecordingKey
                                          ? "Press ANY key or shortcut on your keyboard now (e.g. F5, Ctrl+C, Space, Esc, Tab)..."
                                          : "Click 'Record Key' to capture any physical keypress directly from your keyboard."
                                    opacity: 0.7
                                    font.pointSize: Kirigami.Theme.smallFont.pointSize
                                }
                            }

                            QQC2.Button {
                                text: root.isRecordingKey ? "Cancel" : "Record Key"
                                icon.name: root.isRecordingKey ? "dialog-cancel" : "media-record"
                                highlighted: root.isRecordingKey
                                onClicked: {
                                    root.isRecordingKey = !root.isRecordingKey
                                    if (root.isRecordingKey) {
                                        recorderBox.forceActiveFocus()
                                    }
                                }
                            }

                            QQC2.Button {
                                visible: Boolean(root.recordedAction)
                                text: "Assign: " + root.recordedDisplay
                                icon.name: "dialog-ok-apply"
                                highlighted: true
                                onClicked: root.selectAction(root.recordedAction)
                            }
                        }
                    }

                    QQC2.Label {
                        text: "Common Keyboard Keys:"
                        font.bold: true
                        opacity: 0.8
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        Repeater {
                            model: [
                                { label: "Enter", action: "key KEY_ENTER" },
                                { label: "Space", action: "key KEY_SPACE" },
                                { label: "Escape", action: "key KEY_ESC" },
                                { label: "Tab", action: "key KEY_TAB" },
                                { label: "Backspace", action: "key KEY_BACKSPACE" },
                                { label: "Delete", action: "key KEY_DELETE" },
                                { label: "Left Shift", action: "key KEY_LEFTSHIFT" },
                                { label: "Left Ctrl", action: "key KEY_LEFTCTRL" },
                                { label: "Left Alt", action: "key KEY_LEFTALT" },
                                { label: "Super / Win", action: "key KEY_LEFTMETA" },
                                { label: "F1", action: "key KEY_F1" },
                                { label: "F2", action: "key KEY_F2" },
                                { label: "F3", action: "key KEY_F3" },
                                { label: "F4", action: "key KEY_F4" },
                                { label: "F5", action: "key KEY_F5" },
                                { label: "F6", action: "key KEY_F6" },
                                { label: "F7", action: "key KEY_F7" },
                                { label: "F8", action: "key KEY_F8" },
                                { label: "F9", action: "key KEY_F9" },
                                { label: "F10", action: "key KEY_F10" },
                                { label: "F11", action: "key KEY_F11" },
                                { label: "F12", action: "key KEY_F12" }
                            ]

                            QQC2.Button {
                                text: modelData.label
                                onClicked: root.selectAction(modelData.action)
                            }
                        }
                    }

                    Kirigami.Separator {
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Kirigami.Units.smallSpacing

                        QQC2.TextField {
                            id: customKeyInput
                            Layout.fillWidth: true
                            placeholderText: "Or type manual keycode (e.g. C, F11, or KEY_ENTER)..."
                            onAccepted: root.assignCustomKey()
                        }

                        QQC2.Button {
                            text: "Assign"
                            icon.name: "dialog-ok-apply"
                            enabled: customKeyInput.text.trim().length > 0
                            onClicked: root.assignCustomKey()
                        }
                    }
                }

                // Tab 5: Disable
                ColumnLayout {
                    spacing: Kirigami.Units.mediumSpacing
                    Layout.fillWidth: true

                    QQC2.Label {
                        text: "Disable Button:"
                        font.bold: true
                        opacity: 0.8
                    }

                    QQC2.Label {
                        text: "Disables this button completely so that clicking it sends no action or keypress to the system."
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        opacity: 0.7
                    }

                    QQC2.Button {
                        text: "Disable This Button"
                        icon.name: "dialog-cancel"
                        onClicked: root.selectAction("disabled")
                    }
                }
            }
        }
    }
}
