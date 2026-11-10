"""Obtain the open-source tools WENGOLD can drive.

A verification run reported "simulator-backed verification: blocked because the
external simulators weren't installed", and WENGOLD correctly called its own
checks inconclusive. Honest, and a dead end: the user is told what is missing and
given nothing to do about it.

This module is the thing to do about it. It fetches the YosysHQ OSS CAD Suite —
one archive that contains iverilog, verilator, yosys, ghdl and SymbiYosys — into a
per-user directory, then **runs every binary it installed** before claiming
success. An archive that unpacks but whose binaries abort is not an install.

Deliberate limits:

  * **nothing is installed system-wide.** No root, no `apt`, no writes outside
    `~/.local/share/wengold/tools/`. Uninstalling is deleting one directory.
  * **PATH is not edited.** `--where` prints the export line; changing a user's
    shell profile behind their back is not this tool's call.
  * **the version is pinned** and recorded, so a later run knows what it has.
  * **a failed download is a failure**, never a silent skip. A half-installed
    toolchain that reports "not installed" later is worse than none.

Commercial tools (VCS, Xcelium, JasperGold, ZeBu...) are not obtainable here and
are reported as such rather than pretended.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

__all__ = ["suite_dir", "detect", "install_suite", "probe", "OSS_SUITE_VERSION"]

# Pinned. An unpinned toolchain makes a result unreproducible: the same property
# could pass on one release and fail on the next, with nothing recording which.
OSS_SUITE_VERSION = "20261110"

_BASE = "https://github.com/YosysHQ/oss-cad-suite-build/releases/download"

# The binaries WENGOLD actually drives, and what each is for. Checking these
# rather than "is the directory non-empty" is the difference between an install
# and an unpacked archive.
PROBE = [
    ("iverilog", ["-V"], "SystemVerilog simulation (4-state)"),
    # `vvp` with no argument prints "no input file" and exits 255 by design; -V
    # is the probe that answers "does this binary run".
    ("vvp", ["-V"], "the Icarus runtime"),
    ("verilator", ["--version"], "lint and fast simulation"),
    ("yosys", ["-V"], "synthesis and formal front-end"),
    ("ghdl", ["--version"], "VHDL analysis"),
]


def _platform_tag() -> str:
    """The OSS CAD Suite asset name for this machine."""
    s = platform.system().lower()
    m = platform.machine().lower()
    if s == "linux":
        return "linux-arm64" if m in ("aarch64", "arm64") else "linux-x64"
    if s == "darwin":
        return "macos-arm64" if m in ("aarch64", "arm64") else "macos-x64"
    raise RuntimeError(
        f"no OSS CAD Suite build for {platform.system()} {platform.machine()}. "
        f"Install iverilog and yosys with your system package manager instead.")


def suite_dir() -> Path:
    """Where the suite is installed. One directory, removable in one step."""
    base = os.environ.get("WENGOLD_TOOLS_DIR")
    if base:
        return Path(base)
    return Path.home() / ".local" / "share" / "wengold" / "tools"


def _bin_dir(root: Path) -> Path:
    # the archive unpacks to oss-cad-suite/ with bin/ inside
    for cand in (root / "oss-cad-suite" / "bin", root / "bin", root):
        if (cand / "yosys").exists() or (cand / "iverilog").exists():
            return cand
    return root / "oss-cad-suite" / "bin"


def probe(bin_dir: Path) -> list[dict]:
    """Run each binary. An archive that unpacks but cannot execute is not an install.

    `LD_LIBRARY_PATH` is cleared: the suite ships its own libraries, and an
    inherited path from another toolchain makes every binary abort with a stack
    smashing error that reads as a broken build.
    """
    env = dict(os.environ)
    env.pop("LD_LIBRARY_PATH", None)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    out = []
    for name, args, what in PROBE:
        exe = bin_dir / name
        if not exe.exists():
            out.append({"tool": name, "ok": False, "why": "not in the archive",
                        "what": what})
            continue
        try:
            r = subprocess.run([str(exe), *args], capture_output=True, text=True,
                               timeout=60, env=env)
            text = (r.stdout or r.stderr).strip().splitlines()
            first = text[0][:70] if text else ""
            out.append({"tool": name, "ok": r.returncode == 0, "version": first,
                        "what": what})
        except (OSError, subprocess.SubprocessError) as e:
            out.append({"tool": name, "ok": False, "why": str(e)[:70], "what": what})
    return out


def detect() -> dict:
    """What is already available, without installing anything."""
    bin_dir = _bin_dir(suite_dir())
    if bin_dir.exists():
        results = probe(bin_dir)
        if any(r["ok"] for r in results):
            return {"installed": True, "dir": str(bin_dir), "probe": results,
                    "source": "wengold tools"}
    # fall back to whatever is on PATH
    on_path = {t: shutil.which(t) for t, _, _ in PROBE}
    found = {k: v for k, v in on_path.items() if v}
    return {"installed": bool(found), "dir": None,
            "probe": [{"tool": t, "ok": bool(on_path[t]),
                       "version": on_path[t] or "", "what": w}
                      for t, _, w in PROBE],
            "source": "PATH" if found else None}


def install_suite(dest: Path | None = None, version: str = OSS_SUITE_VERSION,
                  progress=print) -> dict:
    """Download, unpack, and verify. Returns what happened; raises on failure."""
    dest = Path(dest or suite_dir())
    tag = _platform_tag()
    ext = "zip" if tag.startswith("macos") else "tgz"
    # The release tag is dashed (2026-11-10) while the asset name is not
    # (oss-cad-suite-linux-x64-20261110.tgz). Building both from one string gave
    # a 404 that looked like a network problem.
    if len(version) == 8 and version.isdigit():
        rel = f"{version[:4]}-{version[4:6]}-{version[6:]}"
    else:
        rel = version
    url = f"{_BASE}/{rel}/oss-cad-suite-{tag}-{version}.{ext}"

    progress(f"  downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(dest.parent)) as tmp:
        archive = Path(tmp) / f"suite.{ext}"
        try:
            with urllib.request.urlopen(url, timeout=300) as r, \
                    open(archive, "wb") as f:
                shutil.copyfileobj(r, f)
        except Exception as e:                                   # noqa: BLE001
            raise RuntimeError(
                f"could not download the toolchain: {e}. The URL is {url} — if "
                f"this machine has no outbound HTTPS, install iverilog and yosys "
                f"from your package manager and re-run `wengold tools`.") from e

        size = archive.stat().st_size
        progress(f"  downloaded {size // 1024 // 1024} MB, unpacking")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        try:
            if ext == "zip":
                with zipfile.ZipFile(archive) as z:
                    z.extractall(dest)
            else:
                with tarfile.open(archive) as t:
                    t.extractall(dest, filter="data")
        except Exception as e:                                   # noqa: BLE001
            raise RuntimeError(f"could not unpack the archive: {e}") from e

    bin_dir = _bin_dir(dest)
    results = probe(bin_dir)
    working = [r for r in results if r["ok"]]
    if not working:
        raise RuntimeError(
            f"unpacked to {dest} but no binary ran. This is not an install; "
            f"delete {dest} and install iverilog and yosys from your package "
            f"manager instead.")

    (dest / "wengold-tools.json").write_text(json.dumps({
        "version": version, "platform": tag, "url": url, "bin": str(bin_dir),
        "probe": results,
    }, indent=2))

    return {"dir": str(bin_dir), "version": version, "probe": results,
            "working": len(working), "total": len(results)}


def path_line(bin_dir: str | Path) -> str:
    """The export line to print. Printed, never applied."""
    return f'export PATH="{bin_dir}:$PATH"'
