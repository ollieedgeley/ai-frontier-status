import QtQuick
import Quickshell.Io

Process {
  id: root
  property int timeoutMs: 65000
  property int maxOutputChars: 524288
  property int maxErrorChars: 4096
  property string output: ""
  property string errorOutput: ""
  property string failure: ""
  property bool pending: false
  property int resultCode: -1
  signal completed(int code)

  function launch() {
    if (pending || running) return
    output = ""
    errorOutput = ""
    failure = ""
    resultCode = -1
    pending = true
    watchdog.restart()
    running = true
  }

  function abort(message) {
    if (!pending) return
    failure = message
    signal(9)
    Qt.callLater(settle)
  }

  function settle() {
    if (!pending || running) return
    watchdog.stop()
    pending = false
    completed(failure ? -1 : resultCode)
  }

  function collect(data, isError) {
    if (!pending || failure) return
    var previous = isError ? errorOutput : output
    var limit = isError ? maxErrorChars : maxOutputChars
    if (data.length > limit - previous.length) {
      abort("Status process output exceeds limit")
      return
    }
    if (isError) errorOutput = previous + data
    else output = previous + data
  }

  property Timer watchdog: Timer {
    interval: root.timeoutMs
    onTriggered: root.abort("Status process timed out")
  }
  stdout: SplitParser {
    splitMarker: ""
    onRead: data => root.collect(data, false)
  }
  stderr: SplitParser {
    splitMarker: ""
    onRead: data => root.collect(data, true)
  }
  onExited: function(exitCode) {
    resultCode = exitCode
    Qt.callLater(settle)
  }
  onRunningChanged: if (!running && pending) Qt.callLater(settle)
}
