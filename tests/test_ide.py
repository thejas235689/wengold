"""The IDE: file tree, code, line diff, pending blocks, root cause.

The IDE is only honest if the pending list is the *result of the analysis* rather
than a guess, and if the artifact it produces really is self-contained.
"""
import re

import pytest

from wengold.graph.builder import GraphBuilder
from wengold.ide import build, changed_lines, collect, line_diff
from wengold.kernel.validity import Result

needs_slang = pytest.mark.skipif(
    not __import__("wengold.graph.slang_backend", fromlist=["available"]).available(),
    reason="pyslang not installed")

BEFORE = "module leaf;\n  assign y = a & b;\nendmodule\n"
AFTER = "module leaf;\n  assign y = a | b;\nendmodule\n"


# ---- the diff --------------------------------------------------------------
def test_line_diff_marks_the_changed_line():
    d = line_diff(BEFORE, AFTER)
    kinds = [row["k"] for row in d]
    assert kinds == ["ctx", "del", "add", "ctx"]
    assert d[1]["t"].strip().startswith("assign y = a & b")
    assert d[2]["t"].strip().startswith("assign y = a | b")
    assert d[1]["o"] == 2 and d[1]["n"] is None      # old line 2, gone
    assert d[2]["n"] == 2 and d[2]["o"] is None      # new line 2, added


def test_changed_lines_gives_the_new_line_numbers():
    assert changed_lines(line_diff(BEFORE, AFTER)) == [2]


def test_line_diff_of_an_added_line():
    d = line_diff("a\nb\n", "a\nb\nc\n")
    assert d[-1]["k"] == "add" and d[-1]["n"] == 3


# ---- assembling ------------------------------------------------------------
def _project(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


@needs_slang
def test_collect_marks_changed_pending_and_clean(tmp_path):
    root = _project(tmp_path, {
        "leaf.sv": "module leaf; endmodule\n",
        "mid.sv": "module mid; leaf u_l (); endmodule\n",
        "top.sv": "module top; mid u_m (); endmodule\n",
        "other.sv": "module other; endmodule\n",
    })
    files = {str(p): p.read_text() for p in root.rglob("*.sv")}
    g = GraphBuilder().build_from_files(files, include_dirs=[str(root)],
                                        backend="slang")
    results = [Result(f"unit_{m}", "sim", depends_on={m})
               for m in ("leaf", "mid", "top", "other")]
    data = collect(root, g, {"leaf.sv"}, {"leaf.sv": BEFORE}, results, {"leaf"})

    status = {f["path"]: f["status"] for f in data["files"]}
    assert status["leaf.sv"] == "changed"
    assert status["other.sv"] == "clean"
    assert data["summary"]["changed"] == 1
    # a change to leaf puts leaf, mid and top in doubt — not `other`
    targets = {p["target"] for p in data["pending"]}
    assert targets == {"leaf", "mid", "top"}
    # each entry is named by the RESULT, so three results on one block read as
    # three lines rather than three identical headings
    assert {p["name"] for p in data["pending"]} == {"unit_leaf", "unit_mid",
                                                   "unit_top"}


@needs_slang
def test_a_pending_block_carries_the_causal_chain(tmp_path):
    root = _project(tmp_path, {
        "leaf.sv": "module leaf; endmodule\n",
        "mid.sv": "module mid; leaf u_l (); endmodule\n",
        "top.sv": "module top; mid u_m (); endmodule\n",
    })
    files = {str(p): p.read_text() for p in root.rglob("*.sv")}
    g = GraphBuilder().build_from_files(files, include_dirs=[str(root)],
                                        backend="slang")
    results = [Result(f"unit_{m}", "sim", depends_on={m})
               for m in ("leaf", "mid", "top")]
    data = collect(root, g, {"leaf.sv"}, {}, results, {"leaf"})
    by_target = {p["target"]: p for p in data["pending"]}
    assert by_target["top"]["verdict"] == "invalidated"
    assert by_target["top"]["path_chain"] == ["leaf", "mid", "top"]
    assert "2 level(s)" in by_target["top"]["cause"]
    assert by_target["leaf"]["certainty"] == "proven"


@needs_slang
def test_nothing_is_pending_when_no_change_reaches_it(tmp_path):
    root = _project(tmp_path, {"a.sv": "module a; endmodule\n",
                               "b.sv": "module b; endmodule\n"})
    files = {str(p): p.read_text() for p in root.rglob("*.sv")}
    g = GraphBuilder().build_from_files(files, include_dirs=[str(root)],
                                        backend="slang")
    results = [Result("unit_a", "sim", depends_on={"a"}),
               Result("unit_b", "sim", depends_on={"b"})]
    data = collect(root, g, {"a.sv"}, {}, results, {"a"})
    assert {p["target"] for p in data["pending"]} == {"a"}


# ---- the artifact ----------------------------------------------------------
@needs_slang
def test_the_html_is_self_contained(tmp_path):
    root = _project(tmp_path, {"leaf.sv": "module leaf; endmodule\n"})
    files = {str(p): p.read_text() for p in root.rglob("*.sv")}
    g = GraphBuilder().build_from_files(files, include_dirs=[str(root)],
                                        backend="slang")
    html = build(root, g, {"leaf.sv"}, {}, [Result("unit_leaf", "sim",
                                                  depends_on={"leaf"})],
                 {"leaf"}, project="demo", revision="r2", version="0.0.0")
    # no external resource loads, and no unsubstituted template fields
    for pat in (r"<link\b", r"<script[^>]+src=", r"@import",
                r"url\(\s*[\"']?https?:"):
        assert not re.search(pat, html, re.I), pat
    for tok in ("{data}", "{project}", "{version}", "{ink}"):
        assert tok not in html, tok
    assert "WENGOLD IDE" in html and "demo" in html and "r2" in html
    # the source really is embedded, so the code pane can show it
    assert "module leaf;" in html


def test_a_file_that_was_not_embedded_is_reported(tmp_path):
    root = _project(tmp_path, {"big.sv": "module big; endmodule\n"})
    import wengold.ide as ide
    files = {str(p): p.read_text() for p in root.rglob("*.sv")}
    g = GraphBuilder().build_from_files(files, include_dirs=[str(root)],
                                        backend="regex")
    old = ide.MAX_EMBED
    try:
        ide.MAX_EMBED = 0
        data = collect(root, g, set(), {}, None, set())
        assert data["summary"]["not_embedded"] == 1
        assert "big.sv" not in data["sources"]
    finally:
        ide.MAX_EMBED = old
