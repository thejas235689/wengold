"""Reproducible, bounded SoC verification example using Wengold's Xezim adapter."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory

from wengold.graph.model import DesignGraph, Node, NodeKind
from wengold.kernel.validity import Result, classify_all
from wengold.tools.adapters.xezim import REFERENCE_VERSION, XezimAdapter

HERE = Path(__file__).resolve().parent
RULE = "rtl/arbiter.sv"
SYSTEM = ["rtl/dma.sv", RULE, "rtl/memory.sv", "subsystem_tb.sv"]
MEMORY = ["rtl/memory.sv", "memory_tb.sv"]
REQS = json.loads((HERE / "requirements.json").read_text())
SYSTEM_REQS = [key for key in REQS if key != "REQ-MEMORY"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_checks(result, requirements):
    hits = re.findall(r"^HIT:(REQ-[A-Z]+)$", result.log, re.M)
    failure = re.search(r"FAIL:(REQ-[A-Z]+):(\d+)", result.log)
    checks = {}
    for req in requirements:
        failed = result.verdict() == "fail" and failure and failure[1] == req
        # Partial traces after a failed or blocked run are not PASS evidence.
        status = ("caught" if failed else
                  ("exercised" if req in hits else "unexercised")
                  if result.verdict() == "pass" else "not_established")
        checks[req] = {"status": status, "observed_hits": hits.count(req)}
        if failed:
            checks[req]["first_failing_cycle"] = int(failure[2])
    return checks


def verify(out, binary="xezim"):
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    adapter = XezimAdapter(binary)
    runs = {}
    with TemporaryDirectory(prefix="wengold-soc-") as temp:
        root = Path(temp)
        shutil.copytree(HERE / "rtl", root / "rtl")
        for file in ["subsystem_tb.sv", "memory_tb.sv", "requirements.json"]:
            shutil.copy2(HERE / file, root / file)

        def run(name, *, memory=False, defines=()):
            sources = MEMORY if memory else SYSTEM
            snapshot = Path("snapshots") / name
            for file in [*sources, "requirements.json"]:
                dest = out / snapshot / file
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / file, dest)
            recipe = {"top": "memory_tb" if memory else "subsystem_tb",
                      "files": sources, "defines": list(defines), "seed": 1,
                      "timeout": 15, "pass_marker": "SOC_PREVIEW_PASS"}
            inputs = {p: digest(out / snapshot / p) for p in [*sources, "requirements.json"]}
            result = adapter.run(cwd=out / snapshot, **recipe)
            log = out / (name + ".log")
            log.write_text(result.log, encoding="utf-8")
            runs[name] = {**result.as_dict(), "log": log.name, "log_sha256": digest(log),
                          "inputs": inputs, "snapshot": snapshot.as_posix(), "recipe": recipe,
                          "checks": run_checks(result, ["REQ-MEMORY"] if memory else SYSTEM_REQS)}

        run("baseline")
        run("no_backpressure", defines=("NO_STALL",))
        run("dropped_write", defines=("DROP_WRITE",))
        run("early_interrupt", defines=("EARLY_IRQ",))
        run("isolated_memory", memory=True)

        rule = root / RULE
        before = rule.read_text()
        if before.count("CPU_FIRST = 1'b1") != 1:
            raise ValueError("expected the pinned CPU-first baseline")
        rule.write_text(before.replace("CPU_FIRST = 1'b1", "CPU_FIRST = 1'b0"))
        changed = {p for p, sha in runs["baseline"]["inputs"].items()
                   if digest(root / p) != sha}
        # Reviewed file dependencies for these fixed recipes, not automatic SoC inference.
        graph = DesignGraph()
        for p in {*SYSTEM, *MEMORY, "requirements.json"}:
            graph.add_node(Node(p, NodeKind.FILE))
        previous = [Result(name, "simulation", set(runs[name]["inputs"]))
                    for name in ("baseline", "isolated_memory")
                    if runs[name]["verdict"] == "pass"]
        # Represents imported evidence with no recorded compile inputs.
        previous.append(Result("unmapped_external_result", "simulation"))
        impact = {x.result.id: {"verdict": x.verdict.value, "reason": x.reason}
                  for x in classify_all(graph, previous, changed)}
        if impact.get("baseline", {}).get("verdict") == "invalidated":
            run("old_checker_after_rule_change")
            run("reverified_dma_first", defines=("EXPECT_DMA_FIRST",))

    expected_passes = ("baseline", "no_backpressure", "isolated_memory", "reverified_dma_first")
    passed = (
        all(r["spec"].get("version") == REFERENCE_VERSION for r in runs.values())
        and all(runs.get(n, {}).get("verdict") == "pass" for n in expected_passes)
        and all(c["status"] == "exercised" for c in runs["baseline"]["checks"].values())
        and runs["no_backpressure"]["checks"]["REQ-HOLD"]["status"] == "unexercised"
        and all(runs[name]["checks"][req]["status"] == "caught" for name, req in (
            ("dropped_write", "REQ-DATA"), ("early_interrupt", "REQ-IRQ"),
            ("old_checker_after_rule_change", "REQ-PRIORITY")))
        and runs["reverified_dma_first"]["checks"]["REQ-PRIORITY"]["status"] == "exercised"
        and all(impact.get(n, {}).get("verdict") == v for n, v in (
            ("baseline", "invalidated"), ("isolated_memory", "valid"),
            ("unmapped_external_result", "unknown")))
    )
    report = {"schema_version": 2, "status": "preview_verified" if passed else "preview_not_verified",
              "scope": "directed subsystem simulation, not SoC signoff",
              "requirements": REQS, "runs": runs, "changed_inputs": sorted(changed),
              "dependency_scope": "reviewed inputs of bundled recipes only",
              "prior_evidence_impact": impact}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def replay(report_path, name, binary="xezim"):
    report_path = report_path.resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema_version") != 2 or name not in report["runs"]:
        raise ValueError("select a named run from a version 2 evidence report")
    prior = report["runs"][name]
    root = report_path.parent

    def contained(parent, relative):
        path = (parent / relative).resolve()
        if Path(relative).is_absolute() or not path.is_relative_to(parent):
            raise ValueError(f"evidence path escapes its directory: {relative}")
        return path

    snapshot = contained(root, prior["snapshot"])
    recipe = prior["recipe"]
    if set(prior["inputs"]) != {*recipe["files"], "requirements.json"}:
        raise ValueError("snapshot inputs do not match the replay recipe")
    for file, expected in prior["inputs"].items():
        path = contained(snapshot, file)
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"snapshot hash mismatch: {file}")
    log = contained(root, prior["log"])
    if not log.is_file() or digest(log) != prior["log_sha256"]:
        raise ValueError(f"original transcript hash mismatch: {prior['log']}")

    result = XezimAdapter(binary).run(cwd=snapshot, **recipe)
    checks = run_checks(result, prior["checks"])
    match = (result.settled and result.spec.get("version") == prior["spec"].get("version")
             and result.verdict() == prior["verdict"] and checks == prior["checks"])
    return {"status": "replay_matched" if match else "replay_mismatch",
            "run": name, "original_verdict": prior["verdict"], **result.as_dict(),
            "checks": checks, "log": result.log}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    modes = p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--output", type=Path, help="new evidence output directory")
    modes.add_argument("--replay", type=Path, metavar="REPORT", help="replay a saved evidence report")
    p.add_argument("--run", help="run name from the saved report")
    p.add_argument("--xezim", default="xezim")
    args = p.parse_args()
    if bool(args.replay) != bool(args.run):
        p.error("--replay and --run must be used together")
    try:
        if args.replay:
            result = replay(args.replay, args.run, args.xezim)
            print(json.dumps(result, indent=2))
            raise SystemExit(result["status"] != "replay_matched")
        result = verify(args.output, args.xezim)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.exit(2, f"{exc}\n")
    print(f"{result['status']} — {args.output / 'report.json'}")
    raise SystemExit(result["status"] != "preview_verified")
