import QtQuick
import qs.Commons
import qs.Ui

// Bar button that opens Themes Explorer. The launcher starts its local server
// on demand and toggles an already-open window rather than opening a second
// one, so this stays a single command.
BarWidget {
  id: root
  moduleName: "mythz.themes-explorer"

  // The plugin is self-contained: `omarchy plugin add` only clones the repo, so
  // there is no install step to put a launcher on PATH. Resolve it relative to
  // this file instead, and strip the file:// scheme QML resolves URLs into.
  readonly property string launcher: Qt.resolvedUrl("bin/omarchy-themes-explorer").toString().replace(/^file:\/\//, "")

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    tooltipText: "Explore themes"
    // execArgv, not a shell string: the launcher path is a real filesystem path
    // and must not be re-tokenized on spaces in $HOME.
    onPressed: function (mouseButton) {
      if (mouseButton === Qt.RightButton)
        Util.execArgv([root.launcher, "--tab"])
      else
        Util.execArgv([root.launcher])
    }
  }
}
