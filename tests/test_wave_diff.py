"""PASS-versus-FAIL VCD differential comparison tests."""
import pytest

from wengold.wave_diff import compare_waveforms


def wave(times, values, scale="1"):
    return {
        "source": "vcd", "cycles": len(times), "times": times,
        "time_unit_ns": scale, "time_unit_label": "ns",
        "signals": [
            {"name": "tb.dut.clk", "width": 1, "values": [0, 1, 0, 1][:len(times)]},
            {"name": "tb.dut.count", "width": 4, "values": values},
        ],
    }


def test_identical_pass_and_fail_captures_have_no_differences():
    report = compare_waveforms(wave([0, 5, 10], [0, 1, 2]),
                               wave([0, 5, 10], [0, 1, 2]))
    assert report["status"] == "identical_on_common_signals"
    assert report["total_differences"] == 0
    assert report["first_divergence"] is None


def test_reports_first_divergence_and_per_signal_difference_counts():
    report = compare_waveforms(wave([0, 5, 10, 15], [0, 1, 2, 3]),
                               wave([0, 5, 10, 15], [0, 1, 7, 7]))
    assert report["status"] == "different"
    assert report["first_divergence"]["signal"] == "tb.dut.count"
    assert report["first_divergence"]["time_ns"] == "10"
    assert report["first_divergence"]["pass"] == 2
    assert report["first_divergence"]["fail"] == 7
    assert report["per_signal"][0]["differences"] == 2


def test_aligns_different_timescales_in_physical_nanoseconds():
    passed = wave([0, 5, 10], [0, 1, 2], scale="1")
    failed = wave([0, 5000, 10000], [0, 1, 9], scale="0.001")
    report = compare_waveforms(passed, failed)
    assert report["first_divergence"]["time_ns"] == "10"
    assert report["first_divergence"]["pass"] == 2
    assert report["first_divergence"]["fail"] == 9


def test_reports_unknown_vs_known_without_hiding_it():
    report = compare_waveforms(wave([0, 5], [0, None]),
                               wave([0, 5], [0, 1]))
    assert report["unknown_differences"] == 1
    assert report["differences"][0]["kind"] == "unknown_vs_known"


def test_reports_signals_present_in_only_one_capture():
    passed = wave([0, 5], [0, 1])
    failed = wave([0, 5], [0, 1])
    failed["signals"].append({"name": "tb.dut.extra", "width": 1, "values": [0, 0]})
    report = compare_waveforms(passed, failed)
    assert report["fail_only_signals"] == ["tb.dut.extra"]


def test_rejects_no_shared_signal_names_and_nonoverlapping_capture():
    passed = wave([0, 5], [0, 1])
    failed = wave([0, 5], [0, 1])
    failed["signals"] = [{"name": "other.count", "width": 4, "values": [0, 1]}]
    with pytest.raises(ValueError, match="no matching"):
        compare_waveforms(passed, failed)
    failed["signals"] = passed["signals"]
    failed["times"] = [100, 105]
    with pytest.raises(ValueError, match="overlapping"):
        compare_waveforms(passed, failed)


def test_caps_reported_differences_without_losing_total_count():
    passed = wave([0, 5, 10, 15], [0, 0, 0, 0])
    failed = wave([0, 5, 10, 15], [1, 1, 1, 1])
    report = compare_waveforms(passed, failed, max_differences=2)
    assert report["total_differences"] == 4
    assert report["reported_differences"] == 2
    assert report["truncated"] is True
