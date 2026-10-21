"""Evidence must be bound to the exact inputs, run and environment."""
from wengold.ledger.evidence import make_evidence
from wengold.ledger.repro import DesignInputs, RunSpec, digest_text, repro_hash


def _inputs(tmp_path, text="module a; endmodule\n"):
    p = tmp_path / "a.sv"
    p.write_text(text)
    return DesignInputs.from_files(rtl=[str(p)])


def test_repro_is_stable_for_same_inputs():
    run = RunSpec(tool="verilator", argv=("--lint-only",), seed=1)
    inp = DesignInputs(rtl=(("a.sv", "sha256:abc"),))
    assert repro_hash(inp, run) == repro_hash(inp, run)


def test_repro_changes_with_rtl_content(tmp_path):
    run = RunSpec(tool="verilator")
    a = _inputs(tmp_path, "module a; endmodule\n")
    b = _inputs(tmp_path, "module a; wire x; endmodule\n")
    assert a.digest() != b.digest()
    assert repro_hash(a, run) != repro_hash(b, run)


def test_repro_changes_with_seed_and_args():
    inp = DesignInputs(rtl=(("a.sv", "sha256:abc"),))
    r1 = RunSpec(tool="cocotb", seed=1)
    r2 = RunSpec(tool="cocotb", seed=2)
    r3 = RunSpec(tool="cocotb", seed=1, argv=("-f", "Makefile"))
    assert repro_hash(inp, r1) != repro_hash(inp, r2)
    assert repro_hash(inp, r1) != repro_hash(inp, r3)


def test_evidence_records_binding_and_recheck(tmp_path):
    inp = _inputs(tmp_path)
    run = RunSpec(tool="cocotb", seed=7)
    ev = make_evidence("sim:pass", "cocotb", artifact_text="all good",
                       inputs=inp, run=run, artifact="results.xml")
    assert ev.digest == digest_text("all good")
    assert ev.repro
    assert ev.is_reproducible(inp, run)
    # a different run no longer matches this evidence
    assert not ev.is_reproducible(inp, RunSpec(tool="cocotb", seed=8))
    assert ev.as_dict()["run"]["seed"] == 7
