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


def _build(args):
    from .graph.builder import GraphBuilder
    files = _collect(args.path)
    incdirs = list(args.include or [])
    incdirs += [str(Path(args.path) / d) for d in ("include", "inc", "rtl/include")]
    return GraphBuilder().build_from_files(files, include_dirs=incdirs), files


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

    p = sub.add_parser("serve", help="run the MCP server over stdio")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", help="run the bundled SoC walkthrough")
    p.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
