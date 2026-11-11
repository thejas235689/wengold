"""Workflow tests: real intake + measured coverage, mocked local inference.

The tests must never fabricate simulator PASS, formal proof, or signoff.
"""
import json
import pytest

from wengold import dv_pipeline


@pytest.fixture
def project(tmp_path):
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "requirements.md").write_text(
        "REQ-01 Reset count to zero. REQ-02 Enable increments count.\n")
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "counter.sv").write_text(
        "module counter(input logic clk, rst_n, en, output logic [3:0] count);\n"
        "always_ff @(posedge clk or negedge rst_n)\n"
        "if (!rst_n) count <= 0; else if (en) count <= count + 1;\n"
        "endmodule\n")
    return tmp_path


def test_spec_and_rtl_intake_with_provenance(project):
    report = dv_pipeline.intake(project, "spec/requirements.md", "rtl/counter.sv")
    assert report["status"] == "sources_loaded_not_verified"
    assert report["modules"] == ["counter"]
    assert len(report["spec_sha256"]) == 64
    assert "REQ-02" in report["spec_excerpt"]
    with pytest.raises(Exception):
        dv_pipeline.intake(project, "../secrets.md", "rtl/counter.sv")


def test_pdf_is_never_treated_as_prompt_text(project):
    (project / "spec" / "spec.pdf").write_bytes(b"%PDF-1.4\n\x00")
    with pytest.raises(ValueError, match="exported"):
        dv_pipeline.intake(project, "spec/spec.pdf", "rtl/counter.sv")


@pytest.mark.parametrize("kind", ["verification_plan", "uvm", "sva", "testcases"])
def test_local_ai_artifacts_are_drafts(project, monkeypatch, kind):
    class Local:
        def _require_instruction_following(self, *_): pass
        def ask(self, prompt, system=""):
            assert "REQ-01" in prompt
            assert "DRAFT" in system
            return "DRAFT: requirements and UVM tests subject to review"
    monkeypatch.setattr(dv_pipeline, "model_client", lambda *_args: Local())
    out = dv_pipeline.generate_artifact(
        project, "spec/requirements.md", "rtl/counter.sv", kind,
        "ollama", "http://127.0.0.1:11434", "local-model")
    assert out["status"] == "draft_not_verified"
    assert out["kind"] == kind
    assert out["spec_sha256"] == dv_pipeline.intake(
        project, "spec/requirements.md", "rtl/counter.sv")["spec_sha256"]


def test_coverage_gaps_with_actual_counts(project):
    result = project / "results"
    result.mkdir()
    (result / "coverage.json").write_text(json.dumps({
        "bins": [
            {"name": "reset", "hits": 12},
            {"name": "increment", "hits": 4},
            {"name": "overflow", "hits": 0},
            {"name": "unreachable_by_design", "hits": 0,
             "excluded": True, "reason": "approved unreachable"}
        ]}))
    out = dv_pipeline.coverage_report(project, "results/coverage.json", 90)
    assert out["covered"] == 2
    assert out["eligible"] == 3
    assert out["coverage_percent"] == 66.67
    assert not out["target_reached"]
    assert out["uncovered"] == ["overflow"]
    assert "UNCONFIRMED" in out["closure"]


def test_coverage_validation_fails_closed(project):
    (project / "coverage.json").write_text(
        json.dumps({"bins": [{"name": "x", "hits": -2}]}))
    with pytest.raises(ValueError):
        dv_pipeline.coverage_report(project, "coverage.json")
    (project / "coverage.json").write_text(json.dumps({
        "bins": [{"name": "x", "hits": 0, "excluded": True}]}))
    with pytest.raises(ValueError, match="no eligible"):
        dv_pipeline.coverage_report(project, "coverage.json")


def test_regression_rejects_non_simulation_manifest(project):
    (project / "flow.json").write_text(json.dumps({
        "kind": "physical_drc", "argv": ["python3", "-V"],
        "inputs": ["rtl/counter.sv"], "artifacts": []
    }))
    with pytest.raises(ValueError, match="regression"):
        dv_pipeline.run_regression(project, "flow.json")


def test_ai_debug_only_evidence_hypotheses(project, monkeypatch):
    (project / "run.log").write_text(
        "FATAL: scoreboard expected 7 got 3 at t=200\n")
    class Local:
        def ask(self, prompt, system=""):
            assert "expected 7 got 3" in prompt
            assert "hypotheses" in system.lower()
            return "Hypothesis: monitor samples a cycle late; confirm via VCD"
    monkeypatch.setattr(dv_pipeline, "model_client", lambda *_: Local())
    result = dv_pipeline.triage(project, "run.log", "ollama",
                                "http://127.0.0.1:11434", "local-model")
    assert result["status"] == "ai_debug_hypotheses_unverified"
    assert len(result["log_sha256"]) == 64



def test_draft_export_is_explicit_and_never_overwrites(project):
    draft = {"status": "draft_not_verified", "kind": "verification_plan",
             "text": "# DRAFT verification plan"}
    output = dv_pipeline.save_draft(
        project, draft, "wengold-drafts/verification_plan.md")
    assert output["status"] == "saved_unverified_draft"
    assert (project / "wengold-drafts" / "verification_plan.md").is_file()
    with pytest.raises(FileExistsError):
        dv_pipeline.save_draft(project, draft, "wengold-drafts/verification_plan.md")
    with pytest.raises(ValueError):
        dv_pipeline.save_draft(project, draft, "rtl/counter.sv")
    with pytest.raises(ValueError):
        dv_pipeline.save_draft(project, draft, "../escape.md")


def test_regression_rejects_vacuous_no_artifact_manifest(project):
    (project / "flow.json").write_text(json.dumps({
        "kind": "uvm", "argv": ["python3", "-V"],
        "inputs": ["rtl/counter.sv"], "artifacts": []}))
    with pytest.raises(ValueError, match="evidence"):
        dv_pipeline.run_regression(project, "flow.json")


def test_specification_file_is_auto_discovered(project):
    from wengold.project_scan import discover
    from wengold.desktop import build_state
    inventory = discover(project)
    assert "spec/requirements.md" in inventory["specifications"]
    state = build_state(str(project))
    assert "spec/requirements.md" in state["file_paths"]
