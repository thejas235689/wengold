"""02 · Formal, emulation and FPGA."""
from wengold.tools.registry import tools_in_group

GROUP = tools_in_group("formal")


def _by(key):
    return next(t for t in GROUP if t.key == key)


def test_open_formal_backend():
    assert _by("yosys").open_source
    assert _by("symbiyosys").open_source
    assert _by("z3").open_source


def test_commercial_formal_and_emulation():
    assert _by("jaspergold").role == "formal"
    assert _by("vcformal").role == "formal"
    assert _by("onespin").role == "formal"
    assert {_by(k).role for k in ("zebu", "palladium", "veloce")} == {"emulation"}


def test_fpga_and_regression():
    assert {_by(k).role for k in ("vivado", "quartus")} == {"fpga"}
    assert _by("vmanager").role == "regression"
