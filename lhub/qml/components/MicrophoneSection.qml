import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import ".."

ColumnLayout {
    id: root

    property var deviceData: ({})
    property string _lastDeviceId: ""

    signal volumeChanged(int volume)
    signal mutedToggled(bool muted)
    signal eqEnabledToggled(bool enabled)
    signal highpassChanged(bool enabled, int freq)
    signal eqBandChanged(string bandId, real gain)
    signal presetSelected(string presetName)
    signal monitoringToggled(bool enabled)
    signal defaultSourceRequested(bool useEqSource)
    signal profileSelected(string profileName)
    signal saveProfileRequested(string profileName)
    signal newProfileRequested()
    signal deleteProfileRequested(string profileName)
    signal resetDefaultRequested()

    readonly property Theme theme: Theme {}
    readonly property bool hasMic: Boolean(root.deviceData && root.deviceData.hasMicrophone)
    readonly property bool isMuted: Boolean(root.deviceData && root.deviceData.micMuted)
    readonly property bool isMonitoring: Boolean(root.deviceData && root.deviceData.micMonitoring)
    readonly property bool isEqEnabled: Boolean(root.deviceData && root.deviceData.micEqEnabled)
    readonly property bool isHpfEnabled: Boolean(root.deviceData && root.deviceData.micHighpassEnabled)
    readonly property bool isVirtualActive: Boolean(root.deviceData && root.deviceData.micVirtualSourceActive)
    readonly property bool isEqDefault: Boolean(root.deviceData && root.deviceData.micIsEqDefaultSource)
    readonly property var bandsList: (root.deviceData && root.deviceData.micEqBands) ? root.deviceData.micEqBands : []
    readonly property int bandCount: bandsList.length
    readonly property var presetsList: (root.deviceData && root.deviceData.micPresets) ? root.deviceData.micPresets : []

    visible: root.hasMic
    spacing: 16

    onDeviceDataChanged: {
        var nextId = root.deviceData && root.deviceData.id ? String(root.deviceData.id) : ""
        if (nextId !== root._lastDeviceId) {
            volumeDebounce.stop()
            hpfDebounce.stop()
            root._lastDeviceId = nextId
        }
    }

    function formatDb(val) {
        var rounded = Math.round(val * 2) / 2
        if (Math.abs(rounded) < 0.05) return "0.0 dB"
        var prefix = rounded > 0 ? "+" : ""
        return prefix + rounded.toFixed(1) + " dB"
    }

    Timer {
        id: volumeDebounce
        interval: 45
        repeat: false
        onTriggered: root.volumeChanged(Math.round(volumeSlider.value))
    }

    Timer {
        id: hpfDebounce
        interval: 45
        repeat: false
        onTriggered: root.highpassChanged(root.isHpfEnabled, Math.round(hpfSlider.value))
    }

    // =========================================================================
    // 1. INPUT GAIN, MUTE, LIVE VOICE TEST & DEFAULT SOURCE CARD
    // =========================================================================
    Rectangle {
        Layout.fillWidth: true
        radius: theme.radiusLg
        color: theme.bgSurface
        border.color: root.isMonitoring ? theme.positive : theme.borderSubtle
        border.width: 1
        implicitHeight: inputCol.implicitHeight + 36

        Behavior on border.color { ColorAnimation { duration: 180 } }

        ColumnLayout {
            id: inputCol
            anchors.fill: parent
            anchors.margins: 18
            spacing: 16

            // Header Row with Mute & Live Test Toggle
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        text: "Microphone Audio"
                        color: theme.textPrimary
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }

                    Text {
                        text: "Control input gain, mute state, and monitor your processed voice live."
                        color: theme.textSecondary
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }

                // Mute Toggle Button
                UiButton {
                    text: root.isMuted ? "Muted" : "Mute"
                    variant: root.isMuted ? "danger" : "default"
                    iconName: root.isMuted ? "microphone-sensitivity-muted-symbolic" : "audio-input-microphone-symbolic"
                    checkable: true
                    checked: root.isMuted
                    toolTipText: root.isMuted ? "Unmute microphone" : "Mute microphone"
                    onClicked: root.mutedToggled(!root.isMuted)
                }

                // Live Voice Monitor ("Test") Toggle Button
                UiButton {
                    id: testVoiceBtn
                    text: root.isMonitoring ? "Stop Test" : "Test Voice"
                    iconName: root.isMonitoring ? "media-playback-stop-symbolic" : "audio-headphones-symbolic"
                    checkable: true
                    checked: root.isMonitoring
                    toolTipText: "Hear your own voice live through your output device while tuning the EQ"
                    onClicked: root.monitoringToggled(!root.isMonitoring)
                }
            }

            // Live Monitoring Banner
            Rectangle {
                visible: root.isMonitoring
                Layout.fillWidth: true
                radius: theme.radiusMd
                color: theme.positiveSoft
                border.color: theme.positive
                border.width: 1
                implicitHeight: monitorBannerRow.implicitHeight + 18

                RowLayout {
                    id: monitorBannerRow
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 10
                    anchors.topMargin: 9
                    anchors.bottomMargin: 9
                    spacing: 10

                    Rectangle {
                        width: 9
                        height: 9
                        radius: 5
                        color: theme.positive

                        SequentialAnimation on opacity {
                            running: root.isMonitoring
                            loops: Animation.Infinite
                            NumberAnimation { from: 1.0; to: 0.3; duration: 650; easing.type: Easing.InOutSine }
                            NumberAnimation { from: 0.3; to: 1.0; duration: 650; easing.type: Easing.InOutSine }
                        }
                    }

                    Text {
                        text: "Live Voice Test active — speak into your mic while adjusting any EQ slider below to hear changes in real time."
                        color: theme.textPrimary
                        font.pixelSize: 12
                        font.weight: Font.Medium
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }

                    UiButton {
                        variant: "subtle"
                        compact: true
                        text: "Stop"
                        onClicked: root.monitoringToggled(false)
                    }
                }
            }

            // Input Gain Slider
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                RowLayout {
                    Layout.fillWidth: true

                    Text {
                        text: "Input Gain"
                        color: theme.textPrimary
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }

                    Item { Layout.fillWidth: true }

                    Rectangle {
                        radius: theme.radiusPill
                        color: root.isMuted ? theme.dangerSoft : theme.accentSoft
                        border.color: root.isMuted ? theme.dangerBorder : theme.accentBorder
                        border.width: 1
                        implicitWidth: volValLbl.implicitWidth + 20
                        implicitHeight: 26

                        Text {
                            id: volValLbl
                            anchors.centerIn: parent
                            text: root.isMuted ? "Muted" : (Math.round(volumeSlider.value) + "%")
                            color: root.isMuted ? theme.danger : theme.accent
                            font.pixelSize: 12
                            font.weight: Font.Bold
                        }
                    }
                }

                QQC2.Slider {
                    id: volumeSlider
                    Layout.fillWidth: true
                    implicitHeight: 28
                    from: 0
                    to: 150
                    stepSize: 1
                    opacity: root.isMuted ? 0.5 : 1.0

                    Binding {
                        target: volumeSlider
                        property: "value"
                        value: root.deviceData.micVolume !== undefined ? root.deviceData.micVolume : 100
                        when: !volumeSlider.pressed && !volumeDebounce.running
                    }

                    onMoved: {
                        if (pressed) {
                            volumeDebounce.restart()
                        } else {
                            volumeDebounce.stop()
                            root.volumeChanged(Math.round(value))
                        }
                    }

                    onPressedChanged: {
                        if (!pressed && volumeDebounce.running) {
                            volumeDebounce.stop()
                            root.volumeChanged(Math.round(value))
                        }
                    }

                    background: Rectangle {
                        x: volumeSlider.leftPadding
                        y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                        width: volumeSlider.availableWidth
                        height: 6
                        radius: 3
                        color: theme.bgControl
                        border.color: theme.borderSubtle
                        border.width: 1

                        // 100% reference tick
                        Rectangle {
                            x: parent.width * (100.0 / 150.0)
                            y: -3
                            width: 1
                            height: parent.height + 6
                            color: theme.borderStrong
                        }

                        Rectangle {
                            width: volumeSlider.visualPosition * parent.width
                            height: parent.height
                            radius: 3
                            color: volumeSlider.value > 100 ? theme.warning : theme.accent
                        }
                    }

                    handle: Rectangle {
                        x: volumeSlider.leftPadding + volumeSlider.visualPosition * (volumeSlider.availableWidth - width)
                        y: volumeSlider.topPadding + volumeSlider.availableHeight / 2 - height / 2
                        width: 18
                        height: 18
                        radius: 9
                        color: volumeSlider.pressed ? theme.accentHover : theme.textPrimary
                        border.color: volumeSlider.value > 100 ? theme.warning : theme.accent
                        border.width: volumeSlider.hovered || volumeSlider.pressed ? 3 : 2

                        Behavior on border.width { NumberAnimation { duration: 100 } }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true

                    Text { text: "0%"; color: theme.textMuted; font.pixelSize: 11 }
                    Item { Layout.fillWidth: true }
                    Text { text: "100% (Nominal)"; color: theme.textMuted; font.pixelSize: 11 }
                    Item { Layout.fillWidth: true }
                    Text { text: "150% (Boost)"; color: theme.textMuted; font.pixelSize: 11 }
                }
            }

            // Hairline Divider
            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: theme.borderSubtle
            }

            // Virtual PipeWire Source / System Default Mic Bar
            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                Rectangle {
                    width: 8
                    height: 8
                    radius: 4
                    color: root.isEqDefault ? theme.positive : (root.isVirtualActive ? theme.accent : theme.textMuted)
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        text: root.deviceData.micVirtualSourceDescription || "L-Hub PipeWire EQ Source"
                        color: theme.textPrimary
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    Text {
                        text: root.isEqDefault
                              ? "Active as your default PipeWire microphone — apps like Discord & OBS receive your EQ."
                              : "Select as default microphone so apps automatically receive your PipeWire EQ signal."
                        color: theme.textSecondary
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }

                Rectangle {
                    visible: root.isEqDefault
                    radius: theme.radiusPill
                    color: theme.positiveSoft
                    border.color: theme.positive
                    border.width: 1
                    implicitWidth: defBadgeLbl.implicitWidth + 18
                    implicitHeight: 28

                    Text {
                        id: defBadgeLbl
                        anchors.centerIn: parent
                        text: "Default Mic"
                        color: theme.positive
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }

                UiButton {
                    visible: !root.isEqDefault
                    variant: "primary"
                    compact: true
                    text: "Set as Default Mic"
                    iconName: "audio-input-microphone-symbolic"
                    toolTipText: "Route apps to the L-Hub PipeWire EQ virtual microphone by default"
                    onClicked: root.defaultSourceRequested(true)
                }
            }
        }
    }

    // =========================================================================
    // 2. PROFILES, PRESETS & 6-BAND EQUALIZER CARD
    // =========================================================================
    Rectangle {
        Layout.fillWidth: true
        radius: theme.radiusLg
        color: theme.bgSurface
        border.color: theme.borderSubtle
        border.width: 1
        implicitHeight: eqCardCol.implicitHeight + 36

        ColumnLayout {
            id: eqCardCol
            anchors.fill: parent
            anchors.margins: 18
            spacing: 16

            // Profile Bar (Save / New / Reset / Delete)
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

            // Equalizer Header + Bypass Switch
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        text: "Voice Equalizer"
                        color: theme.textPrimary
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }

                    Text {
                        text: "Native 6-band PipeWire biquad EQ. Double-click any band value to reset it to 0 dB."
                        color: theme.textSecondary
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }

                UiButton {
                    text: root.isEqEnabled ? "EQ Active" : "EQ Bypassed"
                    iconName: root.isEqEnabled ? "view-media-equalizer" : "audio-volume-muted-symbolic"
                    checkable: true
                    checked: root.isEqEnabled
                    toolTipText: "Toggle EQ processing on or off for instant A/B comparison"
                    onClicked: root.eqEnabledToggled(!root.isEqEnabled)
                }
            }

            // Quick Presets Row
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Text {
                    text: "Quick Presets"
                    color: theme.textSecondary
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 8

                    Repeater {
                        model: root.presetsList.length

                        UiButton {
                            readonly property var presetObj: (index < root.presetsList.length) ? root.presetsList[index] : null
                            variant: "pill"
                            compact: true
                            text: presetObj ? presetObj.name : ""
                            toolTipText: presetObj ? presetObj.description : ""
                            onClicked: {
                                if (presetObj && presetObj.name) {
                                    root.presetSelected(presetObj.name)
                                }
                            }
                        }
                    }
                }
            }

            // 6-Band Vertical Equalizer Rack
            Rectangle {
                Layout.fillWidth: true
                radius: theme.radiusMd
                color: theme.bgControl
                border.color: root.isEqEnabled ? theme.borderSubtle : theme.borderSubtle
                border.width: 1
                implicitHeight: eqRackRow.implicitHeight + 28
                opacity: root.isEqEnabled ? 1.0 : 0.48

                Behavior on opacity { NumberAnimation { duration: 150 } }

                RowLayout {
                    id: eqRackRow
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 8

                    // Left dB scale legend
                    ColumnLayout {
                        Layout.fillHeight: true
                        Layout.preferredWidth: 34
                        Layout.topMargin: 28
                        Layout.bottomMargin: 42

                        Text {
                            text: "+12"
                            color: theme.textMuted
                            font.pixelSize: 10
                            font.weight: Font.Medium
                            Layout.alignment: Qt.AlignRight
                        }
                        Item { Layout.fillHeight: true }
                        Text {
                            text: "0 dB"
                            color: theme.textSecondary
                            font.pixelSize: 10
                            font.weight: Font.DemiBold
                            Layout.alignment: Qt.AlignRight
                        }
                        Item { Layout.fillHeight: true }
                        Text {
                            text: "-12"
                            color: theme.textMuted
                            font.pixelSize: 10
                            font.weight: Font.Medium
                            Layout.alignment: Qt.AlignRight
                        }
                    }

                    // 6 Fixed-Count EQ Band Columns (never recreated during drag)
                    Repeater {
                        model: root.bandCount

                        Item {
                            id: bandCol
                            readonly property var bandData: (index < root.bandsList.length) ? root.bandsList[index] : null
                            readonly property string bandId: bandData ? String(bandData.id) : ("eq_band_" + (index + 1))
                            readonly property real serverGain: (bandData && bandData.gain !== undefined) ? Number(bandData.gain) : 0.0

                            Layout.fillWidth: true
                            implicitHeight: bandLayout.implicitHeight

                            Timer {
                                id: bandDebounce
                                interval: 35
                                repeat: false
                                onTriggered: root.eqBandChanged(bandCol.bandId, Math.round(bandSlider.value * 2) / 2)
                            }

                            ColumnLayout {
                                id: bandLayout
                                anchors.left: parent.left
                                anchors.right: parent.right
                                spacing: 8

                                // Live dB badge (double-click resets band to 0 dB)
                                Rectangle {
                                    Layout.alignment: Qt.AlignHCenter
                                    radius: theme.radiusXs
                                    color: {
                                        if (bandSlider.value > 0.05) return theme.accentSoft
                                        if (bandSlider.value < -0.05) return theme.purpleSoft
                                        return theme.bgSurface
                                    }
                                    border.color: {
                                        if (bandSlider.value > 0.05) return theme.accentBorder
                                        if (bandSlider.value < -0.05) return theme.purple
                                        return theme.borderSubtle
                                    }
                                    border.width: 1
                                    implicitWidth: 62
                                    implicitHeight: 22

                                    Text {
                                        anchors.centerIn: parent
                                        text: root.formatDb(bandSlider.value)
                                        color: {
                                            if (bandSlider.value > 0.05) return theme.accent
                                            if (bandSlider.value < -0.05) return theme.purple
                                            return theme.textSecondary
                                        }
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onDoubleClicked: {
                                            bandDebounce.stop()
                                            bandSlider.value = 0.0
                                            root.eqBandChanged(bandCol.bandId, 0.0)
                                        }
                                    }
                                }

                                // Vertical EQ Fader
                                QQC2.Slider {
                                    id: bandSlider
                                    orientation: Qt.Vertical
                                    Layout.alignment: Qt.AlignHCenter
                                    implicitWidth: 32
                                    implicitHeight: 156
                                    from: -12.0
                                    to: 12.0
                                    stepSize: 0.5

                                    Binding {
                                        target: bandSlider
                                        property: "value"
                                        value: bandCol.serverGain
                                        when: !bandSlider.pressed && !bandDebounce.running
                                    }

                                    onMoved: {
                                        if (pressed) {
                                            bandDebounce.restart()
                                        } else {
                                            bandDebounce.stop()
                                            root.eqBandChanged(bandCol.bandId, Math.round(value * 2) / 2)
                                        }
                                    }

                                    onPressedChanged: {
                                        if (!pressed && bandDebounce.running) {
                                            bandDebounce.stop()
                                            root.eqBandChanged(bandCol.bandId, Math.round(value * 2) / 2)
                                        }
                                    }

                                    background: Item {
                                        x: bandSlider.leftPadding + bandSlider.availableWidth / 2 - width / 2
                                        y: bandSlider.topPadding
                                        width: 24
                                        height: bandSlider.availableHeight

                                        // Center 0 dB reference line
                                        Rectangle {
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            y: parent.height / 2
                                            width: 20
                                            height: 1
                                            color: theme.borderStrong
                                        }

                                        // Track rail
                                        Rectangle {
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            y: 0
                                            width: 6
                                            height: parent.height
                                            radius: 3
                                            color: theme.bgSurface
                                            border.color: theme.borderSubtle
                                            border.width: 1

                                            // Center-origin boost/cut fill bar
                                            Rectangle {
                                                readonly property real midY: parent.height / 2
                                                readonly property real handleY: (1.0 - bandSlider.position) * parent.height
                                                x: 0
                                                width: parent.width
                                                y: Math.min(midY, handleY)
                                                height: Math.abs(handleY - midY)
                                                radius: 3
                                                color: bandSlider.value >= 0 ? theme.accent : theme.purple
                                            }
                                        }
                                    }

                                    handle: Rectangle {
                                        x: bandSlider.leftPadding + bandSlider.availableWidth / 2 - width / 2
                                        y: bandSlider.topPadding + (1.0 - bandSlider.position) * (bandSlider.availableHeight - height)
                                        width: 18
                                        height: 18
                                        radius: 9
                                        color: bandSlider.pressed ? theme.accentHover : theme.textPrimary
                                        border.color: bandSlider.value < -0.05 ? theme.purple : theme.accent
                                        border.width: bandSlider.hovered || bandSlider.pressed ? 3 : 2

                                        Behavior on border.width { NumberAnimation { duration: 100 } }
                                    }
                                }

                                // Band Label & Frequency
                                ColumnLayout {
                                    Layout.alignment: Qt.AlignHCenter
                                    spacing: 1

                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: bandCol.bandData ? (bandCol.bandData.label || "") : ""
                                        color: theme.textPrimary
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }

                                    Text {
                                        Layout.alignment: Qt.AlignHCenter
                                        text: bandCol.bandData ? (bandCol.bandData.freqLabel || "") : ""
                                        color: theme.textMuted
                                        font.pixelSize: 11
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // Hairline Divider
            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: theme.borderSubtle
            }

            // High-Pass Filter (Low-Cut) Controls
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 10
                opacity: root.isEqEnabled ? 1.0 : 0.48

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Text {
                            text: "High-Pass Filter (Low-Cut)"
                            color: theme.textPrimary
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                        }

                        Text {
                            text: "Filters out low-frequency desk rumble, bumps, and heavy plosives."
                            color: theme.textSecondary
                            font.pixelSize: 12
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }

                    Rectangle {
                        radius: theme.radiusPill
                        color: root.isHpfEnabled ? theme.accentSoft : theme.bgControl
                        border.color: root.isHpfEnabled ? theme.accentBorder : theme.borderSubtle
                        border.width: 1
                        implicitWidth: hpfBadgeLbl.implicitWidth + 20
                        implicitHeight: 28

                        Text {
                            id: hpfBadgeLbl
                            anchors.centerIn: parent
                            text: root.isHpfEnabled ? (Math.round(hpfSlider.value) + " Hz") : "Off"
                            color: root.isHpfEnabled ? theme.accent : theme.textSecondary
                            font.pixelSize: 12
                            font.weight: Font.Bold
                        }
                    }

                    UiButton {
                        text: root.isHpfEnabled ? "On" : "Off"
                        compact: true
                        checkable: true
                        checked: root.isHpfEnabled
                        onClicked: root.highpassChanged(!root.isHpfEnabled, Math.round(hpfSlider.value))
                    }
                }

                QQC2.Slider {
                    id: hpfSlider
                    Layout.fillWidth: true
                    implicitHeight: 26
                    from: 40
                    to: 250
                    stepSize: 5
                    enabled: root.isHpfEnabled && root.isEqEnabled
                    opacity: enabled ? 1.0 : 0.45

                    Binding {
                        target: hpfSlider
                        property: "value"
                        value: root.deviceData.micHighpassFreq !== undefined ? root.deviceData.micHighpassFreq : 80
                        when: !hpfSlider.pressed && !hpfDebounce.running
                    }

                    onMoved: {
                        if (pressed) {
                            hpfDebounce.restart()
                        } else {
                            hpfDebounce.stop()
                            root.highpassChanged(root.isHpfEnabled, Math.round(value))
                        }
                    }

                    onPressedChanged: {
                        if (!pressed && hpfDebounce.running) {
                            hpfDebounce.stop()
                            root.highpassChanged(root.isHpfEnabled, Math.round(value))
                        }
                    }

                    background: Rectangle {
                        x: hpfSlider.leftPadding
                        y: hpfSlider.topPadding + hpfSlider.availableHeight / 2 - height / 2
                        width: hpfSlider.availableWidth
                        height: 6
                        radius: 3
                        color: theme.bgControl
                        border.color: theme.borderSubtle
                        border.width: 1

                        Rectangle {
                            width: hpfSlider.visualPosition * parent.width
                            height: parent.height
                            radius: 3
                            color: theme.accent
                        }
                    }

                    handle: Rectangle {
                        x: hpfSlider.leftPadding + hpfSlider.visualPosition * (hpfSlider.availableWidth - width)
                        y: hpfSlider.topPadding + hpfSlider.availableHeight / 2 - height / 2
                        width: 16
                        height: 16
                        radius: 8
                        color: hpfSlider.pressed ? theme.accentHover : theme.textPrimary
                        border.color: theme.accent
                        border.width: hpfSlider.hovered || hpfSlider.pressed ? 3 : 2
                    }
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 8

                    Repeater {
                        model: [60, 80, 100, 120, 180]

                        UiButton {
                            text: modelData + " Hz"
                            compact: true
                            checkable: true
                            enabled: root.isEqEnabled
                            checked: root.isHpfEnabled && Math.round(hpfSlider.value) === modelData
                            onClicked: {
                                hpfDebounce.stop()
                                hpfSlider.value = modelData
                                root.highpassChanged(true, modelData)
                            }
                        }
                    }
                }
            }
        }
    }
}
