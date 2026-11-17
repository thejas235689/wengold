import pytest

from wengold.wave import parse_vcd
from wengold.wave_inspect import nearest_sample, next_change, render_value, time_label, wave_drom


TRACE = """$timescale
  10 ps
$end
$scope module tb $end
$var wire 1 ! valid $end
$var wire 4 " bus [3:0] $end
$scope module dut $end
$var wire 1 ! valid $end
$var real 1 r analogue $end
$upscope $end $upscope $end
$enddefinitions $end
$dumpvars 0! bz " r1.5 r $end
#3 1! b1xz0 "
#3 z!
#9 x! b1111 "
#21 0!
"""


def test_parse_aliases_dumpvars_multiple_commands_and_four_state_bits():
    trace = parse_vcd(TRACE)
    assert trace["timescale"] == "10ps"
    assert trace["times"] == [0, 3, 9, 21]
    assert trace["unsupported_signals"] == 1
    by_name = {s["name"]: s for s in trace["signals"]}
    a = by_name["tb.valid"]
    b = by_name["tb.dut.valid"]
    assert a["logic_values"] == b["logic_values"] == ["0", "z", "x", "0"]
    assert a["values"] == [0, None, None, 0]
    bus = by_name["tb.bus"]
    assert bus["logic_values"] == ["zzzz", "1xz0", "1111", "1111"]
    assert render_value(bus, 1, "Hex") == "1XZ0"
    assert render_value(bus, 2, "Signed") == "-1"
    assert render_value(bus, 2, "Unsigned") == "15"
    assert render_value(bus, 2, "Binary") == "0b1111"
    assert render_value(a, 1, "Unsigned") == "Z"


def test_limits_and_real_time_navigation_are_explicit():
    trace = parse_vcd(TRACE, limit=2, signal_limit=1)
    assert trace["times"] == [0, 3]
    assert trace["samples_truncated"]
    assert trace["signals_omitted"] == 2
    assert not parse_vcd(TRACE, limit=4)["samples_truncated"]
    assert time_label(9, trace["timescale"]) == "90 ps"
    assert time_label(9, None) == "9 ticks"
    assert nearest_sample([0, 3, 9, 21], 6) == 1
    signal = parse_vcd(TRACE)["signals"][-1]
    assert next_change(signal, 1, 1) == 2  # Z -> X counts as a change
    assert next_change(signal, 3, -1) == 2
    assert next_change(signal, 0, -1) is None
    with pytest.raises(ValueError, match="backwards"):
        parse_vcd(TRACE.replace("#21", "#8"))


def test_irregular_vcd_export_is_proportional_and_keeps_source_and_endpoint():
    trace = parse_vcd(TRACE)
    trace.update(source="waves/actual.vcd", source_sha256="a" * 64)
    by_name = {s["name"]: s for s in trace["signals"]}
    result = wave_drom(trace, [by_name["tb.valid"], by_name["tb.bus"]], 3, 0)
    assert result["wengold"] == {
        "kind": "observed_vcd", "source": "waves/actual.vcd", "source_sha256": "a" * 64,
        "timescale": "10ps", "start_tick": 0, "end_tick": 21,
        "ticks_per_slot": 3, "samples_truncated": False,
    }
    assert result["signal"][0]["wave"] == "0z.x...0"
    assert result["signal"][1] == {"name": "tb.bus", "wave": "z=.=....", "data": ["1XZ0", "0xF"]}
    assert "30 ps" in result["foot"]["text"]
    assert "endpoint" in result["foot"]["text"]
    with pytest.raises(ValueError, match="8 slots"):
        wave_drom(trace, [by_name["tb.valid"]], 0, 3, max_slots=7)


def test_vcd_bit_selects_stay_distinct_and_oversized_signals_are_reported():
    trace = parse_vcd("""$var wire 1 ! q [3] $end
$var wire 1 # q [2] $end
$var wire 999999 % too_wide $end
$enddefinitions $end
#0
0! 1#
""")
    assert [s["name"] for s in trace["signals"]] == ["q[2]", "q[3]"]
    assert trace["unsupported_signals"] == 1
