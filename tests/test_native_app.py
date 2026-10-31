"""The native window.

These tests were blocked from landing for many turns: the write API refused the
file and I never found out why until I bisected it to a backticked shell-looking
string in a docstring. So the window has been checked by rendering a screenshot and
looking at it, which catches layout and misses everything that is not visible.

The one that would have caught the most: **the hint bar must list every command the
pane accepts.** Twice I added a command and forgot the hint — `review` and `vibe`
both shipped missing from it, and both times I found it by reading a screenshot.

PyQt6 is optional, so the whole module skips when it is absent.
"""
import os
import sys

import pytest

# must be set before Qt is imported, or the window tries to open a display
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")


def make_window(path):
    """A window over `path`, plus the app object that must stay alive."""
    from wengold.desktop import build_state
    from wengold.native import _qt, build_window

    QtCore, _QtGui, QtWidgets = _qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    win = build_window(build_state(str(path)))
    return app, win


@pytest.fixture
def project(tmp_path):
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "a.sv").write_text(
        "module a(input logic c, output logic q);\n  assign q = c;\nendmodule\n")
    return tmp_path


# ---- construction --------------------------------------------------------
def test_the_window_builds_without_an_event_loop(project):
    """`build_window` is separate from `main` so this is possible."""
    app, win = make_window(project)
    assert win is not None
    assert win.windowTitle().startswith("WENGOLD"), win.windowTitle()


def test_the_three_panes_exist(project):
    app, win = make_window(project)
    assert win.tree is not None, "FILES"
    assert win.detail is not None, "DETAIL"
    assert win.transcript is not None, "the CLI pane"


# ---- the strip -----------------------------------------------------------
def test_the_strip_names_design_units_not_coverage(project):
    """It used to say `100% cov`, which is not coverage of anything — it is the
    share of files that contained a design unit."""
    app, win = make_window(project)
    text = win.coverage.text()
    assert "design units" in text
    assert "cov" not in text.replace("design units", "")
    assert "/" in text, "a ratio, not a percentage"


# ---- the hint bar --------------------------------------------------------
def test_the_hint_bar_lists_every_command(project):
    """`review` and `vibe` both shipped missing from this bar. Twice."""
    from wengold.desktop import CLI_COMMANDS

    app, win = make_window(project)
    hint = win.input.placeholderText() or ""
    assert len(CLI_COMMANDS) > 3, "the list must not be empty or the loop is vacuous"
    assert hint, "the hint bar is empty"
    for cmd in CLI_COMMANDS:
        assert cmd in hint, f"{cmd!r} is accepted by the pane but not in the hint"


# ---- running a command ---------------------------------------------------
def test_a_command_runs_and_lands_in_the_transcript(project):
    app, win = make_window(project)
    before = win.transcript.toPlainText()
    win.input.setText("summary")
    win._run()
    after = win.transcript.toPlainText()
    assert len(after) > len(before)
    assert "summary" in after
    assert "blocks" in after
    assert win.input.text() == "", "the input clears after a command"


def test_an_unknown_command_does_not_kill_the_window(project):
    app, win = make_window(project)
    win.input.setText("rm -rf /")
    win._run()                                   # must not raise
    assert "unknown command" in win.transcript.toPlainText()


# ---- selecting a file ----------------------------------------------------
def test_selecting_a_file_shows_its_source(project):
    """A detail pane that describes a file without showing it is a strange thing
    for a tool whose job is reading RTL."""
    app, win = make_window(project)
    win._select_file("rtl/a.sv")
    shown = win.detail.toHtml()
    assert "module a" in shown
    assert "assign q = c" in shown


def test_html_in_a_source_file_is_escaped(project):
    """`<=` and `&` in RTL would otherwise be read as markup."""
    (project / "rtl" / "b.sv").write_text(
        "module b(input logic a, output logic q);\n"
        "  assign q = a & 1'b1;\nendmodule\n")
    app, win = make_window(project)
    win._select_file("rtl/b.sv")
    shown = win.detail.toHtml()
    assert "&amp;" in shown or "&#38;" in shown, "the ampersand was not escaped"


# ---- the escape helper ---------------------------------------------------
def test_esc_escapes_but_leaves_quotes_alone():
    from wengold.native import _esc
    assert _esc("a <= b") == "a &lt;= b"
    assert _esc("a & b") == "a &amp; b"
    assert _esc("say \"hi\"") == "say \"hi\"", (
        "quotes need no escaping in body text")


# ---- the screenshot path -------------------------------------------------
def test_the_window_can_be_rendered_offscreen(project):
    """The screenshot path exercises the same construction, so it must work
    headless or CI cannot check the layout at all."""
    app, win = make_window(project)
    win.resize(900, 600)
    win.show()
    app.processEvents()
    pix = win.grab()
    assert pix.width() > 0 and pix.height() > 0
    win.close()
