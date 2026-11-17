"""Native Qt workspaces for WENGOLD Silicon Studio.

All controls use local, bounded backends. Job results are never fabricated.
Qt is imported lazily so the CLI remains usable without PyQt6.
"""
from __future__ import annotations

from .studio_workspace import source, save_source, list_evidence, formal_report
from .studio_jobs import StudioJobs, crossprobe


def make_studio_tabs(state, QtCore, QtGui, QtWidgets, parent=None):
    root = state["path"]
    jobs = StudioJobs(root)
    tabs = QtWidgets.QTabWidget(parent)
    tabs.setObjectName("studioTabs")
    tabs.setDocumentMode(True)
    tabs.setMovable(False)
    tabs.jobs = jobs
    files = list(state.get("file_paths", []))

    def column():
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)
        return widget, layout

    def toolbar(layout, *widgets):
        row = QtWidgets.QHBoxLayout()
        for item in widgets:
            row.addWidget(item)
        row.addStretch(1)
        layout.addLayout(row)

    def alert(message, error=False):
        status.setText(str(message))
        status.setProperty("severity", "error" if error else "info")
        status.style().unpolish(status)
        status.style().polish(status)

    # RTL source editor: load, modify, save with hash conflict detection.
    edit_page, edit_layout = column()
    edit_picker = QtWidgets.QComboBox()
    edit_picker.setObjectName("rtlFilePicker")
    edit_picker.addItems(files)
    open_btn = QtWidgets.QPushButton("Open source")
    save_btn = QtWidgets.QPushButton("Save source")
    syntax_btn = QtWidgets.QPushButton("Check HDL syntax")
    open_btn.setObjectName("openRtlButton")
    save_btn.setObjectName("saveRtlButton")
    toolbar(edit_layout, edit_picker, open_btn, save_btn, syntax_btn)
    editor = QtWidgets.QPlainTextEdit()
    editor.setObjectName("rtlEditor")
    editor.setPlaceholderText("Open discovered RTL, UVM, verification and automation source files")
    editor.setStyleSheet("font-family: monospace; font-size: 12px;")
    edit_layout.addWidget(editor)
    edit_detail = QtWidgets.QLabel("Changes must be saved and rechecked before reuse of evidence.")
    edit_layout.addWidget(edit_detail)
    edit_state = {"file": None, "sha": None, "loading": False, "dirty": False}

    def load_editor(rel=None):
        rel = rel or edit_picker.currentText()
        if not rel:
            alert("No indexed source", True)
            return
        if edit_state["dirty"]:
            answer = QtWidgets.QMessageBox.question(
                tabs, "Unsaved RTL", "Discard unsaved source edits?")
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        try:
            data = source(root, rel)
            edit_state["loading"] = True
            editor.setPlainText(data["content"])
            edit_state.update(file=rel, sha=data["sha256"], dirty=False, loading=False)
            alert(f"Opened {rel} ({data['bytes']} bytes)")
        except Exception as exc:
            edit_state["loading"] = False
            alert(f"RTL open failed: {exc}", True)

    def on_edit():
        if not edit_state["loading"]:
            edit_state["dirty"] = True
            edit_detail.setText("Unsaved source. Syntax and formal results do not cover this edit.")

    editor.textChanged.connect(on_edit)
    open_btn.clicked.connect(lambda: load_editor())

    def save_editor():
        if not edit_state["file"]:
            alert("Open a source file first", True)
            return
        try:
            info = save_source(root, edit_state["file"], editor.toPlainText(),
                               edit_state["sha"])
            edit_state["sha"] = info["sha256"]
            edit_state["dirty"] = False
            edit_detail.setText("Saved. Re-index and rerun affected checks.")
            alert("Saved " + edit_state["file"])
        except Exception as exc:
            alert(f"Save refused: {exc}", True)

    save_btn.clicked.connect(save_editor)

    def start_job(kind, rel, expr=""):
        if not rel:
            alert("Select a source file", True)
            return
        if kind == "syntax" and not rel.lower().endswith((".sv", ".v", ".vhd", ".vhdl")):
            alert("HDL syntax check supports RTL/VHDL files only; Python/Tcl/PSS needs its own tool", True)
            return
        if kind == "syntax" and edit_state["dirty"] and rel == edit_state["file"]:
            alert("Save or discard source edits first", True)
            return
        try:
            job = jobs.submit(kind, rel, expr=expr, engine="explicit", depth=12)
            alert(f"{kind} job queued: {job['id'][:12]}")
            refresh_jobs()
        except Exception as exc:
            alert(f"Job refused: {exc}", True)

    syntax_btn.clicked.connect(lambda: start_job("syntax", edit_state["file"]))
    tabs.addTab(edit_page, "RTL Editor")

    from .native_implementation import make_implementation_tab
    implementation = make_implementation_tab(root, files, QtCore, QtGui, QtWidgets)
    tabs.addTab(implementation, "Synthesis / PPA")
    tabs.implementation = implementation

    # Waveforms and automatic findings share the same observed samples.
    from .native_wave_view import make_wave_view
    from .native_wave_debug import make_wave_debug

    def probe_signal(signal):
        try:
            matches = crossprobe(root, files, signal)
            lines = [f"{v['file']}:{v['line']}  {v['text'].strip()}"
                     for v in matches["matches"]]
            return (f"{signal} — lexical matches; hierarchy not resolved\n"
                    + ("\n".join(lines) if lines else "No RTL token match"),
                    matches["matches"])
        except Exception as exc:
            return str(exc), []

    def activate_tab(title):
        # Navigate by title because the desktop shell wraps pages in scroll areas.
        for i in range(tabs.count()):
            if tabs.tabText(i) == title:
                tabs.setCurrentIndex(i)
                break

    def open_wave_source(rel, line):
        if edit_state["file"] != rel:
            load_editor(rel)
        if edit_state["file"] != rel:
            return
        # The line match was computed against disk, not an unsaved editor buffer.
        if edit_state["dirty"]:
            activate_tab("RTL Editor")
            alert("Save source and reselect the signal before opening a disk line match", True)
            return
        block = editor.document().findBlockByNumber(line - 1)
        if block.isValid():
            editor.setTextCursor(QtGui.QTextCursor(block))
            editor.centerCursor()
        activate_tab("RTL Editor")

    wave_page = make_wave_view(root, QtCore, QtGui, QtWidgets, alert,
                              probe_signal, open_wave_source)
    tabs.addTab(wave_page, "Waveforms")

    def focus_wave_sample(index):
        activate_tab("Waveforms")
        wave_page.focusSample(index)

    wave_debug = make_wave_debug(QtCore, QtGui, QtWidgets, root,
                                 wave_page.selectSignal, focus_wave_sample)
    tabs.addTab(wave_debug, "Wave Debug")
    tabs.waveDebug = wave_debug
    from .native_trace_tools import make_trace_tools
    trace_tools = make_trace_tools(root, QtCore, QtGui, QtWidgets, alert, focus_wave_sample)
    tabs.addTab(trace_tools, "Trace Tools")

    def trace_loaded(data):
        wave_debug.loadWave(data)
        trace_tools.setTrace(data)

    wave_page.traceLoaded = trace_loaded
    wave_page.refreshFiles = lambda: refresh_evidence()

    def refresh_evidence():
        try:
            inventory = list_evidence(root)
            traces = sorted(inventory["waveforms"] + inventory["fst_waveforms"])
            wave_page.setFiles(traces)
            trace_tools.setFiles(traces)
            previous_report = formal_picker_reports.currentText()
            formal_picker_reports.clear()
            formal_picker_reports.addItems(inventory["formal_reports"])
            if previous_report in inventory["formal_reports"]:
                formal_picker_reports.setCurrentText(previous_report)
            alert("Evidence files refreshed")
        except Exception as exc:
            alert(f"Evidence discovery failed: {exc}", True)

    # Formal execution: source selection and bounded safety property.
    formal_page, formal_layout = column()
    formal_picker = QtWidgets.QComboBox()
    formal_picker.setObjectName("formalSourcePicker")
    formal_picker.addItems(files)
    property_edit = QtWidgets.QLineEdit()
    property_edit.setObjectName("formalProperty")
    property_edit.setPlaceholderText("Safety expression, e.g. count < 4")
    run_formal = QtWidgets.QPushButton("Run Formal")
    run_pipeline = QtWidgets.QPushButton("Syntax → Formal")
    toolbar(formal_layout, formal_picker, property_edit, run_formal, run_pipeline)
    formal_picker_reports = QtWidgets.QComboBox()
    formal_open = QtWidgets.QPushButton("Open imported JSON report")
    toolbar(formal_layout, formal_picker_reports, formal_open)
    formal_result = QtWidgets.QPlainTextEdit()
    formal_result.setObjectName("formalResultViewer")
    formal_result.setReadOnly(True)
    formal_layout.addWidget(formal_result)

    def formal_action(kind):
        if edit_state["dirty"] and edit_state["file"] == formal_picker.currentText():
            alert("Save or discard edited source before formal checking", True)
            return
        start_job(kind, formal_picker.currentText(), property_edit.text())

    run_formal.clicked.connect(lambda: formal_action("formal"))
    run_pipeline.clicked.connect(lambda: formal_action("pipeline"))

    def load_formal_report():
        rel = formal_picker_reports.currentText()
        if not rel:
            alert("No imported JSON reports", True)
            return
        try:
            import json
            record = formal_report(root, rel)
            formal_result.setPlainText(json.dumps(record, indent=2))
            alert("Imported report: provenance not independently verified")
        except Exception as exc:
            alert(f"Report open failed: {exc}", True)

    formal_open.clicked.connect(load_formal_report)
    tabs.addTab(formal_page, "Formal")

    # Job monitor and auditable reviewer decisions.
    job_page, job_layout = column()
    refresh = QtWidgets.QPushButton("Refresh jobs")
    audit = QtWidgets.QPushButton("Audit ledger")
    reviewer = QtWidgets.QLineEdit()
    reviewer.setObjectName("reviewerIdentity")
    reviewer.setPlaceholderText("Reviewer identity (self-asserted)")
    review_credential = QtWidgets.QLineEdit()
    review_credential.setObjectName("reviewCredential")
    review_credential.setPlaceholderText("Local reviewer credential")
    review_credential.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
    review_signature = QtWidgets.QLineEdit()
    review_signature.setObjectName("reviewSignature")
    review_signature.setPlaceholderText("Ed25519 signature (base64) when trust registry is enabled")
    accept = QtWidgets.QPushButton("Accept proof")
    reject = QtWidgets.QPushButton("Reject evidence")
    toolbar(job_layout, refresh, audit, reviewer, review_credential, review_signature, accept, reject)
    job_table = QtWidgets.QTableWidget(0, 5)
    job_table.setObjectName("jobQueue")
    job_table.setHorizontalHeaderLabels(["Job ID", "Kind", "Source", "State", "Review"])
    job_table.horizontalHeader().setStretchLastSection(True)
    job_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
    job_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    job_layout.addWidget(job_table)
    job_result = QtWidgets.QPlainTextEdit()
    job_result.setObjectName("jobEvidence")
    job_result.setReadOnly(True)
    job_layout.addWidget(job_result)
    jobs_by_row = []

    def refresh_jobs():
        nonlocal jobs_by_row
        try:
            import json
            values = jobs.list_jobs()["jobs"]
            jobs_by_row = values
            job_table.setRowCount(len(values))
            for i, job in enumerate(values):
                fields = (job["id"][:12], job["kind"], job["file"],
                          job["status"] + (" · stale" if job.get("stale") else ""),
                          (job.get("review") or {}).get("decision", "pending"))
                for c, value in enumerate(fields):
                    job_table.setItem(i, c, QtWidgets.QTableWidgetItem(value))
            alert(f"{len(values)} local session job(s)")
        except Exception as exc:
            alert(f"Job monitor failed: {exc}", True)

    def job_selected():
        selected = job_table.currentRow()
        if 0 <= selected < len(jobs_by_row):
            import json
            job_result.setPlainText(json.dumps(jobs_by_row[selected], indent=2))

    def decision(value):
        selected = job_table.currentRow()
        if not (0 <= selected < len(jobs_by_row)):
            alert("Select a job first", True)
            return
        try:
            result = jobs.signoff(jobs_by_row[selected]["id"], reviewer.text(), value,
                                  credential=review_credential.text(), signature=review_signature.text())
            alert(f"Recorded {value} at ledger seq {result['review']['ledger_seq']}")
            refresh_jobs()
        except Exception as exc:
            alert(f"Review refused: {exc}", True)

    refresh.clicked.connect(refresh_jobs)
    job_table.itemSelectionChanged.connect(job_selected)
    accept.clicked.connect(lambda: decision("accept"))
    reject.clicked.connect(lambda: decision("reject"))
    audit.clicked.connect(lambda: job_result.setPlainText(str(jobs.audit())))
    tabs.addTab(job_page, "Jobs & Signoff")

    # Agents: actual project/graph facts and bounded orchestration stages.
    agent_page, agent_layout = column()
    agent_hint = QtWidgets.QLabel(
        "Agent orchestration: inspect real design context and queued local verification stages.\n"
        "No unattended RTL repair, unrestricted shell or automatic tapeout signoff.")
    agent_hint.setWordWrap(True)
    agent_layout.addWidget(agent_hint)
    agent_plan = QtWidgets.QPushButton("Inspect graph-based agent plan")
    agent_layout.addWidget(agent_plan)
    agent_trace = QtWidgets.QPlainTextEdit()
    agent_trace.setObjectName("agentPlan")
    agent_trace.setReadOnly(True)
    agent_layout.addWidget(agent_trace)

    def show_plan():
        try:
            from .desktop import _agent
            data = _agent(state, "inspect verification dependencies")
            chunks = [f"{step['label']}\n  {step['cmd']}\n  {step['detail']}"
                      for step in data.get("steps", [])]
            agent_trace.setPlainText("\n\n".join(chunks) + "\n\n" + data.get("summary", ""))
            alert("Plan inspection complete; tool actions were not executed")
        except Exception as exc:
            alert(f"Agent plan failed: {exc}", True)

    agent_plan.clicked.connect(show_plan)
    tabs.addTab(agent_page, "Agents")

    # Durable queue: multiple external worker processes can claim transactionally.
    from .studio_durable import DurableQueue
    durable = DurableQueue(root)
    worker_page, worker_layout = column()
    worker_help = QtWidgets.QLabel(
        "Persistent SQLite queue — run workers in separate Linux terminals:\n"
        f"python3 -m wengold.studio_durable {root} --worker\n"
        "Workers share one SQLite database on the same filesystem. "
        "Review and tapeout signoff remain separate.")
    worker_help.setWordWrap(True)
    worker_layout.addWidget(worker_help)
    worker_kind = QtWidgets.QComboBox()
    worker_kind.addItems(["syntax", "pipeline", "formal"])
    worker_source = QtWidgets.QComboBox()
    worker_source.addItems(files)
    worker_expr = QtWidgets.QLineEdit()
    worker_expr.setPlaceholderText("Formal safety expression")
    worker_submit = QtWidgets.QPushButton("Queue durable job")
    worker_refresh = QtWidgets.QPushButton("Refresh durable queue")
    toolbar(worker_layout, worker_kind, worker_source, worker_expr,
            worker_submit, worker_refresh)
    worker_table = QtWidgets.QTableWidget(0, 6)
    worker_table.setObjectName("durableWorkerQueue")
    worker_table.setHorizontalHeaderLabels(["ID", "Kind", "Source", "State", "Attempt", "Worker"])
    worker_table.horizontalHeader().setStretchLastSection(True)
    worker_layout.addWidget(worker_table)
    worker_detail = QtWidgets.QPlainTextEdit()
    worker_detail.setObjectName("durableWorkerEvidence")
    worker_detail.setReadOnly(True)
    worker_layout.addWidget(worker_detail)

    def refresh_durable():
        import json
        try:
            rows = durable.list_jobs()
            worker_table.setRowCount(len(rows))
            for n, job in enumerate(rows):
                values = (job["id"][:12], job["kind"], job["path"], job["status"],
                          str(job["attempt"]), str(job["owner"] or "—"))
                for col, val in enumerate(values):
                    worker_table.setItem(n, col, QtWidgets.QTableWidgetItem(val))
            worker_detail.setPlainText(json.dumps(rows, indent=2))
            alert(f"{len(rows)} persistent job(s)")
        except Exception as exc:
            alert(f"Durable queue read failed: {exc}", True)

    def submit_durable():
        try:
            d = durable.submit(worker_kind.currentText(), worker_source.currentText(),
                               expr=worker_expr.text())
            alert(f"Queued durable job {d['id'][:12]}")
            refresh_durable()
        except Exception as exc:
            alert(f"Durable submission refused: {exc}", True)

    worker_submit.clicked.connect(submit_durable)
    worker_refresh.clicked.connect(refresh_durable)
    tabs.addTab(worker_page, "Workers")
    tabs.durableQueue = durable
    tabs.durableWorkerTable = worker_table


    # Local LLM and semiconductor discipline prompt workbench.
    from .native_ai import create_ai_tab
    ai_page = create_ai_tab(root, QtCore, QtGui, QtWidgets, tabs)
    tabs.addTab(ai_page, "Local AI")
    tabs.aiPage = ai_page
    from .native_dv_pipeline import make_dv_pipeline_tab
    dv_page = make_dv_pipeline_tab(root, files, QtCore, QtGui, QtWidgets)
    tabs.insertTab(1, dv_page, "DV Workflow")
    tabs.dvWorkflow = dv_page

    status = QtWidgets.QLabel("Native Linux workspace ready")
    status.setObjectName("studioStatus")
    status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    status.setWordWrap(True)
    tabs.statusLabel = status
    def refresh_project_sources(new_state):
        """Update all project source pickers without discarding the editor."""
        nonlocal state
        state = new_state
        updated = list(new_state.get("file_paths", []))
        files[:] = updated
        implementation.refreshSources(updated)
        dv_page.refreshSources(updated)
        if edit_state["file"] and edit_state["file"] not in updated:
            edit_state.update(file=None, sha=None, dirty=False)
            editor.setPlainText("")
            edit_detail.setText("Previously open file was removed; choose another source.")
        for picker in (edit_picker, formal_picker, worker_source):
            previous = picker.currentText()
            picker.blockSignals(True)
            picker.clear()
            allowed = (updated if picker is edit_picker
                       else [p for p in updated if p.lower().endswith((".sv", ".v", ".vhd", ".vhdl"))])
            picker.addItems(allowed)
            if previous in allowed:
                picker.setCurrentText(previous)
            picker.blockSignals(False)
        refresh_evidence()
        alert(f"Discovered {len(updated)} project files")

    tabs.refreshProjectSources = refresh_project_sources
    tabs.editorDirty = lambda: edit_state["dirty"]
    tabs.editorFile = lambda: edit_state["file"]
    tabs.refreshEvidence = refresh_evidence
    tabs.refreshJobs = refresh_jobs
    tabs.loadSource = load_editor
    tabs.sourceEditor = editor
    tabs.waveTable = wave_page.waveTable
    tabs.waveCanvas = wave_page.waveCanvas
    tabs.formalViewer = formal_result
    tabs.jobTable = job_table
    tabs.agentViewer = agent_trace
    refresh_evidence()
    refresh_jobs()
    return tabs
