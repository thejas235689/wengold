"""Real subprocess and evidence policies for EDA flow manifests."""
import json
import sys

import pytest
from wengold.eda_flows import execute_manifest, inspect_manifest


def recipe(tmp_path, *, kind="uvm", script=None):
    (tmp_path / "input.sv").write_text("module m; endmodule\n")
    script = script or "from pathlib import Path; Path('result.txt').write_text('PASS')"
    obj = {
        "kind": kind,
        "argv": [sys.executable, "-c", script],
        "inputs": ["input.sv"], "artifacts": ["result.txt"],
        "timeout_seconds": 10,
    }
    (tmp_path / "flow.json").write_text(json.dumps(obj))
    return "flow.json"


def test_actual_eda_tool_success_requires_artifact(tmp_path):
    path = recipe(tmp_path, kind="uvm")
    inspected = inspect_manifest(tmp_path, path)
    assert inspected["kind"] == "uvm"
    report = execute_manifest(tmp_path, path)
    assert report["status"] == "tool_completed"
    assert report["ok"]
    assert len(report["inputs_sha256"]["input.sv"]) == 64
    assert len(report["artifacts_sha256"]["result.txt"]) == 64
    assert "not signoff" in report["qualification"]


def test_missing_evidence_never_counts_as_success(tmp_path):
    path = recipe(tmp_path, script="print('I pretend to pass')")
    report = execute_manifest(tmp_path, path)
    assert not report["ok"]
    assert report["status"] == "evidence_missing"


def test_exit_nonzero_never_counts_as_success(tmp_path):
    path = recipe(tmp_path, script="import sys; sys.exit(3)")
    report = execute_manifest(tmp_path, path)
    assert not report["ok"]
    assert report["exit_code"] == 3


def test_reject_unsafe_project_path_and_unreviewed_recipe(tmp_path):
    recipe(tmp_path)
    with pytest.raises(ValueError):
        inspect_manifest(tmp_path, "../flow.json")
    with pytest.raises(ValueError):
        inspect_manifest(tmp_path, "/tmp/flow.json")
    data = json.loads((tmp_path / "flow.json").read_text())
    data["kind"] = "made_up_proof"
    (tmp_path / "flow.json").write_text(json.dumps(data))
    with pytest.raises(ValueError):
        execute_manifest(tmp_path, "flow.json")


def test_dft_physical_analog_and_layout_require_actual_results(tmp_path):
    for kind in ("dft", "physical_drc", "physical_lvs", "physical_pex",
                 "analog", "layout", "upf", "rustdv_sim", "pss"):
        recipe(tmp_path, kind=kind)
        report = execute_manifest(tmp_path, "flow.json")
        assert report["kind"] == kind
        assert report["ok"]
        assert report["qualification"].startswith("ENGINEERING TOOL RUN ONLY")
        (tmp_path / "result.txt").unlink()
