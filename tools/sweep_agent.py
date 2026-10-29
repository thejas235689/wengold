"""Run the agent over every fetched project, with real tools, and record it.

Writes one JSON line per project to /scratch/work/sweep.jsonl so a later step can
analyse it without re-running the tools.

Both runners are exercised on the same plan, because the interesting number is the
difference: `SimulatedRunner` settles whatever it is handed, `ToolRunner` settles
only what a tool actually established.
"""
import json
import os
import sys
import time
import traceback
from collections import Counter

sys.path.insert(0, "/scratch/repos/wengold")

from wengold.agent.loop import Agent, SimulatedRunner
from wengold.agent.runners import ToolRunner, Toolchain
from wengold.cli import _collect
from wengold.graph.builder import GraphBuilder
from wengold.graph.model import NodeKind
from wengold.kernel.validity import Result

TOOLS = "/scratch/work/oss-cad-suite/bin"
ROOT = "/scratch/repos/sweep"
OUT = "/scratch/work/sweep.jsonl"


def one(name, path):
    t0 = time.time()
    files = _collect(path)
    g = GraphBuilder().build_from_files(files, backend="auto")
    c = g.completeness()
    blocks = sorted(n for n, d in g.nodes.items() if d.kind is NodeKind.RTL)
    if not blocks:
        return {"project": name, "error": "no RTL blocks", "files": len(files)}

    results = [Result(f"{b}_sim", "sim", depends_on={b}) for b in blocks]
    third = max(1, len(blocks) // 3)
    for i in range(0, len(blocks), third):
        group = blocks[i:i + third]
        results.append(Result(f"cov_{i}", "coverage", depends_on=set(group),
                              depends_on_results={f"{b}_sim" for b in group}))
    changed = {blocks[0]}

    rec = {
        "project": name, "files": len(files), "blocks": len(blocks),
        "results": len(results), "nodes": len(g.nodes),
        "unresolved": len(c["unresolved"]),
        "coverage": round(c["file_coverage"] * 100),
        "complete": bool(c["complete"]),
    }

    # ---- simulated -------------------------------------------------------
    sim = Agent(g, results).run(changed, SimulatedRunner(), strategy="best_first")
    rec["sim_settled"] = sim.settled
    rec["sim_reward"] = round(sim.reward, 3)
    rec["sim_runs"] = sim.runs
    rec["sim_iters"] = sim.iterations

    # ---- real ------------------------------------------------------------
    tc = Toolchain(TOOLS)
    runner = ToolRunner(g, {r.id: r for r in results}, path, toolchain=tc)
    real = Agent(g, results).run(changed, runner, strategy="best_first")
    rec["real_settled"] = real.settled
    rec["real_reward"] = round(real.reward, 3)
    rec["real_runs"] = real.runs
    rec["real_iters"] = real.iterations
    rec["outcomes"] = dict(Counter(
        o.get("outcome") for o in getattr(real, "outcomes", [])))
    rec["tools"] = tc.describe()
    rec["design_files"] = len(runner.project_files())
    rec["secs"] = round(time.time() - t0, 1)

    # the actual verdicts, so the analysis has something per-result to look at
    rec["per_result"] = [
        {"id": o.get("result"), "kind": o.get("kind"),
         "outcome": o.get("outcome"), "rc": o.get("rc")}
        for o in getattr(real, "outcomes", [])
    ]
    return rec


def main():
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT):
            try:
                done.add(json.loads(line)["project"])
            except Exception:
                pass
    projects = sorted(d for d in os.listdir(ROOT)
                      if os.path.isdir(os.path.join(ROOT, d)))
    for name in projects:
        if name in done:
            print(f"  skip {name} (already recorded)")
            continue
        try:
            rec = one(name, os.path.join(ROOT, name))
        except Exception as exc:
            rec = {"project": name, "error": f"{type(exc).__name__}: {exc}",
                   "trace": traceback.format_exc()[-600:]}
        with open(OUT, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"  {name:<20} blocks={rec.get('blocks','-'):>4} "
              f"sim={rec.get('sim_settled','-')} real={rec.get('real_settled','-')} "
              f"outcomes={rec.get('outcomes','-')} {rec.get('secs','')}s")


if __name__ == "__main__":
    main()
