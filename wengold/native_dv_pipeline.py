"""Native Linux specification-to-coverage DV workflow.

The workflow gates show actual source/tool evidence. Local AI runs
asynchronously and produces drafts or hypotheses, never a simulated PASS.
"""
from __future__ import annotations

import json

from . import dv_pipeline, sv_agents
from .ai_workbench import list_models, test_connection
from .native_model import model_controls
from .qwen_cloud import QWEN_BACKEND


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
    backend, endpoint, model, presets = model_controls(QtCore, QtWidgets, "dv", dhir=True)
    modelrow.addWidget(QtWidgets.QLabel("AI model"))
    modelrow.addWidget(backend)
    modelrow.addWidget(endpoint, 2)
    modelrow.addWidget(model, 2)
    check_model = QtWidgets.QPushButton("Test connection")
    check_model.setObjectName("dvTestConnection")
    check_model.setToolTip("Discover local models, or test Qwen4-Max with a short prompt")
    modelrow.addWidget(check_model)
    layout.addLayout(modelrow)
    layout.addLayout(presets)
    model_status = QtWidgets.QLabel("Model not tested · No inference has run")
    model_status.setObjectName("dvModelStatus")
    layout.addWidget(model_status)

    phases = QtWidgets.QTabWidget()
    phases.setObjectName("dvWorkflowStages")
    stages = [
        ("Specification + RTL", "dvIntake", "Load and fingerprint sources"),
        ("Verification Plan", "dvPlan", "Generate AI verification plan"),
        ("UVM + SVA", "dvUvm", "Generate UVM / SVA drafts"),
        ("Testcases + Regression", "dvRegression", "Run reviewed regression"),
        ("Root-Cause Debug", "dvDebug", "Explain actual regression log"),
        ("Coverage Closure", "dvCoverage", "Analyze measured coverage bins"),
        ("Independent Agents", "dvAgent", "Run selected SystemVerilog agent"),
    ]
    controls = {}
    for label, key, action in stages:
        pane = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(pane)
        help_label = QtWidgets.QLabel(
            "Outputs are evidence-gated. Generated content is DRAFT until independently checked.")
        help_label.setWordWrap(True)
        v.addWidget(help_label)
        step_status = QtWidgets.QLabel("NOT RUN · no evidence")
        step_status.setObjectName(key + "Status")
        step_status.setStyleSheet("color:#665C35; font-weight:600; padding:3px 0;")
        v.addWidget(step_status)
        controls[key + "_status"] = step_status
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
        if key == "dvRegression":
            cases = QtWidgets.QPushButton("Generate testcase matrix (AI draft)")
            cases.setObjectName("dvGenerateTestcases")
            v.addWidget(cases)
            controls["testcases_button"] = cases
        if key == "dvCoverage":
            closure = QtWidgets.QPushButton("Draft coverage closure plan with AI")
            closure.setObjectName("dvCoverageClosure")
            v.addWidget(closure)
            controls["coverage_closure_button"] = closure
            target = QtWidgets.QDoubleSpinBox()
            target.setObjectName("dvCoverageTarget")
            target.setRange(0.01, 100)
            target.setValue(95)
            target.setSuffix("% target")
            v.addWidget(target)
            controls["target"] = target
        if key == "dvAgent":
            role = QtWidgets.QComboBox()
            role.setObjectName("dvAgentRole")
            for role_id, (label, _) in sv_agents.ROLES.items():
                role.addItem(label, role_id)
            v.addWidget(role)
            agent_evidence = QtWidgets.QLineEdit()
            agent_evidence.setObjectName("dvAgentInput")
            agent_evidence.setPlaceholderText(
                "Project-relative log/report (required for Debug, Coverage and Signoff)")
            v.addWidget(agent_evidence)
            agent_task = QtWidgets.QLineEdit()
            agent_task.setObjectName("dvAgentTask")
            agent_task.setMaxLength(2000)
            agent_task.setPlaceholderText("Optional task for this run")
            v.addWidget(agent_task)
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
                    "probe": lambda backend, endpoint, model: {
                        "status": "connected" if model in list_models(backend, endpoint)
                        else "model_not_found",
                        "model": model},
                    "roundtrip": test_connection,
                    "sv_agent": sv_agents.run,
                    "intake": dv_pipeline.intake,
                    "generate": dv_pipeline.generate_artifact,
                    "regression": dv_pipeline.run_regression,
                    "debug": dv_pipeline.triage,
                    "coverage": dv_pipeline.coverage_report,
                    "coverage_closure": dv_pipeline.coverage_closure_draft,
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
        controls[key + "_status"].setText("RUNNING · waiting for tool/model evidence")
        cloud = (op in ("sv_agent", "generate", "debug", "coverage_closure")
                 and backend.currentText() == QWEN_BACKEND)
        banner.setText("Running " + key + (" using Alibaba Cloud…" if cloud else " locally…"))
        thread = QtCore.QThread(page)
        worker = Worker(op, values)
        state["thread"], state["worker"] = thread, worker
        worker.moveToThread(thread)
        output = controls[key]["evidence"]
        if key == "dvAgent":
            role.setEnabled(False)
            state["results"].pop("dvAgent:" + values[1], None)

        def done():
            state["busy"] = False
            if key == "dvAgent":
                role.setEnabled(True)
            for pair in controls.values():
                if isinstance(pair, dict):
                    pair["button"].setEnabled(True)
            thread.quit()

        def ok(result):
            result_key = "dvAgent:" + result["role"] if key == "dvAgent" else key
            state["results"][result_key] = result
            if key == "dvIntake":
                state["source_fingerprints"] = (
                    result["spec_sha256"], result["rtl_sha256"])
            if result.get("text"):
                output.setPlainText(result["text"] + "\n\n" + json.dumps(
                    {k: v for k, v in result.items() if k != "text"}, indent=2))
            else:
                output.setPlainText(json.dumps(result, indent=2, default=str))
            run_status = str(result.get("status", "completed"))
            label = ("DRAFT · human review required" if "draft" in run_status
                     else "EVIDENCE IMPORTED · no signoff" if key in ("dvRegression", "dvCoverage")
                     else "SOURCE LOADED · not verified" if key == "dvIntake"
                     else "HYPOTHESIS · confirm with independent tests")
            controls[key + "_status"].setText(label)
            banner.setText(key + ": " + run_status + " — not signoff")
            done()

        def failed(message):
            output.setPlainText("FAILED / NO VALID EVIDENCE\n" + message)
            controls[key + "_status"].setText("FAILED · no checks credited")
            banner.setText(key + ": failed — no checks credited")
            done()

        worker.succeeded.connect(ok)
        worker.failed.connect(failed)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def check_connection():
        if state["busy"]:
            model_status.setText("Another DV task is running")
            return
        state["busy"] = True
        check_model.setEnabled(False)
        cloud = backend.currentText() == QWEN_BACKEND
        model_status.setText("Testing Qwen4-Max…" if cloud else "Connecting to local model server…")
        thread = QtCore.QThread(page)
        worker = Worker("roundtrip" if cloud else "probe", (backend.currentText(),
                                  endpoint.text().strip(), model.text().strip()))
        state["thread"], state["worker"] = thread, worker
        worker.moveToThread(thread)
        def finished(message):
            model_status.setText(message)
            state["busy"] = False
            check_model.setEnabled(True)
            thread.quit()
        worker.succeeded.connect(lambda result:
            finished("Model ready: " + result["model"] if
                     result["status"] in ("connected", "responding") else
                     "Server reachable; chosen model not installed. "
                     "Select or pull the exact model before generating."))
        worker.failed.connect(lambda error: finished("Model unavailable: " + error))
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    check_model.clicked.connect(check_connection)

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

    controls["testcases_button"].clicked.connect(
        lambda: handle("dvRegression", "generate", generation_args("testcases")))
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
    controls["coverage_closure_button"].clicked.connect(
        lambda: handle("dvCoverage", "coverage_closure",
                       (root, controls["dvCoverage_file"].text().strip(),
                        spec.currentText().strip(), rtl.currentText().strip(),
                        backend.currentText(), endpoint.text().strip(),
                        model.text().strip())))

    def run_sv_agent():
        # Keep each role's last result separate even though they share a UI tab.
        role_id = role.currentData()
        selected_spec = spec.currentText().strip()
        handle("dvAgent", "sv_agent",
               (root, role_id, rtl.currentText().strip(), selected_spec,
                agent_evidence.text().strip(), agent_task.text(),
                backend.currentText(), endpoint.text().strip(), model.text().strip()))

    controls["dvAgent"]["button"].clicked.connect(run_sv_agent)

    def show_role_result(_index):
        result = state["results"].get("dvAgent:" + str(role.currentData()))
        controls["dvAgent"]["evidence"].setPlainText(
            json.dumps(result, indent=2) if result else "No result for this role.")
        controls["dvAgent_status"].setText(
            "DRAFT · human review required" if result else "NOT RUN · no evidence")

    role.currentIndexChanged.connect(show_role_result)

    def refresh_files(newfiles):
        # A project refresh invalidates in-memory DV run assumptions. Saved
        # source digests remain in exported artifacts for external audit.
        if state["results"]:
            state["results"].clear()
            state["source_fingerprints"] = None
            for key in ("dvIntake", "dvPlan", "dvUvm", "dvRegression", "dvDebug", "dvCoverage", "dvAgent"):
                controls[key]["evidence"].setPlainText(
                    "STALE — project source inventory refreshed; rerun this stage.")
                controls[key + "_status"].setText("STALE · rerun required")
            banner.setText("STALE EVIDENCE — rerun source intake and independent checks")
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
