"""Native Linux specification-to-coverage DV workflow.

The six independent gates show actual source/tool evidence. Local AI runs
asynchronously and produces drafts or hypotheses, never a simulated PASS.
"""
from __future__ import annotations

import json
import os
from . import dv_pipeline


def make_dv_pipeline_tab(root, files, QtCore, QtGui, QtWidgets):
    page = QtWidgets.QWidget()
    page.setObjectName("dvPipelineWorkbench")
    layout = QtWidgets.QVBoxLayout(page)
    layout.setSpacing(7)
    heading = QtWidgets.QLabel("DESIGN VERIFICATION · SPECIFICATION → COVERAGE")
    heading.setObjectName("dvPipelineHeading")
    layout.addWidget(heading)
    identity = QtWidgets.QHBoxLayout()
    spec = QtWidgets.QComboBox()
    spec.setEditable(True)
    spec.setObjectName("dvSpec")
    spec.addItems([p for p in files if p.lower().endswith((
        ".txt", ".md", ".rst", ".yaml", ".yml", ".json", ".pdf"))])
    rtl = QtWidgets.QComboBox()
    rtl.setEditable(True)
    rtl.setObjectName("dvRtl")
    rtl.addItems([p for p in files if p.lower().endswith((".sv", ".v"))])
    identity.addWidget(QtWidgets.QLabel("Specification"))
    identity.addWidget(spec, 2)
    identity.addWidget(QtWidgets.QLabel("RTL"))
    identity.addWidget(rtl, 2)
    layout.addLayout(identity)

    modelrow = QtWidgets.QHBoxLayout()
    backend = QtWidgets.QComboBox()
    backend.setObjectName("dvBackend")
    backend.addItems(["ollama", "openai"])
    endpoint = QtWidgets.QLineEdit(os.environ.get(
        "WENGOLD_LLM_URL", "http://127.0.0.1:11434"))
    endpoint.setObjectName("dvEndpoint")
    model = QtWidgets.QLineEdit(os.environ.get(
        "WENGOLD_LLM_MODEL", "qwen2.5-coder:7b"))
    model.setObjectName("dvModel")
    modelrow.addWidget(QtWidgets.QLabel("Local AI"))
    modelrow.addWidget(backend)
    modelrow.addWidget(endpoint, 2)
    modelrow.addWidget(model, 2)
    layout.addLayout(modelrow)

    phases = QtWidgets.QTabWidget()
    phases.setObjectName("dvWorkflowStages")
    stages = [
        ("Specification + RTL", "dvIntake", "Load and fingerprint sources"),
        ("Verification Plan", "dvPlan", "Generate AI verification plan"),
        ("UVM + SVA", "dvUvm", "Generate UVM / SVA drafts"),
        ("Testcases + Regression", "dvRegression", "Run reviewed regression"),
        ("Root-Cause Debug", "dvDebug", "Explain actual regression log"),
        ("Coverage Closure", "dvCoverage", "Analyze measured coverage bins"),
    ]
    controls = {}
    for label, key, action in stages:
        pane = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(pane)
        help_label = QtWidgets.QLabel(
            "Outputs are evidence-gated. Generated content is DRAFT until independently checked.")
        help_label.setWordWrap(True)
        v.addWidget(help_label)
        if key == "dvUvm":
            uvm_choice = QtWidgets.QComboBox()
            uvm_choice.setObjectName("dvArtifactKind")
            uvm_choice.addItems(["uvm", "sva", "testcases"])
            v.addWidget(uvm_choice)
            controls["kind"] = uvm_choice
        if key in ("dvRegression", "dvDebug", "dvCoverage"):
            item = QtWidgets.QLineEdit()
            item.setObjectName(key + "File")
            item.setPlaceholderText(
                {"dvRegression": "flows/uvm.json — reviewed tool manifest",
                 "dvDebug": "results/uvm-regression.log — actual failure log",
                 "dvCoverage": "results/coverage.json — actual normalized bins"}
                [key])
            v.addWidget(item)
            controls[key + "_file"] = item
        if key == "dvCoverage":
            target = QtWidgets.QDoubleSpinBox()
            target.setObjectName("dvCoverageTarget")
            target.setRange(0.01, 100)
            target.setValue(95)
            target.setSuffix("% target")
            v.addWidget(target)
            controls["target"] = target
        btn = QtWidgets.QPushButton(action)
        btn.setObjectName(key + "Button")
        v.addWidget(btn)
        if key in ("dvPlan", "dvUvm"):
            save = QtWidgets.QPushButton("Save AI draft to wengold-drafts/")
            save.setObjectName(key + "SaveDraft")
            v.addWidget(save)
            controls[key + "_save"] = save
        report = QtWidgets.QPlainTextEdit()
        report.setReadOnly(True)
        report.setObjectName(key + "Evidence")
        report.setPlaceholderText("No result. This stage has not run.")
        v.addWidget(report, 1)
        controls[key] = {"button": btn, "evidence": report}
        phases.addTab(pane, label)
    layout.addWidget(phases, 1)

    banner = QtWidgets.QLabel(
        "NOT SIGNED OFF · all AI artifacts require human review and real simulator evidence")
    banner.setObjectName("dvPipelineStatus")
    layout.addWidget(banner)

    class Worker(QtCore.QObject):
        succeeded = QtCore.pyqtSignal(object)
        failed = QtCore.pyqtSignal(str)

        def __init__(self, op, values):
            super().__init__()
            self.op, self.values = op, values

        @QtCore.pyqtSlot()
        def run(self):
            try:
                functions = {
                    "intake": dv_pipeline.intake,
                    "generate": dv_pipeline.generate_artifact,
                    "regression": dv_pipeline.run_regression,
                    "debug": dv_pipeline.triage,
                    "coverage": dv_pipeline.coverage_report,
                }
                self.succeeded.emit(functions[self.op](*self.values))
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

    state = {"busy": False, "thread": None, "worker": None,
             "results": {}, "source_fingerprints": None}
    page.pipelineState = state

    def current_sources():
        return root, spec.currentText().strip(), rtl.currentText().strip()

    def generation_args(kind):
        return (*current_sources(), kind, backend.currentText(),
                endpoint.text().strip(), model.text().strip())

    def handle(key, op, values):
        if state["busy"]:
            banner.setText("Another verification stage is running.")
            return
        state["busy"] = True
        for pair in controls.values():
            if isinstance(pair, dict):
                pair["button"].setEnabled(False)
        banner.setText("Running " + key + " — waiting for actual local result.")
        thread = QtCore.QThread(page)
        worker = Worker(op, values)
        state["thread"], state["worker"] = thread, worker
        worker.moveToThread(thread)
        output = controls[key]["evidence"]

        def done():
            state["busy"] = False
            for pair in controls.values():
                if isinstance(pair, dict):
                    pair["button"].setEnabled(True)
            thread.quit()

        def ok(result):
            state["results"][key] = result
            if key == "dvIntake":
                state["source_fingerprints"] = (
                    result["spec_sha256"], result["rtl_sha256"])
            if result.get("text"):
                output.setPlainText(result["text"] + "\n\n" + json.dumps(
                    {k: v for k, v in result.items() if k != "text"}, indent=2))
            else:
                output.setPlainText(json.dumps(result, indent=2, default=str))
            banner.setText(key + ": " + result.get("status", "completed") +
                           " — not signoff")
            done()

        def failed(message):
            output.setPlainText("FAILED / NO VALID EVIDENCE\n" + message)
            banner.setText(key + ": failed — no checks credited")
            done()

        worker.succeeded.connect(ok)
        worker.failed.connect(failed)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    controls["dvIntake"]["button"].clicked.connect(
        lambda: handle("dvIntake", "intake", current_sources()))
    controls["dvPlan"]["button"].clicked.connect(
        lambda: handle("dvPlan", "generate", generation_args("verification_plan")))
    controls["dvUvm"]["button"].clicked.connect(
        lambda: handle("dvUvm", "generate",
                       generation_args(controls["kind"].currentText())))

    def run_regression():
        name = controls["dvRegression_file"].text().strip()
        if not name:
            controls["dvRegression"]["evidence"].setPlainText(
                "Select a reviewed project-relative UVM/PSS/RustDV manifest.")
            return
        accepted = QtWidgets.QMessageBox.question(
            page, "Run independent simulator",
            "This executes a reviewed project-local tool manifest. "
            "Only run source and commands that you trust. Continue?")
        if accepted == QtWidgets.QMessageBox.StandardButton.Yes:
            handle("dvRegression", "regression", (root, name))

    def save_generated(key):
        item = state["results"].get(key)
        if not item or item.get("status") != "draft_not_verified":
            controls[key]["evidence"].appendPlainText("No AI draft available to export.")
            return
        kind = item["kind"]
        default = "wengold-drafts/" + kind + (
            ".sv" if kind in ("uvm", "sva") else ".md")
        name, ok = QtWidgets.QInputDialog.getText(
            page, "Export unverified draft",
            "Project-relative output; existing files will not be replaced:", text=default)
        if not ok:
            return
        try:
            saved = dv_pipeline.save_draft(root, item, name.strip())
            controls[key]["evidence"].appendPlainText(
                "\n" + json.dumps(saved, indent=2))
        except Exception as exc:
            controls[key]["evidence"].appendPlainText(
                "\nSave refused: " + str(exc))

    for key in ("dvPlan", "dvUvm"):
        controls[key + "_save"].clicked.connect(
            lambda _checked=False, k=key: save_generated(k))

    controls["dvRegression"]["button"].clicked.connect(run_regression)
    controls["dvDebug"]["button"].clicked.connect(
        lambda: handle("dvDebug", "debug",
                       (root, controls["dvDebug_file"].text().strip(),
                        backend.currentText(), endpoint.text().strip(),
                        model.text().strip())))
    controls["dvCoverage"]["button"].clicked.connect(
        lambda: handle("dvCoverage", "coverage",
                       (root, controls["dvCoverage_file"].text().strip(),
                        controls["target"].value())))

    def refresh_files(newfiles):
        for widget, endings in (
            (spec, (".txt", ".md", ".rst", ".yaml", ".yml", ".json", ".pdf")),
            (rtl, (".v", ".sv")),
        ):
            chosen = widget.currentText()
            widget.clear()
            widget.addItems([p for p in newfiles if p.lower().endswith(endings)])
            widget.setCurrentText(chosen)

    page.refreshSources = refresh_files
    page.stageControls = controls
    page.workflowTabs = phases
    return page
