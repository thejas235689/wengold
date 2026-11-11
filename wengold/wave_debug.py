"""Evidence-first RTL and testbench waveform diagnostics.

Classifications are heuristic unless explicit DUT/TB scope prefixes are given.
Rules produce candidates, not proven causal statements. The local LLM may only
explain the bounded evidence selected here; it does not generate findings.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

MAX_FINDINGS = 80
TB_TOKENS = {"tb", "testbench", "uvm", "uvm_test_top", "env", "agent",
             "driver", "monitor", "scoreboard", "seqr", "sequencer", "checker"}
DUT_TOKENS = {"dut", "u_dut", "design", "rtl", "core", "u_core", "soc", "u_soc"}


def _matches_prefix(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes if p)


def classify(name: str, dut_roots: tuple[str, ...] = (),
             tb_roots: tuple[str, ...] = ()) -> str:
    """Classify hierarchical names; nested DUT overrides enclosing TB."""
    explicit_dut = _matches_prefix(name, dut_roots)
    explicit_tb = _matches_prefix(name, tb_roots)
    if explicit_dut and not explicit_tb:
        return "rtl"
    if explicit_tb and not explicit_dut:
        return "testbench"
    if explicit_dut and explicit_tb:
        return "ambiguous"
    parts = [p.lower() for p in name.split(".")[:-1]]
    if any(p in DUT_TOKENS for p in parts):
        return "rtl"
    if any(p in TB_TOKENS for p in parts):
        return "testbench"
    return "unclassified"


def _samples(wave: dict):
    times = wave.get("times") or list(range(wave.get("cycles", 0)))
    count = min(len(times), wave.get("cycles", len(times)), 4000)
    return times[:count], count


def diagnose(wave: dict, *, dut_roots: tuple[str, ...] = (),
             tb_roots: tuple[str, ...] = (), handshake_window: int = 6,
             max_findings: int = MAX_FINDINGS) -> dict:
    if not 1 <= handshake_window <= 256 or not 1 <= max_findings <= MAX_FINDINGS:
        raise ValueError("invalid diagnostic limits")
    times, n = _samples(wave)
    rows = []
    values = {}
    classification = {}
    for s in wave.get("signals", [])[:500]:
        name = s.get("name")
        if not isinstance(name, str) or not name:
            continue
        vals = list(s.get("values", []))[:n]
        if len(vals) < n:
            vals += [None] * (n - len(vals))
        values[name] = vals
        classification[name] = classify(name, dut_roots, tb_roots)
        rows.append({"name": name, "width": s.get("width", 1),
                     "domain": classification[name],
                     "unknown_samples": sum(v is None for v in vals)})
    def evidence(kind, domain, severity, title, index, signals, detail, confidence="candidate"):
        if len(findings) >= max_findings:
            return
        findings.append({
            "rule": kind, "domain": domain, "severity": severity,
            "title": title, "sample_index": index,
            "time": times[index] if 0 <= index < n else None,
            "signals": signals, "observed": detail,
            "assessment": confidence, "source": "observed VCD samples",
        })
    findings = []
    for name, vals in values.items():
        leaf = name.rsplit(".", 1)[-1].lower()
        domain = classification[name]
        if all(v is None for v in vals) and n:
            evidence("all_unknown", domain, "warning", "Signal never resolves from X/Z/unobserved",
                     0, [name], "All captured samples are unknown; check reset, drive, dump scope and four-state propagation.")
        else:
            for i in range(1, n):
                if vals[i] is None and vals[i-1] is not None:
                    evidence("unknown_transition", domain, "warning",
                             "Signal transitions from known to X/Z/unobserved", i, [name],
                             f"Value changed from {vals[i-1]} to unknown.")
                    break
        if ("clk" in leaf or "clock" in leaf) and len(set(v for v in vals if v is not None)) == 1 and n > 3:
            evidence("clock_static", domain, "warning", "Observed clock has no transition",
                     0, [name], "Single resolved clock value across captured timestamps; could be gated or insufficient sampling.")

    # Pair expected and actual signals only when they share a parent scope.
    for actual, actual_values in values.items():
        parts = actual.split(".")
        leaf = parts[-1].lower()
        suffix = next((s for s in ("_actual", "_act", "_got") if leaf.endswith(s)), None)
        if not suffix:
            continue
        root = ".".join(parts[:-1])
        stem = parts[-1][:-len(suffix)]
        expected = next((root + "." + stem + ext if root else stem + ext)
                        for ext in ("_expected", "_exp", "_reference", "_ref")
                        if (root + "." + stem + ext if root else stem + ext) in values), None)
        if expected is None:
            continue
        exp_values = values[expected]
        for i, (a, e) in enumerate(zip(actual_values, exp_values)):
            if a is not None and e is not None and a != e:
                evidence("scoreboard_mismatch", classification[actual], "error",
                         "Expected/actual mismatch observed", i, [expected, actual],
                         f"{expected}={e}; {actual}={a}; equal sampling does not establish clocking skew.")
                break

    # Handshake candidates, grouped by matching hierarchical parent.
    for request, req_vals in values.items():
        parts = request.rsplit(".", 1)
        leaf = parts[-1].lower()
        if leaf not in ("req", "request", "valid"):
            continue
        prefix = parts[0] + "." if len(parts) == 2 else ""
        partners = ("ack", "acknowledge") if leaf in ("req", "request") else ("ready",)
        paired = next((prefix + p for p in partners if prefix + p in values), None)
        if paired is None:
            continue
        resp = values[paired]
        for i in range(1, n):
            if req_vals[i] == 1 and req_vals[i-1] != 1:
                end = min(n, i + handshake_window + 1)
                if all(resp[j] != 1 for j in range(i, end)) and end - i > handshake_window:
                    evidence("handshake_timeout_candidate", classification[request], "warning",
                             "Request without observed response in sampling window",
                             i, [request, paired],
                             f"No response high in {handshake_window + 1} captured timestamps. "
                             "This is a sample-window heuristic, not a protocol timing assertion.")
                    break

    counts = Counter(row["domain"] for row in rows)
    groups = {k: [r for r in rows if r["domain"] == k]
              for k in ("rtl", "testbench", "unclassified", "ambiguous")}
    # This does not assert root cause. It prioritizes investigation using signals.
    findings.sort(key=lambda f: (f["severity"] != "error",
                                 f["sample_index"], f["title"]))
    summary = {
        "rtl_signals": counts["rtl"], "testbench_signals": counts["testbench"],
        "unclassified": counts["unclassified"],
        "ambiguous": counts["ambiguous"], "findings": len(findings),
        "errors": sum(f["severity"] == "error" for f in findings),
        "warnings": sum(f["severity"] == "warning" for f in findings),
    }
    return {
        "status": "diagnostic_candidates_not_proven",
        "source": wave.get("source", "vcd"), "times": times,
        "samples": n, "summary": summary, "groups": groups,
        "findings": findings, "configuration": {
            "dut_roots": list(dut_roots), "testbench_roots": list(tb_roots),
            "handshake_window": handshake_window},
        "limits": ["Heuristic scope classification; user-specified prefixes improve accuracy",
                   "VCD snapshots are not guaranteed clock-aligned transaction samples",
                   "Unknown is X/Z/unobserved collapsed by the existing VCD reader",
                   "No causal proof without simulator event, driver, assertion and source evidence"],
    }


def ai_debug_prompt(report: dict) -> tuple[str, str]:
    """Strip diagnostic output to bounded, explicit facts before local inference."""
    core = {k: report.get(k) for k in (
        "source", "samples", "summary", "configuration", "limits")}
    core["findings"] = report.get("findings", [])[:30]
    message = json.dumps(core, ensure_ascii=False, sort_keys=True)[:15000]
    system = ("You are a semiconductor design verification debug assistant. "
              "You receive evidence from a VCD rule engine; do NOT invent signal "
              "values, simulator commands, assertion results, or source locations. "
              "Separate observed waveform facts, possible RTL causes, possible "
              "testbench causes, and recommended confirming tests. "
              "State that all root causes are HYPOTHESES until independently confirmed.")
    user = ("Investigate these waveform findings. Provide a short ranked triage "
            "with evidence references, distinguishing DUT RTL from testbench/"
            "UVM stimulus/monitor/scoreboard. If unclassified, say so. "
            "Do not claim full proof.\n\n" + message)
    return system, user


def explain_with_local_ai(report: dict, backend: str, endpoint: str, model: str) -> dict:
    from .ai_workbench import model_client
    system, prompt = ai_debug_prompt(report)
    answer = model_client(backend, endpoint, model, timeout=90).ask(prompt, system=system)
    return {"status": "ai_hypotheses_unverified", "answer": answer,
            "model": model, "backend": backend,
            "report_sha256": hashlib.sha256(
                json.dumps(report, sort_keys=True).encode()).hexdigest()}
