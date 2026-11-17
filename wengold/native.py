"""The native Linux desktop app.

`wengold desktop` used to launch a Chrome `--app=` window, which is a browser
without its toolbars — not a desktop application. This module is a real one: a Qt
window, native widgets, a menu bar, keyboard shortcuts, and no browser anywhere.

It is deliberately a **separate front end over the same backend**. `build_state`
and `_exec` are the same functions the browser mode uses, so the two cannot drift
apart: if the kernel changes a number, both show the changed number.

PyQt6 is an optional dependency. Without it the module raises `NativeUnavailable`
and the caller falls back to the browser window rather than crashing — a desktop
app that fails to start because of a packaging detail is worse than a browser tab.

Testing without a display
-------------------------
Qt renders offscreen, so the whole window is built and screenshotted in CI:

    QT_QPA_PLATFORM=offscreen python -m wengold.native --screenshot out.png

That is how this was verified. It is not the same as a human clicking it, and the
tests also exercise navigation, project switching and workspace interactions.
"""
from __future__ import annotations

from pathlib import Path

from .native_shell import DESCRIPTIONS, MUTED, STYLESHEET, make_navigation, sync_navigation


class NativeUnavailable(RuntimeError):
    """PyQt6 is not installed, so the native window cannot be built."""


def _esc(text: str) -> str:
    """HTML-escape a line of source so `<=` and `&` survive the detail pane."""
    import html
    return html.escape(text, quote=False)


def _qt():
    """Import Qt, or explain exactly how to get it."""
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise NativeUnavailable(
            "the native app needs PyQt6: python -m pip install PyQt6\n"
            "`wengold desktop` without --native uses a browser window instead."
        ) from exc
    return QtCore, QtGui, QtWidgets


def build_window(state: dict):
    """Construct the main window from an indexed state. Returns the QMainWindow.

    Separated from `main` so tests can build the window and inspect it without an
    event loop, and so the offscreen screenshot path exercises the same code.
    """
    QtCore, QtGui, QtWidgets = _qt()
    from .desktop import CLI_COMMANDS, _exec, _file_detail

    class MainWindow(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.state = state
            self.setWindowTitle(f"WENGOLD — {state['path']}")
            self.resize(1240, 820)
            self.setStyleSheet(STYLESHEET)

            # Project context remains visible while workspaces change.
            strip = QtWidgets.QFrame()
            strip.setObjectName("strip")
            strip.setMinimumHeight(59)
            lay = QtWidgets.QHBoxLayout(strip)
            lay.setContentsMargins(14, 8, 14, 8)
            left = QtWidgets.QVBoxLayout()
            left.setSpacing(2)
            project = QtWidgets.QLabel(Path(state["path"]).name or state["path"])
            project.setObjectName("project")
            project.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            project.setMinimumWidth(0)
            project.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                  QtWidgets.QSizePolicy.Policy.Preferred)
            revision = QtWidgets.QLabel()
            revision.setObjectName("revision")
            revision.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            revision.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                   QtWidgets.QSizePolicy.Policy.Preferred)
            left.addWidget(project)
            left.addWidget(revision)
            self.projectNameLabel = project
            self.projectRevisionLabel = revision
            lay.addLayout(left, 1)
            open_btn = QtWidgets.QPushButton("Open Project")
            open_btn.setObjectName("openProjectButton")
            open_btn.setProperty("primary", True)
            open_btn.setToolTip("Open an existing RTL, verification and automation project (Ctrl+O)")
            open_btn.clicked.connect(self._open_project)
            lay.addWidget(open_btn)
            reload_btn = QtWidgets.QPushButton("Rescan Files")
            reload_btn.setObjectName("rescanFilesButton")
            reload_btn.clicked.connect(self._reload)
            lay.addWidget(reload_btn)
            console = QtWidgets.QPushButton("Console")
            console.setObjectName("toggleConsoleButton")
            console.setCheckable(True)
            console.setToolTip("Show or hide the Wengold command interpreter")
            lay.addWidget(console)
            self.coverage = QtWidgets.QLabel()
            self.coverage.setObjectName("metricHint")

            # ---- the three panes -------------------------------------------
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setHeaderHidden(True)
            self.tree.setIndentation(13)
            self.tree.setAccessibleName("Project file explorer")
            self.tree.itemSelectionChanged.connect(self._on_file)
            self.tree.itemDoubleClicked.connect(self._open_selected_source)

            self.table = QtWidgets.QTableWidget(0, 3)
            self.table.setHorizontalHeaderLabels(["Block", "Deps", "Used by"])
            self.table.setAccessibleName("Indexed design blocks")
            self.table.setAlternatingRowColors(True)
            self.table.verticalHeader().hide()
            self.table.horizontalHeader().setSectionResizeMode(
                0, QtWidgets.QHeaderView.ResizeMode.Stretch)
            for col in (1, 2):
                self.table.horizontalHeader().setSectionResizeMode(
                    col, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            self.table.setEditTriggers(
                QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.table.setSelectionBehavior(
                QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.itemSelectionChanged.connect(self._on_block)

            self.detail = QtWidgets.QTextEdit()
            self.detail.setReadOnly(True)
            self.detail.setAccessibleName("Project details and source preview")

            top = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
            for w, title in ((self.tree, "Project files"), (self.table, "Design blocks"),
                             (self.detail, "Inspector")):
                box = QtWidgets.QFrame()
                box.setProperty("card", True)
                v = QtWidgets.QVBoxLayout(box)
                v.setContentsMargins(8, 8, 8, 8)
                v.setSpacing(6)
                head = QtWidgets.QLabel(title)
                head.setObjectName("sectionTitle")
                v.addWidget(head)
                if w is self.tree:
                    self.fileFilter = QtWidgets.QLineEdit()
                    self.fileFilter.setObjectName("projectFileFilter")
                    self.fileFilter.setClearButtonEnabled(True)
                    self.fileFilter.setPlaceholderText("Filter RTL, UVM, specs, scripts…")
                    self.fileFilter.textChanged.connect(self._filter_files)
                    self.fileFilter.setToolTip("Search discovered project files by path (Ctrl+Shift+F)")
                    self.fileFilter.setAccessibleName("Filter project files")
                    v.addWidget(self.fileFilter)
                    self.fileFilterEmpty = QtWidgets.QLabel("No matching project files.")
                    self.fileFilterEmpty.setObjectName("metricHint")
                    self.fileFilterEmpty.setWordWrap(True)
                    v.addWidget(self.fileFilterEmpty)
                v.addWidget(w)
                top.addWidget(box)
            top.setHandleWidth(7)
            top.setChildrenCollapsible(False)
            top.setSizes([250, 275, 445])
            top.setStretchFactor(2, 1)
            overview = self._overview_page(top)

            # ---- the CLI pane at the bottom --------------------------------
            self.transcript = QtWidgets.QTextEdit()
            self.transcript.setObjectName("transcript")
            self.transcript.setReadOnly(True)
            self.input = QtWidgets.QLineEdit()
            self.input.setPlaceholderText(
                " · ".join(CLI_COMMANDS))
            self.input.returnPressed.connect(self._run)

            bottom = QtWidgets.QWidget()
            bv = QtWidgets.QVBoxLayout(bottom)
            bv.setContentsMargins(8, 4, 8, 8)
            bv.setSpacing(6)
            head = QtWidgets.QLabel("CLI")
            head.setObjectName("sectionTitle")
            bv.addWidget(head)
            bv.addWidget(self.transcript)
            bv.addWidget(self.input)

            # Main engineering views stay above the persistent CIW dock.
            from .native_studio import make_studio_tabs
            self.workspace = make_studio_tabs(state, QtCore, QtGui, QtWidgets, self)
            self._make_pages_scrollable(self.workspace)
            self.workspace.insertTab(0, overview, "Overview")
            self.workspace.setCurrentIndex(0)

            central = QtWidgets.QWidget()
            cv = QtWidgets.QVBoxLayout(central)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(0)
            cv.addWidget(strip)
            body = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(body)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            self.rail, self.workspaceNavigation = make_navigation(QtCore, QtWidgets)
            self.workspaceNavigation.currentItemChanged.connect(self._select_workspace_item)
            row.addWidget(self.rail)
            content = QtWidgets.QWidget()
            self.workspaceLayout = QtWidgets.QVBoxLayout(content)
            self.workspaceLayout.setContentsMargins(0, 0, 0, 0)
            self.workspaceLayout.setSpacing(0)

            heading = QtWidgets.QFrame()
            heading.setObjectName("workspaceHeading")
            headline = QtWidgets.QVBoxLayout(heading)
            headline.setContentsMargins(15, 8, 15, 8)
            headline.setSpacing(2)
            self.workspaceTitle = QtWidgets.QLabel()
            self.workspaceTitle.setObjectName("workspaceTitle")
            self.workspaceSubtitle = QtWidgets.QLabel()
            self.workspaceSubtitle.setObjectName("workspaceSubtitle")
            self.workspaceSubtitle.setWordWrap(True)
            headline.addWidget(self.workspaceTitle)
            headline.addWidget(self.workspaceSubtitle)
            self.workspaceLayout.addWidget(heading)
            self.workspaceLayout.addWidget(self.workspace, 1)
            self.workspaceLayout.addWidget(self.workspace.statusLabel)
            row.addWidget(content, 1)
            cv.addWidget(body, 1)
            self.setCentralWidget(central)
            self._bind_workspace()

            from .native_ciw import install_ciw
            install_ciw(self, bottom, QtCore, QtGui, QtWidgets)
            self.ciwDock.visibilityChanged.connect(console.setChecked)
            console.clicked.connect(self.ciwDock.setVisible)
            self._menus()
            self._refresh_project_header()
            self._populate()
            self._watchSignature = self.state.get("project_inventory", {}).get("signature") if self.state.get("project_inventory") else None
            self.sourceWatch = QtCore.QTimer(self)
            self.sourceWatch.setInterval(10000)
            self.sourceWatch.timeout.connect(self._watch_project)
            self.sourceWatch.start()
            self._say("wengold " + _version() + " — type `help` for commands")

        # -- helpers -------------------------------------------------------
        def _overview_page(self, splitter):
            page = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(page)
            layout.setContentsMargins(12, 10, 12, 0)
            layout.setSpacing(8)
            cards = QtWidgets.QHBoxLayout()
            cards.setSpacing(8)
            self.metricValues = {}
            for key, title, hint in (
                    ("project_files", "Project files", "Discovered source and collateral"),
                    ("blocks", "Design blocks", "RTL graph nodes"),
                    ("unresolved", "Unresolved", "Graph items needing attention")):
                card = QtWidgets.QFrame()
                card.setProperty("card", True)
                column = QtWidgets.QVBoxLayout(card)
                column.setContentsMargins(10, 5, 10, 5)
                column.setSpacing(1)
                label = QtWidgets.QLabel(title)
                label.setObjectName("sectionTitle")
                value = QtWidgets.QLabel()
                value.setObjectName("metricNumber")
                value.setAccessibleName(title + " count")
                value.setToolTip(hint)
                column.addWidget(label)
                column.addWidget(value)
                cards.addWidget(card, 1)
                self.metricValues[key] = value
            layout.addLayout(cards)

            access = QtWidgets.QHBoxLayout()
            self.graphQuality = QtWidgets.QLabel()
            self.graphQuality.setObjectName("graphQuality")
            access.addWidget(self.graphQuality)
            access.addStretch(1)
            for name in ("DV Workflow", "Waveforms", "Jobs & Signoff"):
                button = QtWidgets.QPushButton(name.replace("&", "&&"))
                button.setObjectName("overviewShortcut" + name.split()[0])
                button.clicked.connect(lambda _=False, title=name: self._go_workspace(title))
                access.addWidget(button)
            layout.addLayout(access)
            layout.addWidget(splitter, 1)
            return page

        def _make_pages_scrollable(self, workspace):
            # Dense tool forms must not impose their minimum size on all pages.
            # Scroll only the page that doesn't fit on a smaller Linux display.
            with QtCore.QSignalBlocker(workspace):
                for index in range(workspace.count()):
                    page = workspace.widget(index)
                    title = workspace.tabText(index)
                    workspace.removeTab(index)
                    scroll = QtWidgets.QScrollArea()
                    scroll.setWidgetResizable(True)
                    scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
                    scroll.setWidget(page)
                    workspace.insertTab(index, scroll, title)

        def _bind_workspace(self):
            self.workspace.tabBar().hide()
            titles = [self.workspace.tabText(i) for i in range(self.workspace.count())]
            with QtCore.QSignalBlocker(self.workspaceNavigation):
                self.navigationItems = sync_navigation(
                    self.workspaceNavigation, titles, QtCore, QtGui, QtWidgets)
            self.workspace.currentChanged.connect(self._sync_workspace)
            self._sync_workspace(self.workspace.currentIndex())

        def _go_workspace(self, title):
            for i in range(self.workspace.count()):
                if self.workspace.tabText(i) == title:
                    self.workspace.setCurrentIndex(i)
                    return

        def _select_workspace_item(self, current, _previous):
            title = current.data(QtCore.Qt.ItemDataRole.UserRole) if current else None
            if title:
                self._go_workspace(title)

        def _sync_workspace(self, index):
            if index < 0:
                return
            title = self.workspace.tabText(index)
            self.workspaceTitle.setText(title)
            self.workspaceSubtitle.setText(DESCRIPTIONS.get(title, ""))
            item = self.navigationItems.get(title)
            if item is not None:
                with QtCore.QSignalBlocker(self.workspaceNavigation):
                    self.workspaceNavigation.setCurrentItem(item)

        def _focus_file_filter(self):
            self._go_workspace("Overview")
            self.fileFilter.setFocus()
            self.fileFilter.selectAll()

        def _menus(self):
            bar = self.menuBar()
            file_menu = bar.addMenu("&File")
            open_project = QtGui.QAction("Open Project Folder…", self)
            open_project.setObjectName("openProjectAction")
            open_project.setShortcut("Ctrl+O")
            open_project.triggered.connect(self._open_project)
            file_menu.addAction(open_project)
            reload_ = QtGui.QAction("&Reload", self)
            reload_.setShortcut("Ctrl+R")
            reload_.triggered.connect(self._reload)
            quit_ = QtGui.QAction("&Quit", self)
            quit_.setShortcut("Ctrl+Q")
            quit_.triggered.connect(self.close)
            file_menu.addAction(reload_)
            auto_refresh = QtGui.QAction("Auto-discover project files", self)
            auto_refresh.setObjectName("autoDiscoveryAction")
            auto_refresh.setCheckable(True)
            auto_refresh.setChecked(True)
            auto_refresh.toggled.connect(lambda enabled: self.sourceWatch.start() if enabled else self.sourceWatch.stop())
            file_menu.addAction(auto_refresh)
            file_menu.addSeparator()
            file_menu.addAction(quit_)

            view = bar.addMenu("&View")
            view.addAction(self.ciwDock.toggleViewAction())
            focus_ciw = QtGui.QAction("Focus Command Interpreter", self)
            focus_ciw.setShortcut("Ctrl+`")
            focus_ciw.triggered.connect(self.ciwFocus)
            view.addAction(focus_ciw)
            rail = QtGui.QAction("Show Workspace Sidebar", self)
            rail.setObjectName("toggleWorkspaceSidebarAction")
            rail.setShortcut("Ctrl+B")
            rail.setCheckable(True)
            rail.setChecked(True)
            rail.toggled.connect(self.rail.setVisible)
            view.addAction(rail)
            focus_files = QtGui.QAction("Find Project Files", self)
            focus_files.setShortcut("Ctrl+Shift+F")
            focus_files.triggered.connect(self._focus_file_filter)
            view.addAction(focus_files)
            view.addSeparator()
            workspaces = view.addMenu("Go to Workspace")
            for idx in range(self.workspace.count()):
                name = self.workspace.tabText(idx)
                action = QtGui.QAction(name.replace("&", "&&"), self)
                if idx < 9:
                    action.setShortcut(f"Ctrl+Alt+{idx + 1}")
                action.triggered.connect(
                    lambda _checked=False, title=name: self._go_workspace(title))
                workspaces.addAction(action)
            view.addSeparator()
            for name, focus in (("Files", self.tree), ("Blocks", self.table),
                                ("CLI", self.input)):
                act = QtGui.QAction(name, self)
                act.triggered.connect(lambda _=False, w=focus: self._focus_panel(w))
                view.addAction(act)

            help_menu = bar.addMenu("&Help")
            verify_ui = QtGui.QAction("UI & Tool Diagnostics", self)
            verify_ui.setObjectName("uiDiagnosticsAction")
            verify_ui.triggered.connect(self._show_diagnostics)
            help_menu.addAction(verify_ui)
            about = QtGui.QAction("&About", self)
            about.triggered.connect(self._about)
            help_menu.addAction(about)

        def _focus_panel(self, widget):
            if widget is self.input:
                self.ciwFocus()
            else:
                self._go_workspace("Overview")
                widget.setFocus()

        def _show_diagnostics(self):
            import json
            from .native_health import diagnostics
            report = diagnostics(self, QtWidgets)
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle("WENGOLD — UI & Tool Diagnostics")
            dialog.resize(780, 530)
            layout = QtWidgets.QVBoxLayout(dialog)
            message = QtWidgets.QLabel(
                "Panel availability and actual tool discovery. Missing tools do not count as passed checks.")
            message.setWordWrap(True)
            layout.addWidget(message)
            viewer = QtWidgets.QPlainTextEdit()
            viewer.setObjectName("uiDiagnosticsReport")
            viewer.setReadOnly(True)
            viewer.setPlainText(json.dumps(report, indent=2))
            layout.addWidget(viewer)
            close = QtWidgets.QPushButton("Close")
            close.clicked.connect(dialog.accept)
            layout.addWidget(close)
            dialog.exec()

        def _filter_files(self, query):
            """Filter the inventory without destroying its path metadata."""
            needle = query.strip().casefold()
            matches = 0
            role = QtCore.Qt.ItemDataRole.UserRole
            for i in range(self.tree.topLevelItemCount()):
                group = self.tree.topLevelItem(i)
                if group.data(0, role):
                    match = needle in group.text(0).casefold()
                    group.setHidden(not match)
                    matches += match
                    continue
                visible = 0
                for j in range(group.childCount()):
                    child = group.child(j)
                    match = needle in child.text(0).casefold()
                    child.setHidden(not match)
                    visible += match
                group.setHidden(bool(needle) and visible == 0)
                if needle and visible:
                    group.setExpanded(True)
                matches += visible
            self.fileFilterEmpty.setVisible(matches == 0)
            self.fileFilterEmpty.setText(
                "No matching project files." if needle else "No project files discovered.")

        def _open_selected_source(self, item, _column):
            """Double-click a source file to open it in the real editor."""
            rel = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
            if not rel:
                return
            if Path(rel).suffix.lower() == ".pdf":
                self.statusBar().showMessage(
                    "PDF specifications must be exported to text/Markdown before editing.")
                return
            self.workspace.loadSource(rel)
            # Keep the viewer visible if a dirty-edit confirmation was refused.
            if self.workspace.editorFile() == rel:
                self._go_workspace("RTL Editor")

        def _populate(self):
            """Present design, verification, automation and filelists independently."""
            self.tree.clear()
            inventory = self.state.get("project_inventory") or {}
            categories = (
                ("design", "Design RTL"),
                ("verification", "Verification / UVM"),
                ("automation", "Automation / Scripts"),
                ("filelists", "Filelists / Build"),
                ("specifications", "Specification / Requirements"),
            )
            for key, title in categories:
                paths = inventory.get(key, [])
                group = QtWidgets.QTreeWidgetItem([f"{title} ({len(paths)})"])
                group.setData(0, QtCore.Qt.ItemDataRole.UserRole, None)
                self.tree.addTopLevelItem(group)
                for rel in paths:
                    child = QtWidgets.QTreeWidgetItem([rel])
                    child.setData(0, QtCore.Qt.ItemDataRole.UserRole, rel)
                    child.setToolTip(0, rel)
                    group.addChild(child)
                group.setExpanded(True)
            if not inventory:
                for rel in self.state.get("file_paths", []):
                    item = QtWidgets.QTreeWidgetItem([rel])
                    item.setData(0, QtCore.Qt.ItemDataRole.UserRole, rel)
                    self.tree.addTopLevelItem(item)
            self.table.setRowCount(0)
            g = self.state["graph"]
            for i, b in enumerate(self.state["block_names"]):
                self.table.insertRow(i)
                out = len(g.rtl_ancestors(b)) if hasattr(g, "rtl_ancestors") else 0
                inn = len(g.rtl_descendants(b)) if hasattr(g, "rtl_descendants") else 0
                for col, value in enumerate((b, str(out), str(inn))):
                    cell = QtWidgets.QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(QtCore.Qt.ItemDataRole.UserRole, b)
                    self.table.setItem(i, col, cell)
            if hasattr(self, "fileFilter"):
                self._filter_files(self.fileFilter.text())
            self.detail.setHtml(self._overview_html())

        def _overview_html(self) -> str:
            s = self.state
            notes = "".join(f"<li>{_esc(str(n))}</li>" for n in s.get("notes", []))
            return (
                f"<h3 style='margin:0 0 8px'>{_esc(Path(s['path']).name)}</h3>"
                f"<p style='color:{MUTED}'>{s['files']} files · {s['blocks']} blocks"
                f" · {s['nodes']} nodes · {s['edges']} edges</p>"
                f"<p><b>{s['design_units']}/{s['files']}</b> HDL files contain design units. "
                "Indexing status is not verification coverage.</p>"
                "<p>Select a file to preview its source, or double-click it to edit. "
                "Select a design block to see its dependencies.</p>"
                + (f"<ul>{notes}</ul>" if notes else "")
            )

        def _on_file(self):
            items = self.tree.selectedItems()
            if not items:
                return
            rel = items[0].data(0, QtCore.Qt.ItemDataRole.UserRole)
            if not rel:
                return
            d = _file_detail(self.state, rel)
            # HDL graph details exclude requirements and scripts. Preview them
            # from the guarded workspace instead of showing an empty pane.
            if not d.get("source") and Path(rel).suffix.lower() in (
                    ".md", ".rst", ".txt", ".py", ".tcl", ".do", ".pss",
                    ".psf", ".sh", ".mk", ".yaml", ".yml", ".json", ".f", ".flist"):
                try:
                    from .studio_workspace import source
                    content = source(self.state["path"], rel)["content"]
                    excerpt = "\n".join(content.splitlines()[:400])
                    d = dict(d, source=excerpt, lines=len(content.splitlines()),
                             truncated=len(content.splitlines()) > 400)
                except Exception as exc:
                    self.detail.setPlainText(f"Cannot preview {rel}: {exc}")
                    return
            blocks = d.get("blocks", [])
            rows = "".join(
                f"<tr><td>{b['name']}</td><td align=right>{b['instantiates']}</td>"
                f"<td align=right>{b['instantiated_by']}</td></tr>" for b in blocks)
            source = d.get("source") or ""
            if source:
                # show the code, with line numbers — the pane's job is reading RTL
                body = "\n".join(
                    f"<span style='color:{MUTED}'>{i:>4}</span>  {_esc(line)}"
                    for i, line in enumerate(source.splitlines(), 1))
                more = ("<p style='color:%s'>… truncated at 400 lines</p>" % MUTED
                        if d.get("truncated") else "")
                self.detail.setHtml(
                    f"<h3 style='margin:0 0 2px'>{_esc(rel)}</h3>"
                    f"<p style='color:{MUTED};margin:0 0 8px'>"
                    f"{len(blocks)} block(s) · {d.get('lines', 0)} lines</p>"
                    f"<pre style=\"font-family:monospace;font-size:12px;"
                    f"white-space:pre;margin:0\">{body}</pre>{more}")
            else:
                self.detail.setHtml(
                    f"<h3 style='margin:0 0 8px'>{_esc(rel)}</h3>"
                    f"<p style='color:{MUTED}'>{len(blocks)} block(s)</p>"
                    + (f"<table width='100%' cellspacing=0>{rows}</table>" if rows
                       else "<p>no modules in this file</p>"))

        def _on_block(self):
            rows = self.table.selectedItems()
            if not rows:
                return
            name = self.table.item(rows[0].row(), 0).data(
                QtCore.Qt.ItemDataRole.UserRole)
            g = self.state["graph"]
            node = g.nodes.get(name)
            path = getattr(node, "path", "")
            out = len(g.rtl_ancestors(name)) if hasattr(g, "rtl_ancestors") else 0
            inn = len(g.rtl_descendants(name)) if hasattr(g, "rtl_descendants") else 0
            self.detail.setHtml(
                f"<h3 style='margin:0 0 8px'>{name}</h3>"
                f"<p style='color:{MUTED}'>{path}</p>"
                f"<p>instantiates <b>{out}</b> · instantiated by <b>{inn}</b></p>")

        def _run(self):
            line = self.input.text().strip()
            if not line:
                return
            self._say(f"› {line}")
            try:
                res = _exec(self.state, line)
            except Exception as exc:                       # never kill the window
                self._say(f"  error: {exc}")
                return
            out = res.get("output", "")
            if out:
                self._say("  " + out.replace("\n", "\n  "))
            self.input.clear()

            # `vibe` writes files: reload the index and show what was made, so the
            # generated RTL is on screen rather than a message saying it exists
            if line.split()[0].lower() == "vibe" and res.get("ok"):
                made = res.get("written") or []
                self._reload()
                if made:
                    self._select_file(made[0])

        def _select_file(self, rel: str):
            """Select a file in the tree so the detail pane shows its source."""
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                if item.data(0, QtCore.Qt.ItemDataRole.UserRole) == rel:
                    self.tree.setCurrentItem(item)
                    return
                for j in range(item.childCount()):
                    child = item.child(j)
                    if child.data(0, QtCore.Qt.ItemDataRole.UserRole) == rel:
                        self.tree.setCurrentItem(child)
                        return

        def _say(self, text: str):
            self.transcript.append(text)

        def _active_operations(self):
            """Prevent Qt worker threads being destroyed during project switch."""
            active = []
            workspace = self.workspace
            checks = (
                ("Local AI", getattr(getattr(workspace, "aiPage", None), "aiState", None)),
                ("DV Workflow", getattr(getattr(workspace, "dvWorkflow", None), "pipelineState", None)),
                ("Synthesis / EDA", getattr(getattr(workspace, "implementation", None), "synthesisState", None)),
                ("Wave Debug AI", getattr(getattr(workspace, "waveDebug", None), "debugState", None)),
            )
            for name, state in checks:
                if not state:
                    continue
                if state.get("busy"):
                    active.append(name)
                    continue
                thread = state.get("thread")
                try:
                    if thread is not None and thread.isRunning():
                        active.append(name)
                except RuntimeError:
                    pass
            return active

        def _open_project(self):
            folder = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Open RTL and verification project", self.state["path"])
            if not folder:
                return
            active = self._active_operations()
            if active:
                QtWidgets.QMessageBox.warning(
                    self, "Project is busy",
                    "Cannot switch projects while these jobs are running: "
                    + ", ".join(active) + ". Finish the jobs first.")
                return
            if self.workspace.editorDirty():
                decision = QtWidgets.QMessageBox.question(
                    self, "Unsaved edits", "Discard unsaved edits and open another project?")
                if decision != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
            from .desktop import build_state
            try:
                selected = build_state(folder)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Project load failed", str(exc))
                return
            # Project-dependent workers and file paths must not be kept alive
            # after switching to another root. Recreate the workspace.
            previous_page = self.workspaceTitle.text()
            old = self.workspace
            old.jobs.shutdown()
            from .native_studio import make_studio_tabs
            new = make_studio_tabs(selected, QtCore, QtGui, QtWidgets, self)
            self._make_pages_scrollable(new)
            overview = old.widget(0)
            # Block the old tab signal while moving the shared Overview page.
            with QtCore.QSignalBlocker(old):
                old.removeTab(0)
            new.insertTab(0, overview, "Overview")
            self.workspaceLayout.replaceWidget(old, new)
            self.workspaceLayout.replaceWidget(old.statusLabel, new.statusLabel)
            old.hide()
            old.statusLabel.hide()
            old.statusLabel.setParent(old)
            self.workspace = new
            self._bind_workspace()
            self._go_workspace(previous_page)
            old.deleteLater()
            self.state = selected
            self._watchSignature = (selected.get("project_inventory") or {}).get("signature")
            self._refresh_project_header()
            self._populate()
            self._say(f"  opened project {folder}")

        def _refresh_project_header(self):
            self.setWindowTitle(f"WENGOLD — {self.state['path']}")
            path = Path(self.state["path"]).resolve()
            self.projectNameLabel.setText(path.name or str(path))
            self.projectNameLabel.setToolTip(str(path))
            self.projectRevisionLabel.setText(str(path))
            self.projectRevisionLabel.setToolTip(str(path))
            self.coverage.setText(
                f"{self.state['design_units']}/{self.state['files']} files are design units")
            self.metricValues["project_files"].setText(str(len(self.state.get("file_paths", []))))
            for key in ("blocks", "unresolved"):
                self.metricValues[key].setText(str(self.state[key]))
            complete = self.state["complete"]
            self.graphQuality.setText("Graph complete" if complete else "Graph incomplete")
            self.graphQuality.setToolTip(
                self.coverage.text() + ". Indexing status only, not verification coverage.")
            self.graphQuality.setProperty("attention", not complete)
            self.graphQuality.style().unpolish(self.graphQuality)
            self.graphQuality.style().polish(self.graphQuality)
            self.statusBar().showMessage(
                f"{self.state['files']} HDL files · "
                f"{len(self.state.get('verification_paths', []))} verification · "
                f"{len(self.state.get('automation_paths', []))} automation")

        def _watch_project(self):
            """Detect added/removed/modified files without discarding open edits."""
            from .project_scan import discover
            try:
                changed = discover(self.state["path"])
            except (ValueError, OSError):
                return
            if changed["signature"] == self._watchSignature:
                return
            if self.workspace.editorDirty():
                self.workspace.statusLabel.setText(
                    "Project files changed externally; save/discard edits before Reload")
                return
            self._reload()

        def _reload(self):
            from .desktop import build_state
            if self.workspace.editorDirty():
                answer = QtWidgets.QMessageBox.question(
                    self, "Unsaved edits", "Discard unsaved edits and re-index the project?")
                if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
            try:
                updated = build_state(self.state["path"])
            except Exception as exc:
                self._say(f"  reload failed: {exc}")
                return
            self.state = updated
            self._watchSignature = (updated.get("project_inventory") or {}).get("signature")
            self.workspace.refreshProjectSources(updated)
            self._refresh_project_header()
            self._populate()
            self._say("  source files refreshed")

        def closeEvent(self, event):
            active = self._active_operations()
            if active:
                QtWidgets.QMessageBox.warning(
                    self, "Verification job running",
                    "Finish the active job before closing WENGOLD: "
                    + ", ".join(active) + ".")
                event.ignore()
                return
            # Do not delete a window with live QThreads owned by its pages.
            try:
                self.workspace.jobs.shutdown()
            except Exception:
                pass
            super().closeEvent(event)

        def _about(self):
            QtWidgets.QMessageBox.about(
                self, "WENGOLD",
                f"<b>WENGOLD</b> {_version()}<br><br>"
                "Open silicon verification.<br>"
                "MIT OR Apache-2.0.")

    return MainWindow()


def _version() -> str:
    from . import __version__
    return __version__


def main(path: str = ".", screenshot: str | None = None) -> int:
    """Run the native app. `screenshot` renders once and exits (for CI)."""
    import sys
    QtCore, _QtGui, QtWidgets = _qt()
    from .desktop import build_state

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    # A Linux application-menu entry has no meaningful project working directory.
    # Do not silently index the user's entire HOME when launched without a path.
    if path == "." and not screenshot:
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            None, "Choose WENGOLD Design + Verification Project",
            str(Path.home()))
        if not selected:
            return 0
        path = selected
    # Opening an HDL file from the file manager should use its parent project
    # rather than passing a non-directory to project-local jobs and evidence.
    if Path(path).is_file():
        path = str(Path(path).resolve().parent)
    try:
        state = build_state(path)
    except Exception as exc:
        QtWidgets.QMessageBox.critical(None, "WENGOLD",
                                       f"could not index {path}:\n{exc}")
        return 1
    win = build_window(state)
    win.show()

    if screenshot:
        # offscreen verification: let the layout settle, grab, exit
        def shot():
            win.grab().save(screenshot)
            app.quit()
        QtCore.QTimer.singleShot(400, shot)
        app.exec()
        return 0

    return app.exec()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="WENGOLD native desktop app")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--screenshot", help="render once to a PNG and exit")
    a = ap.parse_args()
    raise SystemExit(main(a.path, a.screenshot))
