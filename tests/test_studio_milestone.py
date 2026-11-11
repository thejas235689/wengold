"""Executable milestone tests: real jobs, ledger, source invalidation and review gating."""
import time
import pytest

from wengold.ide_server import Refused
from wengold.studio_jobs import StudioJobs, crossprobe, syntax_diagnostics


def poll(jobs, jid, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = jobs.get(jid)
        if result["status"] in ("completed", "failed"):
            return result
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_syntax_job_and_ledger(tmp_path):
    (tmp_path / "unit.sv").write_text("module unit; endmodule\n")
    queue = StudioJobs(tmp_path)
    try:
        job = queue.submit("syntax", "unit.sv")
        finished = poll(queue, job["id"])
        assert finished["status"] == "completed"
        assert finished["result"]["status"] in ("clean", "errors", "unavailable")
        assert queue.audit()["ok"]
        assert queue.audit()["count"] >= 2
    finally:
        queue.shutdown()


def test_formal_is_real_and_review_requires_current_proof(tmp_path):
    (tmp_path / "counter.sv").write_text(
        "module counter(input logic clk, input logic rst_n, output logic [1:0] count);\n"
        "always_ff @(posedge clk) begin\n"
        "  if (!rst_n) count <= 0;\n"
        "  else count <= count + 1;\n"
        "end\nendmodule\n")
    jobs = StudioJobs(tmp_path)
    try:
        result = poll(jobs, jobs.submit("formal", "counter.sv", expr="count < 4")["id"])
        assert result["status"] in ("completed", "failed")
        if result["status"] == "completed" and result["result"].get("results"):
            status = result["result"]["results"][0]["status"]
            if status != "proof":
                with pytest.raises(Refused):
                    jobs.signoff(result["id"], "Engineer", "accept")
        (tmp_path / "counter.sv").write_text("module counter; endmodule\n")
        assert jobs.get(result["id"])["stale"]
        with pytest.raises(Refused):
            jobs.signoff(result["id"], "Engineer", "accept")
    finally:
        jobs.shutdown()


def test_reject_records_auditable_decision(tmp_path):
    (tmp_path / "block.sv").write_text("module block; endmodule\n")
    jobs = StudioJobs(tmp_path)
    try:
        completed = poll(jobs, jobs.submit("syntax", "block.sv")["id"])
        assert completed["status"] == "completed"
        reviewed = jobs.signoff(completed["id"], "DV reviewer", "reject")
        assert reviewed["review"]["decision"] == "reject"
        assert jobs.audit()["ok"]
        with pytest.raises(Refused):
            jobs.signoff(completed["id"], "DV reviewer", "reject")
    finally:
        jobs.shutdown()


def test_probe_is_lexical_and_restricted(tmp_path):
    (tmp_path / "core.sv").write_text("logic valid;\nassign ready = valid;\n")
    d = crossprobe(tmp_path, ["core.sv"], "top.unit.valid")
    assert d["leaf"] == "valid"
    assert [x["line"] for x in d["matches"]] == [1, 2]
    assert "lexical" in d["resolution"]
    with pytest.raises(Refused):
        crossprobe(tmp_path, ["core.sv"], "../../unsafe")


def test_reject_invalid_job_configuration(tmp_path):
    (tmp_path / "unit.sv").write_text("module unit; endmodule\n")
    jobs = StudioJobs(tmp_path)
    try:
        with pytest.raises(Refused):
            jobs.submit("shell", "unit.sv")
        with pytest.raises(Refused):
            jobs.submit("formal", "unit.sv", expr="x", depth=1000)
        with pytest.raises(Refused):
            jobs.submit("formal", "unit.sv", expr="")
    finally:
        jobs.shutdown()



def test_pipeline_gates_formal_when_syntax_unavailable_or_invalid(tmp_path, monkeypatch):
    from wengold import studio_jobs
    (tmp_path / "bad.sv").write_text("module bad; endmodule\n")
    monkeypatch.setattr(studio_jobs, "syntax_diagnostics", lambda *_: {
        "status": "errors", "tool": "pyslang",
        "diagnostics": [{"message": "parse error"}]
    })
    jobs = StudioJobs(tmp_path)
    try:
        result = poll(jobs, jobs.submit("pipeline", "bad.sv", expr="x == 1")["id"])
        assert result["status"] == "completed"
        assert result["result"]["skipped_formal"] is True
        assert result["result"]["results"][0]["status"] == "unknown"
        assert result["result"]["stages"][-1]["status"] == "skipped"
        assert jobs.audit()["ok"]
        with pytest.raises(Refused):
            jobs.signoff(result["id"], "DV reviewer", "accept")
    finally:
        jobs.shutdown()
