#!/usr/bin/env python3
"""Real local SystemVerilog LLM smoke: infer -> compile -> optional simulation.

Unlike mock-server tests this REQUIRES an installed local model and Icarus.
Saves a machine-readable evidence report; never claims signoff.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from wengold.ai_workbench import generate, test_connection, validate_rtl


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Real local AI-to-SystemVerilog tool validation")
    parser.add_argument("--project", default=".")
    parser.add_argument("--testbench", default="", help="project-relative self-checking SV testbench")
    parser.add_argument("--top", default="", help="testbench top, e.g. tb")
    parser.add_argument("--output", default="wengold-local-ai-evidence.json")
    args = parser.parse_args(argv)
    backend = os.environ.get("WENGOLD_LLM_BACKEND", "ollama")
    endpoint = os.environ.get("WENGOLD_LLM_URL",
                              "http://127.0.0.1:11434" if backend == "ollama"
                              else "http://127.0.0.1:8080/v1")
    model = os.environ.get("WENGOLD_LLM_MODEL", "").strip()
    if not model:
        print("Set WENGOLD_LLM_MODEL to an installed local coding model", file=sys.stderr)
        return 2
    report = {"model": model, "backend": backend, "endpoint": endpoint,
              "stage": "not_started", "verified": False}
    try:
        probe = test_connection(backend, endpoint, model)
        report["connection"] = probe
        if not probe.get("ok"):
            raise RuntimeError("model does not respond")
        prompt = ("Produce ONLY synthesizable SystemVerilog for a standalone module "
                  "named counter4 with input logic clk, rst_n, en and "
                  "output logic [3:0] count. Active-low asynchronous reset to zero, "
                  "increment on each positive clock edge only if en. No extra modules.")
        candidate = generate("RTL Design", prompt, backend, endpoint, model)
        report["draft_sha256"] = candidate["sha256"]
        report["draft"] = candidate["text"]
        report["stage"] = "generated_draft"
        validation = validate_rtl(candidate["text"], args.project, args.testbench, args.top)
        report["validation"] = validation
        report["stage"] = validation["status"]
        # The only allowed positive outcome is explicitly bounded to the check:
        # no testbench -> syntax-only, not functional verification.
        report["verified"] = False
    except Exception as exc:
        report["stage"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n",
                                     encoding="utf-8")
        print("WENGOLD local model validation:", report["stage"])
        print("Evidence:", args.output)
    return 0 if report["stage"] == "simulation_completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
