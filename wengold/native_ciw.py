"""Docked EDA-style Command Interpreter Window for native Linux WENGOLD.

This is a project-command interpreter, not a shell. Existing commands continue
through the same guarded desktop dispatch; no arbitrary OS commands are run.
"""


def install_ciw(window, widget, QtCore, QtGui, QtWidgets):
    dock = QtWidgets.QDockWidget("Command Interpreter Window", window)
    dock.setObjectName("commandInterpreterDock")
    dock.setAllowedAreas(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea |
                         QtCore.Qt.DockWidgetArea.TopDockWidgetArea)
    dock.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable |
                     QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable)
    dock.setWidget(widget)
    dock.setMinimumHeight(135)

    transcript = window.transcript
    prompt = window.input
    transcript.setObjectName("ciwTranscript")
    prompt.setObjectName("ciwCommandInput")
    transcript.setReadOnly(True)
    transcript.document().setMaximumBlockCount(10000)
    mono = QtGui.QFont("DejaVu Sans Mono", 10)
    transcript.setFont(mono)
    prompt.setFont(mono)
    prompt.setAccessibleName("WENGOLD command interpreter input")

    history = []
    pos = [0]
    pending = [""]
    original_run = window._run

    def dispatch():
        line = prompt.text().strip()
        if not line:
            return
        if not history or history[-1] != line:
            history.append(line)
        if len(history) > 500:
            del history[0]
        pos[0] = len(history)
        pending[0] = ""

        if line == "clear":
            transcript.clear()
            prompt.clear()
            return
        if line in ("tabs", "workspaces"):
            window._say("wengold> " + line)
            window._say("  " + " | ".join(
                window.workspace.tabText(i) for i in range(window.workspace.count())))
            prompt.clear()
            return
        if line.startswith("workspace "):
            target = line.partition(" ")[2].strip().lower()
            window._say("wengold> " + line)
            for i in range(window.workspace.count()):
                if window.workspace.tabText(i).lower() == target:
                    window.workspace.setCurrentIndex(i)
                    window._say("  selected " + window.workspace.tabText(i))
                    prompt.clear()
                    return
            window._say("  unknown workspace; run tabs")
            prompt.clear()
            return
        original_run()

    class HistoryFilter(QtCore.QObject):
        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.Type.KeyPress:
                if event.key() == QtCore.Qt.Key.Key_Up:
                    if pos[0] == len(history):
                        pending[0] = prompt.text()
                    pos[0] = max(0, pos[0] - 1)
                    prompt.setText(history[pos[0]] if history else pending[0])
                    return True
                if event.key() == QtCore.Qt.Key.Key_Down:
                    pos[0] = min(len(history), pos[0] + 1)
                    prompt.setText(history[pos[0]] if pos[0] < len(history)
                                   else pending[0])
                    return True
                if event.key() == QtCore.Qt.Key.Key_Escape:
                    prompt.clear()
                    pos[0] = len(history)
                    return True
            return False

    event_filter = HistoryFilter(prompt)
    prompt.installEventFilter(event_filter)
    dock.historyFilter = event_filter
    dock.commandHistory = history
    window.ciwHistory = history

    layout = widget.layout()
    layout.removeWidget(prompt)
    header = layout.itemAt(0).widget()
    if isinstance(header, QtWidgets.QLabel):
        header.setText("COMMAND INTERPRETER WINDOW · WENGOLD COMMANDS")

    row = QtWidgets.QHBoxLayout()
    label = QtWidgets.QLabel("wengold>")
    label.setObjectName("ciwPromptLabel")
    row.addWidget(label)
    row.addWidget(prompt, 1)
    run = QtWidgets.QPushButton("Run")
    run.setObjectName("ciwRunButton")
    clear = QtWidgets.QPushButton("Clear")
    clear.setObjectName("ciwClearButton")
    copy = QtWidgets.QPushButton("Copy output")
    copy.setObjectName("ciwCopyButton")
    for b in (run, clear, copy):
        row.addWidget(b)
    layout.addLayout(row)

    try:
        prompt.returnPressed.disconnect()
    except (TypeError, RuntimeError):
        pass
    prompt.returnPressed.connect(dispatch)
    run.clicked.connect(dispatch)
    clear.clicked.connect(transcript.clear)
    copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(
        transcript.toPlainText()))

    window.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, dock)
    window.resizeDocks([dock], [250], QtCore.Qt.Orientation.Vertical)
    window.ciwDock = dock
    window.ciwFocus = lambda: (dock.show(), dock.raise_(), prompt.setFocus())
    return dock
