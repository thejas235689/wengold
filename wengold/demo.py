"""Bundled walkthrough: a small SoC, one security bug, and the kernel's answer.

Run:  python -m wengold.demo
"""
from __future__ import annotations

from .graph.builder import GraphBuilder
from .kernel.validity import Result, classify_all
from .kernel.minimize import minimum_new_evidence
from .ledger.store import Ledger

COLOR = {"valid": "\033[32m", "invalidated": "\033[31m", "unknown": "\033[33m"}
RESET = "\033[0m"


def build_graph():
    b = GraphBuilder()
    b.add_rtl("soc_top", "rtl/soc_top.sv", "module soc_top; endmodule", clocks=["clk"], resets=["rst_n"])
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


def main() -> None:
    import os
    graph = build_graph()
    path = "/tmp/wengold-demo-ledger.tof"
    if os.path.exists(path):
        os.remove(path)
    ledger = Ledger(path)

    prior = [
        Result("soc_smoke", "sim", depends_on={"soc_top"}),
        Result("sec_acl_test", "sim", depends_on={"sec_firewall"}),
        Result("dma_key_test", "sim", depends_on={"dma", "sec_firewall"}),
        Result("npu_conv_test", "sim", depends_on={"npu"}),
        Result("a_secure_bit", "formal", depends_on={"sec_firewall"}),
    ]

    print("WENGOLD demo — small inference SoC, one-line security bug in r2\n")
    print("r1 -> r2: rtl/sec_firewall.sv changed (protection bit read backwards)\n")
    changed = {"sec_firewall"}

    classes = classify_all(graph, prior, changed)
    for c in classes:
        col = COLOR[c.verdict.value]
        print(f"  {col}{c.verdict.value:>12}{RESET}  {c.result.id:<14} {c.reason}")

    todo = minimum_new_evidence(graph, classes)
    print(f"\n  minimum new evidence: {todo}")
    print(f"  kept from r1:         "
          f"{sorted({c.result.id for c in classes if c.verdict.value == 'valid'})}")

    ledger.append("run", {"revision": "r2", "changed": sorted(changed)})
    for c in classes:
        ledger.append("verdict", {"result": c.result.id, "verdict": c.verdict.value})
    print(f"\n  ledger: {sum(1 for _ in ledger)} entries, chain verified = {ledger.verify()}")


if __name__ == "__main__":
    main()
