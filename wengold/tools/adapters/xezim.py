"""Xezim SystemVerilog RTL/UVM simulation with explicit test evidence."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil

from ..outcome import Outcome, ToolOutcome, run_tool
from ..registry import TOOL_GROUPS

SPEC = next(t for t in TOOL_GROUPS["simulation"] if t.key == "xezim")
REFERENCE_VERSION = "0.11.6"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_VERSION = re.compile(r"^xezim version (\S+)\s*$", re.M)
_FINISH = re.compile(r"^Simulation finished at time \d+ \(\$finish called\)[ \t]*$", re.M)
_UVM_SUMMARY = re.compile(r"^[ \t]*(?:#[ \t]*)?-{3} UVM Report Summary -{3}[ \t]*$", re.M)
_UVM_COUNTS = re.compile(r"^[ \t]*(?:#[ \t]*)?UVM_(ERROR|FATAL)[ \t]*:[ \t]*(\d+)[ \t]*$", re.M)
_UVM_REPORT = re.compile(r"^[ \t]*(?:#[ \t]*)?UVM_(?:ERROR|FATAL)\b(?![ \t]*:)", re.M)
_NONCONVERGENCE = re.compile(r"^\[WARN\] settle limit was exhausted\b", re.M)


def _project_path(root: Path, name: str, *, directory: bool = False) -> Path:
    p = Path(name)
    resolved = (root / p).resolve()
    if p.is_absolute() or not resolved.is_relative_to(root):
        raise ValueError(f"path must be project-relative: {name}")
    if not (resolved.is_dir() if directory else resolved.is_file()):
        raise ValueError(f"missing project {'directory' if directory else 'source'}: {name}")
    return resolved


def _uvm_source(path: str | Path) -> Path:
    base = Path(path).expanduser().resolve()
    for candidate in (base, base / "src"):
        if (candidate / "uvm_pkg.sv").is_file() and (candidate / "uvm_macros.svh").is_file():
            return candidate
    raise ValueError("select a UVM release root or src directory with uvm_pkg.sv and uvm_macros.svh")


def _simulation_verdict(log: str, rc: int, *, pass_marker: str | None,
                        uvm: bool) -> ToolOutcome:
    if rc < 0 or rc == 3:  # signal or Xezim's stalled-clock watchdog
        return ToolOutcome.ERROR
    summaries = list(_UVM_SUMMARY.finditer(log)) if uvm else []
    counts = _UVM_COUNTS.findall(log[summaries[-1].end():]) if summaries else []
    if uvm and (_UVM_REPORT.search(log) or any(int(count) for _, count in counts)):
        return ToolOutcome.FAIL
    if rc != 0:
        # A frontend failure and a runtime severity can both exit 1. A
        # completed simulation footer distinguishes the latter from setup errors.
        if re.search(r"^Simulation finished at time \d+", log, re.M):
            return ToolOutcome.FAIL
        return ToolOutcome.ERROR
    finish = _FINISH.search(log)
    if _NONCONVERGENCE.search(log) or not finish:
        return ToolOutcome.INCONCLUSIVE
    if uvm and (len(counts) != 2 or {kind for kind, _ in counts} != {"ERROR", "FATAL"}):
        return ToolOutcome.INCONCLUSIVE
    if pass_marker is not None and not any(line.strip() == pass_marker
                                           for line in log[:finish.start()].splitlines()):
        return ToolOutcome.INCONCLUSIVE
    if not uvm and pass_marker is None:
        return ToolOutcome.INCONCLUSIVE
    return ToolOutcome.PASS


class XezimAdapter:
    spec = SPEC

    def __init__(self, binary: str = "xezim"):
        self.binary = binary

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def run(self, *, top: str, files: list[str], cwd: str | Path = ".",
            include_dirs: list[str] | tuple[str, ...] = (),
            defines: list[str] | tuple[str, ...] = (),
            seed: int = 1, timeout: float = 120, pass_marker: str | None = None,
            uvm_dir: str | Path | None = None, uvm_test: str | None = None) -> Outcome:
        root = Path(cwd).resolve()
        if not _IDENTIFIER.fullmatch(top) or not files:
            raise ValueError("Xezim requires a top module identifier and ordered source files")
        if not 0 <= seed <= (1 << 64) - 1 or not 1 <= timeout <= 900:
            raise ValueError("seed must be unsigned 64-bit and timeout between 1 and 900 seconds")
        if pass_marker is not None and (not pass_marker.strip() or len(pass_marker) > 160
                                        or len(pass_marker.splitlines()) != 1):
            raise ValueError("pass marker must be one nonempty line (up to 160 characters)")
        if uvm_test is not None and (uvm_dir is None or
                                     not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$:]*", uvm_test)):
            raise ValueError("UVM test selection requires --uvm-dir and a test name")
        sources = [_project_path(root, name) for name in files]
        if any(p.suffix.lower() not in {".sv", ".v", ".svh", ".vh"} for p in sources):
            raise ValueError("Xezim source files must be Verilog or SystemVerilog")
        includes = [_project_path(root, name, directory=True) for name in include_dirs]
        argv = ["--simulate", "--strict-top", "--error-exit", "--no-cache", "-s", top]
        if uvm_dir is not None:
            if any(p.name.lower() == "uvm_pkg.sv" for p in sources):
                raise ValueError("--uvm-dir selects the UVM package; do not also list uvm_pkg.sv")
            lib = _uvm_source(uvm_dir)
            includes.append(lib)
            sources.insert(0, lib / "uvm_pkg.sv")
        for name in defines:
            key, _, value = name.partition("=")
            if not _IDENTIFIER.fullmatch(key) or any(c in value for c in "\r\n\0"):
                raise ValueError(f"invalid preprocessor definition: {key}")
            argv += ["-D", name]
        for include in includes:
            argv += ["-I", str(include)]
        argv += [str(p) for p in sources] + [f"+seed={seed}"]
        if uvm_test is not None:
            argv.append(f"+UVM_TESTNAME={uvm_test}")
        found = shutil.which(self.binary)
        binary = str(Path(found).resolve()) if found else self.binary
        # Do not inherit flags that change what an evidence run simulates,
        # such as XEZIM_INIT_REG or a different UVM library selection.
        env = {k: v for k, v in os.environ.items() if not k.startswith("XEZIM_")}
        version = run_tool(binary, ["-V"], tool="xezim", action="version",
                           cwd=str(root), timeout=min(5, timeout), env=env)
        if version.outcome is not ToolOutcome.PASS:
            version.action = "simulate"
            # A rc-based probe FAIL is an execution error, not a failed test.
            if version.outcome is ToolOutcome.FAIL:
                version.outcome = ToolOutcome.ERROR
            return version
        match = _VERSION.search(version.log)
        if not match:
            return Outcome("xezim", "simulate", ToolOutcome.ERROR, rc=version.rc,
                           log="Xezim version probe returned no version.\n" + version.log,
                           spec=version.spec)
        result = run_tool(binary, argv, tool="xezim", action="simulate", timeout=timeout,
                          cwd=str(root), env=env,
                          interpret=lambda log, rc: _simulation_verdict(
                              log, rc, pass_marker=pass_marker.strip() if pass_marker else None,
                              uvm=uvm_dir is not None))
        result.spec.update(version=match[1], reference_version=REFERENCE_VERSION,
                           seed=seed, top=top, timeout_seconds=timeout,
                           mode="uvm" if uvm_dir is not None else "rtl",
                           pass_marker=pass_marker, uvm_test=uvm_test,
                           scope="testbench-reported simulation only, not signoff")
        return result
