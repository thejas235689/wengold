"""Reproducible evidence.

A verdict is only as good as the ability to re-check it. Every result is bound
to the exact inputs it consumed (RTL, testbench, assertions, constraints), the
exact run that produced it (tool, version, arguments, seed, working directory,
timeout) and a fingerprint of the environment. Together those give a `repro`
hash: change any of them and the evidence no longer describes the current design,
so the kernel must treat the result as stale rather than valid.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

ENV_KEYS = (
    "SIM", "TOPLEVEL", "MODULE", "SEED", "VERILATOR_ROOT", "PATH_HASH",
    "WENGOLD_TOOLCHAIN", "CONDA_DEFAULT_ENV", "VIRTUAL_ENV",
)


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def digest_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:16]


def digest_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()[:16]


def tool_version(binary: str | None, timeout: float = 10.0) -> str | None:
    if not binary or shutil.which(binary) is None:
        return None
    for flag in ("--version", "-V", "-version"):
        try:
            p = subprocess.run([binary, flag], capture_output=True, text=True, timeout=timeout)
        except Exception:
            continue
        out = (p.stdout or p.stderr or "").strip()
        if out:
            return out.splitlines()[0][:120]
    return None


def env_fingerprint(keys: tuple[str, ...] = ENV_KEYS) -> dict:
    """A stable fingerprint of the environment a run happened in."""
    return {
        "python": sys.version.split()[0],
        "platform": f"{platform.system()}-{platform.release()}-{platform.machine()}",
        "env": {k: os.environ[k] for k in keys if k in os.environ},
    }


@dataclass(frozen=True)
class DesignInputs:
    """The design-side inputs a result consumed, as (path, digest) pairs."""
    rtl: tuple[tuple[str, str], ...] = ()
    testbench: tuple[tuple[str, str], ...] = ()
    assertions: tuple[tuple[str, str], ...] = ()
    constraints: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_files(cls, rtl=(), testbench=(), assertions=(), constraints=()) -> "DesignInputs":
        def pair(paths):
            out = []
            for p in paths:
                try:
                    out.append((p, digest_file(p)))
                except OSError:
                    out.append((p, "missing"))
            return tuple(sorted(out))
        return cls(pair(rtl), pair(testbench), pair(assertions), pair(constraints))

    def as_dict(self) -> dict:
        return {"rtl": dict(self.rtl), "testbench": dict(self.testbench),
                "assertions": dict(self.assertions), "constraints": dict(self.constraints)}

    def digest(self) -> str:
        return digest_text(_canonical(self.as_dict()))


@dataclass(frozen=True)
class RunSpec:
    """The run-side inputs a result was produced by."""
    tool: str
    argv: tuple[str, ...] = ()
    tool_version: str | None = None
    seed: int | None = None
    cwd: str | None = None
    timeout: float | None = None
    env: tuple[tuple[str, str], ...] = ()

    @classmethod
    def make(cls, tool: str, argv=(), binary: str | None = None, seed=None,
             cwd=None, timeout=None, env: dict | None = None) -> "RunSpec":
        return cls(
            tool=tool,
            argv=tuple(str(a) for a in argv),
            tool_version=tool_version(binary or tool),
            seed=seed,
            cwd=cwd,
            timeout=timeout,
            env=tuple(sorted((env or {}).items())),
        )

    def as_dict(self) -> dict:
        return {"tool": self.tool, "argv": list(self.argv), "tool_version": self.tool_version,
                "seed": self.seed, "cwd": self.cwd, "timeout": self.timeout,
                "env": dict(self.env)}

    def digest(self) -> str:
        return digest_text(_canonical(self.as_dict()))


def repro_hash(inputs: DesignInputs, run: RunSpec, env: dict | None = None) -> str:
    """One hash over the inputs, the run and the environment."""
    return digest_text(_canonical({
        "inputs": inputs.digest(),
        "run": run.digest(),
        "env": env if env is not None else env_fingerprint(),
    }))
