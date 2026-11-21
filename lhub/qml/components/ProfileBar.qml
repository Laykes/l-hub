import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import ".."

RowLayout {
    id: root

    property var deviceData: ({})

    signal profileSelected(string profileName)
    signal saveProfileRequested(string profileName)
    signal newProfileRequested()
    signal deleteProfileRequested(string profileName)
    signal resetDefaultRequested()

    readonly property Theme theme: Theme {}

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
        model: root.deviceData.profiles || ["Default"]
        currentIndex: {
            var list = root.deviceData.profiles || []
            var idx = list.indexOf(root.deviceData.activeProfile)
            return idx >= 0 ? idx : 0
        }
        onActivated: function(index) {
            var list = root.deviceData.profiles || []
            if (index >= 0 && index < list.length) {
                var pName = list[index]
                if (pName && pName !== root.deviceData.activeProfile) {
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
        toolTipText: "Save current button mapping to profile '" + (root.deviceData.activeProfile || "Default") + "'"
        onClicked: root.saveProfileRequested(root.deviceData.activeProfile || "Default")
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
        enabled: Boolean(root.deviceData.profiles && root.deviceData.profiles.length > 1 && root.deviceData.activeProfile !== "Default" && root.deviceData.activeProfile !== "Standard")
        toolTipText: "Delete active profile"
        onClicked: root.deleteProfileRequested(root.deviceData.activeProfile || "")
    }
}
