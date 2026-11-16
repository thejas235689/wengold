"""Native Linux Silicon Studio regression tests.

Runs under QT_QPA_PLATFORM=offscreen without a window manager.
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")


@pytest.fixture()
def native_window(tmp_path):
    from PyQt6 import QtWidgets
    from wengold.desktop import build_state
    from wengold.native import build_window

    root = tmp_path
    (root / "rtl").mkdir()
    (root / "rtl" / "module.sv").write_text(
        "module module_a(input logic a, output logic q);\nassign q = a;\nendmodule\n")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = build_window(build_state(str(root)))
    yield root, app, window
    window.close()
    window.workspace.jobs.shutdown()


def test_full_native_workspace_tabs_exist(native_window):
    root, app, window = native_window
    tab = window.workspace
    titles = [tab.tabText(i) for i in range(tab.count())]
    for required in ("Overview", "RTL Editor", "Waveforms", "Formal",
                     "Jobs & Signoff", "Agents"):
        assert required in titles
    assert tab.sourceEditor is not None
    assert tab.waveTable is not None
    assert tab.formalViewer is not None
    assert tab.jobTable is not None
    assert tab.agentViewer is not None


def test_native_rtl_open_and_guarded_save(native_window):
    root, app, window = native_window
    tab = window.workspace
    tab.loadSource("rtl/module.sv")
    assert "module module_a" in tab.sourceEditor.toPlainText()
    tab.sourceEditor.insertPlainText("\n// native editor change")
    from PyQt6.QtWidgets import QPushButton
    save = tab.findChild(QPushButton, "saveRtlButton")
    assert save is not None
    save.click()
    assert "native editor change" in (root / "rtl" / "module.sv").read_text()


def test_native_waveform_and_job_state(native_window):
    root, app, window = native_window
    (root / "waves").mkdir()
    (root / "waves" / "trace.vcd").write_text(
        "$scope module tb $end\n$var wire 1 ! clk $end\n"
        "$upscope $end\n$enddefinitions $end\n#0\n0!\n#5\n1!\n")
    window.workspace.refreshEvidence()
    assert window.workspace.waveTable.rowCount() == 0
    window.workspace.refreshJobs()
    assert window.workspace.jobTable.rowCount() == 0


def test_native_window_renders_offscreen(native_window):
    root, app, window = native_window
    window.show()
    app.processEvents()
    assert window.grab().width() > 0
    assert window.workspace.count() >= 6



def test_native_waveform_canvas_draws_real_vcd_and_selects_signal(native_window):
    from PyQt6.QtWidgets import QPushButton
    root, app, window = native_window
    (root / "waves").mkdir(exist_ok=True)
    (root / "waves" / "sample.vcd").write_text(
        "$scope module tb $end\n$var wire 1 ! clk $end\n"
        "$var wire 1 # unknown $end\n"
        "$upscope $end\n$enddefinitions $end\n"
        "#0\n0!\nx#\n#10\n1!\n1#\n")
    tab = window.workspace
    tab.refreshEvidence()
    buttons = tab.findChildren(QPushButton)
    load = next(x for x in buttons if x.text() == "Load VCD")
    load.click()
    assert tab.waveCanvas.data["cycles"] == 2
    assert tab.waveCanvas.data["signals"]
    assert tab.waveTable.rowCount() == 2
    tab.waveCanvas.set_zoom(2)
    assert tab.waveCanvas.zoom == 2
    window.show()
    app.processEvents()
    assert tab.waveCanvas.grab().width() > 0



def test_native_local_ai_panel_contains_discipline_and_validation_controls(native_window):
    from PyQt6 import QtWidgets
    root, app, window = native_window
    tabs = window.workspace
    assert "Local AI" in [tabs.tabText(i) for i in range(tabs.count())]
    panel = tabs.aiPage
    for name in ("aiBackend", "aiEndpoint", "aiModel", "aiConnect",
                 "aiTestInference", "aiDiscipline", "aiTask", "aiGenerate",
                 "aiCheckRtl", "aiCheckSatya", "aiSatyaUvm", "aiRustDv",
                 "aiArtifactPreview", "aiEvidence", "aiEdaManifest",
                 "aiInspectEdaFlow", "aiRunEdaFlow", "aiRagManifest", "aiRagPreview"):
        assert panel.findChild(QtWidgets.QWidget, name), name
    profiles = panel.findChild(QtWidgets.QComboBox, "aiDiscipline")
    assert profiles.count() == 15



def test_native_multi_rag_preview_retrieves_without_a_model(native_window, monkeypatch):
    import json
    import time
    from PyQt6 import QtWidgets
    from wengold import native_ai

    root, app, window = native_window
    (root / "multi-rag.json").write_text(json.dumps({
        "sources": [{"kind": "rtl", "path": "rtl/module.sv"}],
    }))

    def do_not_generate(*args, **kwargs):
        pytest.fail("preview must not request model inference")

    monkeypatch.setattr(native_ai, "generate", do_not_generate)
    panel = window.workspace.aiPage
    panel.findChild(QtWidgets.QPlainTextEdit, "aiTask").setPlainText("module_a interface")
    panel.findChild(QtWidgets.QPushButton, "aiRagPreview").click()
    deadline = time.monotonic() + 5
    while panel.aiState["busy"] and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    app.processEvents()
    assert not panel.aiState["busy"]
    result = json.loads(panel.aiEvidence.toPlainText())
    assert result["sources"][0]["path"] == "rtl/module.sv"


def test_advanced_wave_debug_separates_rtl_and_testbench(native_window):
    from PyQt6 import QtWidgets
    root, app, window = native_window
    (root / "waves").mkdir(exist_ok=True)
    (root / "waves" / "debug.vcd").write_text(
        "$scope module tb $end\n"
        "$var wire 1 ! req $end\n"
        "$var wire 1 # ack $end\n"
        "$scope module dut $end\n"
        "$var wire 1 $ state $end\n"
        "$upscope $end\n$upscope $end\n$enddefinitions $end\n"
        "#0\n0!\n0#\n0$\n#5\n1!\n0#\nx$\n"
        "#10\n1!\n0#\nx$\n#15\n1!\n0#\nx$\n"
        "#20\n1!\n0#\nx$\n#25\n1!\n0#\nx$\n"
        "#30\n1!\n0#\nx$\n#35\n1!\n0#\nx$\n")
    tabs = window.workspace
    tabs.refreshEvidence()
    load = next(b for b in tabs.findChildren(QtWidgets.QPushButton)
                if b.text() == "Load VCD")
    tabs.findChild(QtWidgets.QComboBox, "waveFilePicker").setCurrentText("waves/debug.vcd")
    load.click()
    debug = tabs.waveDebug
    assert "Wave Debug" in [tabs.tabText(i) for i in range(tabs.count())]
    assert debug.rtlSignals.rowCount() == 1
    assert debug.tbSignals.rowCount() == 2
    assert debug.findingTable.rowCount() >= 2
    assert "root cause NOT proven" in debug.summaryText
    assert not debug.aiFindings.toPlainText()
    for name in ("waveDutScopes", "waveTbScopes", "waveHandshakeWindow",
                 "waveAnalyze", "waveRtlSignals", "waveTbSignals",
                 "waveRootCauseCandidates", "waveEvidenceDetail", "waveExplainAi"):
        assert debug.findChild(QtWidgets.QWidget, name)


def test_native_project_open_and_auto_discovery(native_window, tmp_path, monkeypatch):
    from PyQt6 import QtWidgets
    root, app, window = native_window
    new_root = tmp_path / "external_project"
    (new_root / "design").mkdir(parents=True)
    (new_root / "dv").mkdir()
    (new_root / "scripts").mkdir()
    (new_root / "design" / "cpu.sv").write_text("module cpu; endmodule\n")
    (new_root / "dv" / "cpu_tb.sv").write_text("module cpu_tb; endmodule\n")
    (new_root / "scripts" / "regress.py").write_text("print(42)\n")
    assert window.findChild(QtWidgets.QPushButton, "openProjectButton")
    assert window.findChild(QtWidgets.QPushButton, "rescanFilesButton")
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        lambda *_args, **_kwargs: str(new_root))
    window.findChild(QtWidgets.QPushButton, "openProjectButton").click()
    assert window.state["path"] == str(new_root)
    assert window.state["project_inventory"]["counts"]["verification"] == 1
    assert "Verification / UVM" in window.tree.topLevelItem(1).text(0)
    assert window.workspace.findChild(QtWidgets.QComboBox, "rtlFilePicker").findText(
        "scripts/regress.py") >= 0
    window.workspace.loadSource("scripts/regress.py")
    assert "print(42)" in window.workspace.sourceEditor.toPlainText()
    (new_root / "dv" / "new_monitor.sv").write_text("class new_monitor; endclass\n")
    window._watch_project()
    assert "dv/new_monitor.sv" in window.state["file_paths"]
    assert window.workspace.findChild(QtWidgets.QComboBox, "rtlFilePicker").findText(
        "dv/new_monitor.sv") >= 0


def test_native_buttons_have_working_routing(native_window):
    from PyQt6 import QtWidgets
    root, app, window = native_window
    assert window.menuBar().actions()
    widget = window.workspace
    for button_name in ("openRtlButton", "saveRtlButton", "waveAnalyze",
                        "aiConnect", "aiTestInference", "aiGenerate",
                        "aiCheckRtl", "aiRunEdaFlow", "aiInspectEdaFlow"):
        button = widget.findChild(QtWidgets.QPushButton, button_name)
        assert button is not None and button.isEnabled(), button_name
    window.findChild(QtWidgets.QPushButton, "rescanFilesButton").click()
    assert "source files refreshed" in window.transcript.toPlainText()


def test_implementation_ui_real_evidence_controls(native_window):
    from PyQt6 import QtWidgets
    root, app, window = native_window
    tabs = window.workspace
    assert "Synthesis / PPA" in [tabs.tabText(i) for i in range(tabs.count())]
    panel = tabs.implementation
    for key in ("implSource", "implTop", "implRunSynthesis",
                "implSynthesisLog", "implHierarchy", "implPpaEvidence"):
        assert panel.findChild(QtWidgets.QWidget, key), key
    assert panel.findChild(QtWidgets.QComboBox, "implSource").findText(
        "rtl/module.sv") >= 0
    assert "NOT RUN" in panel.ppaReport.toPlainText()
    assert "NOT AVAILABLE" in panel.ppaReport.toPlainText()


def test_ui_diagnostics_reports_actual_missing_tools(native_window, monkeypatch):
    from PyQt6 import QtWidgets
    from wengold.native_health import diagnostics
    from wengold import native_health
    root, app, window = native_window
    monkeypatch.setattr(native_health.shutil, "which", lambda name: None)
    report = diagnostics(window, QtWidgets)
    assert report["project_exists"]
    assert report["ui"]["project"]["controls_present"]
    assert report["ui"]["synthesis"]["controls_present"]
    assert report["ui"]["local_ai"]["controls_present"]
    assert report["installed_tools"]["yosys"] is None
    assert report["installed_tools"]["iverilog"] is None
    assert report["runtime_gates"]["rtl_simulation"]["status"] == "simulator_missing"
    monkeypatch.setattr(native_health.shutil, "which",
                        lambda name: "/tools/xezim" if name == "xezim" else None)
    report = diagnostics(window, QtWidgets)
    assert report["installed_tools"]["xezim"] == "/tools/xezim"
    assert report["runtime_gates"]["rtl_simulation"]["status"] == "tools_detected_not_executed"
    menu_actions = [a.text() for menu in window.menuBar().actions()
                    for a in menu.menu().actions() if menu.menu()]
    assert "UI & Tool Diagnostics" in menu_actions


def test_graphical_schematic_controls_and_real_cells(native_window):
    from PyQt6 import QtWidgets
    root, app, window = native_window
    panel = window.workspace.implementation
    for name in ("implSchematicCanvas", "implSchematicTabs",
                 "implSchematicZoomIn", "implSchematicZoomOut",
                 "implLiberty", "implSdc", "implEdaManifest",
                 "implInspectFlow", "implRunFlow", "implEdaEvidence"):
        assert panel.findChild(QtWidgets.QWidget, name), name
    canvas = panel.schematicCanvas
    canvas.showSchematic({
        "module": "counter", "truncated": False,
        "cells": [{"id": "gate0", "type": "$_AND_"},
                  {"id": "ff0", "type": "$_DFF_P_"}],
        "edges": [{"from": "gate0", "to": "ff0", "bit": 17}]}
    )
    assert len(canvas.scene().items()) >= 4
    factor = canvas.transform().m11()
    panel.findChild(QtWidgets.QPushButton, "implSchematicZoomIn").click()
    assert canvas.transform().m11() > factor
    assert panel.ppaReport.toPlainText().startswith("Timing: NOT RUN")



def test_dv_workflow_native_stages_and_draft_gates(native_window):
    from PyQt6 import QtWidgets
    root, app, window = native_window
    spec = root / "spec"
    spec.mkdir()
    (spec / "requirements.md").write_text(
        "REQ-1 reset clears state; REQ-2 enable causes increment")
    window._reload()
    panel = window.workspace.dvWorkflow
    tabs = panel.workflowTabs
    assert "DV Workflow" in [
        window.workspace.tabText(i) for i in range(window.workspace.count())]
    assert tabs.count() == 7
    for name in ("dvIntake", "dvPlan", "dvUvm", "dvRegression",
                 "dvDebug", "dvCoverage", "dvAgent"):
        btn = panel.findChild(QtWidgets.QPushButton, name + "Button")
        evidence = panel.findChild(QtWidgets.QPlainTextEdit, name + "Evidence")
        assert btn is not None and btn.isEnabled(), name
        assert evidence is not None and evidence.isReadOnly(), name
    for name in ("dvSpec", "dvRtl", "dvArtifactKind", "dvCoverageTarget",
                 "dvRegressionFile", "dvDebugFile", "dvCoverageFile",
                 "dvPlanSaveDraft", "dvUvmSaveDraft"):
        assert panel.findChild(QtWidgets.QWidget, name), name
    assert panel.findChild(QtWidgets.QComboBox, "dvSpec").findText(
        "spec/requirements.md") >= 0
    assert panel.findChild(QtWidgets.QComboBox, "dvRtl").findText(
        "rtl/module.sv") >= 0
    assert "NOT SIGNED OFF" in panel.findChild(
        QtWidgets.QLabel, "dvPipelineStatus").text()


@pytest.mark.parametrize("prefix", ["ai", "dv"])
def test_dhir_preset_updates_local_model_controls(native_window, prefix):
    from PyQt6 import QtWidgets

    _, _, window = native_window
    button = window.findChild(QtWidgets.QPushButton, prefix + "DhirPreset")
    backend = window.findChild(QtWidgets.QComboBox, prefix + "Backend")
    endpoint = window.findChild(QtWidgets.QLineEdit, prefix + "Endpoint")
    kind = QtWidgets.QComboBox if prefix == "ai" else QtWidgets.QLineEdit
    model = window.findChild(kind, prefix + "Model")
    backend.setCurrentText("ollama")
    endpoint.setText("http://127.0.0.1:11434")
    button.click()
    assert backend.currentText() == "openai"
    assert endpoint.text() == "http://127.0.0.1:8080/v1"
    assert (model.currentText() if prefix == "ai" else model.text()) == "dhir-2b"
    endpoint.setText("http://127.0.0.1:9090/v1")
    button.click()
    assert endpoint.text() == "http://127.0.0.1:9090/v1"


def test_native_sv_agent_roles_keep_separate_results(native_window, monkeypatch):
    import time
    from PyQt6 import QtWidgets
    from wengold import sv_agents

    _, app, window = native_window
    panel = window.workspace.dvWorkflow
    selector = panel.findChild(QtWidgets.QComboBox, "dvAgentRole")
    button = panel.findChild(QtWidgets.QPushButton, "dvAgentButton")
    output = panel.findChild(QtWidgets.QPlainTextEdit, "dvAgentEvidence")
    calls = []

    def run(_root, role, *_args):
        calls.append(role)
        if role == "debug":
            raise RuntimeError("debug model unavailable")
        return {"role": role, "text": role + " draft", "status": "draft_not_verified"}

    monkeypatch.setattr(sv_agents, "run", run)

    def click_and_wait():
        button.click()
        deadline = time.monotonic() + 5
        while panel.pipelineState["busy"] and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        app.processEvents()
        assert not panel.pipelineState["busy"]

    selector.setCurrentIndex(selector.findData("formal"))
    click_and_wait()
    assert "formal draft" in output.toPlainText()
    selector.setCurrentIndex(selector.findData("debug"))
    click_and_wait()
    assert "debug model unavailable" in output.toPlainText()
    selector.setCurrentIndex(selector.findData("spec"))
    click_and_wait()
    assert "spec draft" in output.toPlainText()
    selector.setCurrentIndex(selector.findData("formal"))
    assert "formal draft" in output.toPlainText()
    assert calls == ["formal", "debug", "spec"]


def test_waveform_cursors_hierarchy_pins_bookmark_and_export(native_window, monkeypatch):
    import hashlib
    import json
    from PyQt6 import QtCore, QtWidgets
    from PyQt6.QtTest import QTest

    root, app, window = native_window
    (root / "waves").mkdir()
    vcd = root / "waves" / "debug.vcd"
    vcd.write_text(
        "$timescale 10ps $end\n$scope module tb $end\n$var wire 1 ! clk $end\n"
        "$scope module dut $end\n$var wire 4 # data $end\n"
        "$upscope $end $upscope $end\n$enddefinitions $end\n"
        "#0 0! b0010 #\n#3 1! bz #\n#9 0! b1111 #\n#15 1!\n"
    )
    window.show()
    window._go_workspace("Waveforms")
    app.processEvents()
    tabs = window.workspace
    tabs.refreshEvidence()

    def widget(cls, name):
        result = tabs.findChild(cls, name)
        assert result is not None, name
        return result

    widget(QtWidgets.QPushButton, "waveLoad").click()
    table = tabs.waveTable
    assert table.rowCount() == 2
    finder = widget(QtWidgets.QLineEdit, "waveSignalFilter")
    finder.setText("tb.dut.*")
    assert table.rowCount() == 1
    assert tabs.waveCanvas.visible_signals[0]["name"] == "tb.dut.data"
    table.item(0, 4).setCheckState(QtCore.Qt.CheckState.Checked)
    widget(QtWidgets.QCheckBox, "wavePinnedOnly").setChecked(True)
    finder.clear()
    assert table.rowCount() == 1
    table.setCurrentCell(0, 0)

    QTest.mouseClick(tabs.waveCanvas, QtCore.Qt.MouseButton.LeftButton,
                     pos=QtCore.QPoint(tabs.waveCanvas.sample_x(1) + 2, 48))
    assert tabs.waveCanvas.cursors == (1, None)
    widget(QtWidgets.QPushButton, "waveNextEdge").click()
    assert tabs.waveCanvas.cursors == (2, None)
    widget(QtWidgets.QPushButton, "wavePreviousEdge").click()
    assert tabs.waveCanvas.cursors == (1, None)
    assert table.item(0, 2).text() == "ZZZZ"

    monkeypatch.setattr(QtWidgets.QInputDialog, "getText",
                        lambda *_: ("Dropped write", True))
    widget(QtWidgets.QPushButton, "waveAddBookmark").click()
    combo = widget(QtWidgets.QComboBox, "waveBookmarks")
    assert combo.currentText() == "Dropped write · 30 ps"
    jump = widget(QtWidgets.QLineEdit, "waveJumpTick")
    jump.setText("0")
    widget(QtWidgets.QPushButton, "waveGoToTick").click()
    assert tabs.waveCanvas.cursors == (0, None)
    widget(QtWidgets.QPushButton, "waveUseBookmark").click()
    assert tabs.waveCanvas.cursors == (1, None)

    QTest.mouseClick(tabs.waveCanvas, QtCore.Qt.MouseButton.RightButton,
                     pos=QtCore.QPoint(tabs.waveCanvas.sample_x(2) + 2, 48))
    widget(QtWidgets.QComboBox, "waveRadix").setCurrentText("Signed")
    assert table.item(0, 3).text() == "-1"
    assert "Δ 60 ps" in widget(QtWidgets.QLabel, "waveCursorReadout").text()

    outfile = root / "observed.json"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        lambda *_: (str(outfile), "WaveJSON (*.json)"))
    widget(QtWidgets.QPushButton, "waveExportDrom").click()
    report = json.loads(outfile.read_text())
    assert report["signal"] == [{"name": "tb.dut.data", "wave": "z=", "data": ["-1"]}]
    assert report["wengold"]["source_sha256"] == hashlib.sha256(vcd.read_bytes()).hexdigest()


def test_wave_debug_finding_switches_wrapped_shell_and_sets_cursor(native_window):
    from PyQt6.QtWidgets import QPushButton
    root, app, window = native_window
    (root / "waves").mkdir()
    (root / "waves" / "unanswered.vcd").write_text(
        "$scope module tb $end\n$var wire 1 ! req $end\n"
        "$var wire 1 # ack $end\n$upscope $end\n$enddefinitions $end\n"
        "#0 0! 0#\n#5 1!\n#10\n#15\n#20\n#25\n#30\n#35\n"
    )
    tabs = window.workspace
    tabs.refreshEvidence()
    tabs.findChild(QPushButton, "waveLoad").click()
    window._go_workspace("Wave Debug")
    findings = tabs.waveDebug.findingTable
    assert findings.rowCount() > 0
    time = int(findings.item(0, 2).text())
    findings.setCurrentCell(0, 0)
    assert window.workspaceTitle.text() == "Waveforms"
    index = tabs.waveCanvas.cursors[0]
    assert tabs.waveCanvas.data["times"][index] == time


def test_waveform_opens_explicit_source_match_at_line(native_window):
    from PyQt6.QtWidgets import QComboBox, QPushButton
    root, app, window = native_window
    (root / "waves").mkdir()
    (root / "waves" / "source.vcd").write_text(
        "$scope module tb $end\n$var wire 1 ! q $end\n"
        "$upscope $end\n$enddefinitions $end\n#0 0!\n#5 1!\n"
    )
    tabs = window.workspace
    tabs.refreshEvidence()
    tabs.findChild(QPushButton, "waveLoad").click()
    tabs.waveTable.setCurrentCell(0, 0)
    picker = tabs.findChild(QComboBox, "waveSourceMatch")
    picker.setCurrentText("rtl/module.sv:2")
    assert picker.currentText() == "rtl/module.sv:2"
    tabs.findChild(QPushButton, "waveOpenSourceMatch").click()
    assert window.workspaceTitle.text() == "RTL Editor"
    assert tabs.editorFile() == "rtl/module.sv"
    assert tabs.sourceEditor.textCursor().blockNumber() == 1


def test_trace_tools_compare_and_protocol_navigation(native_window):
    from PyQt6 import QtWidgets
    root, app, window = native_window
    (root / "waves").mkdir()
    base = (
        "$timescale 1ns $end\n$scope module tb $end\n"
        "$var wire 1 ! PCLK $end\n$var wire 1 @ PSEL $end\n"
        "$var wire 1 # PENABLE $end\n$var wire 1 % PREADY $end\n"
        "$var wire 1 & PWRITE $end\n$var wire 8 ' PADDR [7:0] $end\n"
        "$upscope $end\n$enddefinitions $end\n"
        "#0 0! 1@ 0# 0% 1& b00101010 '\n#1 1!\n#2 0! 1#\n"
        "#3 1!\n#4 0! 1%\n#5 1!\n"
    )
    (root / "waves/base.vcd").write_text(base)
    (root / "waves/fail.vcd").write_text(base.replace("#4 0! 1%", "#4 0! 1% b00 '"))
    tabs = window.workspace
    tabs.refreshEvidence()
    window.show()
    window._go_workspace("Trace Tools")
    app.processEvents()

    def widget(cls, name):
        return tabs.findChild(cls, name)

    assert window.workspaceTitle.text() == "Trace Tools"
    widget(QtWidgets.QComboBox, "traceBaseline").setCurrentText("waves/base.vcd")
    widget(QtWidgets.QComboBox, "traceCandidate").setCurrentText("waves/fail.vcd")
    widget(QtWidgets.QPushButton, "traceCompare").click()
    summary = widget(QtWidgets.QLabel, "traceCompareSummary").text()
    assert "First divergence: tb.PADDR at 4 ns" in summary
    assert widget(QtWidgets.QTableWidget, "traceCompareTable").item(0, 0).text() == "tb.PADDR"
    for side in ("Baseline", "Candidate"):
        plot = widget(QtWidgets.QScrollArea, "tracePlot" + side)
        assert plot.widget().cursors[0] == 4

    window._go_workspace("Waveforms")
    widget(QtWidgets.QComboBox, "waveFilePicker").setCurrentText("waves/fail.vcd")
    widget(QtWidgets.QPushButton, "waveLoad").click()
    window._go_workspace("Trace Tools")
    widget(QtWidgets.QLineEdit, "traceProtocolPrefix").setText("tb.")
    widget(QtWidgets.QPushButton, "traceDecode").click()
    lane = widget(QtWidgets.QTableWidget, "traceLaneEvents")
    assert lane.rowCount() == 1
    assert lane.item(0, 2).text() == "1"
    assert "PADDR=0x00" in lane.item(0, 3).text()
    transfers = widget(QtWidgets.QTableWidget, "traceProtocolTransactions")
    assert transfers.item(0, 4).text() == "4 ns"
    lane.cellDoubleClicked.emit(0, 0)
    assert window.workspaceTitle.text() == "Waveforms"
    assert tabs.waveCanvas.data["times"][tabs.waveCanvas.cursors[0]] == 5


def test_native_loads_fst_without_blocking_ui(native_window):
    import shutil
    import subprocess
    import time
    from PyQt6 import QtWidgets
    if not shutil.which("fst2vcd") or not shutil.which("vcd2fst"):
        pytest.skip("requires GTKWave FST conversion tools")
    root, app, window = native_window
    (root / "waves").mkdir()
    temp_vcd = root / "input.vcd"
    temp_vcd.write_text(
        "$date\n test\n$end\n$version\n test\n$end\n$timescale\n1ns\n$end\n"
        "$scope module tb $end\n$var wire 1 ! clk $end\n"
        "$upscope $end\n$enddefinitions $end\n#0\n$dumpvars\n0!\n$end\n#5\n1!\n"
    )
    subprocess.run(["vcd2fst", "-v", str(temp_vcd), "-f", str(root / "waves/live.fst")],
                   check=True, timeout=10)
    tabs = window.workspace
    tabs.refreshEvidence()
    button = tabs.findChild(QtWidgets.QPushButton, "waveLoad")
    assert button.text() == "Load FST"
    button.click()
    assert not button.isEnabled()
    until = time.monotonic() + 4
    while not button.isEnabled() and time.monotonic() < until:
        app.processEvents()
        time.sleep(.01)
    assert button.isEnabled()
    assert tabs.waveCanvas.data["source_format"] == "fst"
    assert tabs.waveCanvas.data["times"] == [0, 5]
