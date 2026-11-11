"""Bounded project file discovery for Linux Silicon Studio.

Separate design RTL, verification/UVM, automation and source lists. This
inventory is intentionally independent from HDL graph elaboration: testbench
scripts are visible in the IDE without being treated as synthesizable RTL.
"""
from __future__ import annotations

from pathlib import Path
import os

RTL_EXT = {".sv", ".svh", ".v", ".vh", ".vhd", ".vhdl"}
AUTOMATION_EXT = {".py", ".tcl", ".do", ".mk", ".sh", ".yaml", ".yml", ".json"}
VERIFICATION_EXT = RTL_EXT | {".pss", ".psf"}
FILELIST_EXT = {".f", ".flist"}
SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "node_modules",
             "target", "build", "dist", ".tox", ".pytest_cache", ".mypy_cache"}
VERIFY_HINTS = {"tb", "testbench", "testbench_uvm", "tests", "test", "verification",
                "verif", "uvm", "dv", "sim", "simulation", "sequences", "agents"}
AUTOMATION_HINTS = {"scripts", "script", "tools", "automation", "ci", "flows",
                    "regression", "regress", "scripts_rtl"}
MAX_FILES = 12000


def category(rel: str) -> str | None:
    path = Path(rel)
    ext = path.suffix.lower()
    parents = {v.lower() for v in path.parts[:-1]}
    name = path.name.lower()
    if ext in FILELIST_EXT or name.startswith("flist."):
        return "filelists"
    if ext in {".pss", ".psf"}:
        return "verification"
    if ext in RTL_EXT:
        leaf = path.stem.lower()
        if parents & VERIFY_HINTS or any(h in leaf for h in (
                "_tb", "tb_", "_test", "_seq", "_driver", "_monitor",
                "_scoreboard", "_agent", "_env", "_checker", "_coverage")):
            return "verification"
        return "design"
    if ext in AUTOMATION_EXT:
        if ext in {".yaml", ".yml", ".json"} and not (parents & AUTOMATION_HINTS):
            return None  # avoid inventorying unrelated metadata/config files
        return "automation"
    return None


def discover(root: str | Path, *, max_files: int = MAX_FILES) -> dict:
    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError("project path must be an existing directory")
    if not 1 <= max_files <= MAX_FILES:
        raise ValueError("max_files outside supported limit")
    categories = {name: [] for name in ("design", "verification", "automation", "filelists")}
    signature = []
    skipped = 0
    for directory, dirs, names in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and
                         not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            kind = category(rel)
            if kind is None:
                continue
            if len(signature) >= max_files:
                skipped += 1
                continue
            try:
                info = path.stat()
            except OSError:
                continue
            categories[kind].append(rel)
            signature.append((rel, info.st_size, info.st_mtime_ns))
    return {
        **categories,
        "counts": {k: len(v) for k, v in categories.items()},
        "total": len(signature), "truncated": bool(skipped),
        "skipped": skipped, "signature": tuple(signature),
    }
