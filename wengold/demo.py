"""Bundled walkthrough: a small SoC, one security bug, and the kernel's answer.

Run:  python -m wengold.demo
"""
from __future__ import annotations

import os

from .agents.orchestrator import Orchestrator
from .graph.builder import GraphBuilder
from .kernel.minimize import minimum_new_evidence
from .kernel.validity import Result, classify_all
from .ledger.store import Ledger
from .tools.adapters.cocotb import CocotbAdapter
from .tools.outcome import Outcome, ToolOutcome

COLOR = {"valid": "\033[32m", "invalidated": "\033[31m", "unknown": "\033[33m"}
RESET = "\033[0m"
LEDGER_PATH = "/tmp/wengold-demo-ledger.tof"


def build_graph():
    b = GraphBuilder()
    b.add_rtl("soc_top", "rtl/soc_top.sv", "module soc_top; endmodule",
              clocks=["clk"], resets=["rst_n"])
    b.add_rtl("dma", "rtl/dma.sv", "module dma; endmodule")
    b.add_rtl("sec_firewall", "rtl/sec_firewall.sv", "module sec_firewall; endmodule")
    b.add_rtl("npu", "rtl/npu.sv", "module npu; endmodule")
    b.instantiate("soc_top", "dma")
    b.instantiate("soc_top", "sec_firewall")
    b.instantiate("soc_top", "npu")
    b.add_test("soc_smoke", verifies=["soc_top"])
    b.add_test("sec_acl_test", verifies=["sec_firewall"], covers=["cov.sec_acl"])
    b.add_test("dma_key_test", verifies=["dma", "sec_firewall"])
    b.add_test("npu_conv_test", verifies=["npu"])
    b.add_assertion("a_secure_bit", on="sec_firewall")
    return b.build()


def prior_results() -> list[Result]:
    return [
        Result("soc_smoke", "sim", depends_on={"soc_top"}),
        Result("sec_acl_test", "sim", depends_on={"sec_firewall"}),
        Result("dma_key_test", "sim", depends_on={"dma", "sec_firewall"}),
        Result("npu_conv_test", "sim", depends_on={"npu"}),
        Result("a_secure_bit", "formal", depends_on={"sec_firewall"}),
        # a result with no recorded dependencies — the kernel refuses to call it valid
        Result("legacy_cov", "coverage", depends_on=set()),
    ]


def _dry_runner(workdir: str):
    """A runner for the walkthrough: sim runs dry, formal has no engine installed."""
    cocotb = CocotbAdapter()

    def run(result_id: str, kind: str) -> Outcome:
        if kind in ("sim", "coverage"):
            return cocotb.run(workdir=workdir, toplevel=result_id, dry_run=True, tests=1)
        return Outcome(kind, "run", ToolOutcome.TOOL_MISSING)

    return run


def main() -> None:
    graph = build_graph()
    if os.path.exists(LEDGER_PATH):
        os.remove(LEDGER_PATH)
    ledger = Ledger(LEDGER_PATH)
    prior = prior_results()

    print("WENGOLD demo — small inference SoC, one-line security bug in r2\n")
    comp = graph.completeness()
    print(f"graph completeness: complete={comp['complete']}  "
          f"unresolved={len(comp['unresolved'])}\n")

    print("r1 -> r2: rtl/sec_firewall.sv changed (protection bit read backwards)\n")
    changed = {"sec_firewall"}

    classes = classify_all(graph, prior, changed)
    for c in classes:
        col = COLOR[c.verdict.value]
        print(f"  {col}{c.verdict.value:>12}{RESET}  {c.result.id:<14} {c.reason}")

    todo = minimum_new_evidence(graph, classes)
    kept = sorted({c.result.id for c in classes if c.verdict.value == "valid"})
    print(f"\n  minimum new evidence: {todo}")
    print(f"  kept from r1:         {kept}")

    # a result derived from a rerun result is stale too — propagation
    prior[3].depends_on_results = {"sec_acl_test"}   # npu summary consumes the acl result
    todo2 = minimum_new_evidence(graph, classes)
    print(f"  with result propagation: {todo2}")

    print("\n  running the verification loop ...")
    orch = Orchestrator(graph, ledger, workdir="/tmp/wengold-demo-run")
    report = orch.run_loop(changed, prior, runner=_dry_runner("/tmp/wengold-demo-run"))
    print(f"    iterations: {len(report['iterations'])}")
    print(f"    rerun:      {report['rerun']}")
    print(f"    settled:    {report['settled']}")
    if report["unsettled"]:
        print(f"    unsettled:  {report['unsettled']}  (no engine installed — reported, not assumed)")

    cp = ledger.checkpoint()
    audit = ledger.audit(checkpoint=True)
    print(f"\n  ledger: {audit.count} entries, chain ok={audit.ok}, "
          f"checkpoint={audit.checkpoint_status} (head {cp['hash'][:12]}…)")


if __name__ == "__main__":
    main()
