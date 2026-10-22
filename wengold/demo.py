"""Bundled walkthrough: a small SoC, one security bug, and the kernel's answer.

Run:  python -m wengold.demo
"""
from __future__ import annotations

import os

from .agents.orchestrator import Orchestrator
from .graph.builder import GraphBuilder
from .kernel import invariants
from .kernel.contract import (Acceptance, Assumptions, Contract, Establishes,
                              Execution, Limits, Method, MethodKind, Scope)
from .kernel.minimize import minimum_new_evidence
from .kernel.reuse import decide, verify_decision
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
        Result("legacy_cov", "coverage", depends_on=set()),
    ]


def _dry_runner(workdir: str):
    cocotb = CocotbAdapter()

    def run(result_id: str, kind: str) -> Outcome:
        if kind in ("sim", "coverage"):
            return cocotb.run(workdir=workdir, toplevel=result_id, dry_run=True, tests=1)
        return Outcome(kind, "run", ToolOutcome.TOOL_MISSING)

    return run


def _firewall_contract() -> Contract:
    return Contract(
        claim="The secure key store is never written by a non-secure transaction.",
        scope=Scope.make(files=["rtl/sec_firewall.sv"], config={"KEYS": 2},
                         reset="async active-low"),
        method=Method.make(MethodKind.PROOF, engine="sby",
                           settings={"mode": "prove", "depth": "unbounded"}),
        assumptions=Assumptions.make(
            ["axi_awvalid held until awready", "reset released before first access"],
            discharged=["axi_awvalid held until awready"]),
        limits=Limits.make(supported_config={"KEYS": [1, 2, 4]},
                           gaps=["key store ECC not modeled"]),
    )


def show_contract() -> None:
    """What a result establishes, and under what conditions it may be reused."""
    print("\n  result contract and the four questions\n")
    c = _firewall_contract()
    r = Result("sec_firewall_proof", "formal", depends_on={"sec_firewall"},
               contract=c, execution=Execution.PASSED,
               establishes=Establishes.PROOF, acceptance=Acceptance.ACCEPTED)

    print(f"    claim       {c.claim}")
    print(f"    scope       files={list(c.scope.files)} config={c.config()} reset={c.scope.reset}")
    print(f"    method      {c.method.kind.value} via {c.method.engine} {dict(c.method.settings)}")
    print(f"    assumptions {list(c.assumptions.items)}")
    print(f"    evidence    fingerprints={dict(c.evidence.fingerprints)} "
          f"status={c.evidence.proof_status}")
    print(f"    limits      config={dict(c.limits.supported_config)} gaps={list(c.limits.gaps)}")
    print(f"    questions   execution={r.execution.value}  establishes={r.establishes.value}"
          f"  acceptance={r.acceptance.value}  currency=<computed>")

    graph = build_graph()
    d = decide(graph, r, {"sec_firewall"}, results=[r],
               required=Establishes.PROOF, require_contract=True)
    print(f"\n    reuse?      reusable={d.reusable}  currency={d.currency.value}")
    print(f"    unmet       {d.unmet() or 'none'}")
    rec = d.record(r, Establishes.PROOF).as_dict()
    ok, issues = verify_decision(rec)
    print(f"    decision record independently checked: ok={ok} {issues or ''}")

    # a waiver must not become a technical pass
    w = Result("sec_firewall_proof", "formal", depends_on={"sec_firewall"},
               contract=c, execution=Execution.PASSED,
               establishes=Establishes.PROOF, acceptance=Acceptance.WAIVED)
    dw = decide(graph, w, {"sec_firewall"}, results=[w], required=Establishes.PROOF)
    print(f"    waived:     reusable={dw.reusable} accepted_for_use={dw.accepted_for_use}"
          f"  ({dw.reason})")


def show_formal() -> None:
    """The formal loop: prove, find a counterexample, repair, prove again."""
    from .formal import Property, prove as formal_prove

    good = (
        "module counter (input logic clk, input logic rst_n, input logic en);\n"
        "    parameter MAX = 4;\n"
        "    logic [2:0] count;\n"
        "    always_ff @(posedge clk) begin\n"
        "        if (!rst_n) count <= 0;\n"
        "        else if (en) count <= (count == MAX) ? 0 : count + 1;\n"
        "    end\nendmodule\n")
    bad = good.replace("else if (en) count <= (count == MAX) ? 0 : count + 1;",
                       "else if (en) count <= count + 1;")
    prop = Property.safety("bound", "count <= MAX", clock="clk")

    print("\n  formal verification loop\n")
    r = formal_prove(good, [prop], engine="explicit")["results"][0]
    print(f"    counter.sv      {r.status:>8}  {r.detail}")
    r = formal_prove(bad, [prop], engine="explicit")["results"][0]
    print(f"    counter_bad.sv  {r.status:>8}  {r.detail}")
    steps = len(r.trace) if r.trace else 0
    print(f"    counterexample length: {steps} step(s)")

    def repair(text, failure):
        return text.replace("else if (en) count <= count + 1;",
                            "else if (en) count <= (count == MAX) ? 0 : count + 1;")

    out = formal_prove(bad, [prop], engine="explicit", repair=repair, budget=3)
    print(f"    after repair    {out['results'][0].status:>8}  "
          f"(attempts {len(out['iterations'])}, repaired={out['repaired']})")
    c = out["contracts"][0]
    print(f"    contract        {c.claim}")
    print(f"                    method={c.method.kind.value} "
          f"status={c.evidence.proof_status} gaps={list(c.limits.gaps)}")


def show_frontends() -> None:
    """Register-map and clock-domain-crossing front-ends."""
    from .graph.cdc import analyse as cdc_analyse
    from .graph.regmap import parse_rdl

    print("\n  front-ends\n")
    rdl = ("addrmap sec_ctrl {\n"
           "    reg { field { sw=rw; hw=r; } EN[0:0] = 0;"
           " field { sw=r; hw=w; } STATE[3:1]; } ctrl @ 0x0;\n"
           "    reg { field { sw=rw; hw=r; } KEY[31:0] = 0; } key @ 0x100;\n"
           "};\n")
    amap = parse_rdl(rdl)
    print(f"    regmap  {amap.name}: " + ", ".join(
        f"{r.name}@{hex(r.address)}({[f.name for f in r.fields]})"
        for r in amap.registers))
    rtl = ("module mixed_clocks (input logic clk_a, input logic clk_b, input logic d_in);\n"
           "    logic [7:0] a_reg, b_reg, comb;\n"
           "    always_ff @(posedge clk_a) begin a_reg <= d_in; end\n"
           "    always_ff @(posedge clk_b) begin b_reg <= a_reg; end\n"
           "    assign comb = a_reg + 1;\nendmodule\n")
    rep = cdc_analyse(rtl, "mixed_clocks")
    print(f"    cdc     domains={rep.domains}")
    for c in rep.crossings:
        print(f"            crossing {c.signal}: {c.from_domain} -> {c.to_domain} ({c.kind})")
    if rep.unresolved:
        print(f"            unresolved: {rep.unresolved} (module marked unresolved)")


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

    prior[3].depends_on_results = {"sec_acl_test"}
    print(f"  with result propagation: {minimum_new_evidence(graph, classes)}")

    print("\n  running the verification loop ...")
    orch = Orchestrator(graph, ledger, workdir="/tmp/wengold-demo-run")
    report = orch.run_loop(changed, prior, runner=_dry_runner("/tmp/wengold-demo-run"))
    print(f"    iterations: {len(report['iterations'])}")
    print(f"    rerun:      {report['rerun']}")
    print(f"    settled:    {report['settled']}")
    if report["unsettled"]:
        print(f"    unsettled:  {report['unsettled']}  (no engine installed — reported, not assumed)")

    show_contract()
    show_formal()
    show_frontends()

    print("\n  self-verification of the invalidation logic ...")
    violations = invariants.fuzz(range(120), n_nodes=9, n_edges=16)
    print(f"    invariants + reference cross-check over 120 generated graphs: "
          f"{len(violations)} violation(s)")

    cp = ledger.checkpoint()
    audit = ledger.audit(checkpoint=True)
    print(f"\n  ledger: {audit.count} entries, chain ok={audit.ok}, "
          f"checkpoint={audit.checkpoint_status} (head {cp['hash'][:12]}…)")


if __name__ == "__main__":
    main()
