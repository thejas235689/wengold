"""Explicit four-gate production readiness audit for WENGOLD.

This is not a substitute for independent DV, formal, or foundry signoff.
A gate is only 'executed_with_evidence' when an explicitly selected tool
manifest actually ran and produced new files on this machine. All resulting
engineering assertions remain subject to independent review.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Mapping

from .eda_flows import inspect_manifest, execute_manifest

REQUIRED_GATES = ("local_ai", "uvm", "package_formal", "power",
                  "physical_drc", "physical_lvs", "physical_pex")
FLOW_KINDS = {
    "uvm": "uvm",
    "package_formal": "formal",
    "power": "power",
    "physical_drc": "physical_drc",
    "physical_lvs": "physical_lvs",
    "physical_pex": "physical_pex",
}

def _gate(status: str, *, explanation: str, evidence=None) -> dict:
    return {"status": status, "explanation": explanation,
            "evidence": evidence or {}}

def assess(root: str | Path, *, manifests: Mapping[str, str] | None = None,
           backend: str = "ollama", endpoint: str = "http://127.0.0.1:11434",
           model: str = "", execute: bool = False, probe_ai: bool = False) -> dict:
    """Review manifests without running them unless execute=True.

    Live AI probe is opt-in independently. No third-party binaries or PDK
    assets are fetched, installed, or fabricated here.
    """
    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError("project must be an existing directory")
    configs = dict(manifests or {})
    unknown = set(configs) - set(FLOW_KINDS)
    if unknown:
        raise ValueError("unknown readiness gates: " + ", ".join(sorted(unknown)))
    results = {}
    if not model:
        results["local_ai"] = _gate("not_configured",
            explanation="Select a local model name; model inference has not been exercised.")
    elif not probe_ai:
        results["local_ai"] = _gate("not_executed",
            explanation="A model name is configured; use --probe-ai for a real loopback roundtrip.")
    else:
        try:
            from .ai_workbench import test_connection
            response = test_connection(backend, endpoint, model)
            results["local_ai"] = _gate(
                "live_inference_observed" if response.get("ok") else "failed",
                explanation=("Actual local model response observed, not RTL-quality proof."
                             if response.get("ok") else "Local model did not respond as requested."),
                evidence={"model": model, "backend": backend,
                          "status": response.get("status"),
                          "sample": response.get("sample", "")[:120]})
        except Exception as exc:
            results["local_ai"] = _gate("failed",
                explanation=f"Live local inference failed: {type(exc).__name__}: {exc}")
    for gate, kind in FLOW_KINDS.items():
        manifest = configs.get(gate, "")
        if not manifest:
            results[gate] = _gate("not_configured",
                explanation=f"Review and supply a project-relative {kind!r} EDA manifest.")
            continue
        try:
            info = inspect_manifest(base, manifest)
            if info["kind"] != kind:
                raise ValueError(
                    f"manifest kind {info['kind']!r} does not match expected {kind!r}")
            if not info["artifacts_expected"]:
                raise ValueError("at least one independently generated evidence artifact is required")
            inspection = {
                "manifest": manifest, "manifest_sha256": info["manifest_sha256"],
                "executable": info["executable"],
                "expected_artifacts": info["artifacts_expected"],
            }
            if not execute:
                results[gate] = _gate("configured_not_executed",
                    explanation="Manifest reviewed structurally; actual tool has NOT run.",
                    evidence=inspection)
            else:
                execution = execute_manifest(base, manifest)
                results[gate] = _gate(
                    "executed_with_evidence" if execution["ok"] else "failed",
                    explanation=("Real executable ran and fresh artifact evidence was found; "
                                 "its contents, coverage, constraints and signoff are not yet certified."
                                 if execution["ok"] else
                                 "Tool run did not produce acceptable execution evidence."),
                    evidence={**inspection,
                              "tool_status": execution["status"],
                              "exit_code": execution["exit_code"],
                              "artifacts_sha256": execution["artifacts_sha256"],
                              "missing_artifacts": execution["missing_artifacts"],
                              "stale_artifacts": execution["stale_artifacts"],
                              "log_tail": execution["log"][-1500:]})
        except Exception as exc:
            results[gate] = _gate("failed",
                explanation=f"{type(exc).__name__}: {exc}")
    executed = sum(result["status"] in ("live_inference_observed", "executed_with_evidence")
                   for result in results.values())
    return {
        "project": str(base),
        "execution_opt_in": execute,
        "ai_probe_opt_in": probe_ai,
        "gates": results,
        "observed_gates": executed,
        "required_gates": len(REQUIRED_GATES),
        "all_gates_observed": executed == len(REQUIRED_GATES),
        "signoff": "NOT ESTABLISHED",
        "warnings": [
            "A successful executable and a fresh artifact do NOT prove a correct UVM scoreboard or formal property.",
            "Package-aware formal needs an external frontend/engine with real elaboration and independently checked proof output.",
            "Power and physical design require trusted Liberty/SDC/activity/PDK/rule decks and genuine signoff criteria.",
            "Local AI responses are drafts or explanatory text, never automatic verification signoff.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect WENGOLD local AI, UVM, package-formal and physical signoff readiness")
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument("--uvm-manifest", default="")
    parser.add_argument("--formal-manifest", default="")
    parser.add_argument("--power-manifest", default="")
    parser.add_argument("--drc-manifest", default="")
    parser.add_argument("--lvs-manifest", default="")
    parser.add_argument("--pex-manifest", default="")
    parser.add_argument("--backend", choices=("ollama", "openai"), default="ollama")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="")
    parser.add_argument("--probe-ai", action="store_true",
                        help="make a real roundtrip to the selected local AI server")
    parser.add_argument("--execute", action="store_true",
                        help="EXECUTE all explicitly supplied reviewed tool manifests")
    parser.add_argument("--output", default="",
                        help="write JSON audit to this path in addition to stdout")
    args = parser.parse_args(argv)
    mapping = {
        "uvm": args.uvm_manifest, "package_formal": args.formal_manifest,
        "power": args.power_manifest, "physical_drc": args.drc_manifest,
        "physical_lvs": args.lvs_manifest, "physical_pex": args.pex_manifest,
    }
    try:
        result = assess(args.project, manifests={k: v for k, v in mapping.items() if v},
                        backend=args.backend, endpoint=args.endpoint,
                        model=args.model, execute=args.execute, probe_ai=args.probe_ai)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    output = json.dumps(result, indent=2, sort_keys=True)
    print(output)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    return 0 if result["all_gates_observed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
