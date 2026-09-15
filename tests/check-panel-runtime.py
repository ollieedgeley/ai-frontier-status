#!/usr/bin/env python3
"""Load the real plugin against the installed Omarchy QML components."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


repo = Path(__file__).resolve().parents[1]
shell = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell"
with tempfile.TemporaryDirectory(prefix="frontier-panel-test-") as directory:
    root = Path(directory)
    for module in ("Commons", "Ui"):
        (root / module).symlink_to(shell / module, target_is_directory=True)
    shutil.copytree(repo, root / "plugin", ignore=shutil.ignore_patterns(".git", "__pycache__"))
    (root / "shell.qml").write_text('''import QtQuick
import Quickshell

ShellRoot {
  Loader {
    id: widget
    source: "PLUGIN_URL"
  }
  Timer {
    interval: 1000
    running: true
    onTriggered: {
      if (widget.status !== Loader.Ready || !widget.item.panelItem) {
        console.error("FAIL: bar widget did not load its panel")
        Qt.exit(1)
        return
      }
      var panel = widget.item.panelItem
      panel.openSettings()
      if (!panel.settingsOpen) {
        console.error("FAIL: settings did not open")
        Qt.exit(1)
        return
      }
      panel.closeSettings()
      if (panel.settingsOpen) {
        console.error("FAIL: settings did not close")
        Qt.exit(1)
        return
      }
      console.log("PASS: bar widget and panel load; settings open and close")
      Qt.quit()
    }
  }
}
'''.replace("PLUGIN_URL", (root / "plugin/BarWidget.qml").as_uri()))
    result = subprocess.run(
        ["quickshell", "-p", str(root), "--no-color"],
        env={**os.environ, "QT_QPA_PLATFORM": "wayland"},
        capture_output=True, text=True, timeout=15,
    )
    output = result.stdout + result.stderr
    print(output, end="")
    raise SystemExit(0 if result.returncode == 0 and
                     "PASS: bar widget and panel load; settings open and close" in output else 1)
