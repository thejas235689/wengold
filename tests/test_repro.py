"""Failure reproduction: capture, replay, and refusing to lie.

The load-bearing test is `test_a_drifted_file_is_not_reported_as_reproduced`.
A reproducer that reproduces everything reproduces nothing, and reporting
"reproduced" against changed RTL is the worst failure this feature could have.
"""
import json
import os

import pytest

from wengold.kernel.validity import Result
from wengold.repro import (Bundle, capture, drift, file_hashes, load, replay,
                           save)


@pytest.fixture()
def tree(tmp_path):
    (tmp_path / "a.sv").write_text("module a; endmodule\n")
    (tmp_path / "b.sv").write_text("module b; endmodule\n")
    return tmp_path


def _result(rid="sim_a", status="fail"):
    r = Result(rid, "sim", depends_on={"a"})
    r.status = status
    return r


def test_capture_pins_every_file(tree):
    b = capture(str(tree), _result(), detail="assertion failed at cycle 21")
    assert len(b.files) == 2
    assert set(b.files) == {"a.sv", "b.sv"}
    assert all(len(h) == 16 for h in b.files.values())


def test_a_bundle_round_trips_through_json(tree):
    b = capture(str(tree), _result(), verdict="invalidated", detail="boom",
                tool="iverilog", tool_version="12.0")
    b2 = Bundle.from_json(b.to_json())
    assert b2.result_id == b.result_id and b2.files == b.files
    assert b2.verdict == "invalidated" and b2.tool_version == "12.0"


def test_a_foreign_json_is_rejected():
    with pytest.raises(ValueError):
        Bundle.from_json('{"result_id": "x"}')


def test_an_unchanged_tree_reproduces(tree):
    b = capture(str(tree), _result())
    rep = replay(b, str(tree))
    assert rep.reproduced and rep.clean
    assert rep.drift == {"changed": [], "missing": [], "added": []}


def test_a_drifted_file_is_not_reported_as_reproduced(tree):
    """The one that matters.

    Edit one file and the replay must refuse. Reporting success here would mean
    the tool claims to have reproduced a result it has not — against different
    code.
    """
    b = capture(str(tree), _result())
    (tree / "a.sv").write_text("module a; wire x; endmodule\n")
    rep = replay(b, str(tree))
    assert not rep.reproduced
    assert rep.drift["changed"] == ["a.sv"]
    assert any("different code" in n for n in rep.notes)
    assert "NOT REPRODUCED" in rep.render()


def test_a_deleted_file_is_reported_separately_from_a_change(tree):
    b = capture(str(tree), _result())
    os.remove(tree / "b.sv")
    rep = replay(b, str(tree))
    assert not rep.reproduced
    assert rep.drift["missing"] == ["b.sv"]
    assert rep.drift["changed"] == [], "a deletion is not a modification"


def test_an_added_file_is_reported(tree):
    b = capture(str(tree), _result())
    (tree / "c.sv").write_text("module a; endmodule\n")   # shadows `a`
    rep = replay(b, str(tree))
    assert not rep.reproduced
    assert rep.drift["added"] == ["c.sv"]
    assert any("shadow" in n for n in rep.notes)


def test_save_and_load_round_trip_on_disk(tree, tmp_path):
    b = capture(str(tree), _result())
    p = save(b, tmp_path / "sub" / "bundle.json")
    assert p.exists()
    assert load(p).files == b.files
    assert json.loads(p.read_text())["wengold_repro"] == 1


def test_file_hashes_ignores_non_hdl(tree):
    (tree / "notes.txt").write_text("hello")
    assert set(file_hashes(str(tree))) == {"a.sv", "b.sv"}


def test_a_missing_file_hashes_as_missing(tree):
    h = file_hashes(str(tree), ["a.sv", "nope.sv"])
    assert h["nope.sv"] == "missing"
