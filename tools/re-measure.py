#!/usr/bin/env python3
"""Re-measure the real-project table in RESULTS.md.

Why this exists
---------------
RESULTS.md was taken at v0.27.1 and nobody could re-run it, for two reasons that
this script fixes:

1. **The repository coordinates were never recorded.** The table named projects
   ("neorv32", "Anvil-Pro") but not where to get them, so a re-measurement had to
   guess. A guess that fetches the wrong repository produces a number that looks
   real, which is worse than no number.

2. **The measurement is backend-dependent and the backend was not recorded.** With
   `pyslang` installed the elaborator resolves most modules; without it the code
   falls back to a bounded regex elaborator and reports far fewer blocks and far
   more unresolved nodes. Measured on the same trees:

       repo     with pyslang        without
       ibex     345 blocks, 12 unr  338 blocks, 190 unr
       cva6     458 blocks, 26 unr  503 blocks, 306 unr

   Neither set is wrong — they answer different questions — but only the first is
   comparable to the published table. **This script refuses to report numbers from
   the fallback**, because a table whose values depend silently on what happened to
   be installed is not a measurement.

Usage
-----
    python tools/re-measure.py                 # every repo in the manifest
    python tools/re-measure.py --only neorv32
    python tools/re-measure.py --check         # is this machine able to measure?

The manifest is `tools/repositories.json`. Adding a repository means adding an
owner/repo there, which is the point: the coordinates belong in the repository, not
in somebody's shell history.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "tools" / "repositories.json"


def have_backend() -> tuple[bool, str]:
    """Is the good elaborator available? A missing pyslang is a hard stop."""
    try:
        import pyslang  # noqa: F401
    except ImportError:
        return False, ("pyslang is not installed — the regex fallback reports far "
                       "fewer blocks and far more unresolved nodes, so its numbers "
                       "are not comparable with RESULTS.md")
    return True, "pyslang present"


def fetch(owner: str, repo: str, dest: Path) -> bool:
    """One tarball, no history — a clone would be slow and we do not need it."""
    for ref in ("refs/heads/main", "refs/heads/master"):
        url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
        tgz = dest / "src.tgz"
        r = subprocess.run(["curl", "-sL", "-m", "120", "-o", str(tgz), url],
                           capture_output=True)
        if r.returncode != 0 or not tgz.exists() or tgz.stat().st_size < 20_000:
            continue
        try:
            with tarfile.open(tgz) as t:
                t.extractall(dest, filter="data")
            return True
        except (tarfile.TarError, OSError):
            continue
    return False


def measure(path: Path) -> dict:
    sys.path.insert(0, str(ROOT))
    from wengold.desktop import build_state

    s = build_state(str(path))
    notes = s.get("notes") or []
    if any("fell back" in n for n in notes):
        raise RuntimeError("the regex elaborator was used — refusing to report")
    return {
        "files": s["files"], "nodes": s["nodes"], "edges": s["edges"],
        "blocks": s["blocks"], "unresolved": s["unresolved"],
        "design_units": s["design_units"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="one owner/repo from the manifest")
    ap.add_argument("--check", action="store_true", help="report whether this "
                    "machine can measure, then exit")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    ok, why = have_backend()
    if args.check:
        print(f"  {why}")
        return 0 if ok else 1
    if not ok:
        print(f"  refusing to measure: {why}", file=sys.stderr)
        return 2

    manifest = json.loads(MANIFEST.read_text())
    repos = manifest["repositories"]
    if args.only:
        repos = [r for r in repos if f"{r['owner']}/{r['repo']}" == args.only
                 or r["name"] == args.only]
        if not repos:
            print(f"  {args.only!r} is not in {MANIFEST.name}", file=sys.stderr)
            return 2

    rows = []
    for r in repos:
        slug = f"{r['owner']}/{r['repo']}"
        tmp = Path(tempfile.mkdtemp(prefix="wengold-rm-"))
        try:
            if not fetch(r["owner"], r["repo"], tmp):
                rows.append({"repo": r["name"], "slug": slug, "error": "fetch failed"})
                continue
            m = measure(tmp)
            m.update(repo=r["name"], slug=slug)
            rows.append(m)
        except RuntimeError as e:
            rows.append({"repo": r["name"], "slug": slug, "error": str(e)})
        except Exception as e:                                  # noqa: BLE001
            rows.append({"repo": r["name"], "slug": slug,
                         "error": f"{type(e).__name__}: {e}"})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"  {'repo':<26} {'files':>6} {'nodes':>7} {'edges':>7} "
          f"{'blocks':>7} {'unres':>6} {'design-unit files':>18}")
    for row in rows:
        if "error" in row:
            print(f"  {row['repo']:<26} {row['error']}")
            continue
        du = f"{row['design_units']}/{row['files']}"
        print(f"  {row['repo']:<26} {row['files']:>6} {row['nodes']:>7} "
              f"{row['edges']:>7} {row['blocks']:>7} {row['unresolved']:>6} "
              f"{du:>18}")
    bad = [r for r in rows if "error" in r]
    print(f"\n  {len(rows) - len(bad)} measured, {len(bad)} could not be")
    print("  'design-unit files' is the share of files containing a module, "
          "package or interface — not test coverage.")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
