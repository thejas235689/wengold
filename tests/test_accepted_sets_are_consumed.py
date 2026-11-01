"""Accepted input must actually do something.

The registry in `tests/fixtures/input_formats.json` records where each accepted
set's evidence comes from. Two of the four entries were self-referential: the
loader checked against our own examples, and the app's command list checked against
a hint bar derived from the same tuple.

These two tests make those independent, by comparing against a *second*
implementation rather than against themselves:

  * `desktop.py` declares its commands in a tuple **and** dispatches them in an
    `if verb == ...` chain. The two are separate code and can drift — a verb in the
    tuple with no branch falls through and returns nothing.

  * `generate/spec.py` accepts a set of keys, and `emit.py` consumes them. A key the
    loader accepts but the emitter ignores is a spec that parses and silently
    produces nothing, which is the worst outcome for a generator. Tested
    behaviourally: delete the key from a real example and the output must change,
    or the key must be required.
"""
import copy
import dataclasses
import inspect
import re
from pathlib import Path

import pytest
import yaml

from wengold import desktop

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "timer" / "timer.spec.yaml"


# ---- the app's command list vs its dispatch chain ------------------------
def test_every_declared_command_has_a_dispatch_branch():
    """A verb in CLI_COMMANDS with no branch falls through and returns nothing."""
    branches = set(re.findall(r'verb == "([a-z]+)"',
                              inspect.getsource(desktop._exec)))
    declared = set(desktop.CLI_COMMANDS)
    assert declared, "CLI_COMMANDS is empty"
    assert not declared - branches, (
        f"{sorted(declared - branches)} are listed in CLI_COMMANDS but _exec has no "
        f"branch for them")


def test_every_dispatch_branch_is_declared():
    """The other direction: an unreachable branch is dead code that looks live."""
    branches = set(re.findall(r'verb == "([a-z]+)"',
                              inspect.getsource(desktop._exec)))
    declared = set(desktop.CLI_COMMANDS)
    assert not branches - declared, (
        f"{sorted(branches - declared)} are dispatched but not in CLI_COMMANDS, so "
        f"the `verb not in CLI_COMMANDS` guard rejects them first")


def test_each_declared_command_actually_runs(tmp_path):
    """Not just a branch — a call that returns something."""
    (tmp_path / "a.sv").write_text(
        "module a(input logic c, output logic q);\n  assign q = c;\nendmodule\n")
    state = desktop.build_state(str(tmp_path))
    for verb in desktop.CLI_COMMANDS:
        out = desktop._exec(state, verb)
        assert isinstance(out, dict), verb
        assert "ok" in out, verb


# ---- the spec keys vs what the emitter consumes --------------------------
def _emit(spec_dict, tmp_path):
    from wengold.generate.emit import emit_rtl
    from wengold.generate.spec import load_spec

    p = tmp_path / "s.spec.yaml"
    p.write_text(yaml.safe_dump(spec_dict))
    return emit_rtl(load_spec(str(p)))


def _perturb(value):
    """A type-appropriate change that the emitter could not possibly ignore."""
    if isinstance(value, str):
        return value + "_perturbed"
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 7
    if isinstance(value, list):
        return list(value) + (list(value)[:1] if value else [])
    if isinstance(value, dict):
        d = dict(value)
        d["_perturbed"] = 1
        return d
    return value


def _example_keys():
    keys = set()
    for f in ROOT.glob("examples/**/*.spec.yaml"):
        keys |= set(yaml.safe_load(f.read_text()))
    return sorted(keys)


#: keys no example uses, each with the test that proves it is consumed anyway.
#: An entry here is a promise, not an exemption.
COVERED_ELSEWHERE = {
    "name": "test_name_is_an_alias_for_module",
}


def test_every_accepted_key_appears_in_a_shipped_example():
    """Without this, a key added to `_TOP_KEYS` but absent from every example is
    never exercised by the perturbation test below — which is how an ignored key
    would slip through. It found `name` the first time it ran."""
    from wengold.generate.spec import _TOP_KEYS

    covered = set(_example_keys()) | set(COVERED_ELSEWHERE)
    missing = sorted(_TOP_KEYS - covered)
    assert not missing, (
        f"{missing} are accepted by the loader but no shipped example uses them and "
        f"no test covers them, so nothing proves the emitter consumes them")


def test_every_covered_elsewhere_key_names_a_real_test():
    """The allowlist must not become a place to hide."""
    src = Path(__file__).read_text()
    for key, test in COVERED_ELSEWHERE.items():
        assert f"def {test}(" in src, f"{key} names {test}, which does not exist"


def test_name_is_an_alias_for_module(tmp_path):
    """`name:` is accepted as an alternative spelling of `module:`."""
    from wengold.generate.spec import load_spec

    body = yaml.safe_load(EXAMPLE.read_text())
    body.pop("module")
    body["name"] = "aliased"
    p = tmp_path / "s.spec.yaml"
    p.write_text(yaml.safe_dump(body))
    assert load_spec(str(p)).name == "aliased"


@pytest.mark.parametrize("key", _example_keys())
def test_no_spec_key_is_accepted_and_ignored(key, tmp_path):
    """Perturb the key's value: the output must change, or the loader must reject it.

    Deleting the key is the wrong probe — `clock` and `reset` default to `clk_i`
    and `rst_ni`, which is exactly what the example uses, so deleting them changes
    nothing for a reason that has nothing to do with being ignored. Changing the
    value has no such blind spot.
    """
    from wengold.generate.spec import SpecError

    base = yaml.safe_load(EXAMPLE.read_text())
    full = _emit(base, tmp_path)
    assert full.strip(), "the baseline emits nothing — the test would be vacuous"

    changed = copy.deepcopy(base)
    changed[key] = _perturb(changed[key])
    try:
        out = _emit(changed, tmp_path)
    except (SpecError, KeyError, TypeError):
        return          # rejected: the loader validated it, so it is consumed
    assert out != full, (
        f"perturbing {key!r} changed nothing — the loader accepts it and nothing "
        f"downstream reads it")


def test_the_spec_dataclasses_have_no_unused_field(tmp_path):
    """A field on ModuleSpec that the emitter never reads is the same bug one level
    down, and a source scan gets it wrong for properties like `all_ports`."""
    from wengold.generate import emit
    from wengold.generate.spec import ModuleSpec, Parameter, Port, Register

    src = inspect.getsource(emit)
    for cls in (ModuleSpec, Register, Port, Parameter):
        for f in dataclasses.fields(cls):
            if f.name in src:
                continue
            # properties count: `ports` is consumed through `all_ports`
            assert hasattr(cls, f"all_{f.name}s") or hasattr(cls, f"all_{f.name}"), (
                f"{cls.__name__}.{f.name} is never read by emit.py")
