"""Native Linux Local AI workbench for silicon engineering disciplines.

Qt thread worker keeps slow local inference off the UI thread. The generated
artifact is always a draft. Compiler/simulator evidence is displayed separately.
"""
from __future__ import annotations

import os

from .ai_prompts import PROFILES
from .ai_workbench import (generate, list_models, tool_status, validate_rtl, satya_check,
                           satya_generate_uvm, rustdv_unit_check, test_connection)


def create_ai_tab(root, QtCore, QtGui, QtWidgets, parent=None):
    page = QtWidgets.QWidget(parent)
    page.setObjectName("localAiWorkbench")
    outer = QtWidgets.QVBoxLayout(page)
    outer.setSpacing(8)

    row = QtWidgets.QHBoxLayout()
    backend = QtWidgets.QComboBox()
    backend.setObjectName("aiBackend")
    backend.addItems(["ollama", "openai"])
    endpoint = QtWidgets.QLineEdit(os.environ.get("WENGOLD_LLM_URL",
                                                "http://127.0.0.1:11434"))
    endpoint.setObjectName("aiEndpoint")
    model = QtWidgets.QComboBox()
    model.setObjectName("aiModel")
    model.setEditable(True)
    env_model = os.environ.get("WENGOLD_LLM_MODEL", "qwen2.5-coder:7b")
    model.addItem(env_model)
    discover = QtWidgets.QPushButton("Connect / Models")
    discover.setObjectName("aiConnect")
    roundtrip = QtWidgets.QPushButton("Test Inference")
    roundtrip.setObjectName("aiTestInference")
    row.addWidget(QtWidgets.QLabel("Backend"))
    row.addWidget(backend)
    row.addWidget(QtWidgets.QLabel("Local server"))
    row.addWidget(endpoint, 2)
    row.addWidget(QtWidgets.QLabel("Model"))
    row.addWidget(model, 2)
    row.addWidget(discover)
    row.addWidget(roundtrip)
    outer.addLayout(row)

    mode = QtWidgets.QComboBox()
    mode.setObjectName("aiDiscipline")
    mode.addItems(list(PROFILES))
    outer.addWidget(mode)

    task = QtWidgets.QPlainTextEdit()
    task.setObjectName("aiTask")
    task.setPlaceholderText(
        "Describe an RTL block, UVM environment, PSS scenario, RustDV testbench, "
        "DFT architecture, UPF checks, physical/analog/layout verification plan…")
    task.setMaximumHeight(115)
    outer.addWidget(task)

    actions = QtWidgets.QHBoxLayout()
    generate_btn = QtWidgets.QPushButton("Generate Draft")
    generate_btn.setObjectName("aiGenerate")
    compile_btn = QtWidgets.QPushButton("Check RTL with Icarus")
    compile_btn.setObjectName("aiCheckRtl")
    satya_btn = QtWidgets.QPushButton("Check PSS with Satya")
    satya_btn.setObjectName("aiCheckSatya")
    uvm_btn = QtWidgets.QPushButton("Satya → UVM")
    uvm_btn.setObjectName("aiSatyaUvm")
    rust_btn = QtWidgets.QPushButton("RustDV Unit Tests")
    rust_btn.setObjectName("aiRustDv")
    actions.addWidget(generate_btn)
    actions.addWidget(compile_btn)
    actions.addWidget(satya_btn)
    actions.addWidget(uvm_btn)
    actions.addWidget(rust_btn)
    actions.addStretch(1)
    outer.addLayout(actions)

    validation = QtWidgets.QHBoxLayout()
    testbench = QtWidgets.QLineEdit()
    testbench.setObjectName("aiTestbench")
    testbench.setPlaceholderText("Optional existing project-relative self-checking TB: tb/counter_tb.sv")
    top = QtWidgets.QLineEdit()
    top.setObjectName("aiTop")
    top.setPlaceholderText("Simulation top; RustDV project path for Rust check")
    validation.addWidget(QtWidgets.QLabel("Testbench"))
    validation.addWidget(testbench, 2)
    validation.addWidget(QtWidgets.QLabel("Top"))
    validation.addWidget(top)
    outer.addLayout(validation)

    preview = QtWidgets.QPlainTextEdit()
    preview.setObjectName("aiArtifactPreview")
    preview.setPlaceholderText("AI output appears here as DRAFT; review before use.")
    preview.setFont(QtGui.QFont("DejaVu Sans Mono", 10))
    outer.addWidget(preview, 3)
    evidence = QtWidgets.QPlainTextEdit()
    evidence.setObjectName("aiEvidence")
    evidence.setReadOnly(True)
    evidence.setPlaceholderText("Tool evidence and connection status; no fabricated signoff.")
    outer.addWidget(evidence, 1)
    status = QtWidgets.QLabel("Local AI disabled until a real model server responds")
    status.setObjectName("aiStatus")
    outer.addWidget(status)

    class Worker(QtCore.QObject):
        finished = QtCore.pyqtSignal(object)
        failed = QtCore.pyqtSignal(str)

        def __init__(self, op, values):
            super().__init__()
            self.op, self.values = op, values

        @QtCore.pyqtSlot()
        def run(self):
            try:
                if self.op == "connect":
                    result = {"models": list_models(*self.values)}
                elif self.op == "roundtrip":
                    result = test_connection(*self.values)
                elif self.op == "generate":
                    result = generate(*self.values[:5])
                    if self.values[0] == "RTL Design":
                        result["validation"] = validate_rtl(
                            result["text"], self.values[5], self.values[6], self.values[7])
                elif self.op == "validate":
                    result = validate_rtl(*self.values)
                elif self.op == "satya":
                    result = satya_check(*self.values)
                elif self.op == "satya_uvm":
                    result = satya_generate_uvm(*self.values)
                elif self.op == "rustdv":
                    result = rustdv_unit_check(*self.values)
                else:
                    raise ValueError("unknown workbench operation")
                self.finished.emit(result)
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

    state = {"draft": None, "busy": False, "thread": None, "worker": None}
    page.aiState = state

    def perform(op, values):
        if state["busy"]:
            status.setText("A local AI or tool check is still running")
            return
        state["busy"] = True
        for btn in (discover, roundtrip, generate_btn, compile_btn, satya_btn, uvm_btn, rust_btn):
            btn.setEnabled(False)
        status.setText("Running " + op + " (real local execution)…")
        thread = QtCore.QThread(page)
        worker = Worker(op, values)
        state["thread"], state["worker"] = thread, worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def completed(result):
            import json
            if op == "connect":
                model.clear()
                model.addItems(result["models"])
                if not result["models"]:
                    evidence.setPlainText("Server replied but reports zero models.")
                else:
                    evidence.setPlainText("Local server models: " + ", ".join(result["models"]))
            elif op == "satya_uvm" and result.get("ok"):
                preview.setPlainText(result["code"])
                evidence.setPlainText("SATYA UVM GENERATED · UNVERIFIED\n" + result.get("note", ""))
            elif op == "generate":
                state["draft"] = result
                preview.setPlainText(result["text"])
                import json
                evidence.setPlainText(
                    "AI-GENERATED DRAFT | " + result["model"] + " | sha256 " +
                    result["sha256"] + "\n" +
                    json.dumps(result.get("validation"), indent=2))
                if isinstance(result.get("validation"), dict):
                    if result["validation"]["status"] == "simulation_completed":
                        status.setText("Simulation completed; testbench quality and signoff not proven")
                    elif result["validation"]["status"] == "failed":
                        status.setText("Generated RTL FAILED an independent check")
            else:
                evidence.setPlainText(json.dumps(result, indent=2))
            status.setText(op + " completed; consult actual evidence and limits")
            finish()

        def error(message):
            evidence.setPlainText("NO RESULT: " + message)
            status.setText("Operation failed; no valid evidence")
            finish()

        def finish():
            state["busy"] = False
            for btn in (discover, generate_btn, compile_btn, satya_btn):
                btn.setEnabled(True)
            thread.quit()

        worker.finished.connect(completed)
        worker.failed.connect(error)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def choose_backend(selected):
        if selected == "ollama":
            endpoint.setText("http://127.0.0.1:11434")
        else:
            endpoint.setText("http://127.0.0.1:8080/v1")

    backend.currentTextChanged.connect(choose_backend)
    discover.clicked.connect(lambda: perform("connect", (backend.currentText(),
                                                         endpoint.text().strip())))
    roundtrip.clicked.connect(lambda: perform(
        "roundtrip", (backend.currentText(), endpoint.text().strip(), model.currentText().strip())))
    generate_btn.clicked.connect(lambda: perform(
        "generate", (mode.currentText(), task.toPlainText(), backend.currentText(),
                     endpoint.text().strip(), model.currentText().strip(),
                     root, testbench.text().strip(), top.text().strip())))

    def check_rtl():
        if mode.currentText() != "RTL Design":
            evidence.setPlainText(
                "Icarus gate applies only to standalone RTL. UVM, PSS, RustDV, "
                "analog, DFT, layout and physical outputs require their own tools.")
            return
        if not preview.toPlainText().strip():
            evidence.setPlainText("No draft RTL")
            return
        perform("validate", (preview.toPlainText(), root, testbench.text().strip(),
                             top.text().strip()))

    compile_btn.clicked.connect(check_rtl)

    def check_pss():
        if mode.currentText() != "Portable Stimulus / Satya":
            evidence.setPlainText("Choose Portable Stimulus / Satya first.")
            return
        perform("satya", (root, testbench.text().strip()))

    satya_btn.clicked.connect(check_pss)
    uvm_btn.clicked.connect(lambda: perform("satya_uvm", (root, testbench.text().strip())))
    rust_btn.clicked.connect(lambda: perform("rustdv", (root, top.text().strip())))
    page.aiPreview = preview
    page.aiEvidence = evidence
    page.aiStatus = status
    page.aiTools = tool_status()
    return page
