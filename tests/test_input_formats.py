"""No format may reject unknown input without evidence that its table is right.

Two releases in a row shipped a checker that refused valid input — the FSL command
tables and then the CDC attributes — because the accepted set was written from
memory. Both times the tests passed, because the tests used the same invented set.

This test is the structural fix: every module that rejects unknown keys, attributes
or commands must be listed in `tests/fixtures/input_formats.json` with the evidence
that its table matches reality. Adding a format without evidence fails here, which
is the only point at which the mistake is cheap.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = Path(__file__).parent / "fixtures" / "input_formats.json"

#: text that means "this module refuses input it does not recognise"
REJECTS = ("unsupported key", "unknown argument", "unknown command",
           "is not one of", "unknown attribute")


def modules_that_reject():
    """Modules whose *code* refuses input it does not recognise.

    Comment lines are stripped first: `agent/runners.py` mentions "unknown
    command" in a comment about a compiler flag, and registering that as a format
    would be worse than the false negative.
    """
    found = set()
    for p in (ROOT / "wengold").rglob("*.py"):
        try:
            lines = p.read_text(errors="replace").splitlines()
        except OSError:
            continue
        code = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
        if any(t in code for t in REJECTS):
            found.add(str(p.relative_to(ROOT)))
    return found


def test_the_registry_covers_every_module_that_rejects_input():
    registry = json.loads(REGISTRY.read_text())["formats"]
    found = modules_that_reject()
    missing = sorted(found - set(registry))
    assert not missing, (
        f"{missing} reject unknown input but are not in "
        f"tests/fixtures/input_formats.json — state what verifies their accepted "
        f"set, or the next invented table ships silently")


def test_every_registry_entry_names_a_real_test():
    registry = json.loads(REGISTRY.read_text())["formats"]
    for module, entry in registry.items():
        assert (ROOT / module).exists(), f"{module} is in the registry but not in the tree"
        test = entry["test"]
        path, _, name = test.partition("::")
        assert (ROOT / path).exists(), f"{module}: {path} does not exist"
        assert f"def {name}(" in (ROOT / path).read_text(), (
            f"{module}: {path} has no {name}")


def test_every_external_fixture_exists_and_is_not_empty():
    registry = json.loads(REGISTRY.read_text())["formats"]
    external = {k: v for k, v in registry.items() if v["evidence"] == "external"}
    assert external, "no format claims external evidence — did the registry get emptied?"
    for module, entry in external.items():
        fixture = ROOT / entry["fixture"]
        assert fixture.exists(), f"{module}: fixture {entry['fixture']} is missing"
        assert len(fixture.read_text()) > 200, f"{module}: fixture looks empty"


def test_the_registry_is_not_a_rubber_stamp():
    """Every entry must say what its evidence is. `evidence: trust me` fails."""
    registry = json.loads(REGISTRY.read_text())["formats"]
    allowed = {"external", "own examples", "internal"}
    for module, entry in registry.items():
        assert entry["evidence"] in allowed, (
            f"{module}: evidence {entry['evidence']!r} is not one of {sorted(allowed)}")
        assert entry["source"].strip(), f"{module}: no source given"
