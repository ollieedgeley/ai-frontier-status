import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.ollieedgeley.ai-frontier-status"
  ipcTarget: "io.github.ollieedgeley.ai-frontier-status"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.45)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string fetchScript: Model.fileUrlToPath(Qt.resolvedUrl("fetch-status"))
  readonly property string catalogPath: Model.fileUrlToPath(Qt.resolvedUrl("companies.json"))

  property var catalog: []
  property var reportCompanies: []
  property string loadError: ""
  property string commandStdout: ""
  property string commandStderr: ""
  property bool loading: false
  property bool refreshQueued: false
  property bool settingsOpen: false
  property int lastExitCode: 0

  readonly property int refreshIntervalSec: Model.clampRefreshInterval(setting("refreshIntervalSec", 60), 60)
  readonly property var enabledMap: Model.enabledMapFromSettings(root.settings, catalog)
  readonly property var visibleCompanies: Model.visibleCompanies(catalog, reportCompanies, enabledMap)
  readonly property bool unavailable: Model.anyUnavailable(visibleCompanies)
  readonly property bool alarming: !loading && (Model.anyDegraded(visibleCompanies) || unavailable)
  readonly property string tooltipText: Model.tooltipText(visibleCompanies)
  readonly property var enabledFetchIds: Model.enabledFetchIds(catalog, enabledMap)

  function open() {
    root.controller.show()
    if (visibleCompanies.length === 0 || loadError !== "") refresh()
  }

  function close() {
    settingsOpen = false
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) close()
    else open()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function openSettings() { settingsOpen = true }
  function closeSettings() { settingsOpen = false }

  function persistWidgetSettings(values) {
    var enabledIds = values && values.enabledIds !== undefined
      ? values.enabledIds
      : Model.enabledIdList(enabledMap).join(",")
    var interval = values && values.refreshIntervalSec !== undefined
      ? values.refreshIntervalSec
      : refreshIntervalSec
    var entry = Model.widgetSettingsEntry(root.moduleName, enabledIds, interval)
    if (!entry) return false
    root.settings = entry
    if (hostWidget && "settings" in hostWidget) hostWidget.settings = entry
    if (bar && bar.shell && typeof bar.shell.updateEntryInline === "function")
      bar.shell.updateEntryInline(root.moduleName, entry)
    return true
  }

  function setCompanyEnabled(id, enabled) {
    persistWidgetSettings({
      enabledIds: Model.enabledIdList(Model.withCompanyEnabled(enabledMap, id, enabled)).join(",")
    })
    Qt.callLater(refresh)
  }

  function setRefreshInterval(seconds) {
    var next = Model.clampRefreshInterval(seconds, refreshIntervalSec)
    if (next === refreshIntervalSec) return
    persistWidgetSettings({ refreshIntervalSec: next })
  }

  function refresh() {
    if (fetchProcess.running) {
      refreshQueued = true
      return
    }
    if (enabledFetchIds.length === 0) {
      reportCompanies = []
      loadError = ""
      loading = false
      return
    }
    refreshQueued = false
    loading = true
    commandStdout = ""
    commandStderr = ""
    lastExitCode = 0
    fetchProcess.command = ["python3", fetchScript, "fetch", "--enabled", enabledFetchIds.join(",")]
    fetchProcess.running = true
  }

  function finishRefresh() {
    loading = false
    var parsed = Model.parseReport(commandStdout, catalog)
    if (lastExitCode !== 0 || !parsed.ok) {
      loadError = parsed.error || commandStderr || "Status fetch failed"
      if (refreshQueued) Qt.callLater(refresh)
      return
    }
    reportCompanies = parsed.companies
    loadError = ""
    if (refreshQueued) Qt.callLater(refresh)
  }

  function openStatusPage(url) {
    var target = String(url || "").trim()
    if (!target) return
    Qt.openUrlExternally(target)
  }

  function indicatorColor(company) {
    if (!company) return dim
    if (company.degraded || company.error) return urgent
    return foreground
  }

  onOpenedChanged: {
    if (opened) Qt.callLater(function() { keyCatcher.forceActiveFocus() })
    else settingsOpen = false
  }

  FileView {
    path: root.catalogPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.catalog = Model.catalogFromJson(text())
    onLoadFailed: if (!catalogProcess.running) catalogProcess.running = true
  }

  Process {
    id: catalogProcess
    running: false
    command: ["python3", root.fetchScript, "catalog"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var loaded = Model.catalogFromJson(text)
        if (loaded.length) root.catalog = loaded
      }
    }
  }

  Component.onCompleted: if (!catalogProcess.running) catalogProcess.running = true

  onCatalogChanged: if (catalog.length && enabledFetchIds.length) refresh()

  Timer {
    interval: root.refreshIntervalSec * 1000
    running: root.enabledFetchIds.length > 0
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  IpcHandler {
    target: root.ipcTarget

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { root.refresh() }
  }

  Process {
    id: fetchProcess
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.commandStdout = String(text || "")
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.commandStderr = String(text || "")
    }
    onExited: function(exitCode) {
      root.lastExitCode = exitCode
      Qt.callLater(root.finishRefresh)
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(390))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: root.settingsOpen

      onCloseRequested: root.settingsOpen ? root.closeSettings() : root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onActivateRequested: if (!root.settingsOpen) root.refresh()
      onTextKey: function(text) {
        if (text === "s" || text === "S") {
          if (root.settingsOpen) root.closeSettings()
          else root.openSettings()
        } else if (!root.settingsOpen && (text === "r" || text === "R")) {
          root.refresh()
        }
      }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: panelFlick.width
          spacing: Style.space(12)

          PanelHero {
            width: parent.width
            title: root.settingsOpen ? "Settings" : "Frontier status"
            meta: root.settingsOpen
              ? "Companies and poll interval"
              : Model.heroMeta(root.visibleCompanies, root.loading, root.loadError)
            foreground: root.foreground
            fontFamily: root.fontFamily

            iconComponent: Component {
              Text {
                text: root.settingsOpen ? "󰒓" : "󰠠"
                color: root.alarming && !root.settingsOpen ? root.urgent : root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.display
              }
            }

            trailingControl: Component {
              Row {
                spacing: Style.space(4)

                PanelActionButton {
                  visible: !root.settingsOpen
                  iconText: "󰑐"
                  tooltipText: "Refresh status"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  enabled: !fetchProcess.running
                  onClicked: root.refresh()
                }

                PanelActionButton {
                  iconText: root.settingsOpen ? "󰁍" : "󰒓"
                  tooltipText: root.settingsOpen ? "Back to status" : "Settings"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  onClicked: root.settingsOpen ? root.closeSettings() : root.openSettings()
                }
              }
            }
          }

          SettingsView {
            visible: root.settingsOpen
            width: parent.width
            catalog: root.catalog
            enabledMap: root.enabledMap
            refreshIntervalSec: root.refreshIntervalSec
            foreground: root.foreground
            fontFamily: root.fontFamily
            onCompanyToggled: function(id, enabled) { root.setCompanyEnabled(id, enabled) }
            onIntervalModified: function(seconds) { root.setRefreshInterval(seconds) }
            onCloseRequested: root.closeSettings()
          }

          Text {
            visible: !root.settingsOpen && root.visibleCompanies.length === 0
            width: parent.width
            text: "No companies enabled. Open settings to choose which status pages to watch."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          Repeater {
            model: root.settingsOpen ? [] : root.visibleCompanies

            Rectangle {
              required property var modelData
              width: parent.width
              implicitHeight: row.implicitHeight + Style.space(14)
              radius: Style.cornerRadius
              color: rowMouse.containsMouse
                ? Style.hoverFillFor(root.foreground, Color.accent)
                : "transparent"

              Row {
                id: row
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(10)
                anchors.rightMargin: Style.space(10)
                spacing: Style.space(10)

                Rectangle {
                  width: Style.space(8)
                  height: Style.space(8)
                  radius: width / 2
                  anchors.verticalCenter: parent.verticalCenter
                  color: root.indicatorColor(modelData)
                }

                Column {
                  width: parent.width - Style.space(18) - parent.spacing
                  spacing: Style.space(2)

                  Text {
                    width: parent.width
                    text: modelData.name
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                    elide: Text.ElideRight
                  }

                  Text {
                    width: parent.width
                    text: modelData.error
                      ? modelData.error
                      : (modelData.incidents && modelData.incidents.length
                        ? modelData.incidents[0].name
                        : modelData.label)
                    color: modelData.degraded ? root.urgent : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }
                }
              }

              MouseArea {
                id: rowMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.openStatusPage(modelData.url)
              }
            }
          }
        }
      }
    }
  }
}
