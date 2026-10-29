"""A runner that acts on the world instead of on a model of it.

`SimulatedRunner` settles every check it is handed, and says so in its own
docstring: *"This is a model, not a measurement."* That makes the agent loop real
in structure and fictional in effect — it measures how well it orders checks, not
whether any check passed.

This module closes that gap with the tools that actually exist on the machine.
`ToolRunner` shells out to Verilator, Icarus Verilog and Yosys, and reports what
they said.

The hard part is not running a tool. It is deciding what a tool's answer *means*
for a result, and refusing to over-claim:

| the tool said | what it settles |
| --- | --- |
| Verilator reports a lint/elaboration **error** | the check **fails** — a design that does not elaborate cannot simulate |
| Verilator lints **clean** | **nothing**. It compiled. The property was not checked. |
| Yosys elaborates cleanly | **nothing**. It elaborated. Nothing was proved. |
| the tool is not installed | `tool_missing` — never a pass |
| the result maps to no file | `inconclusive` — never a pass |

A lint pass settling a simulation result would be the exact defect this project
keeps finding in itself: a confident answer to a question that was not asked. So
`pass` is only ever returned when a tool genuinely checked the thing.

That means `ToolRunner` settles **fewer** results than `SimulatedRunner` did. That
is the honest direction, and the benchmark in `docs/` reports both.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

__all__ = ["ToolRunner", "Toolchain"]

# A lint or elaboration run on a real core can take a while; a hung tool must not
# hang the agent.
DEFAULT_TIMEOUT = 120

# Errors that mean "the runner handed the tool the wrong inputs", not "the design
# is broken". A missing include, a missing module, a wrong-language file or a
# file-order violation are all our fault; reporting them as a design failure is the
# same confident-wrong-answer shape this module exists to avoid.
_INPUT_PROBLEMS = (
    "must be read before",                     # file order
    "cannot find file containing module",      # module outside our file set
    "cannot find file:",
    "no such file",
    "unexpected identifier-for",               # a VHDL file fed to Verilator
    "define or directive not defined",         # a macro we were not given
    "pinnotfound",                             # a testbench pin with no module
    "pin not found",
)

# The honest consequence of that list: without a project's own build metadata —
# filelist, `define`s, include paths — a lint cannot tell "the design is broken"
# from "we handed the tool an incomplete project". When it cannot tell, it must not
# say "broken". That is why the sweep below settles nothing.


def _is_input_problem(log: str) -> bool:
    low = log.lower()
    return any(p in low for p in _INPUT_PROBLEMS)


class Toolchain:
    """Which of the tools this runner can use are actually installed."""

    NAMES = ("verilator", "iverilog", "vvp", "yosys", "ghdl")

    @classmethod
    def empty(cls) -> "Toolchain":
        """A toolchain that finds nothing.

        Needed because `extra_path` *extends* PATH rather than replacing it — which
        is right for a user pointing at an OSS CAD Suite install, and wrong for
        anyone trying to test the no-tools path on a machine that has the tools.
        """
        tc = cls.__new__(cls)
        tc.found = {}
        return tc

    def __init__(self, extra_path: str | None = None):
        self.found: dict[str, str] = {}
        # `extra_path` is how a user points at an OSS CAD Suite install without
        # editing PATH for the whole session — the suite's `environment` script is
        # not the only way to reach it, and requiring it would be a worse API.
        search = None
        if extra_path:
            search = str(extra_path) + os.pathsep + os.environ.get("PATH", "")
        for name in self.NAMES:
            path = shutil.which(name, path=search)
            if path:
                self.found[name] = path

    def has(self, name: str) -> bool:
        return name in self.found

    def missing(self) -> list[str]:
        return [n for n in self.NAMES if n not in self.found]

    def describe(self) -> str:
        if not self.found:
            return "no simulator or prover found on PATH"
        return ", ".join(f"{n}" for n in self.NAMES if n in self.found)


class ToolRunner:
    """Run a check with a real tool, or say precisely why it could not.

    `graph` and `results` are the same objects the loop already holds: a result's
    `depends_on` names design nodes, and a node names a file. That chain is how a
    result becomes a command line.
    """

    def __init__(self, graph, results, root=".", toolchain: Toolchain | None = None,
                 timeout: int = DEFAULT_TIMEOUT, on_step=None):
        self.graph = graph
        self.results = results
        self.root = Path(root)
        self.tools = toolchain or Toolchain()
        self.timeout = timeout
        self.on_step = on_step
        self.calls: list[str] = []
        # Elaboration is a property of the whole design, so every result on a
        # project asks the identical question. Without this the sweep ran Verilator
        # once per block — 345 identical lint runs on a core like ibex — which is
        # both slow and pointless. Keyed by the exact argv, so a cache hit can only
        # return the answer the tool already gave for the same command.
        self._cache: dict[tuple, tuple[int, str, float]] = {}

    # -- mapping a result to files -----------------------------------------
    def files_for(self, rid: str) -> list[str]:
        """The design files a result rests on, in a stable order."""
        result = self.results.get(rid) if hasattr(self.results, "get") else None
        if result is None:
            return []
        nodes = getattr(result, "depends_on", None) or ()
        out: list[str] = []
        for name in sorted(nodes):
            node = self.graph.nodes.get(name)
            path = getattr(node, "path", None)
            if not path:
                continue
            # Node paths are relative to the process CWD (the graph was built
            # there), not to `root`. Resolving against `root` double-prefixed the
            # project directory and every tool was handed a path that did not
            # exist — which read as "elaboration failed" for a file that lints
            # cleanly. Absolute paths also make `cwd=root` harmless.
            p = Path(str(path))
            if not p.is_absolute():
                candidate = p.resolve()
                if not candidate.exists():
                    alt = (self.root / p).resolve()
                    if alt.exists():
                        candidate = alt
                p = candidate
            if p.exists() and str(p) not in out:
                out.append(str(p))
        return out

    # Verilator reads SystemVerilog. Handing it a `.vhd` produces a wall of syntax
    # errors that look like a broken design and are in fact a wrong tool — which is
    # what the first sweep did to neorv32, whose cache is VHDL.
    VERILOG_SUFFIXES = (".v", ".sv", ".vh", ".svh")
    VHDL_SUFFIXES = (".vhd", ".vhdl")

    def project_files(self, language: str = "verilog") -> list[str]:
        """Every design file in the graph.

        Elaboration is a whole-design property: `soc_top` instantiates `dma`, so
        linting `soc_top.sv` alone reports a missing module and reads as a design
        error. The first version did exactly that and blamed the RTL for its own
        incomplete file list.
        """
        seen: list[str] = []
        for node in self.graph.nodes.values():
            path = getattr(node, "path", None)
            if not path:
                continue
            p = Path(str(path))
            if not p.is_absolute():
                # graph paths are relative to the project root; fall back to the
                # CWD for a graph built elsewhere
                candidate = (self.root / p).resolve()
                if not candidate.exists():
                    candidate = p.resolve()
                p = candidate
            suffix = p.suffix.lower()
            if language == "verilog" and suffix in self.VHDL_SUFFIXES:
                continue
            if language == "vhdl" and suffix in self.VERILOG_SUFFIXES:
                continue
            if p.exists() and str(p) not in seen:
                seen.append(str(p))
        return sorted(seen)

    # -- running -----------------------------------------------------------
    def _run(self, argv: list[str]) -> tuple[int, str, float]:
        key = tuple(argv)
        if key in self._cache:
            rc, out, _secs = self._cache[key]
            return rc, out, 0.0          # cached: no time spent this call
        result = self._run_uncached(argv)
        self._cache[key] = result
        return result

    def _run_uncached(self, argv: list[str]) -> tuple[int, str, float]:
        started = time.monotonic()
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=self.timeout, cwd=str(self.root))
            rc, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return 124, f"timed out after {self.timeout}s", time.monotonic() - started
        except OSError as exc:
            return 127, f"could not execute {argv[0]}: {exc}", \
                time.monotonic() - started
        return rc, out, time.monotonic() - started

    def _outcome(self, rid, kind, tool, outcome, rc, log, secs, note=""):
        rec = {"result": rid, "tool": tool, "outcome": outcome, "rc": rc,
               "kind": kind, "secs": round(secs, 3),
               "log": log[-4000:] if log else "", "note": note}
        if self.on_step:
            try:
                self.on_step(rec)
            except Exception:
                pass
        return rec

    def __call__(self, rid: str, kind: str) -> dict:
        self.calls.append(rid)
        files = self.files_for(rid)
        if not files:
            return self._outcome(
                rid, kind, "none", "inconclusive", 0, "",
                0.0, "the result names no existing design file")

        if kind in ("lint", "sim", "elaborate"):
            return self._lint(rid, kind, files)
        if kind in ("formal", "proof", "assertion"):
            return self._elaborate(rid, kind, files)
        # coverage, regmap, cdc: no tool here answers these, and pretending
        # otherwise is what this module exists to stop
        return self._outcome(
            rid, kind, "none", "inconclusive", 0, "", 0.0,
            f"no installed tool answers a {kind!r} check")

    def _lint(self, rid, kind, files):
        if not self.tools.has("verilator"):
            return self._outcome(rid, kind, "verilator", "tool_missing", 127, "",
                                 0.0, "verilator is not on PATH")
        # the whole design, not just this result's files — see project_files()
        design = self.project_files() or files
        argv = [self.tools.found["verilator"], "--lint-only", "-Wno-fatal", *design]
        rc, log, secs = self._run(argv)
        if rc == 0:
            # linting clean proves the design elaborates. It does NOT prove the
            # property holds, so it settles nothing.
            return self._outcome(
                rid, kind, "verilator", "inconclusive", rc, log, secs,
                "linted clean — the design elaborates, but the check was not run")
        if rc == 124:
            return self._outcome(rid, kind, "verilator", "inconclusive", rc, log,
                                 secs, "verilator timed out")
        if _is_input_problem(log):
            # our file list, our order or our language choice — not the design
            return self._outcome(
                rid, kind, "verilator", "inconclusive", rc, log, secs,
                "the tool rejected the file list, not the design")
        # a real elaboration error is a real failure
        return self._outcome(rid, kind, "verilator", "fail", rc, log, secs,
                             "elaboration failed, so the check cannot pass")

    def _elaborate(self, rid, kind, files):
        if not self.tools.has("yosys"):
            return self._outcome(rid, kind, "yosys", "tool_missing", 127, "",
                                 0.0, "yosys is not on PATH")
        script = "; ".join([*(f"read_verilog -sv {f}" for f in files),
                            "hierarchy -auto-top", "proc"])
        argv = [self.tools.found["yosys"], "-q", "-p", script]
        rc, log, secs = self._run(argv)
        if rc == 0:
            return self._outcome(
                rid, kind, "yosys", "inconclusive", rc, log, secs,
                "elaborated cleanly — nothing was proved")
        if rc == 124:
            return self._outcome(rid, kind, "yosys", "inconclusive", rc, log, secs,
                                 "yosys timed out")
        return self._outcome(rid, kind, "yosys", "fail", rc, log, secs,
                             "elaboration failed, so the proof cannot pass")


def benchmark_against_simulated(graph, results, changed, root=".",
                                max_iters=3) -> dict:
    """Run the same loop twice — once on a model, once on the tools.

    Returns both runs and the counts, so the difference is visible rather than
    asserted. The point is not that the real runner does better; it is that the
    number it reports is measured.
    """
    from .loop import Agent, SimulatedRunner

    sim = Agent(graph, list(results.values()) if hasattr(results, "values")
                else results)
    run_sim = sim.run(changed, SimulatedRunner(), max_iters=max_iters)

    real_runner = ToolRunner(graph, results, root)
    real = Agent(graph, list(results.values()) if hasattr(results, "values")
                 else results)
    run_real = real.run(changed, real_runner, max_iters=max_iters)
    return {"simulated": run_sim, "real": run_real, "toolchain": real_runner.tools}
