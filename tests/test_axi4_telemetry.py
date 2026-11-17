"""AXI4 traffic reconstruction tests using captured, clocked signal values."""
import pytest

from wengold.axi4_telemetry import decode_axi4, discover_axi4_signal_map


REQUIRED = (
    "AWVALID", "AWREADY", "AWADDR", "AWID", "AWLEN",
    "WVALID", "WREADY", "WDATA", "WLAST",
    "BVALID", "BREADY", "BID", "BRESP",
    "ARVALID", "ARREADY", "ARADDR", "ARID", "ARLEN",
    "RVALID", "RREADY", "RID", "RDATA", "RLAST", "RRESP",
)


def make_wave(cycles, events, *, prefix="tb.dut.axi"):
    current_defaults = {name: 0 for name in REQUIRED}
    current_defaults["ARESETn"] = 1
    current_defaults["AWBURST"] = 1
    current_defaults["ARBURST"] = 1
    signal_values = {name: [] for name in current_defaults}
    clock_values = []
    for cycle in range(cycles):
        row = dict(current_defaults)
        row.update(events.get(cycle, {}))
        for name in signal_values:
            signal_values[name].extend([row[name], row[name]])
        clock_values.extend([0, 1])
    signals = [{
        "name": f"{prefix}.{name.lower()}",
        "width": 64 if name in {"AWADDR", "ARADDR", "WDATA", "RDATA"} else 8,
        "values": vals,
    } for name, vals in signal_values.items()]
    signals.append({"name": "tb.dut.aclk", "width": 1, "values": clock_values})
    return {
        "source": "axi4-test.vcd",
        "clock": "tb.dut.aclk",
        "times": list(range(cycles * 2)),
        "cycles": cycles * 2,
        "signals": signals,
    }


def signal_map_for(wave):
    return {
        name: f"tb.dut.axi.{name.lower()}"
        for name in REQUIRED + ("ARESETn", "AWBURST", "ARBURST")
    }


def test_axi4_decodes_write_read_ids_and_two_write_beats_with_stall():
    wave = make_wave(8, {
        0: {"AWVALID": 1, "AWREADY": 0, "AWID": 3,
            "AWADDR": 0x1000, "AWLEN": 1},
        1: {"AWVALID": 1, "AWREADY": 0, "AWID": 3,
            "AWADDR": 0x1000, "AWLEN": 1},
        2: {"AWVALID": 1, "AWREADY": 1, "AWID": 3,
            "AWADDR": 0x1000, "AWLEN": 1},
        3: {"WVALID": 1, "WREADY": 1, "WDATA": 0xAA, "WLAST": 0},
        4: {"WVALID": 1, "WREADY": 1, "WDATA": 0xBB, "WLAST": 1},
        5: {"BVALID": 1, "BREADY": 1, "BID": 3, "BRESP": 0},
        6: {"ARVALID": 1, "ARREADY": 1, "ARID": 5,
            "ARADDR": 0x2000, "ARLEN": 0},
        7: {"RVALID": 1, "RREADY": 1, "RID": 5,
            "RDATA": 0x1234, "RRESP": 0, "RLAST": 1},
    })
    result = decode_axi4(wave, signal_map=signal_map_for(wave),
                         max_stall_cycles=2)

    assert result["status"] == "decoded_with_issues"
    assert result["sampled_rising_edges"] == 8
    assert len(result["transactions"]) == 2
    write, read = result["transactions"]
    assert (write["operation"], write["transaction_id"], write["address"]) == (
        "write", "3", "0x1000")
    assert write["beats"] == write["expected_beats"] == 2
    assert write["response"] == "OKAY"
    assert write["status"] == "ok"
    assert write["attributes"]["first_data"] == "0xaa"
    assert write["attributes"]["last_data"] == "0xbb"
    assert (read["operation"], read["transaction_id"], read["address"]) == (
        "read", "5", "0x2000")
    assert read["beats"] == read["expected_beats"] == 1
    assert read["response"] == "OKAY"
    assert result["metrics"]["aw_stall_cycles"] == 2
    assert result["metrics"]["aw_stall_events"] == 1
    assert result["metrics"]["transactions"] == 2
    assert result["metrics"]["protocol_errors"] == 0
    finding = next(f for f in result["findings"]
                   if f["rule"] == "axi4_aw_backpressure")
    assert finding["severity"] == "warning"
    assert finding["details"]["stall_cycles"] == 2


def test_axi4_flags_early_wlast_and_write_response_error():
    wave = make_wave(3, {
        0: {"AWVALID": 1, "AWREADY": 1, "AWID": 1,
            "AWADDR": 0x80, "AWLEN": 1},
        1: {"WVALID": 1, "WREADY": 1, "WDATA": 0x55, "WLAST": 1},
        2: {"BVALID": 1, "BREADY": 1, "BID": 1, "BRESP": 2},
    })
    result = decode_axi4(wave, signal_map=signal_map_for(wave))
    rules = {f["rule"] for f in result["findings"]}
    assert "early_wlast" in rules
    assert "write_response_error" in rules
    assert result["transactions"][0]["status"] == "error"
    assert result["transactions"][0]["response"] == "SLVERR"


def test_axi4_flags_orphan_write_and_read_beats():
    wave = make_wave(2, {
        0: {"WVALID": 1, "WREADY": 1, "WDATA": 0xAB, "WLAST": 1},
        1: {"RVALID": 1, "RREADY": 1, "RID": 7,
            "RDATA": 0x99, "RRESP": 0, "RLAST": 1},
    })
    result = decode_axi4(wave, signal_map=signal_map_for(wave))
    rules = {f["rule"] for f in result["findings"]}
    assert "orphan_w_beat" in rules
    assert "orphan_r_beat" in rules
    assert result["transactions"] == []


def test_axi4_reset_aborts_open_transaction_without_fabricating_completion():
    wave = make_wave(3, {
        0: {"AWVALID": 1, "AWREADY": 1, "AWID": 2,
            "AWADDR": 0x3000, "AWLEN": 3},
        1: {"ARESETn": 0},
        2: {"ARESETn": 1},
    })
    result = decode_axi4(wave, signal_map=signal_map_for(wave))
    assert result["transactions"] == []
    assert result["metrics"]["reset_cycles"] == 1
    assert any(f["rule"] == "reset_aborted_transaction"
               for f in result["findings"])


def test_axi4_unknown_control_is_never_treated_as_a_handshake():
    wave = make_wave(2, {
        0: {"AWVALID": "x", "AWREADY": 1, "AWID": 1,
            "AWADDR": 0x10, "AWLEN": 0},
    })
    result = decode_axi4(wave, signal_map=signal_map_for(wave))
    assert result["transactions"] == []
    assert result["metrics"]["unknown_handshake_controls"] >= 1
    assert any(f["rule"] == "unknown_handshake_control"
               for f in result["findings"])


def test_axi4_missing_required_signal_is_a_clear_error():
    wave = make_wave(1, {})
    wave["signals"] = [s for s in wave["signals"]
                       if not s["name"].endswith(".awlen")]
    with pytest.raises(ValueError, match="AWLEN"):
        decode_axi4(wave, prefix="tb.dut.axi")


def test_axi4_interface_prefix_discovery_supports_flattened_names():
    wave = make_wave(1, {})
    for signal in wave["signals"]:
        if signal["name"] != "tb.dut.aclk":
            leaf = signal["name"].rsplit(".", 1)[-1]
            signal["name"] = "tb.dut.m_axi_" + leaf
    mapping = discover_axi4_signal_map(wave, prefix="tb.dut.m_axi")
    assert mapping["AWVALID"] == "tb.dut.m_axi_awvalid"
    assert mapping["RREADY"] == "tb.dut.m_axi_rready"


def test_axi4_ambiguous_interface_requires_explicit_selection():
    wave = make_wave(1, {})
    duplicate = []
    for signal in wave["signals"]:
        if signal["name"] == "tb.dut.aclk":
            continue
        copied = dict(signal)
        copied["name"] = copied["name"].replace("tb.dut.axi.", "tb.dut.s_axi.")
        duplicate.append(copied)
    wave["signals"].extend(duplicate)
    with pytest.raises(ValueError, match="ambiguous"):
        decode_axi4(wave)



def test_axi4_late_wlast_and_burst_overrun_are_reported():
    wave = make_wave(4, {
        0: {"AWVALID": 1, "AWREADY": 1, "AWID": 4,
            "AWADDR": 0x400, "AWLEN": 0},
        1: {"WVALID": 1, "WREADY": 1, "WDATA": 0x1, "WLAST": 0},
        2: {"WVALID": 1, "WREADY": 1, "WDATA": 0x2, "WLAST": 1},
        3: {"BVALID": 1, "BREADY": 1, "BID": 4, "BRESP": 0},
    })
    result = decode_axi4(wave, signal_map=signal_map_for(wave))
    rules = {f["rule"] for f in result["findings"]}
    assert "missing_wlast" in rules
    assert "write_burst_overrun" in rules
    assert "late_wlast" in rules


def test_axi4_late_rlast_is_reported_against_arlen():
    wave = make_wave(4, {
        0: {"ARVALID": 1, "ARREADY": 1, "ARID": 9,
            "ARADDR": 0x900, "ARLEN": 0},
        1: {"RVALID": 1, "RREADY": 1, "RID": 9,
            "RDATA": 0x10, "RRESP": 0, "RLAST": 0},
        2: {"RVALID": 1, "RREADY": 1, "RID": 9,
            "RDATA": 0x11, "RRESP": 0, "RLAST": 1},
    })
    result = decode_axi4(wave, signal_map=signal_map_for(wave))
    rules = {f["rule"] for f in result["findings"]}
    assert "missing_rlast" in rules
    assert "read_burst_overrun" in rules
    assert "late_rlast" in rules
