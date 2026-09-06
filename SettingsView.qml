import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Column {
  id: root

  property var catalog: []
  property var enabledMap: ({})
  property int refreshIntervalSec: Model.DEFAULT_REFRESH_SEC
  property string companyFilter: ""
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  readonly property var filteredCatalog: Model.filterCatalog(catalog, companyFilter)

  signal companyToggled(string id, bool enabled)
  signal intervalModified(int seconds)

  spacing: Style.space(12)

  NumberField {
    width: parent.width
    label: "Poll interval (seconds)"
    value: root.refreshIntervalSec
    from: Model.MIN_REFRESH_SEC
    to: Model.MAX_REFRESH_SEC
    stepSize: Model.MIN_REFRESH_SEC
    foreground: root.foreground
    fontFamily: root.fontFamily
    onModified: function(next) {
      root.intervalModified(Model.clampRefreshInterval(next, root.refreshIntervalSec))
    }
  }

  PanelSectionHeader {
    text: "Companies"
    foreground: root.foreground
    fontFamily: root.fontFamily
  }

  TextField {
    width: parent.width
    placeholderText: "Filter companies"
    foreground: root.foreground
    font.family: root.fontFamily
    onTextChanged: root.companyFilter = text
  }

  Text {
    visible: root.filteredCatalog.length === 0
    width: parent.width
    text: "No companies match that filter."
    color: Qt.darker(root.foreground, 1.5)
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
  }

  Repeater {
    model: root.filteredCatalog

    Toggle {
      required property var modelData
      width: parent.width
      label: modelData.name
      description: modelData.url
      checked: Model.isEnabled(modelData.id, root.enabledMap)
      foreground: root.foreground
      fontFamily: root.fontFamily
      onClicked: root.companyToggled(modelData.id, !Model.isEnabled(modelData.id, root.enabledMap))
    }
  }
}
