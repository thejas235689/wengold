"""Local AI: loopback inference, real compiler evidence, optional Satya PSS check.

An LLM draft is never automatically promoted to verification signoff.
"""
from __future__ import annotations

import hashlib
import ipaddress
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

from .ai_prompts import make_prompt
from .agent.llm import LocalModel, probe


def model_client(backend: str, endpoint: str, model: str, timeout: float = 120.0) -> LocalModel:
    if backend not in ("ollama", "openai"):
        raise ValueError("unsupported backend")
    if not model or len(model) > 200:
        raise ValueError("select a model")
    parsed = urlparse(endpoint)
    try:
        local = ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        local = parsed.hostname == "localhost"
    if parsed.scheme != "http" or not local or parsed.username or parsed.password:
        raise ValueError("local AI endpoint must be HTTP loopback only")
    return LocalModel(model=model, endpoint=endpoint, backend=backend,
                      timeout=timeout, temperature=0.1)


def list_models(backend: str, endpoint: str) -> list[str]:
    model_client(backend, endpoint, "__probe__", 5.0)
    return probe(endpoint, backend, timeout=5.0).models


def generate(profile: str, task: str, backend: str, endpoint: str, model: str) -> dict:
    system, prompt = make_prompt(profile, task)
    client = model_client(backend, endpoint, model)
    client._require_instruction_following("generate engineering artifacts")
    output = client.unfence(client.ask(prompt, system=system))
    if not output.strip():
        raise RuntimeError("empty model result")
    return {"profile": profile, "model": model, "backend": backend, "text": output,
            "sha256": hashlib.sha256(output.encode()).hexdigest(),
            "status": "draft", "validation": "not run"}


def run_tool(argv: list[str], *, cwd: str | None = None, timeout=25) -> dict:
    try:
        p = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return {"ok": p.returncode == 0, "exit_code": p.returncode,
                "output": p.stdout[-16000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": None, "output": "tool timed out"}
    except OSError as exc:
        return {"ok": False, "exit_code": None, "output": str(exc)}


def project_file(root: str | Path, rel: str, suffixes: tuple[str, ...]) -> Path:
    base = Path(root).resolve()
    path = (base / rel).resolve()
    if not rel or Path(rel).is_absolute() or not path.is_relative_to(base):
        raise ValueError("file must be project relative")
    if not path.is_file() or path.suffix.lower() not in suffixes:
        raise ValueError("existing supported project file required")
    return path


def validate_rtl(code: str, root: str | Path, testbench: str = "",
                 top: str = "") -> dict:
    report = {"status": "draft", "syntax": "not_run",
              "simulation": "not_run", "evidence": []}
    if not code.strip():
        report["error"] = "empty source"
        return report
    compiler, simulator = shutil.which("iverilog"), shutil.which("vvp")
    if not compiler:
        report["error"] = "iverilog missing"
        return report
    if testbench and not simulator:
        report["error"] = "vvp missing"
        return report
    if top and not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9$]*", top):
        raise ValueError("invalid top")
    with tempfile.TemporaryDirectory(prefix="wengold-ai-") as tmp:
        rtl = Path(tmp) / "draft.sv"
        rtl.write_text(code)
        syntax = run_tool([compiler, "-g2012", "-tnull", str(rtl)], timeout=20)
        report["syntax"] = "pass" if syntax["ok"] else "fail"
        report["evidence"].append({"stage": "syntax", "tool": "iverilog", **syntax})
        if not syntax["ok"]:
            report["status"] = "failed"
            return report
        report["status"] = "syntax_checked"
        if not testbench:
            report["note"] = "No independent testbench. Functionality is unverified."
            return report
        tb = project_file(root, testbench, (".sv", ".v"))
        output = str(Path(tmp) / "run.vvp")
        argv = [compiler, "-g2012", "-o", output]
        if top:
            argv += ["-s", top]
        compiled = run_tool(argv + [str(rtl), str(tb)], timeout=25)
        report["evidence"].append({"stage": "testbench_compile", "tool": "iverilog", **compiled})
        if not compiled["ok"]:
            report.update(status="failed", simulation="compile_failed")
            return report
        sim = run_tool([simulator, output], cwd=tmp, timeout=25)
        report["evidence"].append({"stage": "simulation", "tool": "vvp", **sim})
        if not sim["ok"] or re.search(r"\b(?:FAIL|ERROR|FATAL)\b", sim["output"], re.I):
            report.update(status="failed", simulation="fail")
        else:
            report.update(status="simulation_completed", simulation="exit_zero")
            report["note"] = ("Simulation exited zero but testbench assertion quality "
                              "and coverage have not been established. Not signoff.")
        return report


def tool_status() -> dict:
    return {tool: bool(shutil.which(tool)) for tool in
            ("iverilog", "vvp", "verilator", "satya", "cargo",
             "vcs", "xrun", "vsim", "ngspice", "klayout")}


def satya_check(root: str | Path, model_rel: str) -> dict:
    path = project_file(root, model_rel, (".pss", ".psf", ".json"))
    exe = shutil.which("satya")
    if not exe:
        return {"ok": False, "status": "unavailable", "output": "Satya not installed"}
    result = run_tool([exe, "check", str(path)], cwd=str(Path(root).resolve()), timeout=30)
    return {"status": "check_pass" if result["ok"] else "check_failed", **result}



def satya_generate_uvm(root: str | Path, model_rel: str) -> dict:
    """Generate UVM sequences with Satya's documented UVM backend.

    This confirms generator invocation only; it does not simulate the sequences.
    """
    path = project_file(root, model_rel, (".pss", ".psf", ".json"))
    exe = shutil.which("satya")
    if not exe:
        return {"ok": False, "status": "unavailable", "output": "Satya not installed"}
    with tempfile.TemporaryDirectory(prefix="wengold-pss-") as tmp:
        output = Path(tmp) / "sequences.sv"
        res = run_tool([exe, "gen", str(path), "--backend", "uvm",
                        "-o", str(output)], cwd=str(Path(root).resolve()), timeout=45)
        if not res["ok"] or not output.is_file():
            return {"ok": False, "status": "generation_failed", **res}
        code = output.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "status": "generated_unverified",
                "output": res["output"], "code": code[:150000],
                "sha256": hashlib.sha256(code.encode()).hexdigest(),
                "note": "Generated UVM code has not been compiled or simulated."}


def rustdv_unit_check(project_root: str | Path, rel: str = "") -> dict:
    """Offline Cargo unit tests only; NOT DUT simulation or UVM conformance.

    rel must name an existing Cargo.toml-containing project directory.
    """
    base = Path(project_root).resolve()
    target = (base / rel).resolve()
    if Path(rel).is_absolute() or not target.is_relative_to(base):
        raise ValueError("RustDV project must be within project root")
    if not target.is_dir() or not (target / "Cargo.toml").is_file():
        raise ValueError("select a RustDV project directory with Cargo.toml")
    cargo = shutil.which("cargo")
    if not cargo:
        return {"ok": False, "status": "unavailable", "output": "Rust cargo not installed"}
    result = run_tool([cargo, "test", "--offline", "--locked"],
                      cwd=str(target), timeout=120)
    return {"status": "unit_tests_pass" if result["ok"] else "unit_tests_failed",
            "scope": "Rust unit tests only; no RTL simulator launched", **result}


def test_connection(backend: str, endpoint: str, model: str) -> dict:
    """Actually round-trip a short instruction through the selected local LLM."""
    info = list_models(backend, endpoint)
    if model not in info:
        return {"ok": False, "status": "model_missing", "models": info}
    client = model_client(backend, endpoint, model, timeout=45.0)
    response = client.ask("Reply with a single word: ready",
                          system="Follow the user's short instruction.")
    return {"ok": bool(response.strip()), "status": "responding",
            "model": model, "backend": backend, "sample": response[:120]}



def rustdv_simulate(project_root: str | Path, rel: str = "",
                    simulator: str = "icarus") -> dict:
    """Invoke rustdv's documented VPI simulation script in an existing checkout.

    This is a script-reported regression status, not independent DUT signoff.
    The engineer must have RustDV and its simulator installed locally.
    """
    base = Path(project_root).resolve()
    target = (base / rel).resolve()
    if Path(rel).is_absolute() or not target.is_relative_to(base):
        raise ValueError("RustDV checkout must be project-relative")
    script = (target / "sim" / "run_rustdv.sh").resolve()
    if not script.is_relative_to(target) or not script.is_file():
        raise ValueError("RustDV sim/run_rustdv.sh not found in checkout")
    if simulator not in ("icarus", "verilator"):
        raise ValueError("supported simulators: icarus or verilator")
    if not shutil.which("bash"):
        return {"status": "unavailable", "ok": False, "output": "bash unavailable"}
    args = ["bash", str(script)]
    if simulator == "verilator":
        args.extend(["release", "verilator"])
    result = run_tool(args, cwd=str(target), timeout=180)
    # The upstream README describes this exact regression marker.
    marker = "REGRESSION: PASS" in result["output"]
    status = "script_reported_pass" if result["ok"] and marker else "regression_failed_or_unconfirmed"
    return {"status": status, "ok": result["ok"] and marker,
            "simulator": simulator, "scope": "RustDV simulator script output, not independent signoff",
            **result}
