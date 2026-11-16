"""Exercise the preview with both real and absent simulator tooling."""
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "examples/soc_verification/run.py"
spec = importlib.util.spec_from_file_location("soc_verification_preview", SCRIPT)
assert spec is not None and spec.loader is not None
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def test_missing_xezim_cannot_certify_preview(tmp_path):
    report = preview.verify(tmp_path / "evidence", str(tmp_path / "absent"))
    assert report["status"] == "preview_not_verified"
    assert report["runs"]["baseline"]["verdict"] == "tool_missing"
    assert report["runs"]["dropped_write"]["checks"]["REQ-DATA"]["status"] == "not_established"


@pytest.mark.skipif(not shutil.which("xezim"), reason="requires Xezim 0.11.6")
def test_soc_preview_live(tmp_path):
    output = tmp_path / "evidence"
    report = preview.verify(output)
    assert report["status"] == "preview_verified", report
    assert json.loads((output / "report.json").read_text()) == report
    for name, run in report["runs"].items():
        assert preview.digest(output / (name + ".log")) == run["log_sha256"]
    assert report["changed_inputs"] == ["rtl/arbiter.sv"]
    assert report["runs"]["baseline"]["inputs"]["rtl/arbiter.sv"] != (
        report["runs"]["reverified_dma_first"]["inputs"]["rtl/arbiter.sv"])
    assert report["runs"]["dropped_write"]["checks"]["REQ-DATA"]["first_failing_cycle"] > 0
    assert report["runs"]["early_interrupt"]["checks"]["REQ-IRQ"]["first_failing_cycle"] > 0
