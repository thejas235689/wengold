from __future__ import annotations

import json

from wengold.verification import manifest_agents
from wengold.verification.orchestration import AgentStatus, RunStatus


def _project(tmp_path, *, kind="simulation"):
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "top.sv").write_text("module top; endmodule\n")
    (tmp_path / "flows").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "flows" / "smoke.json").write_text(json.dumps({
        "kind": kind,
        "argv": ["python3", "-c", "from pathlib import Path; Path('results/done.txt').write_text('ok')"],
        "inputs": ["rtl/top.sv"],
        "artifacts": ["results/done.txt"],
        "timeout_seconds": 10,
    }))
    return tmp_path


def test_reviewed_manifest_runs_real_process_and_records_ledger(tmp_path):
    root = _project(tmp_path)
    result = manifest_agents.run_reviewed_manifests(root, ["flows/smoke.json"])
    assert result.status is RunStatus.PASS
    assert result.iterations == 1
    assert result.reports[0].status is AgentStatus.PASS
    assert (root / "results" / "done.txt").read_text() == "ok"
    ledger = list((root / "results" / "loop-stitch-ledger.jsonl").read_text().splitlines())
    assert len(ledger) == 2
    assert json.loads(ledger[0])["kind"] == "loop_stitch_iteration"
    assert json.loads(ledger[1])["kind"] == "loop_stitch_result"


def test_missing_executable_is_blocked_not_pass(tmp_path):
    root = _project(tmp_path)
    path = root / "flows" / "smoke.json"
    data = json.loads(path.read_text())
    data["argv"][0] = "wengold-no-such-executable-xyz"
    path.write_text(json.dumps(data))
    result = manifest_agents.run_reviewed_manifests(root, ["flows/smoke.json"])
    assert result.status is RunStatus.BLOCKED
    assert result.reports[0].status is AgentStatus.BLOCKED


def test_formal_manifest_is_not_misrepresented_as_simulation(tmp_path):
    root = _project(tmp_path, kind="formal")
    result = manifest_agents.run_reviewed_manifests(root, ["flows/smoke.json"])
    assert result.status is RunStatus.BLOCKED
    assert result.reports[0].status is AgentStatus.BLOCKED
    assert not (root / "results" / "done.txt").exists()


def test_failed_tool_run_does_not_stitch_outputs(tmp_path):
    root = _project(tmp_path)
    path = root / "flows" / "smoke.json"
    data = json.loads(path.read_text())
    data["argv"] = ["python3", "-c", "raise SystemExit(3)"]
    path.write_text(json.dumps(data))
    result = manifest_agents.run_reviewed_manifests(root, ["flows/smoke.json"])
    assert result.status is RunStatus.FAIL
    assert result.reports[0].status is AgentStatus.FAIL
    assert "manifest:flows/smoke.json" not in result.stitch.outputs


def test_manifest_selection_required_and_ledger_path_confined(tmp_path):
    root = _project(tmp_path)
    try:
        manifest_agents.run_reviewed_manifests(root, [])
    except ValueError as exc:
        assert "at least one" in str(exc)
    else:
        raise AssertionError("empty manifest list should be rejected")
    try:
        manifest_agents.run_reviewed_manifests(
            root, ["flows/smoke.json"], ledger_path="../outside.jsonl"
        )
    except ValueError as exc:
        assert "inside the project" in str(exc)
    else:
        raise AssertionError("ledger path traversal should be rejected")
