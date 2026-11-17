"""Advanced native wave-debug panel: separate DUT RTL from TB/UVM observations.

All findings are deterministic rules over actual VCD samples. The opt-in local
LLM explains the evidence in a worker thread and cannot sign off a cause.
"""
from __future__ import annotations

import json
import os

from .wave_debug import diagnose, explain_with_local_ai
from .otel_telemetry import (build_otlp_bundle, write_otlp_bundle,\n                             send_dynatrace_otlp)


def make_wave_debug(QtCore, QtGui, QtWidgets, project_root, on_crossprobe=None,
                    on_select_time=None):
    page = QtWidgets.QWidget()
    page.setObjectName("advancedWaveDebug")
    layout = QtWidgets.QVBoxLayout(page)
    layout.setContentsMargins(9, 9, 9, 9)
    layout.setSpacing(7)
    roots = QtWidgets.QHBoxLayout()
    dut = QtWidgets.QLineEdit("tb.dut")
    dut.setObjectName("waveDutScopes")
    dut.setPlaceholderText("DUT hierarchy roots: tb.dut, tb.u_dut")
    tb = QtWidgets.QLineEdit("tb")
    tb.setObjectName("waveTbScopes")
    tb.setPlaceholderText("TB/UVM hierarchy roots: tb")
    window = QtWidgets.QSpinBox()
    window.setRange(1, 256)
    window.setValue(6)
    window.setObjectName("waveHandshakeWindow")
    run = QtWidgets.QPushButton("Analyze VCD evidence")
    run.setObjectName("waveAnalyze")
    for w in (QtWidgets.QLabel("RTL / DUT"), dut, QtWidgets.QLabel("TB / UVM"), tb,
              QtWidgets.QLabel("Handshake samples"), window, run):
        roots.addWidget(w)
    layout.addLayout(roots)

    views = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
    rtl_panel = QtWidgets.QWidget()
    rtl_layout = QtWidgets.QVBoxLayout(rtl_panel)
    rtl_title = QtWidgets.QLabel("DUT RTL — observed signals")
    rtl_layout.addWidget(rtl_title)
    rtl_table = QtWidgets.QTableWidget(0, 3)
    rtl_table.setObjectName("waveRtlSignals")
    rtl_table.setHorizontalHeaderLabels(["RTL signal", "Width", "Unknown samples"])
    rtl_table.horizontalHeader().setStretchLastSection(True)
    rtl_layout.addWidget(rtl_table)
    tb_panel = QtWidgets.QWidget()
    tb_layout = QtWidgets.QVBoxLayout(tb_panel)
    tb_layout.addWidget(QtWidgets.QLabel("Verification environment — observed signals"))
    tb_table = QtWidgets.QTableWidget(0, 3)
    tb_table.setObjectName("waveTbSignals")
    tb_table.setHorizontalHeaderLabels(["TB/UVM signal", "Width", "Unknown samples"])
    tb_table.horizontalHeader().setStretchLastSection(True)
    tb_layout.addWidget(tb_table)
    views.addWidget(rtl_panel)
    views.addWidget(tb_panel)
    layout.addWidget(views, 2)

    finding_table = QtWidgets.QTableWidget(0, 5)
    finding_table.setObjectName("waveRootCauseCandidates")
    finding_table.setHorizontalHeaderLabels(["Severity", "Domain", "Sample time", "Rule", "Observation"])
    finding_table.horizontalHeader().setStretchLastSection(True)
    finding_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    layout.addWidget(finding_table, 2)

    findings_detail = QtWidgets.QPlainTextEdit()
    findings_detail.setObjectName("waveEvidenceDetail")
    findings_detail.setMaximumHeight(115)
    findings_detail.setReadOnly(True)
    layout.addWidget(findings_detail)

    otel_row = QtWidgets.QHBoxLayout()
    export_otel_button = QtWidgets.QPushButton("Export OpenTelemetry bundle")
    export_otel_button.setObjectName("waveExportOtel")
    export_otel_button.setEnabled(False)
    otel_hint = QtWidgets.QLabel("OTLP traces · metrics · logs — vendor-neutral JSON")
    otel_row.addWidget(export_otel_button)
    otel_row.addWidget(otel_hint, 1)
    layout.addLayout(otel_row)

    dynatrace_row = QtWidgets.QHBoxLayout()
    dynatrace_endpoint = QtWidgets.QLineEdit(
        os.environ.get("WENGOLD_DYNATRACE_OTLP_ENDPOINT", ""))
    dynatrace_endpoint.setObjectName("waveDynatraceEndpoint")
    dynatrace_endpoint.setPlaceholderText(
        "https://<environment-id>.live.dynatrace.com/api/v2/otlp")
    dynatrace_token = QtWidgets.QLineEdit(
        os.environ.get("WENGOLD_DYNATRACE_API_TOKEN", ""))
    dynatrace_token.setObjectName("waveDynatraceToken")
    dynatrace_token.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
    dynatrace_token.setPlaceholderText("Dynatrace API token (logs.ingest / metrics.ingest / openTelemetryTrace.ingest)")
    send_dynatrace_button = QtWidgets.QPushButton("Send via Dynatrace OTLP")
    send_dynatrace_button.setObjectName("waveSendDynatrace")
    send_dynatrace_button.setEnabled(False)
    dynatrace_row.addWidget(QtWidgets.QLabel("Dynatrace OTLP base"))
    dynatrace_row.addWidget(dynatrace_endpoint, 2)
    dynatrace_row.addWidget(dynatrace_token, 2)
    dynatrace_row.addWidget(send_dynatrace_button)
    layout.addLayout(dynatrace_row)

    ai_row = QtWidgets.QHBoxLayout()
    backend = QtWidgets.QComboBox()
    backend.addItems(["ollama", "openai"])
    backend.setObjectName("waveAiBackend")
    endpoint = QtWidgets.QLineEdit(os.environ.get("WENGOLD_LLM_URL", "http://127.0.0.1:11434"))
    endpoint.setObjectName("waveAiEndpoint")
    model = QtWidgets.QLineEdit(os.environ.get("WENGOLD_LLM_MODEL", "qwen2.5-coder:7b"))
    model.setObjectName("waveAiModel")
    explain = QtWidgets.QPushButton("Explain evidence using Local AI")
    explain.setObjectName("waveExplainAi")
    ai_row.addWidget(QtWidgets.QLabel("Local model"))
    ai_row.addWidget(backend)
    ai_row.addWidget(endpoint, 2)
    ai_row.addWidget(model)
    ai_row.addWidget(explain)
    layout.addLayout(ai_row)
    ai_text = QtWidgets.QPlainTextEdit()
    ai_text.setObjectName("waveAiRootCause")
    ai_text.setReadOnly(True)
    ai_text.setPlaceholderText("No AI output until you explicitly request local inference.")
    ai_text.setMaximumHeight(135)
    layout.addWidget(ai_text)
    state = {"wave": None, "report": None, "busy": False, "otel_busy": False, "worker": None, "thread": None, "otel_worker": None, "otel_thread": None}
    page.debugState = state

    def update_table(table, group):
        table.setRowCount(len(group))
        for i, item in enumerate(group):
            for c, value in enumerate((item["name"], item["width"], item["unknown_samples"])):
                table.setItem(i, c, QtWidgets.QTableWidgetItem(str(value)))

    def chosen_roots(field):
        return tuple(x.strip() for x in field.text().split(",") if x.strip())

    def analyze():
        data = state["wave"]
        if data is None:
            findings_detail.setPlainText("Load a real VCD through the Waveforms tab first.")
            return
        try:
            report = diagnose(data, dut_roots=chosen_roots(dut),
                              tb_roots=chosen_roots(tb),
                              handshake_window=window.value())
        except (ValueError, TypeError) as exc:
            findings_detail.setPlainText("Diagnostic configuration error: " + str(exc))
            return
        state["report"] = report
        update_table(rtl_table, report["groups"]["rtl"])
        update_table(tb_table, report["groups"]["testbench"])
        rows = report["findings"]
        finding_table.setRowCount(len(rows))
        for i, finding in enumerate(rows):
            for c, value in enumerate((finding["severity"], finding["domain"],
                                       finding["time"], finding["rule"],
                                       finding["title"])):
                finding_table.setItem(i, c, QtWidgets.QTableWidgetItem(str(value)))
        findings_detail.setPlainText(
            json.dumps({"summary": report["summary"], "limits": report["limits"]},
                       indent=2))
        ai_text.clear()
        export_otel_button.setEnabled(True)
        send_dynatrace_button.setEnabled(True)
        page.summaryText = ("Observed %d signals, %d evidence candidates; "
                            "root cause NOT proven." %
                            (sum(len(v) for v in report["groups"].values()), len(rows)))

    def export_otel():
        report = state["report"]
        wave_data = state["wave"]
        if report is None or wave_data is None:
            findings_detail.setPlainText("Analyze a loaded VCD before exporting telemetry.")
            return
        filename, _selected = QtWidgets.QFileDialog.getSaveFileName(
            page, "Export OpenTelemetry bundle",
            "wengold-otel-bundle.json", "JSON bundle (*.json)")
        if not filename:
            return
        try:
            bundle = build_otlp_bundle(
                report,
                run_id=wave_data.get("run_id"),
                time_unit_ns=wave_data.get("time_unit_ns") or 1,
                time_unit_label=wave_data.get("time_unit_label") or "tick")
            target = write_otlp_bundle(filename, bundle)
            findings_detail.setPlainText(
                "OpenTelemetry bundle exported.\n"
                f"File: {target}\n"
                f"Trace ID: {bundle['metadata']['trace_id']}\n"
                f"Findings: {len(report.get('findings', []))}\n"
                "The JSON contains separate OTLP traces, metrics and logs payloads. "
                "No data was sent to an external service.")
        except (OSError, TypeError, ValueError) as exc:
            findings_detail.setPlainText(f"OpenTelemetry export failed: {exc}")

    class OtelUploadWorker(QtCore.QObject):
        succeeded = QtCore.pyqtSignal(object)
        failed = QtCore.pyqtSignal(str)

        def __init__(self, arguments):
            super().__init__()
            self.arguments = arguments

        @QtCore.pyqtSlot()
        def run(self):
            try:
                self.succeeded.emit(send_dynatrace_otlp(*self.arguments))
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

    def send_to_dynatrace():
        report = state["report"]
        wave_data = state["wave"]
        endpoint_value = dynatrace_endpoint.text().strip()
        token_value = dynatrace_token.text().strip()
        if report is None or wave_data is None:
            findings_detail.setPlainText(
                "Analyze a loaded VCD before sending telemetry.")
            return
        if not endpoint_value or not token_value:
            findings_detail.setPlainText(
                "Enter the Dynatrace OTLP base URL and an ingest API token. "
                "The token is kept in this session only and is not saved.")
            return
        if state["otel_busy"]:
            return
        try:
            bundle = build_otlp_bundle(
                report,
                run_id=wave_data.get("run_id"),
                time_unit_ns=wave_data.get("time_unit_ns") or 1,
                time_unit_label=wave_data.get("time_unit_label") or "tick")
        except (TypeError, ValueError) as exc:
            findings_detail.setPlainText(f"Telemetry preparation failed: {exc}")
            return
        state["otel_busy"] = True
        send_dynatrace_button.setEnabled(False)
        export_otel_button.setEnabled(False)
        findings_detail.setPlainText(
            "Sending OTLP Protobuf traces, metrics and logs to Dynatrace…")
        thread = QtCore.QThread(page)
        worker = OtelUploadWorker((bundle, endpoint_value, token_value))
        worker.moveToThread(thread)
        state["otel_thread"], state["otel_worker"] = thread, worker

        def upload_done():
            state["otel_busy"] = False
            send_dynatrace_button.setEnabled(state["report"] is not None)
            export_otel_button.setEnabled(state["report"] is not None)
            thread.quit()

        def upload_success(result):
            findings_detail.setPlainText(
                "Dynatrace OTLP export accepted by the HTTP endpoints.\n"
                f"Endpoint: {result['endpoint_host']}\n"
                f"Signals sent: {', '.join(result['signals_sent'])}\n"
                "This confirms HTTP ingestion responses, not that a dashboard "
                "or downstream processing rule is configured.")
            upload_done()

        def upload_failed(message):
            findings_detail.setPlainText(
                "Dynatrace OTLP export failed.\n" + message +
                "\nIf one or more earlier signals were sent, inspect the "
                "message before retrying to avoid duplicate telemetry.")
            upload_done()

        worker.succeeded.connect(upload_success)
        worker.failed.connect(upload_failed)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    send_dynatrace_button.clicked.connect(send_to_dynatrace)

    def show_finding():
        row = finding_table.currentRow()
        report = state["report"]
        if not report or row < 0 or row >= len(report["findings"]):
            return
        finding = report["findings"][row]
        findings_detail.setPlainText(json.dumps(finding, indent=2))
        if on_crossprobe and finding["signals"]:
            on_crossprobe(finding["signals"][0])
        if on_select_time:
            on_select_time(finding["sample_index"])

    def select_signal(table):
        row = table.currentRow()
        if row < 0 or not on_crossprobe:
            return
        item = table.item(row, 0)
        if item:
            on_crossprobe(item.text())

    rtl_table.itemSelectionChanged.connect(lambda: select_signal(rtl_table))
    tb_table.itemSelectionChanged.connect(lambda: select_signal(tb_table))
    finding_table.itemSelectionChanged.connect(show_finding)
    run.clicked.connect(analyze)
    export_otel_button.clicked.connect(export_otel)

    class AiWorker(QtCore.QObject):
        succeeded = QtCore.pyqtSignal(object)
        failed = QtCore.pyqtSignal(str)

        def __init__(self, arguments):
            super().__init__()
            self.arguments = arguments

        @QtCore.pyqtSlot()
        def run(self):
            try:
                self.succeeded.emit(explain_with_local_ai(*self.arguments))
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

    def do_explain():
        if state["report"] is None:
            ai_text.setPlainText("Analyze an actual loaded VCD before asking Local AI.")
            return
        if state["busy"]:
            return
        state["busy"] = True
        explain.setEnabled(False)
        ai_text.setPlainText("Calling selected LOCAL model with bounded waveform evidence…")
        args = (state["report"], backend.currentText(), endpoint.text().strip(),
                model.text().strip())
        thread = QtCore.QThread(page)
        worker = AiWorker(args)
        worker.moveToThread(thread)
        state["thread"], state["worker"] = thread, worker

        def success(reply):
            ai_text.setPlainText(
                "AI HYPOTHESES — NOT VERIFIED\n"
                f"Model: {reply['model']}\n"
                f"Evidence SHA256: {reply['report_sha256']}\n\n"
                + reply["answer"])
            done()
        def failed(message):
            ai_text.setPlainText("LOCAL AI FAILED — no analysis produced\n" + message)
            done()
        def done():
            state["busy"] = False
            explain.setEnabled(True)
            thread.quit()
        worker.succeeded.connect(success)
        worker.failed.connect(failed)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    explain.clicked.connect(do_explain)
    page.loadWave = lambda data: (state.update(wave=data), analyze())
    page.analyzeWave = analyze
    page.rtlSignals = rtl_table
    page.tbSignals = tb_table
    page.findingTable = finding_table
    page.aiFindings = ai_text
    page.rootEvidence = findings_detail
    return page
