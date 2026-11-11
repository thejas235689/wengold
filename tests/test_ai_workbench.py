"""Local AI workbench safety and evidence tests. No actual LLM required."""
import shutil
import pytest

from wengold.ai_prompts import PROFILES, make_prompt
from wengold.ai_workbench import (
    model_client, generate, validate_rtl, satya_check,
    satya_generate_uvm, rustdv_unit_check,
)


def test_all_requested_disciplines_have_nonempty_prompts():
    expected = {"RTL Design", "SystemVerilog DV", "UVM",
                "Portable Stimulus / Satya", "RustDV", "Formal Verification",
                "DFT", "Power-Aware Design", "Power-Aware Verification",
                "Physical Design", "Physical Verification",
                "Analog Design", "Analog Verification",
                "Layout Design", "Layout Verification"}
    assert expected == set(PROFILES)
    for key in expected:
        system, question = make_prompt(key, "review my block")
        assert "DRAFT" in system and "review my block" in question
    with pytest.raises(ValueError):
        make_prompt("nonexistent", "x")
    with pytest.raises(ValueError):
        make_prompt("RTL Design", "")


def test_only_loopback_model_endpoints_are_accepted():
    for url in ("http://example.com:11434", "https://127.0.0.1:11434",
                "http://localhost.evil.org:11434", "http://user:pass@localhost:11434"):
        with pytest.raises(ValueError):
            model_client("ollama", url, "model")
    assert model_client("ollama", "http://127.0.0.1:11434", "model").model == "model"


def test_generated_rtl_is_always_a_draft(monkeypatch):
    from wengold import ai_workbench
    class Dummy:
        def _require_instruction_following(self, *_): pass
        def ask(self, *_args, **_kwargs): return "module demo; endmodule"
        def unfence(self, x): return x
    monkeypatch.setattr(ai_workbench, "model_client", lambda *_: Dummy())
    out = generate("RTL Design", "counter", "ollama", "http://127.0.0.1:11434", "fake")
    assert out["status"] == "draft"
    assert out["validation"] == "not run"
    assert out["text"].startswith("module")


def test_no_simulation_can_be_claimed_without_testbench(tmp_path):
    result = validate_rtl("module demo; endmodule\n", tmp_path)
    if shutil.which("iverilog"):
        assert result["syntax"] == "pass"
        assert result["status"] == "syntax_checked"
    else:
        assert result["status"] == "draft"
        assert result["syntax"] == "not_run"
    assert result["simulation"] == "not_run"


@pytest.mark.skipif(not (shutil.which("iverilog") and shutil.which("vvp")),
                    reason="Icarus not installed")
def test_real_counter_with_selfchecking_tb_and_failing_tb(tmp_path):
    rtl = """module counter4(input logic clk,rst_n,en,output logic [3:0] count);
always_ff @(posedge clk or negedge rst_n)
if (!rst_n) count <= 0; else if (en) count <= count + 1;
endmodule"""
    (tmp_path / "tb.sv").write_text("""module tb;
reg clk=0,rst_n=0,en=0; wire [3:0] count;
counter4 dut(clk,rst_n,en,count);
always #5 clk=~clk;
initial begin
#12; rst_n=1; en=1; #10;
if (count !== 1) $fatal(1,"FAIL: count wrong");
$display("PASS"); $finish;
end
endmodule""")
    report = validate_rtl(rtl, tmp_path, "tb.sv", "tb")
    assert report["status"] == "simulation_completed"
    assert report["simulation"] == "exit_zero"
    assert "Not signoff" in report["note"]
    broken = rtl.replace("count <= count + 1", "count <= count")
    fail = validate_rtl(broken, tmp_path, "tb.sv", "tb")
    assert fail["status"] == "failed"
    assert fail["simulation"] == "fail"


def test_satya_and_rustdv_adapters_refuse_unsafe_paths(tmp_path):
    (tmp_path / "test.pss").write_text("component c {};")
    with pytest.raises(ValueError):
        satya_check(tmp_path, "../test.pss")
    with pytest.raises(ValueError):
        satya_generate_uvm(tmp_path, "../test.pss")
    with pytest.raises(ValueError):
        rustdv_unit_check(tmp_path, "../rustdv")
    with pytest.raises(ValueError):
        rustdv_unit_check(tmp_path, "nonexistent")
