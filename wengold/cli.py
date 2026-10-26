"""WENGOLD command line — terminal-native, alongside Git, Tcl and your EDA tools."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SRC_EXT = {".sv", ".svh", ".v", ".vh", ".rdl", ".f", ".vhd", ".vhdl"}


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
    # graph notes carry the things that change how the numbers should be read —
    # a silent fallback to the weak front-end, above all
    for note in list(dict.fromkeys(graph.notes))[:5]:
        # deduplicated: the same missing include is recorded once per unit that
        # fails to resolve it, and this printed it six times in a row
        print(f"  !! {note}")
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


def cmd_singularity(args) -> int:
    """Singular configurations: which blocks a change propagates furthest from."""
    from .graph.singularity import conditioning, damping, singular_nodes

    graph, _files = _build(args)
    c = conditioning(graph)
    print(f"blocks: {c['blocks']}   condition number: {c['condition_number']:.2f}")
    print(f"verdict: {c['verdict']}")
    if c["worst"]:
        print(f"worst: {c['worst']} — a change there reaches {c['worst_radius']} "
              f"block(s); median is {c['median']:.0f}")
    nodes = singular_nodes(graph, threshold=args.threshold)
    if nodes:
        print(f"\nsingular configurations (>={args.threshold:.0%} of the design):")
        for s in nodes[: args.top]:
            print(s.render())
    else:
        print(f"\nno block reaches >={args.threshold:.0%} of the design")
    if args.damp and c["worst"]:
        d = damping(graph, c["worst"])
        print(f"\ndamping '{c['worst']}': {d['before']} -> {d['after']} block(s) "
              f"({d['fraction_before']:.1%} -> {d['fraction_after']:.1%})")
        print(f"  cost: {d['cost']}")
    return 0


def cmd_repro(args) -> int:
    """Capture a result's inputs, or replay a bundle against the current tree."""
    from .repro import capture, load, replay, save

    if args.action == "replay":
        rep = replay(load(args.bundle), args.root)
        print(rep.render())
        return 0 if rep.reproduced else 1

    from .kernel.validity import Result

    graph, _files = _build(args)
    if not args.result:
        print("  capture needs --result <id>")
        return 2
    r = Result(args.result, args.kind or "sim")
    r.status = args.status or "fail"
    b = capture(args.path, r, verdict=args.verdict or "", detail=args.detail or "",
                tool=args.tool or "", tool_version=args.tool_version or "")
    out = args.out or f"{args.result}.repro.json"
    p = save(b, out)
    print(f"  captured {b.result_id} ({b.kind}) status={b.status}")
    print(f"  {len(b.files)} file(s) pinned -> {p}")
    return 0


def cmd_propose(args) -> int:
    """Show the edits the kernel can justify. Never applies without --apply."""
    from .agent.propose import propose_all

    graph, _files = _build(args)
    props = propose_all(graph, graph.completeness(), args.path)
    if not props:
        print("  no proposals: the kernel has nothing to justify an edit with")
        return 0
    print(f"  {len(props)} proposal(s)\n")
    for p in props:
        print(p.render())
        print()
    if not args.apply:
        print("  nothing applied. re-run with --apply <id> to write one.")
        return 0
    chosen = [p for p in props if p.id == args.apply]
    if not chosen:
        print(f"  no proposal with id {args.apply!r}; ids: "
              f"{', '.join(p.id for p in props)}")
        return 2
    out = chosen[0].apply(args.path)
    print(f"  applied {chosen[0].id} -> {out}")
    return 0


def cmd_desktop(args) -> int:
    """Serve the local WENGOLD app and open a browser."""
    from .desktop import serve
    serve(args.path, port=args.port, open_browser=not args.no_browser)
    return 0


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


def cmd_spec_from_text(args) -> int:
    """Text -> spec, with the spec checked before anyone trusts it."""
    from .spec_frontend import (check_pipeline, draft_spec, load_or_train,
                                validate)

    path = args.model or f".wengold/spec-model-{args.arch}.json"
    model, vocab_list = load_or_train(path, verbose=True, arch=args.arch)
    d = draft_spec(args.text, model, vocab_list)
    print(f"model: {args.arch}")
    print(f"in   : {args.text}")
    if not d.ok:
        print(f"draft: unreadable — {d.error}")
        print("\n  The model could not read that sentence. It knows the grammar it")
        print("  was trained on and nothing else; a sentence outside it is refused")
        print("  rather than guessed at.")
        return 1

    spec = dict(d.spec)
    print(f"draft: register {spec['register']} @ 0x{spec['addr']:02x}, field "
          f"{spec['name']} bits {spec['hi']}:{spec['lo']}, {spec['access']}, "
          f"reset {spec['reset']}")

    problems = validate(spec)
    if problems:
        print("\nvalidation: REFUSED")
        for p in problems:
            print(f"  ! {p}")
        return 1
    print("validation: accepted — access mode, bit range, alignment and reset "
          "all check out")

    out = check_pipeline(spec, module=args.module)
    print(f"\nrtl       : {out['conformance']}")
    print(f"properties: {'emitted' if out['properties_emitted'] else 'none'}")
    f = out["formal"]
    print(f"formal    : `{f['property']}` -> {f['status']}  ({f['detail']})")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(out["rtl"])
        print(f"\nwrote {args.out}")
    print("\n  The model drafted this; the checker decided. The formal run verifies")
    print("  that this spec yields correct RTL — it cannot verify that the spec is")
    print("  what the sentence meant. That is the model's job, and it is measured")
    print("  by held-out accuracy, not by the prover.")
    return 0


def cmd_learn(args) -> int:
    """Methods, and the jobs the exact code cannot do on its own."""
    from .graph.model import NodeKind

    if args.task == "generative":
        from .learn.coverage import benchmark
        print("generative stimulus — three families, one yardstick\n")
        print("  The design is a passcode chain. The corpus reaches stage 2 and")
        print("  never stage 3, and the symbol that would finish it appears")
        print("  nowhere in the data. Ground truth is the engine's own reachable")
        print("  set, so 'did the model help?' has a number, not an impression.\n")
        res = benchmark(samples=args.instances, epochs=args.epochs,
                        seed=args.seed)
        print(f"\n  {'model':<24}{'states':>9}{'stage2':>9}{'unlock':>8}")
        print("  " + "-" * 48)
        for r in res["rows"]:
            print(f"  {r['model']:<24}"
                  f"{str(r['states_reached']) + '/' + str(r['of_states']):>9}"
                  f"{r['stage2_rate']:>8.0%}{r['unlock_rate']:>8.0%}")
        by = {r["model"]: r for r in res["rows"]}
        base = by.get("random", {}).get("stage2_rate", 0.0)
        best = max((r for r in res["rows"]
                    if r["model"] not in ("random", "corpus (partial only)")),
                   key=lambda r: r["stage2_rate"], default=None)
        if best:
            print(f"\n  best generator: {best['model']}")
            if base and best["stage2_rate"] > base:
                print(f"  It reaches the deep state {best['stage2_rate'] / base:.1f}x "
                      f"as often as random sampling ({best['stage2_rate']:.0%} vs "
                      f"{base:.0%}) — a real coverage gain from the corpus.")
            else:
                print("  It does not beat random sampling here. Nothing in the")
                print("  corpus teaches it the structure; the honest answer is to")
                print("  use constrained-random, not the model.")
            print(f"  No model reproduces the corpus itself "
                  f"({by['corpus (partial only)']['stage2_rate']:.0%}); they are all")
            print("  far weaker than the data they were shown.")
        return 0

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
        # The path argument is accepted and ignored: this trains on designs it
        # generates, not on the project named. Saying so is the difference between
        # a demo and a claim about the user's design.
        if args.path and args.path not in (".", ""):
            print(f"  !! this trains on {args.designs} generated register designs — "
                  f"it does NOT read {args.path}. Its features describe generated "
                  f"spec fields and do not apply to a real core.")
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

    if args.task == "regress":
        from .kernel.validity import Result
        from .learn import regression as R
        from .learn.trees import (DecisionTreeRegressor,
                                  GradientBoostingRegressor,
                                  RandomForestRegressor)
        graph, _files = _build(args)
        mods = sorted(n for n, d in graph.nodes.items()
                      if d.kind is NodeKind.RTL)
        if len(mods) < 8:
            print("wengold: need a project with more blocks")
            return 1
        suite = [Result(f"unit_{m}", "sim", depends_on={m}) for m in mods]
        for target in ("doubtful", "unknown"):
            X, y, _blocks = R.build_dataset(graph, suite,
                                            max_blocks=args.blocks,
                                            target=target)
            if len(set(y)) < 2:
                print(f"\ntarget {target}: constant ({y[0]:.0f}) — nothing to learn")
                continue
            print(f"\ntarget {target}: {len(X)} blocks, values "
                  f"{min(y):.0f}-{max(y):.0f}")
            print(f"  {'model':<18}{'test MAE':>10}{'test R2':>10}")
            print("  " + "-" * 38)
            _, _, _tb, base = R.evaluate(lambda: R.LinearRegression(), X, y,
                                         seed=args.seed)
            print(f"  {'predict the mean':<18}{base.mae:>10.2f}{base.r2:>+10.3f}")
            for name, fac in (
                    ("linear regression", lambda: R.LinearRegression()),
                    ("decision tree", lambda: DecisionTreeRegressor(max_depth=3)),
                    ("random forest", lambda: RandomForestRegressor(
                        n_trees=25, max_depth=5)),
                    ("gradient boosting", lambda: GradientBoostingRegressor(
                        n_estimators=40, max_depth=3))):
                _m, _tr, te, _b = R.evaluate(fac, X, y, seed=args.seed)
                print(f"  {name:<18}{te.mae:>10.2f}{te.r2:>+10.3f}")
        print("\n  The label is exact — the kernel computes it. This is a surrogate for")
        print("  it, and after the edge-index fix the kernel walks a real graph in")
        print("  milliseconds, so the honest reading is that the methods work on")
        print("  this data rather than that they are needed.")
        return 0

    if args.task == "dbscan":
        from .learn.dbscan import cluster_blocks_dbscan
        graph, _files = _build(args)
        res, blocks, outliers = cluster_blocks_dbscan(graph, eps=args.eps,
                                                      min_pts=args.min_pts)
        if not blocks:
            print("wengold: no RTL blocks in the graph")
            return 1
        sizes: dict[int, int] = {}
        for lab in res.labels:
            if lab >= 0:
                sizes[lab] = sizes.get(lab, 0) + 1
        print(f"blocks: {len(blocks)}   eps: {res.eps:.3f}   min_pts: {res.min_pts}")
        print(f"clusters: {res.clusters}   unassigned (outliers): {len(outliers)} "
              f"({len(outliers) / len(blocks):.0%})")
        print(f"  cluster sizes: "
              f"{sorted(sizes.values(), reverse=True)[:12]}")
        print("\nblocks whose dependency signature resembles nothing else in the")
        print("design — worth a look, either genuinely special or a modelling slip:")
        for b in outliers[:args.show]:
            print(f"  {b}")
        if len(outliers) > 20:
            print(f"  ({len(outliers)} is a lot — lower --eps to widen the"
                  f" neighbourhood, or raise --min-pts)")
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
    from .learn.unsupervised import dependency_signature
    dups = near_duplicates(graph, min_neighbours=args.min_neighbours)
    print(f"\nreuse candidates ({len(dups)} pairs, each block with at least "
          f"{args.min_neighbours} neighbour(s)):")
    for a, b, s in dups[:args.show]:
        na, nb = len(dependency_signature(graph, a)), len(dependency_signature(graph, b))
        print(f"  {a}  ~  {b}   jaccard {s:.3f}   "
              f"({min(na, nb)} deps each)")
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


def cmd_agent(args) -> int:
    """Perceive → reason → plan → act → reflect → adapt, over the real kernel."""
    from .agent import Agent, Bandit
    from .agent.loop import SimulatedRunner
    from .agent.perception import perceive
    from .graph.model import NodeKind
    from .kernel.validity import Result

    graph, _files = _build(args)
    blocks = sorted(n for n, d in graph.nodes.items()
                    if d.kind is NodeKind.RTL)
    if not blocks:
        print("wengold: no RTL blocks in the graph")
        return 1
    # one simulation per block, and a coverage result summarising each third of
    # them — enough structure that the ordering question is real
    results = [Result(f"{b}_sim", "sim", depends_on={b}) for b in blocks]
    third = max(1, len(blocks) // 3)
    for i in range(0, len(blocks), third):
        group = blocks[i:i + third]
        results.append(Result(
            f"cov_{i}", "coverage", depends_on=set(group),
            depends_on_results={f"{b}_sim" for b in group}))

    changed = set(args.change or []) or {blocks[0]}
    print(f"agent over {len(blocks)} blocks, {len(results)} results")
    print(f"changed: {', '.join(sorted(changed))}\n")

    if args.mode == "react":
        from .agent.react import react
        ctx = perceive(graph, results, changed)
        run = react(ctx, SimulatedRunner())
        print(run.render())
        return 0
    if args.mode == "search":
        from .agent.search import best_of_k, score_order, scaling_curve, single
        ctx = perceive(graph, results, changed)
        print("  test-time scaling under a 15% per-check failure rate\n")
        print("     k   settled   (mean over 100 rollouts)")
        for row in scaling_curve(ctx, ks=(1, 2, 4, 8, 16), failure_p=0.15,
                                 trials=100, seed=args.seed):
            print(f"  {row['k']:>4}   {row['settled']:>7.2f}")
        print("\n  'k' is how many orders were tried; k=1 is the plain greedy order.")
        print("  If the settled count does not rise with k, the search found nothing")
        print("  — which is the honest answer when one check settles everything.")
        return 0
    if args.mode == "orchestrate":
        from .agent.orchestra import Orchestra
        ctx = perceive(graph, results, changed)
        result = Orchestra().run(ctx, SimulatedRunner())
        print(Orchestra.render(result))
        if not result["executed"]:
            print("\n  The reviewer refused to execute. That is the point of having")
            print("  one: a plan that relies on a tool the machine does not have is")
            print("  stopped before a check is spent, not discovered at run time.")
        return 0

    bandit = Bandit(seed=args.seed)
    agent = Agent(graph, results, bandit=bandit, seed=args.seed)
    for ep in range(max(1, args.episodes)):
        run = agent.run(changed, SimulatedRunner(), strategy=args.strategy,
                        adaptive=(args.strategy is None), budget=args.budget)
        if ep == 0:
            print(run.render())
            print()
    print("adaptation:" if args.strategy is None else "adaptation (one arm):")
    print(bandit.render())
    print("\n  Five stages are wired to real data: the graph, the kernel's verdicts,"
          "\n  the tool probes and the ledger. Two honest limits are printed rather"
          "\n  than hidden:")
    print("  - whether a check *settles* a result is modelled, because no"
          "\n    simulator or prover is installed here")
    print("  - planning order buys nothing on this structure: the kernel's minimum"
          "\n    evidence is already minimal and settling the base cascades")
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

    p = sub.add_parser("singularity",
                       help="find blocks whose change voids the most evidence")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--define", action="append", default=[])
    p.add_argument("--backend", default="auto", choices=["auto", "slang", "regex"])
    p.add_argument("--threshold", type=float, default=0.25,
                   help="fraction of the design that counts as singular")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--damp", action="store_true",
                   help="report what isolating the worst block would buy")
    p.set_defaults(func=cmd_singularity)

    p = sub.add_parser("repro",
                       help="capture a result's inputs, or replay a bundle")
    p.add_argument("action", choices=["capture", "replay"])
    p.add_argument("path", nargs="?", default=".",
                   help="design root (capture) or bundle file (replay)")
    p.add_argument("--result", help="the result id being captured")
    p.add_argument("--kind", default="sim")
    p.add_argument("--status", default="fail")
    p.add_argument("--verdict", default="")
    p.add_argument("--detail", default="")
    p.add_argument("--tool", default="")
    p.add_argument("--tool-version", dest="tool_version", default="")
    p.add_argument("--out", default="")
    p.add_argument("--root", default=".", help="tree to replay against")
    p.add_argument("--bundle", default="", help="bundle file for replay")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--define", action="append", default=[])
    p.add_argument("--backend", default="auto", choices=["auto", "slang", "regex"])
    p.set_defaults(func=cmd_repro)

    p = sub.add_parser("propose",
                       help="show edits the kernel can justify; apply only on request")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--apply", default="", metavar="ID",
                   help="write the proposal with this id")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--define", action="append", default=[])
    p.add_argument("--backend", default="auto", choices=["auto", "slang", "regex"])
    p.set_defaults(func=cmd_propose)

    p = sub.add_parser("desktop",
                       help="serve the local WENGOLD app and open a browser")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", dest="no_browser", action="store_true")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--define", action="append", default=[])
    p.add_argument("--backend", default="auto", choices=["auto", "slang", "regex"])
    p.set_defaults(func=cmd_desktop)

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

    p = sub.add_parser("spec-from-text",
                       help="draft a register spec from a sentence, and check it")
    p.add_argument("text", help="the sentence to read")
    p.add_argument("--module", default="drafted")
    p.add_argument("--arch", default="transformer",
                   choices=["transformer", "lstm"],
                   help="which seq2seq model reads the sentence")
    p.add_argument("--model", default=None,
                   help="model file (default: .wengold/spec-model-<arch>.json)")
    p.add_argument("--out", help="write the emitted RTL here")
    p.set_defaults(func=cmd_spec_from_text)

    p = sub.add_parser("learn", help="machine learning over the graph")
    p.add_argument("task", nargs="?", default="cluster",
                   choices=["cluster", "supervised", "rl", "regress", "dbscan",
                            "generative"])
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
    p.add_argument("--blocks", type=int, default=120,
                   help="blocks to build the regression dataset from")
    p.add_argument("--eps", type=float, default=None,
                   help="DBSCAN neighbourhood radius (default: the 90th-percentile "
                        "k-distance)")
    p.add_argument("--min-pts", type=int, default=3, help="DBSCAN minimum points")
    p.add_argument("--max-pending", type=int, default=40,
                   help="sample the pending set down to this many checks "
                        "(one change can put hundreds in doubt)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--save", help="write the trained model to this path")
    p.add_argument("--epochs", type=int, default=150,
                   help="training epochs for the generative models")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_learn)

    p = sub.add_parser("serve", help="run the MCP server over stdio")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("agent", help="perceive, reason, plan, act, reflect, adapt")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--include", action="append", default=[])
    p.add_argument("--define", action="append", default=[])
    p.add_argument("--backend", default="auto", choices=["auto", "slang", "regex"])
    p.add_argument("--change", action="append", default=[],
                   help="a node that changed (default: the first block)")
    p.add_argument("--strategy", default=None,
                   choices=["cheapest", "greedy", "best_first"],
                   help="fix a planning strategy instead of learning one")
    p.add_argument("--budget", type=int, default=None,
                   help="cap the number of checks")
    p.add_argument("--mode", default="stages",
                   choices=["stages", "react", "search", "orchestrate"],
                   help="stages: perceive→reason→plan→act→reflect→adapt; "
                        "react: thought/action/observation loop; "
                        "search: test-time scaling; orchestrate: planner/reviewer/executor")
    p.add_argument("--episodes", type=int, default=6,
                   help="runs to let the bandit adapt over")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_agent)

    p = sub.add_parser("demo", help="run the bundled SoC walkthrough")
    p.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
