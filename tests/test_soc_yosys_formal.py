"""The formal runner must fail closed when tooling is missing."""
import importlib.util
import json
from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1]
          / "examples/soc_verification/formal/run.py")
spec = importlib.util.spec_from_file_location("soc_yosys_formal", SCRIPT)
assert spec is not None and spec.loader is not None
formal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(formal)


def test_missing_tools_cannot_verify(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    output = tmp_path / "evidence"
    report = formal.verify(output)
    assert report["status"] == "suite_not_verified"
    assert all(job["verdict"] == "tool_error" for job in report["jobs"].values())
    assert json.loads((output / "report.json").read_text()) == report
    assert report["inputs"]["rtl/arbiter.sv"]


def test_connectivity_jobs_check_induction_cover_and_specific_faults():
    for policy in ("cpu_first", "dma_first"):
        kind, _, _, modes, expected = formal.JOBS["subsystem_" + policy]
        assert kind == "subsystem"
        assert set(modes) == {"bmc", "induction", "cover"}
        assert expected is None
    for job, expected in [
        ("subsystem_misrouted_address", "write_address_matches_owner"),
        ("subsystem_corrupted_payload", "write_payload_matches_owner"),
        ("subsystem_dropped_write", "watched_subsystem_readback"),
    ]:
        assert formal.JOBS[job][-2:] == (("bmc",), expected)
