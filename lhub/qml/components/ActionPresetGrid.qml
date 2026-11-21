import QtQuick
import QtQuick.Layouts
import ".."

Flickable {
    id: root

    property string heading: ""
    property var actions: []
    property string currentAction: ""
    property bool showCategorySuffix: false
    property bool compact: false

    signal actionSelected(string action)

    readonly property Theme theme: Theme {}

    contentWidth: width
    contentHeight: contentCol.implicitHeight
    clip: true

    ColumnLayout {
        id: contentCol
        width: root.width
        spacing: 10

        Text {
            visible: root.heading.length > 0
            text: root.heading
            color: theme.textSecondary
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }

        Flow {
            Layout.fillWidth: true
            spacing: root.compact ? 6 : 8

            Repeater {
                model: root.actions

                UiButton {
                    compact: root.compact
                    iconName: modelData.icon || "input-keyboard-symbolic"
                    text: root.showCategorySuffix ? (modelData.label + " · " + modelData.cat) : modelData.label
                    checked: modelData.action === root.currentAction
                    onClicked: root.actionSelected(modelData.action)
                }
            }
        }
    }
}
