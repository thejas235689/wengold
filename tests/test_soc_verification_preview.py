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


@pytest.mark.skipif(not shutil.which("xezim"), reason="requires Xezim 0.11.6")
def test_replay_relocated_snapshots_and_detect_tampering(tmp_path):
    output = tmp_path / "evidence"
    report = preview.verify(output)
    assert report["status"] == "preview_verified"
    relocated = output.rename(tmp_path / "relocated")
    saved = relocated / "report.json"
    before = saved.read_bytes()
    for name, run in report["runs"].items():
        result = preview.replay(saved, name)
        assert result["status"] == "replay_matched", result
        assert result["verdict"] == run["verdict"]
    assert saved.read_bytes() == before

    changed = report["runs"]["reverified_dma_first"]
    arbiter = relocated / changed["snapshot"] / "rtl/arbiter.sv"
    assert "CPU_FIRST = 1'b0" in arbiter.read_text()
    arbiter.write_text(arbiter.read_text() + "\n// tampered\n")
    with pytest.raises(ValueError, match="snapshot hash mismatch"):
        preview.replay(saved, "reverified_dma_first")

    log = relocated / report["runs"]["baseline"]["log"]
    log.write_text(log.read_text() + "\ntampered\n")
    with pytest.raises(ValueError, match="original transcript hash mismatch"):
        preview.replay(saved, "baseline")


@pytest.mark.skipif(not shutil.which("xezim"), reason="requires Xezim 0.11.6")
def test_live_dropped_dma_write_exports_observed_readback(tmp_path):
    import subprocess

    from wengold.studio_workspace import waveform
    from wengold.wave_inspect import wave_drom

    example = SCRIPT.parent
    shutil.copytree(example / "rtl", tmp_path / "rtl")
    shutil.copy(example / "subsystem_tb.sv", tmp_path)
    (tmp_path / "waves").mkdir()
    files = sorted(path.relative_to(tmp_path).as_posix()
                   for path in (tmp_path / "rtl").glob("*.sv"))
    run = subprocess.run(["xezim", "--wave", "-D", "WENGOLD_DEBUG_VCD", "-D", "DROP_WRITE",
                          "-s", "subsystem_tb", *files, "subsystem_tb.sv"],
                         cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False)
    transcript = run.stdout + run.stderr
    assert run.returncode != 0
    assert "WENGOLD_VCD_TICK:112" in transcript
    assert "FAIL:REQ-DATA:10" in transcript
    trace = waveform(tmp_path, "waves/dma-debug.vcd")
    assert trace["timescale"] == "1ns"
    signals = {s["name"]: s for s in trace["signals"]}
    report = wave_drom(trace, [signals["subsystem_tb.rd"], signals["subsystem_tb.value"]],
                       trace["times"].index(110), trace["times"].index(112))
    assert report["wengold"]["ticks_per_slot"] == 1
    assert report["signal"] == [
        {"name": "subsystem_tb.rd", "wave": "==.", "data": ["0x4", "0x5"]},
        {"name": "subsystem_tb.value", "wave": "==.", "data": ["0x39", "0x00"]},
    ]
