"""Four-area release gate checks: no fake model, UVM, formal, PDK results."""
import json
from pathlib import Path
import sys

import pytest

from wengold.production_readiness import assess, main


def _recipe(root: Path, kind: str, *, name="flow.json", file="results/tool.txt"):
    (root / "design.sv").write_text("module m; endmodule")
    (root / name).write_text(json.dumps({
        "kind": kind,
        "argv": [sys.executable, "-c",
                 "from pathlib import Path; "
                 "Path('results').mkdir(exist_ok=True); "
                 f"Path({file!r}).write_text('TOOL_RUN')"],
        "inputs": ["design.sv"], "artifacts": [file],
        "timeout_seconds": 15,
    }))
    return name


def test_fresh_project_has_zero_confirmed_production_gates(tmp_path):
    report = assess(tmp_path)
    assert report["observed_gates"] == 0
    assert report["required_gates"] == 7
    assert not report["all_gates_observed"]
    assert report["signoff"] == "NOT ESTABLISHED"
    assert all(x["status"] == "not_configured" for x in report["gates"].values())


def test_tool_recipe_cannot_pass_without_explicit_execute(tmp_path):
    manifest = _recipe(tmp_path, "uvm")
    result = assess(tmp_path, manifests={"uvm": manifest})
    assert result["gates"]["uvm"]["status"] == "configured_not_executed"
    assert not (tmp_path / "results" / "tool.txt").exists()
    executed = assess(tmp_path, manifests={"uvm": manifest}, execute=True)
    assert executed["gates"]["uvm"]["status"] == "executed_with_evidence"
    assert (tmp_path / "results" / "tool.txt").is_file()
    assert executed["observed_gates"] == 1
    assert executed["signoff"] == "NOT ESTABLISHED"


def test_package_aware_formal_requires_external_proof_manifest(tmp_path):
    _recipe(tmp_path, "formal")
    bad = assess(tmp_path, manifests={"package_formal": "flow.json"})
    assert bad["gates"]["package_formal"]["status"] == "configured_not_executed"
    assert not bad["all_gates_observed"]
    # A mismatched flow cannot be treated as formal:
    (tmp_path / "flow.json").write_text(
        (tmp_path / "flow.json").read_text().replace('"formal"', '"uvm"'))
    refused = assess(tmp_path, manifests={"package_formal": "flow.json"})
    assert refused["gates"]["package_formal"]["status"] == "failed"


@pytest.mark.parametrize("gate,kind", [
    ("power", "power"),
    ("physical_drc", "physical_drc"),
    ("physical_lvs", "physical_lvs"),
    ("physical_pex", "physical_pex"),
])
def test_physical_gates_need_real_tool_execution(tmp_path, gate, kind):
    manifest = _recipe(tmp_path, kind)
    inspected = assess(tmp_path, manifests={gate: manifest})
    assert inspected["gates"][gate]["status"] == "configured_not_executed"
    assert "signoff" in inspected and inspected["signoff"] == "NOT ESTABLISHED"


def test_missing_outputs_dont_claim_proof(tmp_path):
    (tmp_path / "rtl.sv").write_text("module m; endmodule")
    (tmp_path / "no_artifact.json").write_text(json.dumps({
        "kind": "formal", "argv": [sys.executable, "-c", "print('PASS')"],
        "inputs": ["rtl.sv"], "artifacts": ["missing.log"],
    }))
    report = assess(tmp_path, manifests={"package_formal": "no_artifact.json"},
                    execute=True)
    assert report["gates"]["package_formal"]["status"] == "failed"
    assert not report["all_gates_observed"]


def test_live_local_model_probe_is_separate_and_optional(tmp_path, monkeypatch):
    def mock_probe(backend, endpoint, model):
        assert backend == "ollama"
        assert endpoint == "http://127.0.0.1:11434"
        assert model == "test-model"
        return {"ok": True, "status": "responding", "sample": "ready"}
    monkeypatch.setattr("wengold.ai_workbench.test_connection", mock_probe)
    not_called = assess(tmp_path, model="test-model")
    assert not_called["gates"]["local_ai"]["status"] == "not_executed"
    yes = assess(tmp_path, model="test-model", probe_ai=True)
    assert yes["gates"]["local_ai"]["status"] == "live_inference_observed"
    assert yes["signoff"] == "NOT ESTABLISHED"


def test_cli_returns_nonzero_when_any_gate_unverified(tmp_path, capsys):
    assert main([str(tmp_path)]) == 1
    response = json.loads(capsys.readouterr().out)
    assert response["observed_gates"] == 0
    assert response["required_gates"] == 7
