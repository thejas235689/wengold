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
    save = tab.findChild(type(tab.sourceEditor).parentWidget if False else __import__(
        "PyQt6").QtWidgets.QPushButton, "saveRtlButton")
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
