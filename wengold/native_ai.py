"""Native Linux Local AI workbench for silicon engineering disciplines.

Qt thread worker keeps slow local inference off the UI thread. The generated
artifact is always a draft. Compiler/simulator evidence is displayed separately.
"""
from __future__ import annotations

import os

from .agent.llm import DEFAULT_OLLAMA, DEFAULT_OPENAI, PRESETS, preset

from .ai_prompts import PROFILES
from .multi_rag import MultiRAG
from .eda_flows import inspect_manifest, execute_manifest
from .ai_workbench import (generate, list_models, tool_status, validate_rtl, satya_check,
                           satya_generate_uvm, rustdv_unit_check, rustdv_simulate, test_connection)


def create_ai_tab(root, QtCore, QtGui, QtWidgets, parent=None):
    page = QtWidgets.QWidget(parent)
    page.setObjectName("localAiWorkbench")
    outer = QtWidgets.QVBoxLayout(page)
    outer.setSpacing(8)

    row = QtWidgets.QHBoxLayout()
    backend = QtWidgets.QComboBox()
    backend.setObjectName("aiBackend")
    backend.addItems(["ollama", "openai"])
    env_model = os.environ.get("WENGOLD_LLM_MODEL", "qwen2.5-coder:7b")
    configured = preset(env_model)
    configured_backend = os.environ.get("WENGOLD_LLM_BACKEND", "").strip().lower()
    backend.setCurrentText(configured_backend or (configured.backend if configured else "ollama"))
    default_endpoint = DEFAULT_OPENAI if backend.currentText() == "openai" else DEFAULT_OLLAMA
    endpoint = QtWidgets.QLineEdit(os.environ.get("WENGOLD_LLM_URL") or default_endpoint)
    endpoint.setObjectName("aiEndpoint")
    model = QtWidgets.QComboBox()
    model.setObjectName("aiModel")
    model.setEditable(True)
    model.addItem(env_model)
    dhir_button = QtWidgets.QPushButton("Use Dhīr 2B")
    dhir_button.setObjectName("aiDhirPreset")
    dhir_button.setToolTip(PRESETS["dhir-2b"].note + "\nStart locally with: " +
                           PRESETS["dhir-2b"].serve)

    def select_dhir():
        previous = DEFAULT_OPENAI if backend.currentText() == "openai" else DEFAULT_OLLAMA
        if endpoint.text().strip() in ("", previous):
            endpoint.setText(DEFAULT_OPENAI)
        backend.setCurrentText("openai")
        model.setCurrentText("dhir-2b")

    dhir_button.clicked.connect(select_dhir)
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
    row.addWidget(dhir_button)
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
    rustsim_btn = QtWidgets.QPushButton("Run RustDV VPI")
    rustsim_btn.setObjectName("aiRustDvSimulator")
    actions.addWidget(generate_btn)
    actions.addWidget(compile_btn)
    actions.addWidget(satya_btn)
    actions.addWidget(uvm_btn)
    actions.addWidget(rust_btn)
    actions.addWidget(rustsim_btn)
    eda_btn = QtWidgets.QPushButton("Run reviewed EDA flow")
    eda_btn.setObjectName("aiRunEdaFlow")
    actions.addWidget(eda_btn)
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
    eda_row = QtWidgets.QHBoxLayout()
    manifest = QtWidgets.QLineEdit()
    manifest.setObjectName("aiEdaManifest")
    manifest.setPlaceholderText("Project-relative reviewed EDA recipe, e.g. flows/uvm.json")
    inspect_btn = QtWidgets.QPushButton("Inspect EDA recipe")
    inspect_btn.setObjectName("aiInspectEdaFlow")
    eda_row.addWidget(QtWidgets.QLabel("EDA manifest"))
    eda_row.addWidget(manifest, 1)
    eda_row.addWidget(inspect_btn)
    outer.addLayout(eda_row)

    rag_row = QtWidgets.QHBoxLayout()
    rag_manifest = QtWidgets.QLineEdit()
    rag_manifest.setObjectName("aiRagManifest")
    rag_manifest.setPlaceholderText("Optional project-relative manifest, e.g. multi-rag.json")
    rag_preview = QtWidgets.QPushButton("Preview Multi-RAG context")
    rag_preview.setObjectName("aiRagPreview")
    rag_row.addWidget(QtWidgets.QLabel("Multi-RAG"))
    rag_row.addWidget(rag_manifest, 1)
    rag_row.addWidget(rag_preview)
    outer.addLayout(rag_row)

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
                    rag = self.values[8]
                    options = {"project_root": self.values[5], "rag_manifest": rag} if rag else {}
                    result = generate(*self.values[:5], **options)
                    if self.values[0] == "RTL Design" and not rag:
                        result["validation"] = validate_rtl(
                            result["text"], self.values[5], self.values[6], self.values[7])
                elif self.op == "rag_preview":
                    result = MultiRAG.load(self.values[0], self.values[1]).retrieve(self.values[2])
                elif self.op == "validate":
                    result = validate_rtl(*self.values)
                elif self.op == "satya":
                    result = satya_check(*self.values)
                elif self.op == "satya_uvm":
                    result = satya_generate_uvm(*self.values)
                elif self.op == "rustdv":
                    result = rustdv_unit_check(*self.values)
                elif self.op == "rustdv_sim":
                    result = rustdv_simulate(*self.values)
                elif self.op == "eda_inspect":
                    result = inspect_manifest(*self.values)
                elif self.op == "eda_run":
                    result = execute_manifest(*self.values)
                else:
                    raise ValueError("unknown workbench operation")
                self.finished.emit(result)
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

    state = {"draft": None, "busy": False, "thread": None, "worker": None}
    page.aiState = state

    buttons = (discover, roundtrip, generate_btn, compile_btn, satya_btn, uvm_btn,
               rust_btn, rustsim_btn, eda_btn, inspect_btn, rag_preview)

    def perform(op, values):
        if state["busy"]:
            status.setText("A local AI or tool check is still running")
            return
        state["busy"] = True
        for btn in buttons:
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
                report = {"validation": result["validation"]}
                if "retrieval" in result:
                    report["retrieval"] = result["retrieval"]
                evidence.setPlainText(
                    "AI-GENERATED DRAFT | " + result["model"] + " | sha256 " +
                    result["sha256"] + "\n" + json.dumps(report, indent=2))
                if isinstance(result.get("validation"), dict):
                    if result["validation"]["status"] == "simulation_completed":
                        status.setText("Simulation completed; testbench quality and signoff not proven")
                    elif result["validation"]["status"] == "failed":
                        status.setText("Generated RTL FAILED an independent check")
            else:
                evidence.setPlainText(json.dumps(result, indent=2))
            if op != "generate" or not isinstance(result.get("validation"), dict) or result["validation"]["status"] not in ("simulation_completed", "failed"):
                status.setText(op + " completed; consult actual evidence and limits")
            finish()

        def error(message):
            evidence.setPlainText("NO RESULT: " + message)
            status.setText("Operation failed; no valid evidence")
            finish()

        def finish():
            state["busy"] = False
            for btn in buttons:
                btn.setEnabled(True)
            thread.quit()

        worker.finished.connect(completed)
        worker.failed.connect(error)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def choose_backend(selected):
        if endpoint.text().strip() in ("", DEFAULT_OLLAMA, DEFAULT_OPENAI):
            endpoint.setText(DEFAULT_OPENAI if selected == "openai" else DEFAULT_OLLAMA)

    backend.currentTextChanged.connect(choose_backend)
    discover.clicked.connect(lambda: perform("connect", (backend.currentText(),
                                                         endpoint.text().strip())))
    roundtrip.clicked.connect(lambda: perform(
        "roundtrip", (backend.currentText(), endpoint.text().strip(), model.currentText().strip())))
    generate_btn.clicked.connect(lambda: perform(
        "generate", (mode.currentText(), task.toPlainText(), backend.currentText(),
                     endpoint.text().strip(), model.currentText().strip(),
                     root, testbench.text().strip(), top.text().strip(),
                     rag_manifest.text().strip())))
    rag_preview.clicked.connect(lambda: perform(
        "rag_preview", (root, rag_manifest.text().strip() or "multi-rag.json",
                        task.toPlainText())))

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
    rustsim_btn.clicked.connect(lambda: perform("rustdv_sim",
                                               (root, top.text().strip(), "icarus")))
    inspect_btn.clicked.connect(lambda: perform("eda_inspect", (root, manifest.text().strip())))

    def run_eda():
        if not manifest.text().strip():
            evidence.setPlainText("Select an existing, reviewed project-relative EDA manifest.")
            return
        answer = QtWidgets.QMessageBox.question(
            page, "Execute project EDA recipe",
            "This will execute the executable and arguments declared in the selected "
            "project manifest. Only run reviewed, trusted manifests. Continue?")
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        perform("eda_run", (root, manifest.text().strip()))

    eda_btn.clicked.connect(run_eda)
    page.aiPreview = preview
    page.aiEvidence = evidence
    page.aiStatus = status
    page.aiTools = tool_status()
    return page
