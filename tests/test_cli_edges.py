"""CLI edge cases found by exercising every command.

Two were real: a property naming a signal the file does not define raised an
unhandled `UnsupportedConstruct` traceback, and `--results` pointed at a directory
raised `IsADirectoryError`. Both are user errors and should read like user errors.

The third was a doc/code mismatch: the README advertised `wengold learn waveform`
and the CLI had no such task.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


def run(*args):
    return subprocess.run([sys.executable, "-m", "wengold.cli", *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)


def test_a_bad_signal_name_is_a_message_not_a_traceback():
    r = run("formal", str(EX / "formal" / "counter.sv"), "--property", "q == 0")
    assert "Traceback" not in r.stderr, r.stderr[-400:]
    assert "cannot prove" in r.stdout
    assert r.returncode == 2


def test_a_directory_where_a_results_file_belongs_is_a_message():
    r = run("classify", str(EX), "--changed", "dma", "--results", str(EX))
    assert "Traceback" not in r.stderr, r.stderr[-400:]
    assert "expects a JSON file" in r.stdout
    assert r.returncode == 2


def test_learn_waveform_exists_because_the_readme_says_it_does():
    """A documented command must be a real command."""
    readme = (ROOT / "README.md").read_text()
    if "learn waveform" not in readme:
        pytest.skip("the README no longer advertises it")
    r = run("learn", "waveform", "--help")
    assert "invalid choice" not in r.stderr, r.stderr[:300]


def test_learn_waveform_reads_a_vcd(tmp_path):
    vcd = tmp_path / "t.vcd"
    vcd.write_text(
        "$timescale 1ns $end\n$scope module tb $end\n"
        "$var wire 1 ! clk $end\n$var reg 4 $ d [3:0] $end\n$upscope $end\n"
        "$enddefinitions $end\n#0\n0!\nb0000 $\n#5\n1!\nb0001 $\n"
        "#10\n0!\nb0010 $\n")
    r = run("learn", "waveform", str(vcd), "--show", "3")
    assert r.returncode == 0, r.stderr[-300:]
    assert "signal" in r.stdout and "toggles" in r.stdout
    assert "tb.clk" in r.stdout


def test_learn_waveform_refuses_a_non_vcd():
    r = run("learn", "waveform", str(EX))
    assert r.returncode == 2
    assert "expects a .vcd" in r.stdout


def test_cdc_exits_one_when_it_finds_a_crossing():
    """Not a failure: a nonzero exit means 'there are crossings', the way grep
    means 'there are matches'. Documented here so nobody 'fixes' it."""
    r = run("cdc", str(EX / "cdc" / "mixed_clocks.sv"))
    assert r.returncode == 1
    assert "crossing" in r.stdout
