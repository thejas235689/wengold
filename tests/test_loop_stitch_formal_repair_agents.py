from __future__ import annotations

from pathlib import Path

from wengold.tools.outcome import ToolOutcome
from wengold.verification import formal_agents, repair_agents
from wengold.verification.orchestration import AgentStatus


def _formal_agent(tmp_path, monkeypatch, *, proof_mode="prove", actual_mode="prove", parsed=ToolOutcome.PASS):
    manifest = tmp_path / "flows" / "formal.json"
    manifest.parent.mkdir()
    sby_dir = tmp_path / "formal"
    sby_dir.mkdir()
    (sby_dir / "top.sby").write_text(
        "[options]\nmode " + actual_mode + "\n[engines]\nsmtbmc\n")
    manifest.write_text('{"kind":"formal","engine":"symbiyosys","proof_mode":"' +
                        proof_mode + '","argv":["sby","-f","formal/top.sby"]}')
    agent = formal_agents.SymbiYosysManifestAgent(tmp_path, "flows/formal.json")
    monkeypatch.setattr(formal_agents, "inspect_manifest", lambda *_: {
        "kind": "formal", "artifacts_expected": ["formal/PASS"]
    })
    monkeypatch.setattr(formal_agents, "execute_manifest", lambda *_: {
        "ok": parsed is ToolOutcome.PASS,
        "status": "tool_completed" if parsed is ToolOutcome.PASS else "tool_failed",
        "exit_code": 0 if parsed is ToolOutcome.PASS else 1,
        "log": "DONE (PASS, rc=0)" if parsed is ToolOutcome.PASS else "DONE (FAIL, rc=1)",
        "input_unchanged": True,
        "inputs_sha256": {"rtl/top.sv": "a" * 64},
        "artifacts_sha256": {"formal/PASS": "b" * 64},
        "missing_artifacts": [], "stale_artifacts": [],
    })
    return agent


def test_formal_agent_requires_unbounded_prove_mode(tmp_path, monkeypatch):
    agent = _formal_agent(tmp_path, monkeypatch, proof_mode="bmc")
    report = agent.execute({})
    assert report.status is AgentStatus.BLOCKED
    assert "bounded BMC" in report.findings[0]


def test_formal_agent_requires_parsed_sby_pass_and_fresh_evidence(tmp_path, monkeypatch):
    agent = _formal_agent(tmp_path, monkeypatch)
    report = agent.execute({})
    assert report.status is AgentStatus.PASS
    assert report.outputs["formal:flows/formal.json"]["status"] == "symbiyosys_proof_pass"
    assert report.evidence_refs == ("formal/PASS",)


def test_formal_counterexample_is_fail_not_pass(tmp_path, monkeypatch):
    agent = _formal_agent(tmp_path, monkeypatch, parsed=ToolOutcome.FAIL)
    report = agent.execute({})
    assert report.status is AgentStatus.FAIL
    assert not report.outputs


def test_repair_proposal_never_modifies_rtl(tmp_path):
    rtl = tmp_path / "rtl" / "top.sv"
    rtl.parent.mkdir()
    original = "module top;\n  assign ready = valid;\nendmodule\n"
    rtl.write_text(original)
    agent = repair_agents.RepairProposalAgent(
        tmp_path, "rtl/top.sv",
        {"category": "assertion_failure", "file": "rtl/top.sv",
         "log": "ready = valid"},
    )
    report = agent.execute({})
    assert report.status is AgentStatus.PASS
    payload = report.outputs["repair_proposal:rtl/top.sv"]
    assert payload["status"] == "proposal_only_requires_engineer_approval"
    assert payload["source_unchanged"] is True
    assert payload["verification_status"] == "NOT_RUN"
    assert rtl.read_text() == original


def test_repair_proposal_rejects_path_escape(tmp_path):
    agent = repair_agents.RepairProposalAgent(
        tmp_path, "../outside.sv", {"category": "unknown"}
    )
    report = agent.execute({})
    assert report.status is AgentStatus.BLOCKED


def test_formal_agent_checks_actual_sby_file_not_only_manifest_claim(tmp_path, monkeypatch):
    agent = _formal_agent(tmp_path, monkeypatch, proof_mode="prove", actual_mode="bmc")
    report = agent.execute({})
    assert report.status is AgentStatus.BLOCKED
    assert "actual .sby" in report.findings[0]
