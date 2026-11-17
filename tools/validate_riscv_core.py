#!/usr/bin/env python3
"""Elaborate the user's rv64_core RTL with yosys-slang and optionally map a VCD.

Usage:
  python tools/validate_riscv_core.py /path/to/rv64_core
  python tools/validate_riscv_core.py /path/to/rv64_core --vcd sim.vcd --vcd-root tb_core_top
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Executing this file by path puts tools/ (not the repository root) on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wengold.rtl_hierarchy import (
    crossprobe_hierarchy_to_vcd,
    elaborate_with_slang_ast,
    elaborate_with_yosys,
    load_riscv_core_sources,
)
from wengold.wave import from_vcd


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--top", default="riscv_core_top")
    parser.add_argument("--yosys", default="yosys")
    parser.add_argument("--frontend", choices=("slang_ast", "slang", "yosys"),
                        default="slang_ast")
    parser.add_argument("--slang", default="slang")
    parser.add_argument("--plugin", default="slang")
    parser.add_argument("--unroll-limit", type=int, default=4096,
                        help="maximum procedural loop iterations for Yosys-Slang")
    parser.add_argument("--vcd", type=Path)
    parser.add_argument("--vcd-root", default="tb_core_top")
    parser.add_argument("--dut-instance", default="u_core")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    root = args.project_root.resolve()
    sources = load_riscv_core_sources(root)
    if args.frontend == "slang_ast":
        graph = elaborate_with_slang_ast(
            root, sources, top=args.top, slang=args.slang)
    else:
        graph = elaborate_with_yosys(
            root, sources, top=args.top, yosys=args.yosys,
            frontend=args.frontend, slang_plugin=args.plugin,
            sv_standard="1800-2017", slang_unroll_limit=args.unroll_limit,
        )
    report = {
        "project": str(root),
        "top": graph["top"],
        "source_count": len(sources),
        "source_files": sources,
        "instance_count": graph["instance_count"],
        "connection_count": graph["connection_count"],
        "connection_unit": graph.get("connection_unit", "port-bit connections"),
        "truncated": graph["truncated"],
        "frontend": graph["frontend"],
        "qualification": graph["qualification"],
        "diagnostics": graph.get("diagnostics", graph.get("warnings", [])),
    }
    if args.vcd:
        if not args.vcd.is_file():
            parser.error(f"VCD capture does not exist: {args.vcd}")
        wave = from_vcd(args.vcd)
        report["waveform"] = {
            "path": str(args.vcd.resolve()),
            "timescale": wave.get("timescale"),
            "samples": wave.get("cycles"),
            "signal_count": len(wave.get("signals", [])),
        }
        report["crossprobe"] = crossprobe_hierarchy_to_vcd(
            graph, wave, vcd_root=args.vcd_root,
            dut_instance=args.dut_instance,
        )
    else:
        report["waveform"] = {
            "status": "NOT RUN",
            "reason": "No RISC-V VCD capture was found/provided. Pass --vcd to validate exact signal mapping.",
        }

    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + chr(10), encoding="utf-8")
    print(rendered)
    if args.vcd and report["crossprobe"]["matched_ports"] == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
