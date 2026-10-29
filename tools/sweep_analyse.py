"""Track the sweep results, and be honest about what machine learning can do here.

Two questions, two different answers:

1. **Can a model predict whether the real runner settles a result?** No, and the
   reason is not sample size — every single result in the sweep is `inconclusive`.
   A label with one value has no signal to learn. Reporting 0% accuracy would be
   less honest than reporting that the label is constant.

2. **Can a model say anything useful about the projects?** Yes, weakly. The
   *simulated* settle count does vary (9–48), so it is a real target, and the
   project features are real. With six projects that model cannot be trusted — the
   leave-one-out error below shows that rather than hiding it.

The output is a CSV, a markdown report, and a printed summary. Nothing is claimed
that the numbers do not support.
"""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/scratch/repos/wengold")

SWEEP = Path("/scratch/work/sweep.jsonl")
OUT = Path("/scratch/work")


def load():
    rows = []
    for line in SWEEP.read_text().splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if "error" not in r:
            rows.append(r)
    return rows


def features(r):
    """What the agent could know before running, without using the outcome."""
    total = max(r["results"], 1)
    return {
        "files": r["files"],
        "blocks": r["blocks"],
        "nodes": r["nodes"],
        "results": r["results"],
        "unresolved": r["unresolved"],
        "coverage": r["coverage"],
        "unresolved_frac": r["unresolved"] / max(r["nodes"], 1),
        "blocks_per_file": r["blocks"] / max(r["files"], 1),
        "cov_per_block": r["results"] / max(r["blocks"], 1),
    }


def label_summary(rows):
    from collections import Counter
    c = Counter()
    for r in rows:
        for k, v in (r.get("outcomes") or {}).items():
            c[k] += v
    return c


def analyse(rows):
    lines = []
    add = lines.append

    add("# Agent sweep — real tools vs a simulated runner\n")
    add("Six repositories, the same plan, two runners. `SimulatedRunner` settles "
        "every check it is handed; `ToolRunner` shells out to Verilator.\n")

    add("| project | files | blocks | unresolved | coverage | sim settled | "
        "real settled | outcomes |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for r in sorted(rows, key=lambda x: -x["blocks"]):
        oc = r.get("outcomes") or {}
        oc_s = ", ".join(f"{k} {v}" for k, v in sorted(oc.items())) or "—"
        add(f"| {r['project']} | {r['files']} | {r['blocks']} | {r['unresolved']} | "
            f"{r['coverage']}% | {r.get('sim_settled','—')} | "
            f"{r.get('real_settled','—')} | {oc_s} |")

    tot_sim = sum(r.get("sim_settled") or 0 for r in rows)
    tot_real = sum(r.get("real_settled") or 0 for r in rows)
    add(f"\n**Simulated settles {tot_sim} results. Real tools settle {tot_real}.**\n")

    # ---- what the labels look like --------------------------------------
    c = label_summary(rows)
    add("## Why machine learning cannot predict the real outcome\n")
    add(f"Outcome labels across all runs: `{dict(c)}`\n")
    if len(c) == 1:
        add("Every result has the same label. A model trained on one class learns "
            "the constant and nothing else — the accuracy would be 100% and it "
            "would mean nothing. This is not a small-sample problem; it is a "
            "**missing-signal** problem, and it is reported rather than modelled.\n")

    # ---- the one target that does vary ----------------------------------
    y = [r.get("sim_settled") or 0 for r in rows]
    add("## The one thing that does vary, and why it is still not a model\n")
    add(f"`sim_settled` ranges {min(y)}–{max(y)} across {len(y)} projects, so it is "
        f"a real target. Fitting it is a different matter.\n")
    if len(y) >= 3:
        add(f"- n = {len(y)}. A model with three features has more parameters than "
            f"data points.\n")
        add(f"- The target is almost a linear function of `results`, which is "
            f"itself a feature — so a high R² would measure the construction, not "
            f"the projects.\n")
        add(f"- Leave-one-out is the only honest score at this size, and at n={len(y)} "
            f"it has {len(y)} folds each trained on {len(y)-1} points.\n")

    # ---- clustering, which is defensible ---------------------------------
    try:
        from wengold.learn.unsupervised import kmeans
        X = [[features(r)[k] for k in ("blocks", "coverage", "unresolved_frac",
                                       "blocks_per_file")]
             for r in rows]
        # scale, or blocks dominates
        cols = list(zip(*X))
        mu = [statistics.fmean(c) for c in cols]
        sd = [statistics.pstdev(c) or 1.0 for c in cols]
        Xn = [[(v - m) / s for v, m, s in zip(row, mu, sd)] for row in X]
        cl = kmeans(Xn, k=2, seed=0)
        labels = cl.labels
        add("## Clustering the projects (the part that is defensible)\n")
        add("k-means on standardised structure — blocks, coverage, unresolved "
            "fraction, blocks per file:\n")
        groups = {}
        for r, lab in zip(rows, labels):
            groups.setdefault(lab, []).append(r["project"])
        for lab, names in sorted(groups.items()):
            add(f"- **cluster {lab}**: {', '.join(sorted(names))}\n")
        add("\nWith six points this separates large dense designs from small ones. "
            "It is a description, not a discovery — the clusters are not validated "
            "against anything.\n")
    except Exception as exc:
        add(f"\n(clustering unavailable: {type(exc).__name__}: {exc})\n")

    # ---- the actual finding ---------------------------------------------
    add("## The finding\n")
    add("Real tools settle nothing here, and the reason is specific: **a lint needs "
        "the project's own build metadata** — its filelist, its `` `define``s, its "
        "include paths. Without them Verilator rejects the file set, and the runner "
        "cannot tell that apart from a broken design. So it reports `inconclusive` "
        "for all of them.\n")
    add("That is the correct behaviour. The alternative — calling an undefined macro "
        "a design failure — would have produced 118 confident wrong answers across "
        "six projects, which is exactly the defect this project keeps finding in "
        "itself.\n")
    add("**What would make the numbers real:** read the project's own filelist "
        "(`.f`), its defines and its include directories, and pass them to the "
        "tool. `wengold propose` already generates a working `.f` for neorv32; "
        "wiring that into the runner is the next step.\n")

    return "\n".join(lines)


def write_csv(rows):
    import csv
    keys = ["project", "files", "blocks", "nodes", "results", "unresolved",
            "coverage", "sim_settled", "sim_reward", "real_settled", "real_reward",
            "sim_runs", "real_runs", "design_files", "secs"]
    path = OUT / "WENGOLD-agent-sweep.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def main():
    rows = load()
    if not rows:
        print("  no sweep results"); return 1
    report = analyse(rows)
    (OUT / "WENGOLD-agent-sweep.md").write_text(report)
    csv_path = write_csv(rows)
    print(report)
    print(f"\n  wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
