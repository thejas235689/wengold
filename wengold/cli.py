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

    p = sub.add_parser("serve", help="run the MCP server over stdio")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", help="run the bundled SoC walkthrough")
    p.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
