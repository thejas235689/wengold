"""Dockable-style native implementation report: real synthesis, PPA caveats.

The three analysis columns match EDA workbench expectations while never
substituting estimated or synthetic area, timing or power for tool evidence.
"""
from __future__ import annotations

import json
from .synthesis_tools import run_synthesis


def make_implementation_tab(root, files, QtCore, QtGui, QtWidgets):
    page = QtWidgets.QWidget()
    page.setObjectName("implementationWorkbench")
    outer = QtWidgets.QVBoxLayout(page)

    toolbar = QtWidgets.QHBoxLayout()
    selector = QtWidgets.QComboBox()
    selector.setObjectName("implSource")
    selector.addItems([f for f in files if f.lower().endswith((".sv", ".v"))])
    top = QtWidgets.QLineEdit()
    top.setObjectName("implTop")
    top.setPlaceholderText("Module top (empty = auto-detect)")
    synth = QtWidgets.QPushButton("Run Yosys Synthesis")
    synth.setObjectName("implRunSynthesis")
    toolbar.addWidget(QtWidgets.QLabel("RTL source"))
    toolbar.addWidget(selector, 3)
    toolbar.addWidget(QtWidgets.QLabel("Top"))
    toolbar.addWidget(top, 1)
    toolbar.addWidget(synth)
    outer.addLayout(toolbar)

    panes = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
    left = QtWidgets.QWidget()
    l = QtWidgets.QVBoxLayout(left)
    l.addWidget(QtWidgets.QLabel("Synthesis configuration & tool log"))
    synth_log = QtWidgets.QPlainTextEdit()
    synth_log.setObjectName("implSynthesisLog")
    synth_log.setReadOnly(True)
    synth_log.setPlainText(
        "Select an existing RTL source, then run Yosys. "
        "Complex designs require a reviewed multi-file synthesis flow.")
    l.addWidget(synth_log)

    center = QtWidgets.QWidget()
    c = QtWidgets.QVBoxLayout(center)
    c.addWidget(QtWidgets.QLabel("Design hierarchy / generic netlist"))
    hierarchy = QtWidgets.QTreeWidget()
    hierarchy.setObjectName("implHierarchy")
    hierarchy.setHeaderLabels(["Module / Cell type", "Count"])
    c.addWidget(hierarchy)
    netlist = QtWidgets.QPlainTextEdit()
    netlist.setObjectName("implNetlistDetails")
    netlist.setReadOnly(True)
    netlist.setPlaceholderText("Real generated module/cell breakdown appears here.")
    c.addWidget(netlist)

    right = QtWidgets.QWidget()
    r = QtWidgets.QVBoxLayout(right)
    r.addWidget(QtWidgets.QLabel("PPA / timing evidence"))
    ppa = QtWidgets.QPlainTextEdit()
    ppa.setObjectName("implPpaEvidence")
    ppa.setReadOnly(True)
    ppa.setPlainText(
        "Timing: NOT RUN. Requires Liberty, SDC and STA.\n"
        "Area: NOT AVAILABLE without technology mapping.\n"
        "Power: NOT RUN. Requires activity and library power models.\n"
        "Generic cell counts will be shown after real synthesis.")
    r.addWidget(ppa)
    for widget in (left, center, right):
        panes.addWidget(widget)
    panes.setSizes([330, 470, 320])
    outer.addWidget(panes, 1)
    status = QtWidgets.QLabel("No synthesis has run")
    status.setObjectName("implStatus")
    outer.addWidget(status)

    class Worker(QtCore.QObject):
        completed = QtCore.pyqtSignal(object)
        failed = QtCore.pyqtSignal(str)

        def __init__(self, args):
            super().__init__()
            self.args = args

        @QtCore.pyqtSlot()
        def run(self):
            try:
                self.completed.emit(run_synthesis(*self.args))
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

    state = {"thread": None, "worker": None, "busy": False, "result": None}
    page.synthesisState = state

    def refresh_files(updated_files):
        chosen = selector.currentText()
        selector.clear()
        selector.addItems([f for f in updated_files if f.lower().endswith((".sv", ".v"))])
        if selector.findText(chosen) >= 0:
            selector.setCurrentText(chosen)

    def show_result(result):
        state["result"] = result
        if not result.get("ok"):
            status.setText("Synthesis not completed: " + result.get("status", "unknown"))
            synth_log.setPlainText(result.get("log") or result.get("message", "No evidence"))
            return
        status.setText("Yosys generic synthesis completed; NOT physical signoff")
        synth_log.setPlainText(result["log"])
        hierarchy.clear()
        for module in result["modules"]:
            item = QtWidgets.QTreeWidgetItem(
                [module["name"], str(module["cells"])])
            hierarchy.addTopLevelItem(item)
            for cell_type, number in sorted(module["cell_types"].items()):
                item.addChild(QtWidgets.QTreeWidgetItem([cell_type, str(number)]))
            item.setExpanded(True)
        netlist.setPlainText(json.dumps(result["modules"], indent=2))
        ppa.setPlainText(
            f"Modules: {result['module_count']}\n"
            f"Generic cells: {result['total_cells']}\n"
            f"Named wires: {result['total_wire_names']}\n\n"
            f"Timing: {result['timing']}\n"
            f"Physical area: {result['chip_area']}\n"
            f"Power: {result['power']}\n\n"
            f"RTL SHA256: {result['source_sha256']}\n"
            f"Netlist SHA256: {result['netlist_sha256']}\n"
            f"{result['qualification']}")

    def launch():
        if state["busy"]:
            return
        rel = selector.currentText()
        if not rel:
            status.setText("Select a design RTL file before synthesis.")
            return
        state["busy"] = True
        synth.setEnabled(False)
        status.setText("Running Yosys on the selected local RTL source…")
        thread = QtCore.QThread(page)
        worker = Worker((root, rel, top.text().strip()))
        state["thread"], state["worker"] = thread, worker
        worker.moveToThread(thread)

        def done():
            state["busy"] = False
            synth.setEnabled(True)
            thread.quit()

        worker.completed.connect(lambda result: (show_result(result), done()))
        worker.failed.connect(lambda error: (
            status.setText("Synthesis failed"),
            synth_log.setPlainText(error), done()))
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    synth.clicked.connect(launch)
    page.refreshSources = refresh_files
    page.synthLog = synth_log
    page.hierarchy = hierarchy
    page.ppaReport = ppa
    page.synthButton = synth
    return page
