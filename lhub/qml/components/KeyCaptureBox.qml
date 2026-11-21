import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import ".."

Rectangle {
    id: root

    property bool isRecording: false
    property string recordedAction: ""
    property string recordedDisplay: ""

    signal recordingToggled(bool active)
    signal keyCaptured(int key, int modifiers)
    signal actionAssigned(string action)

    readonly property Theme theme: Theme {}

    implicitHeight: recRow.implicitHeight + 24
    radius: theme.radiusMd
    color: root.isRecording ? theme.accentSoft : theme.bgSurface
    border.color: root.isRecording ? theme.accent : theme.borderSubtle
    border.width: root.isRecording ? 2 : 1
    focus: true

    Keys.onPressed: function(event) {
        if (root.isRecording) {
            event.accepted = true
            root.keyCaptured(event.key, event.modifiers)
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
            color: root.isRecording ? theme.accentMedium : theme.bgControl

            Kirigami.Icon {
                anchors.centerIn: parent
                source: "input-keyboard-symbolic"
                width: 20
                height: 20
                isMask: true
                color: root.isRecording ? theme.accent : theme.textSecondary
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2

            Text {
                text: root.isRecording
                      ? "Listening for key press..."
                      : (root.recordedDisplay ? ("Captured: " + root.recordedDisplay) : "Live Keyboard Capture")
                color: root.isRecording ? theme.accent : theme.textPrimary
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }

            Text {
                text: root.isRecording
                      ? "Press any key or shortcut now (e.g. F5, Ctrl+C, Space, Esc)..."
                      : "Capture any physical key or modifier combo directly from your keyboard."
                color: theme.textSecondary
                font.pixelSize: 11
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        UiButton {
            variant: root.isRecording ? "default" : "primary"
            compact: true
            text: root.isRecording ? "Cancel" : "Record Key"
            iconName: root.isRecording ? "dialog-cancel-symbolic" : "media-record-symbolic"
            onClicked: {
                var next = !root.isRecording
                root.recordingToggled(next)
                if (next) {
                    root.forceActiveFocus()
                }
            }
        }

        UiButton {
            visible: Boolean(root.recordedAction)
            variant: "primary"
            compact: true
            text: "Assign " + root.recordedDisplay
            onClicked: root.actionAssigned(root.recordedAction)
        }
    }
}
