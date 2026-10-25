"""WENGOLD command line — terminal-native, alongside Git, Tcl and your EDA tools."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SRC_EXT = {".sv", ".svh", ".v", ".vh", ".rdl", ".f"}


def _collect(path: str) -> dict[str, str]:
    files: dict[str, str] = {}
    p = Path(path)
    if p.is_file():
        files[p.name] = p.read_text(errors="replace")
        return files
    for f in sorted(p.rglob("*")):
        if f.is_file() and f.suffix.lower() in SRC_EXT:
            files[str(f.relative_to(p))] = f.read_text(errors="replace")
    return files


def _read(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"wengold: no such file: {path}")
    return p.read_text(errors="replace")


def _build(args):
    from .graph.builder import GraphBuilder
    files = _collect(args.path)
    incdirs = list(args.include or [])
    # include directories are searched *and* added to the file set, the way a real
    # flow passes +incdir+ together with its file list — otherwise every
    # `include in the project is reported unresolved.
    for d in incdirs:
        p = Path(d)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in SRC_EXT:
                    files.setdefault(str(f), f.read_text(errors="replace"))
    incdirs += [str(Path(args.path) / d) for d in ("include", "inc", "rtl/include")]
    defines = {}
    for d in (getattr(args, "define", None) or []):
        name, _, value = d.partition("=")
        defines[name] = value or "1"
    backend = getattr(args, "backend", "auto")
    return (GraphBuilder().build_from_files(files, include_dirs=incdirs,
                                            defines=defines, backend=backend), files)


def cmd_index(args) -> int:
    graph, files = _build(args)
    report = graph.completeness()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "files": sorted(files),
        "nodes": {n.id: {"kind": n.kind.value, "resolved": n.resolved} for n in graph.nodes.values()},
        "edges": [{"src": e.src, "dst": e.dst, "kind": e.kind.value} for e in graph.edges],
        "completeness": report,
    }, indent=2))
    print(f"indexed {len(files)} file(s), {len(graph.nodes)} nodes, "
          f"{len(graph.edges)} edges -> {out}")
    print(f"complete: {report['complete']}  unresolved: {len(report['unresolved'])}")
    for issue in report["issues"][:10]:
        print(f"  ! {issue}")
    return 0


def cmd_completeness(args) -> int:
    graph, _files = _build(args)
    report = graph.completeness()
    print(json.dumps(report, indent=2))
    return 0 if report["complete"] else 1


def cmd_classify(args) -> int:
    from .kernel.minimize import minimum_new_evidence
    from .kernel.validity import Result, classify_all
    graph, _files = _build(args)
    payload = json.loads(Path(args.results).read_text())
    results = [Result(id=r["id"], kind=r.get("kind", "sim"),
                      depends_on=set(r.get("depends_on", [])),
                      depends_on_results=set(r.get("depends_on_results", [])))
               for r in payload]
    changed = set(args.changed.split(","))
    classes = classify_all(graph, results, changed)
    for c in classes:
        print(f"  {c.verdict.value:>12}  {c.result.id:<20} {c.reason}")
    todo = minimum_new_evidence(graph, classes)
    print(f"\nminimum new evidence: {todo}")
    return 0


def cmd_formal(args) -> int:
    from .formal import Property, prove
    text = _read(args.file)
    props = [Property.safety(f"p{i}", expr, clock=args.clock, reset=args.reset)
             for i, expr in enumerate(args.property)]
    out = prove(text, props, engine=args.engine, depth=args.depth, budget=args.budget)
    for r in out["results"]:
        print(f"  {r.status:>8}  {r.property:<10} {r.engine:<8} {r.detail}")
    for c in out["contracts"]:
        print(f"  contract: {c.claim}  [{c.method.kind.value}"
              f"{', ' + ', '.join(c.limits.gaps) if c.limits.gaps else ''}]")
    if out["counterexamples"]:
        print(f"  counterexamples: {out['counterexamples']}")
    if args.sva:
        print(out["sva"])
    return 0 if out["proved"] else 1


def cmd_regmap(args) -> int:
    from .graph.regmap import parse_ipxact, parse_rdl
    text = _read(args.file)
    amap = parse_ipxact(text) if args.file.endswith(".xml") else parse_rdl(text)
    print(f"{amap.name}: {len(amap.registers)} register(s)")
    for r in amap.registers:
        fields = ", ".join(f"{f.name}[{f.msb}:{f.lsb}]{f.sw}" for f in r.fields)
        print(f"  {hex(r.address):>10}  {r.name:<16} {fields}")
    for issue in amap.check():
        print(f"  ! {issue}")
    return 0 if not amap.check() else 1


def cmd_cdc(args) -> int:
    from .graph.cdc import analyse
    text = _read(args.file)
    rep = analyse(text, Path(args.file).stem)
    print(f"domains: {rep.domains}")
    for c in rep.crossings:
        print(f"  crossing {c.signal}: {c.from_domain} -> {c.to_domain} ({c.kind})")
    if rep.unresolved:
        print(f"  unresolved (no determinable domain): {rep.unresolved}")
    return 0 if not rep.crossings else 1


def cmd_generate(args) -> int:
    """Spec in, SystemVerilog out — and then check the code against the spec."""
    from .generate.emit import emit_map, emit_props, emit_rtl
    from .generate.spec import SpecError, load_spec

    try:
        spec = load_spec(args.spec)
    except SpecError as exc:
        print(f"wengold: {exc}", file=sys.stderr)
        return 2

    rtl = emit_rtl(spec)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    rtl_path = outdir / f"{spec.name}.sv"
    rtl_path.write_text(rtl)
    written = [str(rtl_path)]

    props = emit_props(spec)
    if props:
        props_path = outdir / f"{spec.name}_props.sv"
        props_path.write_text(props)
        written.append(str(props_path))

    (outdir / f"{spec.name}.map.json").write_text(
        json.dumps(emit_map(spec), indent=2) + "\n")
    written.append(str(outdir / f"{spec.name}.map.json"))

    print(f"generated {spec.name}: "
          f"{len(spec.registers)} register(s), "
          f"{sum(len(r.fields) for r in spec.registers)} field(s), "
          f"{len(spec.all_ports)} port(s)")
    for w in written:
        print(f"  {w}")

    if args.no_check:
        return 0

    from .generate.conform import check
    report = check(rtl, spec)
    print()
    print(report.summary())
    return 0 if report.ok else 1


def cmd_rootcause(args) -> int:
    """Explain why something is unknown, unresolved or invalidated."""
    from .rootcause import diagnose_node, diagnose_verdict

    graph, _files = _build(args)
    root = Path(args.path)
    if root.is_file():
        root = root.parent
    status = 0

    nodes = list(args.node)
    if args.all_unresolved:
        nodes += sorted(graph.unresolved_nodes())

    for name in nodes:
        diag = diagnose_node(graph, name, root)
        print(diag.render())
        print()
        if diag.status == "unresolved":
            status = 1

    if args.result:
        diag = diagnose_verdict(graph, args.result, args.depends, args.change)
        print(diag.render())
        if diag.status in ("unknown", "invalidated"):
            status = status or 1

    if not nodes and not args.result:
        print("nothing asked: pass --node NAME, --all-unresolved, or --result ID")
        return 2
    return status


def cmd_ide(args) -> int:
    """Write a self-contained IDE for a project: files, RTL, change, pending."""
    from . import __version__
    from .graph.model import EdgeKind, NodeKind
    from .ide import build
    from .kernel.validity import Result

    graph, _files = _build(args)
    root = Path(args.path)
    if root.is_file():
        root = root.parent

    def _rel(p) -> str:
        """Paths in the graph may be absolute while --change is relative. Compare
        in one space, or a changed block is silently never matched."""
        path = Path(str(p))
        try:
            path = path.relative_to(root)
        except ValueError:
            pass
        return str(path).replace("\\", "/")

    changed_files = {_rel(c) for c in (args.change or [])}
    befores: dict[str, str] = {}
    for spec in (args.before or []):
        rel, _, src = spec.partition("=")
        try:
            befores[_rel(rel)] = Path(src).read_text(errors="replace")
        except OSError as exc:
            print(f"wengold: cannot read --before {src}: {exc}", file=sys.stderr)
            return 2

    # which blocks changed: the modules defined in the changed files, unless the
    # caller names them explicitly
    changes = set(args.change_block or [])
    if not changes:
        for nid, node in graph.nodes.items():
            if node.kind is NodeKind.RTL and node.path \
                    and _rel(node.path) in changed_files:
                changes.add(nid)

    # a suite to reason over: one unit result per block, plus an integration
    # result on the top of the hierarchy — a block nothing instantiates, with the
    # deepest subtree under it
    mods = sorted(n for n, d in graph.nodes.items() if d.kind is NodeKind.RTL)
    roots = [m for m in mods
             if not [e for e in graph.out_edges(m)
                     if e.kind is EdgeKind.INSTANTIATES]]
    top = max(roots, key=lambda m: len(graph.ancestors(m)), default=None)
    results = [Result(f"unit_{m}", "sim", depends_on={m}) for m in mods]
    if top:
        results += [Result(f"integration_{top}", "sim", depends_on={top}),
                    Result("signoff", "coverage", depends_on={top},
                           depends_on_results={f"integration_{top}"})]

    # a waveform, from a real source: a simulator's VCD, or the counterexample
    # the formal engine already computes for a property that fails
    wave = None
    if args.vcd:
        from .wave import from_vcd
        try:
            wave = from_vcd(args.vcd)
            print(f"  waveform: {args.vcd} "
                  f"({wave['cycles']} cycle(s), {len(wave['signals'])} signal(s))")
        except OSError as exc:
            print(f"wengold: cannot read --vcd {args.vcd}: {exc}", file=sys.stderr)
            return 2
    if args.property and args.wave_file:
        from .wave import from_formal
        wf = root / args.wave_file
        try:
            text = wf.read_text(errors="replace")
        except OSError as exc:
            print(f"wengold: cannot read --wave-file {args.wave_file}: {exc}",
                  file=sys.stderr)
            return 2
        wave = from_formal(text, args.property, reset=args.reset,
                           clock=args.clock, engine=args.wave_engine)
        if wave is None:
            print(f"  waveform: `{args.property}` did not fail on "
                  f"{args.wave_file} — nothing to draw")
        else:
            print(f"  waveform: counterexample of `{args.property}` "
                  f"({wave['cycles']} cycle(s))")

    html = build(root, graph, changed_files, befores, results, changes,
                 project=root.name, revision=args.revision, version=__version__,
                 wave=wave)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    s = build.__globals__  # noqa: F841  (kept for clarity; summary printed below)
    from .ide import collect
    data = collect(root, graph, changed_files, befores, results, changes)
    sm = data["summary"]
    print(f"wrote {out}  ({out.stat().st_size // 1024} KB)")
    print(f"  {sm['files']} file(s), {sm['blocks']} block(s), "
          f"{sm['changed']} changed, {sm['pending']} pending, "
          f"{sm['unresolved']} unresolved")
    print(f"  suite: {len(results)} result(s) — one unit per block"
          f"{f', plus integration on {top}' if top else ''}")
    return 0


def cmd_learn(args) -> int:
    """Three methods, three jobs the exact code cannot do on its own."""
    from .graph.model import NodeKind

    if args.task == "supervised":
        from .learn.supervised import (FEATURE_KEYS, build_dataset,
                                       majority_baseline, precision_at_k,
                                       train_eval)
        ex = build_dataset(n_designs=args.designs, seed=args.seed,
                           verbose=args.verbose)
        if not ex:
            print("wengold: no labelled examples could be produced")
            return 1
        pos = sum(e.label for e in ex)
        print(f"examples: {len(ex)}  fail: {pos}  hold: {len(ex) - pos} "
              f"({pos / len(ex):.0%} fail)")
        print("labels: the formal engine, run on each generated design")
        model, tr, te = train_eval(ex, seed=args.seed)
        base = majority_baseline(ex)
        print(f"  majority-class baseline : {base:.3f}")
        print(f"  train                   : {tr.render()}")
        print(f"  held out (by design)    : {te.render()}")
        k = max(1, len(ex) // 10)
        print(f"  precision@{k} (triage)     : "
              f"{precision_at_k(model, ex, k):.3f}")
        print("  note: the features make this close to a rule — the score says the"
              "\n        rule is learnable, not that the model is clever.")
        if args.save:
            model.save(args.save)
            print(f"  saved model -> {args.save}  ({len(FEATURE_KEYS)} features)")
        return 0

    if args.task == "rl":
        from .kernel.validity import Result
        from .learn import rl
        graph, _files = _build(args)
        mods = sorted(n for n, d in graph.nodes.items()
                      if d.kind is NodeKind.RTL)
        if len(mods) < 3:
            print("wengold: need a project with several blocks")
            return 1
        top = max(mods, key=lambda m: len(graph.ancestors(m)))
        suite = [Result(f"unit_{m}", "sim", depends_on={m}) for m in mods]
        suite.append(Result("integration", "sim", depends_on={top}))
        insts = [i for i in (rl.instance_from_graph(graph, suite, {m}, seed=k,
                                                   max_results=args.max_pending)
                             for k, m in enumerate(mods[:args.instances]))
                 if i.all_results >= 3]
        if len(insts) < 3:
            print("wengold: not enough pending sets to learn from")
            return 1
        cut = len(insts) * 2 // 3
        train_set, test_set = insts[:cut], insts[cut:]
        print(f"instances: {len(insts)}  (train {len(train_set)}, test "
              f"{len(test_set)})")
        print(f"  {insts[0].note}")
        agent = rl.train(train_set, episodes=args.episodes, seed=args.seed)
        print(f"\n  {'policy':<16}{'mean cost':>11}{'settled':>10}")
        print("  " + "-" * 37)
        rows = [("random", rl.evaluate(rl.random_policy, test_set)),
                ("cheapest first", rl.evaluate(rl.cheapest_first, test_set)),
                ("greedy ratio", rl.evaluate(rl.greedy_ratio, test_set)),
                ("RL (learned)", rl.evaluate(None, test_set, agent=agent))]
        for name, res in rows:
            print(f"  {name:<16}{res['mean_cost']:>11.2f}"
                  f"{res['mean_settled']:>9.0%}")
        best = max(rows, key=lambda t: (t[1]["mean_settled"], -t[1]["mean_cost"]))
        print(f"\n  best on this problem: {best[0]}")
        if best[0] != "RL (learned)":
            print("  The learned policy does not beat the simple heuristic here.")
            print("  Greedy-by-ratio is already near-optimal for this reward, so")
            print("  the honest recommendation is to use it, not the model.")
        return 0

    # cluster (default)
    from .learn.unsupervised import cluster_blocks, near_duplicates
    graph, _files = _build(args)
    clusters, c = cluster_blocks(graph, k=args.k)
    if not clusters:
        print("wengold: no RTL blocks in the graph")
        return 1
    blocks = sum(len(cl.members) for cl in clusters)
    print(f"blocks: {blocks}   k: {c.k}   silhouette: {c.silhouette:.3f}")
    print("  silhouette is the separation of the clusters; 0 means the split is")
    print("  arbitrary, so anything near it should not be believed.\n")
    for cl in clusters:
        print(f"  cluster {cl.label}  ({len(cl.members)} blocks)  "
              f"distinctive: {', '.join(cl.distinctive)}")
        print(f"      {cl.note}")
        print(f"      {', '.join(cl.members[:6])}"
              f"{' …' if len(cl.members) > 6 else ''}")
    from .learn.unsupervised import neighbour_sets
    dups = near_duplicates(graph, min_neighbours=args.min_neighbours)
    print(f"\nreuse candidates ({len(dups)} pairs, each block with at least "
          f"{args.min_neighbours} neighbour(s)):")
    for a, b, s in dups[:args.show]:
        na, nb = len(neighbour_sets(graph, a)), len(neighbour_sets(graph, b))
        print(f"  {a}  ~  {b}   jaccard {s:.3f}   "
              f"({min(na, nb)} shared neighbours)")
    if not dups:
        print("  none above the threshold")
    elif len(dups) > 20 * args.show:
        print(f"  {len(dups)} pairs is a lot — raise --min-neighbours to keep "
              f"only the pairs that rest on more than one edge")
    return 0


def cmd_serve(args) -> int:
    from .mcp.server import main as serve
    serve()
    return 0


def cmd_demo(args) -> int:
    from .demo import main as demo
    demo()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="wengold",
                                     description="WENGOLD — open silicon verification.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", help="index a project into a dependency graph")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--define", action="append", default=[],
                   help="a preprocessor define, NAME or NAME=VALUE (repeatable)")
    p.add_argument("--backend", default="auto", choices=["auto", "slang", "regex"])
    p.add_argument("--out", default=".tof/index.json")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("completeness", help="report the graph's completeness")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--include", action="append", default=[])
    p.set_defaults(func=cmd_completeness)

    p = sub.add_parser("classify", help="classify prior results against a change set")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--changed", required=True)
    p.add_argument("--results", required=True)
    p.add_argument("--include", action="append", default=[])
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("formal", help="prove properties against an RTL file")
    p.add_argument("file")
    p.add_argument("--property", action="append", required=True,
                   help="an expression to prove (repeatable)")
    p.add_argument("--clock", default="clk")
    p.add_argument("--reset", default=None)
    p.add_argument("--engine", default="auto", choices=["auto", "explicit", "z3"])
    p.add_argument("--depth", type=int, default=12)
    p.add_argument("--budget", type=int, default=3)
    p.add_argument("--sva", action="store_true", help="also print the generated SVA")
    p.set_defaults(func=cmd_formal)

    p = sub.add_parser("regmap", help="parse a SystemRDL or IP-XACT register map")
    p.add_argument("file")
    p.set_defaults(func=cmd_regmap)

    p = sub.add_parser("cdc", help="report clock-domain crossings in an RTL file")
    p.add_argument("file")
    p.set_defaults(func=cmd_cdc)

    p = sub.add_parser("generate",
                       help="generate SystemVerilog from a spec, then check it")
    p.add_argument("spec", help="the spec (YAML or JSON)")
    p.add_argument("--out", default="build", help="output directory")
    p.add_argument("--no-check", action="store_true",
                   help="skip the conformance check (not recommended)")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("rootcause",
                       help="explain why something is unknown, unresolved or invalidated")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--define", action="append", default=[])
    p.add_argument("--backend", default="auto", choices=["auto", "slang", "regex"])
    p.add_argument("--node", action="append", default=[],
                   help="explain this node (repeatable)")
    p.add_argument("--all-unresolved", action="store_true",
                   help="explain every unresolved node")
    p.add_argument("--result", help="a result id to explain")
    p.add_argument("--depends", action="append", default=[],
                   help="a dependency of that result (repeatable)")
    p.add_argument("--change", action="append", default=[],
                   help="a node that changed (repeatable)")
    p.set_defaults(func=cmd_rootcause)

    p = sub.add_parser("ide", help="write a self-contained IDE for a project")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--define", action="append", default=[])
    p.add_argument("--backend", default="auto", choices=["auto", "slang", "regex"])
    p.add_argument("--change", action="append", default=[],
                   help="a file that changed, relative to the project (repeatable)")
    p.add_argument("--before", action="append", default=[],
                   help="REL=PATH giving the pre-change content of a file")
    p.add_argument("--change-block", action="append", default=[],
                   help="name a changed block explicitly (repeatable)")
    p.add_argument("--revision", default="working copy")
    p.add_argument("--vcd", help="draw a waveform from a simulator VCD dump")
    p.add_argument("--wave-file",
                   help="RTL file to run --property on for a counterexample wave")
    p.add_argument("--property", help="the property to check for a waveform")
    p.add_argument("--reset", default=None, help="reset signal for --property")
    p.add_argument("--clock", default=None, help="clock signal for --property")
    p.add_argument("--wave-engine", default="explicit",
                   choices=["explicit", "z3"], help="engine for --property")
    p.add_argument("--out", default="wengold-ide.html")
    p.set_defaults(func=cmd_ide)

    p = sub.add_parser("learn", help="machine learning over the graph")
    p.add_argument("task", nargs="?", default="cluster",
                   choices=["cluster", "supervised", "rl"])
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--define", action="append", default=[])
    p.add_argument("--backend", default="auto", choices=["auto", "slang", "regex"])
    p.add_argument("--k", type=int, default=None, help="cluster count (default: by silhouette)")
    p.add_argument("--show", type=int, default=8, help="reuse candidates to print")
    p.add_argument("--min-neighbours", type=int, default=2,
                   help="a reuse candidate must have at least this many "
                        "neighbours (1 floods on a big design)")
    p.add_argument("--designs", type=int, default=16, help="designs to generate")
    p.add_argument("--episodes", type=int, default=2000)
    p.add_argument("--instances", type=int, default=30)
    p.add_argument("--max-pending", type=int, default=40,
                   help="sample the pending set down to this many checks "
                        "(one change can put hundreds in doubt)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--save", help="write the trained model to this path")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_learn)

    p = sub.add_parser("serve", help="run the MCP server over stdio")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", help="run the bundled SoC walkthrough")
    p.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
