import QtQuick
import Quickshell

ShellRoot {
  id: test
  property int step: 0
  property var cases: [
    ["import time; time.sleep(30)", "Status process timed out"],
    ["print('recovered')", ""],
    ["import sys; sys.stdout.write('x'*1000000)", "Status process output exceeds limit"],
    ["import sys; sys.stderr.write('x'*1000000)", "Status process output exceeds limit"],
    [null, null]
  ]

  function check(condition, message) {
    if (condition) return true
    console.error("FAIL: " + message)
    Qt.exit(1)
    return false
  }

  function next() {
    if (step === cases.length) {
      console.log("PASS: timeout, recovery, stdout/stderr limits and failed launch")
      Qt.quit()
      return
    }
    child.command = cases[step][0] === null
      ? ["/nonexistent/ai-frontier-status-test"]
      : ["python3", "-c", cases[step][0]]
    child.launch()
  }

  BoundedProcess {
    id: child
    timeoutMs: 300
    maxOutputChars: 128
    maxErrorChars: 64
    onCompleted: function(code) {
      if (!test.check(!pending && !running, "child still active")) return
      if (!test.check(output.length <= 128 && errorOutput.length <= 64, "output exceeded limit")) return
      if (test.step === 4) {
        if (!test.check(code !== 0, "failed launch reported success")) return
      } else {
        if (!test.check(failure === test.cases[test.step][1], "unexpected failure at step " + test.step + ": " + failure)) return
        if (test.step === 1 && !test.check(output === "recovered\n" && code === 0, "recovery failed")) return
      }
      test.step++
      Qt.callLater(test.next)
    }
  }
  Timer {
    interval: 10000
    running: true
    onTriggered: test.check(false, "test suite timed out")
  }
  Component.onCompleted: next()
}
