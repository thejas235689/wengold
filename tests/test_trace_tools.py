import hashlib
import shutil
import subprocess
import sys

import pytest

from wengold.fst import to_vcd
from wengold.studio_workspace import list_evidence, waveform
from wengold.wave_compare import compare, plot_window
from wengold.wave_inspect import wave_drom
from wengold.wave_protocol import decode


def sig(name, bits):
    return {"name": name, "width": len(bits[0]),
            "logic_values": bits,
            "values": [None if set(b) & {"x", "z"} else int(b, 2) for b in bits]}


def trace(times, *signals, scale="1ns"):
    return {"times": times, "cycles": len(times), "signals": list(signals), "timescale": scale}


def test_trace_diff_aligns_physical_time_and_reports_missing_width_and_four_state():
    a = trace([10, 11, 14], sig("q", ["0", "z", "1"]), sig("only_a", ["0"] * 3),
              sig("bus", ["00"] * 3))
    b = trace([1100, 1300, 1400, 1500], sig("q", ["0", "x", "1", "1"]),
              sig("only_b", ["0"] * 4), sig("bus", ["000"] * 4), scale="10ps")
    result = compare(a, b, 11, 1300)
    row = {r["name"]: r for r in result["rows"]}
    assert result["times"] == [-1_000_000, 0, 1_000_000, 2_000_000]
    assert result["times"][row["q"]["first"]] == 0
    assert row["only_a"]["status"] == "Baseline only"
    assert row["only_b"]["status"] == "Candidate only"
    assert row["bus"]["status"] == "Width differs"
    plotted, center = plot_window(b, result, "b", "q", row["q"]["first"])
    assert plotted["signals"][0]["logic_values"][center] == "x"
    assert [r["name"] for r in compare(a, b, query="only")["rows"]] == ["only_a", "only_b"]
    with pytest.raises(ValueError, match="observed"):
        compare(a, b, 12, 1300)
    with pytest.raises(ValueError, match="only one"):
        compare(a, {**b, "timescale": None})


def synchronous(cycles, widths, prefix="tb.dut."):
    """Make stable setup (clock low) followed by rising edge values per cycle."""
    count = 2 * len(cycles)
    fields = [sig(prefix + name, [
        value
        for row in cycles
        for value in (format(row.get(name, 0), f"0{width}b"),
                      format(row.get("edge_" + name, row.get(name, 0)), f"0{width}b"))
    ]) for name, width in widths.items()]
    fields += [sig(prefix + "clk", ["0", "1"] * len(cycles))]
    return trace(list(range(count)), *fields)


def test_apb_waits_setup_latency_and_ambiguous_control():
    t = synchronous([
        {"PSEL": 1, "PWRITE": 1, "PADDR": 42},
        {"PSEL": 1, "PENABLE": 1, "PWRITE": 1, "PADDR": 42},
        {"PSEL": 1, "PENABLE": 1, "PREADY": 1, "PWRITE": 1, "PADDR": 42},
        {"PSEL": 1, "PENABLE": 1, "edge_PREADY": 1},
    ], {"PSEL": 1, "PENABLE": 1, "PREADY": 1, "PWRITE": 1, "PADDR": 8})
    report = decode(t, "APB", "tb.dut.", "tb.dut.clk")
    assert report["lanes"] == ["APB"]
    assert report["skipped_control"] == 1
    assert report["events"][0]["wait"] == 1
    assert report["transactions"] == [
        {"kind": "Write", "id": "—", "start": 1, "end": 5, "addr": "0x2A", "sample": 5}
    ]


def test_axi_pairs_read_completion_and_write_response_by_id_and_exposes_beats():
    t = synchronous([
        {"AWVALID": 1, "AWREADY": 1, "AWADDR": 21, "AWID": 1,
         "ARVALID": 1, "ARREADY": 1, "ARADDR": 16, "ARID": 2},
        {"WVALID": 1, "WREADY": 0, "WDATA": 55,
         "ARVALID": 1, "ARREADY": 1, "ARADDR": 72, "ARID": 3},
        {"WVALID": 1, "WREADY": 1, "WDATA": 55, "WLAST": 1,
         "RVALID": 1, "RREADY": 1, "RID": 3, "RLAST": 0},
        {"BVALID": 1, "BREADY": 1, "BID": 1,
         "RVALID": 1, "RREADY": 1, "RID": 3, "RLAST": 1},
        {"RVALID": 1, "RREADY": 1, "RID": 2, "RLAST": 1},
        {"RVALID": 1, "RREADY": 1, "RID": 0, "RLAST": 1},
    ], {**{f"{ch}{edge}": 1 for ch in ("AW", "W", "B", "AR", "R")
           for edge in ("VALID", "READY")},
        "AWADDR": 8, "ARADDR": 8, "AWID": 2, "BID": 2, "ARID": 2,
        "RID": 2, "WLAST": 1, "RLAST": 1, "WDATA": 8})
    report = decode(t, "AXI4", "tb.dut.", "tb.dut.clk")
    assert report["lanes"] == ["AW", "W", "B", "AR", "R"]
    assert next(e for e in report["events"] if e["lane"] == "W")["wait"] == 1
    assert [(r["id"], r["addr"], r["start"], r["end"]) for r in report["transactions"]] == [
        ("0x1", "0x15", 1, 7), ("0x3", "0x48", 3, 7), ("0x2", "0x10", 1, 9)]
    assert report["unpaired_responses"] == 1


def test_axi_lite_without_ids_and_reset_does_not_pair_across_reset():
    t = synchronous([
        {"ARVALID": 1, "ARREADY": 1, "ARADDR": 2, "ARESETn": 1},
        {},
        {"RVALID": 1, "RREADY": 1, "ARESETn": 1},
        {"ARVALID": 1, "ARREADY": 1, "ARADDR": 6, "ARESETn": 1},
        {"RVALID": 1, "RREADY": 1, "ARESETn": 1},
    ], {"ARVALID": 1, "ARREADY": 1, "ARADDR": 8, "RVALID": 1, "RREADY": 1, "ARESETn": 1})
    report = decode(t, "AXI4-Lite", "tb.dut.", "tb.dut.clk")
    assert report["reset_edges"] == 1
    assert report["missing_lanes"] == ["AW", "W", "B"]
    assert report["unpaired_responses"] == 1
    assert report["transactions"][0]["addr"] == "0x06"


VCD = """$date
  Test fixture
$end
$version
  Test fixture
$end
$timescale
  1ns
$end
$scope module tb $end
$var wire 1 ! clk $end
$var wire 2 # q [1:0] $end
$upscope $end
$enddefinitions $end
#0
$dumpvars
0!
bzz #
$end
#5
1!
b10 #
#10
0!
bxx #
"""


@pytest.mark.skipif(not shutil.which("fst2vcd") or not shutil.which("vcd2fst"),
                    reason="requires GTKWave FST conversion tools")
def test_fst_round_trip_has_source_hash_fs_and_four_state_values(tmp_path):
    (tmp_path / "waves").mkdir()
    vcd = tmp_path / "waves" / "demo.vcd"
    fst = vcd.with_suffix(".fst")
    vcd.write_text(VCD)
    subprocess.run(["vcd2fst", "-v", str(vcd), "-f", str(fst)], check=True, timeout=15)
    assert "waves/demo.fst" in list_evidence(tmp_path)["fst_waveforms"]
    a, b = waveform(tmp_path, "waves/demo.vcd"), waveform(tmp_path, "waves/demo.fst")
    assert b["source_format"] == "fst"
    assert b["timescale"] == "1ns"
    assert b["source_sha256"] == hashlib.sha256(fst.read_bytes()).hexdigest()
    assert b["times"] == a["times"]
    assert b["signals"] == a["signals"]
    assert all(row["first"] is None for row in compare(a, b)["rows"])
    payload = wave_drom(b, [b["signals"][1]], 0, 2)
    assert payload["wengold"]["kind"] == "observed_fst"
    assert payload["head"]["text"] == "Observed FST waveform"


def test_fst_missing_timeout_and_output_cap(tmp_path, monkeypatch):
    import wengold.fst as module
    input_ = tmp_path / "capture.fst"
    input_.touch()
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="fst2vcd on PATH"):
        to_vcd(input_, 16)
    script = tmp_path / "decoder"
    script.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write('x' * 1024)\n")
    script.chmod(0o755)
    monkeypatch.setattr(module.shutil, "which", lambda _: str(script))
    with pytest.raises(ValueError, match="viewer limit"):
        to_vcd(input_, 16)
    script.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(45)\n")
    with pytest.raises(ValueError, match="timed out"):
        to_vcd(input_, 16, timeout=.1)


def test_ambiguous_axi_edge_does_not_pair_a_later_response_to_the_wrong_address():
    t = synchronous([
        {"ARVALID": 1, "ARREADY": 1, "ARADDR": 2},
        {"ARVALID": 1, "ARREADY": 0, "edge_ARREADY": 1},
        {"RVALID": 1, "RREADY": 1},
    ], {"ARVALID": 1, "ARREADY": 1, "ARADDR": 8, "RVALID": 1, "RREADY": 1})
    report = decode(t, "AXI4-Lite", "tb.dut.", "tb.dut.clk")
    assert report["skipped_control"] == 1
    assert report["transactions"] == []
    assert report["unpaired_responses"] == 1
    assert report["pairing_uncertain"] == ["read"]


@pytest.mark.skipif(not shutil.which("xezim"), reason="requires Xezim with VCD support")
def test_xezim_axi_lite_capture_decodes_read_latency(tmp_path):
    (tmp_path / "waves").mkdir()
    (tmp_path / "tb.sv").write_text("""`timescale 1ns/1ns
module tb;
  logic ACLK=0, ARESETn=0;
  logic ARVALID=0, ARREADY=0, RVALID=0, RREADY=0;
  logic [7:0] ARADDR=0, RDATA=0;
  logic [1:0] RRESP=0;
  always #5 ACLK = ~ACLK;
  initial begin
    $dumpfile("waves/axi.vcd");
    $dumpvars(0,tb);
    #10; ARESETn=1; ARVALID=1; ARREADY=0; ARADDR='h2a;
    #10; ARREADY=1;
    #10; ARVALID=0; RVALID=1; RREADY=1; RDATA='h5b;
    #10; RVALID=0;
    #1; $finish;
  end
endmodule
""")
    subprocess.run(["xezim", "--wave", "-s", "tb", "tb.sv"], cwd=tmp_path,
                   capture_output=True, check=True, timeout=15)
    report = decode(waveform(tmp_path, "waves/axi.vcd"), "AXI4-Lite", "tb.")
    assert [(event["lane"], event["tick"], event["wait"])
            for event in report["events"]] == [("AR", 25, 1), ("R", 35, 0)]
    assert report["events"][1]["fields"]["RDATA"] == "0x5B"
    assert report["transactions"][0]["addr"] == "0x2A"
    assert report["transactions"][0]["end"] - report["transactions"][0]["start"] == 10
