#!/usr/bin/env python3
"""OpenPiton -> WENGOLD integration smoke on a checked-out upstream repository.

This checks indexing, desktop state and a standalone Verilog syntax compile.
It DOES NOT assert that OpenPiton's entire SoC is elaborated or simulated.
No third-party RTL is copied into WENGOLD's repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BRIDGE = Path("piton/design/chip/chip_bridge/rtl")
BRIDGE_FILES = (
    "chip_bridge.v",
    "chip_bridge_rcv_32.v",
    "chip_bridge_send_32.v",
    "chip_net_chooser_32.v",
    "sync_fifo.v",
)
REQUIRED = {"chip_bridge", "chip_bridge_in", "chip_bridge_out",
            "bridge_network_chooser", "sync_fifo"}


def run(argv: list[str], *, timeout: int = 120) -> dict:
    try:
        result = subprocess.run(argv, text=True, capture_output=True,
                                timeout=timeout, check=False)
        return {"exit_code": result.returncode, "ok": result.returncode == 0,
                "log": (result.stdout + result.stderr)[-12000:]}
    except subprocess.TimeoutExpired:
        return {"exit_code": None, "ok": False, "log": "timeout"}
    except OSError as exc:
        return {"exit_code": None, "ok": False, "log": str(exc)}


def check(root: Path) -> dict:
    from wengold.desktop import build_state, _exec
    from wengold.graph.builder import GraphBuilder
    root = root.resolve()
    if not (root / "README.md").is_file() or not (root / BRIDGE).is_dir():
        raise ValueError("expected an existing checkout of PrincetonUniversity/openpiton")
    report = {"source": "PrincetonUniversity/openpiton", "scope": "chip_bridge",
              "upstream_root": str(root), "status": "not_run",
              "limitations": [
                  "OpenPiton full-system simulation and coherence are NOT exercised",
                  "Ariane/CVA6 Git submodule is NOT exercised",
                  "No OpenPiton toolchain, UVM regression or software boot is executed",
                  "Missing platform macros can make hierarchy incompleteness legitimate",
              ]}
    with tempfile.TemporaryDirectory(prefix="wengold-openpiton-") as temp:
        subset = Path(temp) / "bridge"
        subset.mkdir()
        source_digests = {}
        for name in BRIDGE_FILES:
            source = root / BRIDGE / name
            if not source.is_file():
                raise FileNotFoundError(str(source))
            data = source.read_bytes()
            (subset / name).write_bytes(data)
            source_digests[name] = hashlib.sha256(data).hexdigest()
        report["rtl_files"] = source_digests

        # The same index command a Linux engineer would use in the CIW/CLI.
        indexed = Path(temp) / "index.json"
        cli = run([sys.executable, "-m", "wengold.cli", "index", str(subset),
                   "--backend", "auto", "--out", str(indexed)], timeout=160)
        report["cli"] = cli
        if not cli["ok"] or not indexed.is_file():
            raise AssertionError("WENGOLD CLI indexing failed: " + cli["log"][-3000:])
        parsed = json.loads(indexed.read_text())
        indexed_modules = {name for name, value in parsed["nodes"].items()
                           if value["kind"] == "rtl"}
        report["indexed_modules"] = sorted(indexed_modules & REQUIRED)
        report["module_count"] = len(indexed_modules)
        report["unresolved"] = parsed["completeness"]["unresolved"]
        report["notes"] = parsed["completeness"].get("issues", [])[:12]
        # Reject indexers that silently drop all design units or miss core files.
        essential = {"chip_bridge", "sync_fifo", "bridge_network_chooser"}
        if not essential.issubset(indexed_modules):
            raise AssertionError("missing expected RTL modules: " +
                                 str(sorted(essential - indexed_modules)))

        state = build_state(str(subset))
        report["desktop_state"] = {
            "files": state["files"], "nodes": state["nodes"],
            "edges": state["edges"], "blocks": state["blocks"],
            "unresolved": state["unresolved"], "complete": state["complete"],
        }
        if state["files"] != len(BRIDGE_FILES) or state["blocks"] < 3:
            raise AssertionError("desktop did not index bridge source files")
        for command in ("summary", "files", "blocks", "help"):
            outcome = _exec(state, command)
            if not outcome["ok"] or not outcome.get("output", "").strip():
                raise AssertionError("CIW command failed: " + command)
        report["ciw_commands"] = ["summary", "files", "blocks", "help"]

        iverilog = shutil.which("iverilog")
        if iverilog:
            syntax = run([iverilog, "-g2012", "-tnull", "-s", "sync_fifo",
                          str(subset / "sync_fifo.v")], timeout=25)
            report["isolated_fifo_syntax"] = syntax
            if not syntax["ok"]:
                raise AssertionError("OpenPiton standalone FIFO failed Icarus syntax")
        else:
            report["isolated_fifo_syntax"] = {
                "ok": None, "status": "not_run", "reason": "iverilog unavailable"}
        report["status"] = "PASS_SUBSYSTEM_SMOKE"
        return report


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--openpiton", required=True, type=Path,
                   help="existing, locally checked-out Princeton OpenPiton repository")
    p.add_argument("--report", type=Path, default=Path("openpiton-wengold-evidence.json"))
    args = p.parse_args(argv)
    began = time.time()
    try:
        result = check(args.openpiton)
        code = 0
    except Exception as exc:
        result = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        code = 1
    result["elapsed_seconds"] = round(time.time() - began, 2)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print("OpenPiton / WENGOLD: " + result["status"])
    print("Evidence: " + str(args.report))
    if code:
        print(result["error"], file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
