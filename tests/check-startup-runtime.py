#!/usr/bin/env python3
"""Exercise the real QML startup lifecycle with synthetic helper responses.

Only the temporary copy uses shorter timer constants. No installed settings or
network connections are changed. Requires the installed Omarchy QML components.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
SHELL = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell"
HELPER = '''import json, os, pathlib, time
root = pathlib.Path(__file__).parent
if "catalog" in __import__("sys").argv:
    print(json.dumps({"companies": json.loads((root / "companies.json").read_text())}))
else:
    start = root / "started"
    if not start.exists(): start.write_text(str(time.monotonic()))
    elapsed = time.monotonic() - float(start.read_text())
    mode = os.environ["STARTUP_TEST_MODE"]
    failed = mode == "persistent" or (mode == "recover" and elapsed < 0.5) or mode == "outage" or (mode == "later" and elapsed > 0.4)
    rows = []
    for id in ("openai", "anthropic"):
        outage = mode == "outage" and id == "anthropic"
        rows.append({"id": id, "name": id, "indicator": "major" if outage else "unknown" if failed else "none",
                     "degraded": outage, "error": "Temporary failure in name resolution" if failed and not outage else "",
                     "label": "Partial outage" if outage else "Operational", "incidents": []})
    print(json.dumps({"ok": True, "companies": rows}))
'''
QML = '''import QtQuick
import Quickshell
ShellRoot {
  property int ticks: 0
  property bool observed: false
  property string mode: "MODE"
  Loader {
    id: widget
    source: "PLUGIN_URL"
    onLoaded: item.settings = {enabledIds: "openai,anthropic", refreshIntervalSec: 60}
  }
  function fail(message) { console.error("FAIL " + mode + ": " + message); Qt.exit(1) }
  function pass() { console.log("PASS startup " + mode); Qt.quit() }
  Timer {
    interval: 50; running: true; repeat: true
    onTriggered: {
      ticks++
      var p = widget.item ? widget.item.panelItem : null
      if (!p) { if (ticks > 20) fail("panel did not load"); return }
      if (mode === "later" && ticks === 14) p.refresh()
      if (p.loading || p.reportCompanies.length !== 2) return
      if (mode === "later") {
        if (!p.unavailable) {
          observed = true
          if (p.startupConnecting) fail("successful initial check did not end startup window")
        } else if (observed) {
          if (!p.alarming || p.startupConnecting) fail("post-startup error was hidden")
          else pass()
        }
      } else if (mode === "outage") {
        if (!p.alarming) fail("real outage hidden during startup")
        else pass()
      } else if (!observed && p.unavailable) {
        observed = true
        if (!p.startupConnecting || p.alarming) fail("initial connection failure is alarming")
        if (p.tooltipText !== "Connecting…") fail("missing connecting tooltip")
      } else if (observed && mode === "recover" && !p.unavailable) {
        if (p.startupConnecting || p.alarming) fail("recovered state incorrect")
        else pass()
      } else if (observed && mode === "persistent" && ticks > 30) {
        if (p.startupConnecting || !p.alarming) fail("persistent failure hidden after deadline")
        else pass()
      }
    }
  }
  Timer { interval: 5000; running: true; onTriggered: fail("scenario timed out") }
}
'''

for mode in ("recover", "persistent", "outage", "later"):
    with tempfile.TemporaryDirectory(prefix="frontier-startup-test-") as directory:
        root = Path(directory)
        for module in ("Commons", "Ui"):
            (root / module).symlink_to(SHELL / module, target_is_directory=True)
        shutil.copytree(REPO, root / "plugin", ignore=shutil.ignore_patterns(".git", "__pycache__"))
        model = root / "plugin/Model.js"
        model.write_text(model.read_text().replace("var STARTUP_GRACE_MS = 30 * 1000", "var STARTUP_GRACE_MS = 1200")
                         .replace("var STARTUP_RETRY_MS = 5 * 1000", "var STARTUP_RETRY_MS = 200"))
        (root / "plugin/fetch-status").write_text(HELPER)
        (root / "shell.qml").write_text(QML.replace("MODE", mode).replace("PLUGIN_URL", (root / "plugin/BarWidget.qml").as_uri()))
        result = subprocess.run(["quickshell", "-p", str(root), "--no-color"],
                                env={**os.environ, "STARTUP_TEST_MODE": mode}, capture_output=True, text=True, timeout=10)
        output = result.stdout + result.stderr
        print(output, end="")
        if result.returncode or "PASS startup " + mode not in output:
            raise SystemExit(1)
