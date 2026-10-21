"""01 · Simulation, debug and testbench."""
from wengold.tools.registry import tools_in_group

GROUP = tools_in_group("simulation")


def _by(key):
    return next(t for t in GROUP if t.key == key)


def test_open_simulators_are_first_class():
    assert _by("verilator").open_source and _by("iverilog").open_source


def test_commercial_simulators_present_as_adapters():
    assert not _by("vcs").open_source
    assert not _by("xcelium").open_source
    assert not _by("questa").open_source


def test_debug_and_waveform_tools():
    for key in ("verdi", "simvision", "verisium", "gtkwave"):
        assert _by(key).role in {"debug", "waveform"}


def test_testbench_frameworks():
    assert _by("cocotb").role == "testbench"
    assert _by("uvm").role == "testbench"
