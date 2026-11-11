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
            ("iverilog", "vvp", "verilator", "satya", "cargo")}


def satya_check(root: str | Path, model_rel: str) -> dict:
    path = project_file(root, model_rel, (".pss", ".psf", ".json"))
    exe = shutil.which("satya")
    if not exe:
        return {"ok": False, "status": "unavailable", "output": "Satya not installed"}
    result = run_tool([exe, "check", str(path)], cwd=str(Path(root).resolve()), timeout=30)
    return {"status": "check_pass" if result["ok"] else "check_failed", **result}
