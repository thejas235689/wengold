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
                 "aiInspectEdaFlow", "aiRunEdaFlow"):
        assert panel.findChild(QtWidgets.QWidget, name), name
    profiles = panel.findChild(QtWidgets.QComboBox, "aiDiscipline")
    assert profiles.count() == 15



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



def test_dv_workflow_native_six_stages_and_draft_gates(native_window):
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
    assert tabs.count() == 6
    for name in ("dvIntake", "dvPlan", "dvUvm", "dvRegression",
                 "dvDebug", "dvCoverage"):
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
