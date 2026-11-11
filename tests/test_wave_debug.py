"""Evidence-based waveform RTL versus testbench diagnostics; no fake AI."""
import pytest
from wengold.wave import parse_vcd
from wengold.wave_debug import classify, diagnose, ai_debug_prompt


VCD = """$timescale 1ns $end
$scope module tb $end
$var wire 1 ! clk $end
$var wire 1 " req $end
$var wire 1 # ack $end
$var wire 1 $ payload_expected $end
$var wire 1 % payload_actual $end
$scope module dut $end
$var wire 1 & clk $end
$var wire 1 ' state $end
$var wire 1 ( valid $end
$var wire 1 ) ready $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0"
0#
0$
0%
0&
0'
0(
0)
#5
1!
1"
0#
1$
0%
1&
x'
1(
0)
#10
0!
1"
0#
1$
0%
0&
x'
1(
0)
#15
1!
1"
0#
1$
0%
1&
x'
1(
0)
#20
0!
1"
0#
1$
0%
0&
x'
1(
0)
#25
1!
1"
0#
1$
0%
1&
x'
1(
0)
#30
0!
1"
0#
1$
0%
0&
x'
1(
0)
#35
1!
1"
0#
1$
0%
1&
x'
1(
0)
"""


def test_nested_dut_is_not_classified_as_tb():
    assert classify("tb.dut.state", ("tb.dut",), ("tb",)) == "rtl"
    assert classify("tb.req", ("tb.dut",), ("tb",)) == "testbench"
    assert classify("chip.cache.state") == "unclassified"
    assert classify("tb.dut.valid", ("tb.dut",), ("tb.dut",)) == "ambiguous"


def test_domain_separation_and_explicit_evidence():
    data = parse_vcd(VCD)
    report = diagnose(data, dut_roots=("tb.dut",), tb_roots=("tb",),
                      handshake_window=4)
    assert report["status"] == "diagnostic_candidates_not_proven"
    rtl = {x["name"] for x in report["groups"]["rtl"]}
    tb = {x["name"] for x in report["groups"]["testbench"]}
    assert "tb.dut.state" in rtl
    assert "tb.payload_expected" in tb
    assert rtl.isdisjoint(tb)
    findings = report["findings"]
    assert any(f["rule"] == "scoreboard_mismatch" for f in findings)
    assert any(f["rule"] == "unknown_transition" and "tb.dut.state" in f["signals"] for f in findings)
    assert any(f["rule"] == "handshake_timeout_candidate" for f in findings)
    assert all(f["assessment"] == "candidate" for f in findings)
    assert all(f["time"] in data["times"] for f in findings)


def test_no_phantom_findings_for_simple_clean_waveform():
    data = parse_vcd("""$scope module tb $end
$var wire 1 ! clk $end
$scope module dut $end
$var wire 1 # ready $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0#
#5
1!
1#
#10
0!
0#
#15
1!
1#
""")
    report = diagnose(data, dut_roots=("tb.dut",), tb_roots=("tb",))
    assert report["findings"] == []


def test_ai_prompt_contains_only_bounded_observations():
    report = diagnose(parse_vcd(VCD), dut_roots=("tb.dut",), tb_roots=("tb",))
    system, user = ai_debug_prompt(report)
    assert "HYPOTHESES" in system
    assert "tb.dut.state" in user
    assert "not proven" in system.lower() or "until independently confirmed" in system.lower()
    assert len(user) < 16000


def test_validation_limits():
    wave = parse_vcd(VCD)
    with pytest.raises(ValueError):
        diagnose(wave, handshake_window=0)
    with pytest.raises(ValueError):
        diagnose(wave, max_findings=999)


def test_no_remote_ai_endpoint_or_hidden_fallback(monkeypatch):
    from wengold import wave_debug
    class Dummy:
        def ask(self, message, system=""):
            assert "tb.dut.state" in message
            assert "HYPOTHESES" in system
            return "Hypothesis: DUT state became unknown at captured timestamp 5."
    monkeypatch.setattr("wengold.ai_workbench.model_client",
                        lambda *_args, **_kwargs: Dummy())
    report = diagnose(parse_vcd(VCD), dut_roots=("tb.dut",), tb_roots=("tb",))
    reply = wave_debug.explain_with_local_ai(report, "ollama", "http://127.0.0.1:11434", "test-model")
    assert reply["status"] == "ai_hypotheses_unverified"
    assert len(reply["report_sha256"]) == 64
