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
tests are structural — widget tree, contents, colours — not behavioural.
"""
from __future__ import annotations

from pathlib import Path

# The palette the app was asked for: white ground, crimson accent, near-black text.
# Red is reserved for INVALIDATED, so a red pixel always means the same thing.
GROUND = "#FFFFFF"
PANEL = "#FAFAFA"
LINE = "#E4E4E7"
TEXT = "#18181B"
MUTED = "#71717A"
RED = "#C81E1E"

STYLESHEET = f"""
QMainWindow, QWidget {{ background: {GROUND}; color: {TEXT}; }}
QMenuBar {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
QMenuBar::item:selected {{ background: {LINE}; }}
QMenu {{ background: {GROUND}; border: 1px solid {LINE}; }}
QFrame#strip {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
QLabel#project {{ font-size: 13px; font-weight: 600; }}
QLabel#revision {{ color: {MUTED}; font-size: 11px; }}
QLabel#sectionTitle {{ color: {MUTED}; font-size: 10px; font-weight: 600;
                       letter-spacing: 1px; }}
QTreeWidget, QTableWidget, QTextEdit, QLineEdit {{
    background: {GROUND}; border: 1px solid {LINE}; selection-background-color: {LINE};
    selection-color: {TEXT}; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none;
                        border-bottom: 1px solid {LINE}; padding: 4px 6px;
                        font-size: 10px; font-weight: 600; }}
QTreeWidget::item, QTableWidget::item {{ padding: 3px 4px; }}
QLineEdit {{ border: 1px solid {LINE}; padding: 6px 8px; font-family: monospace; }}
QLineEdit:focus {{ border: 1px solid {TEXT}; }}
QTextEdit#transcript {{ font-family: monospace; font-size: 12px; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QSplitter::handle {{ background: {LINE}; }}
"""


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
    from .desktop import _exec, _file_detail

    class MainWindow(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.state = state
            self.setWindowTitle(f"WENGOLD — {state['path']}")
            self.resize(1180, 760)
            self.setStyleSheet(STYLESHEET)

            # ---- header strip: the revision line, not a logo -----------------
            # The mark rendered as a black blob at 15px in the browser version, so
            # the strip carries information instead.
            strip = QtWidgets.QFrame()
            strip.setObjectName("strip")
            strip.setFixedHeight(52)
            lay = QtWidgets.QHBoxLayout(strip)
            lay.setContentsMargins(14, 8, 14, 8)
            left = QtWidgets.QVBoxLayout()
            left.setSpacing(2)
            project = QtWidgets.QLabel(Path(state["path"]).name or state["path"])
            project.setObjectName("project")
            revision = QtWidgets.QLabel(self._revision())
            revision.setObjectName("revision")
            left.addWidget(project)
            left.addWidget(revision)
            lay.addLayout(left)
            lay.addStretch(1)
            self.coverage = QtWidgets.QLabel(
                f"{state['design_units']}/{state['files']} files are design units")
            self.coverage.setObjectName("revision")
            lay.addWidget(self.coverage)

            # ---- the three panes -------------------------------------------
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setHeaderLabels(["FILE"])
            self.tree.setColumnWidth(0, 230)
            self.tree.itemSelectionChanged.connect(self._on_file)

            self.table = QtWidgets.QTableWidget(0, 3)
            self.table.setHorizontalHeaderLabels(["BLOCK", "OUT", "IN"])
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.setEditTriggers(
                QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            self.table.setSelectionBehavior(
                QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.itemSelectionChanged.connect(self._on_block)

            self.detail = QtWidgets.QTextEdit()
            self.detail.setReadOnly(True)

            top = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
            for w, title in ((self.tree, "FILES"), (self.table, "BLOCKS"),
                             (self.detail, "DETAIL")):
                box = QtWidgets.QWidget()
                v = QtWidgets.QVBoxLayout(box)
                v.setContentsMargins(8, 8, 8, 8)
                v.setSpacing(6)
                head = QtWidgets.QLabel(title)
                head.setObjectName("sectionTitle")
                v.addWidget(head)
                v.addWidget(w)
                top.addWidget(box)
            top.setSizes([260, 420, 480])

            # ---- the CLI pane at the bottom --------------------------------
            self.transcript = QtWidgets.QTextEdit()
            self.transcript.setObjectName("transcript")
            self.transcript.setReadOnly(True)
            self.input = QtWidgets.QLineEdit()
            self.input.setPlaceholderText(
                "summary · files · blocks · verdicts · singularity · review · vibe · help")
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

            vertical = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
            vertical.addWidget(top)
            vertical.addWidget(bottom)
            vertical.setSizes([520, 190])

            central = QtWidgets.QWidget()
            cv = QtWidgets.QVBoxLayout(central)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(0)
            cv.addWidget(strip)
            cv.addWidget(vertical)
            self.setCentralWidget(central)

            self._menus()
            self.statusBar().showMessage(
                f"{state['files']} files · {state['blocks']} blocks · "
                f"{state['nodes']} nodes · {state['unresolved']} unresolved")
            self._populate()
            self._say("wengold " + _version() + " — type `help` for commands")

        # -- helpers -------------------------------------------------------
        def _revision(self) -> str:
            s = self.state
            bits = [Path(s["path"]).name or s["path"],
                    f"{s['blocks']} blocks", f"{s['nodes']} nodes",
                    f"{s['edges']} edges", f"{s['unresolved']} unresolved"]
            return " — ".join(bits)

        def _menus(self):
            bar = self.menuBar()
            file_menu = bar.addMenu("&File")
            reload_ = QtGui.QAction("&Reload", self)
            reload_.setShortcut("Ctrl+R")
            reload_.triggered.connect(self._reload)
            quit_ = QtGui.QAction("&Quit", self)
            quit_.setShortcut("Ctrl+Q")
            quit_.triggered.connect(self.close)
            file_menu.addAction(reload_)
            file_menu.addSeparator()
            file_menu.addAction(quit_)

            view = bar.addMenu("&View")
            for name, focus in (("Files", self.tree), ("Blocks", self.table),
                                ("CLI", self.input)):
                act = QtGui.QAction(name, self)
                act.triggered.connect(lambda _=False, w=focus: w.setFocus())
                view.addAction(act)

            help_menu = bar.addMenu("&Help")
            about = QtGui.QAction("&About", self)
            about.triggered.connect(self._about)
            help_menu.addAction(about)

        def _populate(self):
            self.tree.clear()
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
                for col, text in enumerate((b, str(out), str(inn))):
                    cell = QtWidgets.QTableWidgetItem(text)
                    if col == 0:
                        cell.setData(QtCore.Qt.ItemDataRole.UserRole, b)
                    self.table.setItem(i, col, cell)
            self.detail.setHtml(self._overview_html())

        def _overview_html(self) -> str:
            s = self.state
            notes = "".join(f"<li>{n}</li>" for n in s.get("notes", []))
            return (
                f"<h3 style='margin:0 0 8px'>{Path(s['path']).name}</h3>"
                f"<p style='color:{MUTED}'>{s['files']} files · {s['blocks']} blocks"
                f" · {s['nodes']} nodes · {s['edges']} edges</p>"
                f"<p>Design units <b>{s['design_units']}/{s['files']}</b> · "
                f"complete <b>{s['complete']}</b> · "
                f"unresolved <b>{s['unresolved']}</b></p>"
                + (f"<ul>{notes}</ul>" if notes else "")
            )

        def _on_file(self):
            items = self.tree.selectedItems()
            if not items:
                return
            rel = items[0].data(0, QtCore.Qt.ItemDataRole.UserRole)
            d = _file_detail(self.state, rel)
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

        def _reload(self):
            from .desktop import build_state
            try:
                self.state = build_state(self.state["path"])
            except Exception as exc:
                self._say(f"  reload failed: {exc}")
                return
            self._populate()
            self.statusBar().showMessage(
                f"{self.state['files']} files · {self.state['blocks']} blocks · "
                f"{self.state['unresolved']} unresolved")
            self._say("  reloaded")

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
