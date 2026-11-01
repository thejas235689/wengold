"""The real-project table must be reproducible, and must refuse to lie.

`tools/re-measure.py` exists because RESULTS.md could not be re-run: the repository
coordinates were never recorded, and the measurement depends on which elaborator is
installed without saying so. Both are fixed in the tool; these tests keep them fixed.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "re-measure.py"
MANIFEST = ROOT / "tools" / "repositories.json"


def test_the_tool_and_manifest_exist():
    assert TOOL.exists(), "tools/re-measure.py is what makes RESULTS.md reproducible"
    assert MANIFEST.exists(), "the coordinates must live in the repository"


def test_every_manifest_entry_has_coordinates():
    """A name without an owner/repo is exactly the defect this fixes."""
    data = json.loads(MANIFEST.read_text())
    repos = data["repositories"]
    assert repos, "the manifest is empty"
    for r in repos:
        assert r.get("owner") and r.get("repo"), f"{r} has no coordinates"
        assert "/" not in r["owner"] and "/" not in r["repo"], r
        assert r.get("name"), r


def test_every_entry_says_how_it_was_verified():
    """A coordinate recovered by searching must record what proved it right.

    Fetching the wrong repository produces a number that looks real, so "found it
    on GitHub" is not evidence. `match` records which recorded values agreed.
    """
    data = json.loads(MANIFEST.read_text())
    legend = data["_evidence_legend"]
    for r in data["repositories"]:
        assert r.get("match") in legend, (
            f"{r['name']}: match={r.get('match')!r} is not in the legend")


def test_the_strongest_evidence_is_the_common_case():
    """If most entries were `unmatched`, the manifest would be mostly guesses."""
    data = json.loads(MANIFEST.read_text())
    matches = [r["match"] for r in data["repositories"]]
    strong = sum(1 for m in matches if m in ("exact", "graph", "blocks"))
    assert strong >= len(matches) - 4, (
        f"only {strong} of {len(matches)} have number-checked evidence")


def test_unrecovered_projects_are_named_with_a_reason():
    """Silently dropping a project from the table would be the old failure mode."""
    data = json.loads(MANIFEST.read_text())
    missing = data.get("_not_recovered") or []
    assert missing, "the unmeasured projects must be listed, not omitted"
    for m in missing:
        assert m.get("name") and m.get("why"), m


def test_the_manifest_says_what_is_missing():
    """The 27 unmeasured projects must be acknowledged, not silently absent."""
    note = json.loads(MANIFEST.read_text())["_note"]
    assert "never recorded" in note
    assert "guessed" in note.lower() or "guess" in note.lower()


def test_the_tool_refuses_without_pyslang():
    """Run it in an interpreter where pyslang cannot be imported."""
    r2 = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); "
         "sys.modules['pyslang'] = None; "
         "import importlib.util as u; "
         "s = u.spec_from_file_location('rm', %r); m = u.module_from_spec(s); "
         "s.loader.exec_module(m); ok, why = m.have_backend(); "
         "print(ok, why)" % (str(ROOT), str(TOOL))],
        capture_output=True, text=True, cwd=str(ROOT))
    assert "False" in r2.stdout, r2.stdout + r2.stderr
    assert "not installed" in r2.stdout


def test_the_tool_names_the_backend_requirement():
    """The docstring is the documentation for why the numbers differ."""
    text = TOOL.read_text()
    assert "pyslang" in text
    assert "refuses to report numbers from the fallback" in text or \
           "refusing to measure" in text


def test_results_md_states_the_reproduction_and_the_backend():
    results = (ROOT / "RESULTS.md").read_text()
    assert "Re-measured at v0.54.5" in results
    assert "refuses to report numbers from" in results
    assert "not test coverage" in results
