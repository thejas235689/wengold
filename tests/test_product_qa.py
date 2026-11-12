"""User-action product QA for the native WENGOLD verification desktop.

These exercise actual Qt clicks, not merely widget presence. Inference is
explicitly stubbed in CI; no local model or proof result is fabricated.
"""
from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")


@pytest.fixture
def qa_window(tmp_path):
    from PyQt6 import QtWidgets
    from wengold.desktop import build_state
    from wengold.native import build_window

    (tmp_path / "spec").mkdir()
    (tmp_path / "rtl").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "spec" / "requirements.md").write_text(
        "# Requirements\nREQ-1 asynchronous reset to zero.\n")
    (tmp_path / "rtl" / "counter.sv").write_text(
        "module counter(input logic clk, output logic q); assign q=clk; endmodule\n")
    (tmp_path / "scripts" / "regression.py").write_text("print('real script')\n")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = build_window(build_state(str(tmp_path)))
    window.show()
    app.processEvents()
    yield tmp_path, app, window
    for state in (
        window.workspace.dvWorkflow.pipelineState,
        window.workspace.implementation.synthesisState,
        window.workspace.aiPage.aiState,
        window.workspace.waveDebug.debugState,
    ):
        thread = state.get("thread")
        if thread is not None:
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(5000)
            except RuntimeError:
                pass
    window.workspace.jobs.shutdown()
    window.close()


def _await(app, check, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if check():
            return
        time.sleep(0.018)
    assert check(), "Qt action did not complete or report expected evidence"


def test_search_filter_and_double_click_spec_editor(qa_window):
    from PyQt6 import QtWidgets, QtCore
    root, app, window = qa_window
    finder = window.findChild(QtWidgets.QLineEdit, "projectFileFilter")
    assert finder
    finder.setText("requirements")
    app.processEvents()
    groups = [window.tree.topLevelItem(i)
              for i in range(window.tree.topLevelItemCount())]
    selected = [g for g in groups if not g.isHidden()]
    assert len(selected) == 1
    assert "Specification" in selected[0].text(0)
    assert selected[0].childCount() == 1
    entry = selected[0].child(0)
    window.tree.itemDoubleClicked.emit(entry, 0)
    app.processEvents()
    assert window.workspace.editorFile() == "spec/requirements.md"
    assert "REQ-1" in window.workspace.sourceEditor.toPlainText()
    assert window.workspace.tabText(window.workspace.currentIndex()) == "RTL Editor"
    finder.clear()
    app.processEvents()
    assert all(not group.isHidden() for group in groups)


def test_automation_source_is_readable_but_cannot_run_hdl_syntax(qa_window):
    from PyQt6 import QtWidgets
    root, app, window = qa_window
    studio = window.workspace
    studio.loadSource("scripts/regression.py")
    assert "real script" in studio.sourceEditor.toPlainText()
    buttons = studio.findChildren(QtWidgets.QPushButton)
    check = next(b for b in buttons if b.text() == "Check HDL syntax")
    before = len(studio.jobs.list_jobs())
    check.click()
    assert len(studio.jobs.list_jobs()) == before
    assert "HDL syntax check supports" in studio.statusLabel.text()


def test_clicked_intake_ai_plan_uvm_and_coverage(qa_window, monkeypatch):
    from PyQt6 import QtWidgets
    from wengold import dv_pipeline
    root, app, window = qa_window
    panel = window.workspace.dvWorkflow
    panel.findChild(QtWidgets.QComboBox, "dvSpec").setCurrentText(
        "spec/requirements.md")
    panel.findChild(QtWidgets.QComboBox, "dvRtl").setCurrentText(
        "rtl/counter.sv")
    panel.findChild(QtWidgets.QPushButton, "dvIntakeButton").click()
    _await(app, lambda: "dvIntake" in panel.pipelineState["results"])
    evidence = panel.findChild(QtWidgets.QPlainTextEdit, "dvIntakeEvidence")
    assert "sources_loaded_not_verified" in evidence.toPlainText()
    assert not panel.pipelineState["busy"]

    class MockLocalModel:
        def _require_instruction_following(self, *_):
            pass

        def ask(self, prompt, system=""):
            assert "REQ-1" in prompt
            return "DRAFT: review requirements, assertions and scoreboard"

    monkeypatch.setattr(dv_pipeline, "model_client", lambda *_: MockLocalModel())
    panel.findChild(QtWidgets.QPushButton, "dvPlanButton").click()
    _await(app, lambda: "dvPlan" in panel.pipelineState["results"])
    assert panel.pipelineState["results"]["dvPlan"]["status"] == "draft_not_verified"

    panel.findChild(QtWidgets.QPushButton, "dvUvmButton").click()
    _await(app, lambda: "dvUvm" in panel.pipelineState["results"])
    assert panel.pipelineState["results"]["dvUvm"]["kind"] == "uvm"
    assert "not signoff" in panel.findChild(
        QtWidgets.QLabel, "dvPipelineStatus").text()

    # Import actual, explicit bin observations, not values returned by the model.
    import json
    (root / "coverage.json").write_text(json.dumps({
        "bins": [{"name": "reset", "hits": 3},
                 {"name": "overflow", "hits": 0}]}))
    panel.findChild(QtWidgets.QLineEdit, "dvCoverageFile").setText("coverage.json")
    panel.findChild(QtWidgets.QPushButton, "dvCoverageButton").click()
    _await(app, lambda: "dvCoverage" in panel.pipelineState["results"])
    out = panel.pipelineState["results"]["dvCoverage"]
    assert out["coverage_percent"] == 50.0
    assert not out["target_reached"]
    assert out["uncovered"] == ["overflow"]


def test_active_llm_job_prevents_closing_and_project_switch(qa_window, monkeypatch):
    from PyQt6 import QtWidgets
    root, app, window = qa_window
    messages = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        lambda *args: messages.append(args[2]))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory",
                        lambda *_a, **_kw: str(root))
    state = window.workspace.dvWorkflow.pipelineState
    state["busy"] = True
    window._open_project()
    assert messages and "DV Workflow" in messages[-1]
    assert window.state["path"] == str(root)
    assert window.close() is False
    assert "DV Workflow" in messages[-1]
    state["busy"] = False
