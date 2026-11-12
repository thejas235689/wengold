"""Every key our own examples use must be accepted by the spec loader.

This is the check that was missing for the FSL and CDC tables: the loader rejects
unknown keys, so an invented key set rejects valid input. For those two the source
of truth was an external standard; for the spec format it is the examples we ship,
which is weaker but still real — if `examples/timer/timer.spec.yaml` uses a key the
loader refuses, one of the two is wrong and the shipped example is the one users
copy.

The nested key sets are the risk. `_TOP_KEYS` was easy to get right because every
example shows it; `fields`, `ports` and `assigns` are where an invented name would
hide until someone wrote a spec that used it.
"""
from pathlib import Path

import pytest
import yaml

from wengold.generate.spec import _KEY_SETS, _TOP_KEYS, SpecError, load_spec

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = sorted(ROOT.glob("examples/**/*.spec.yaml"))


def test_there_are_examples_to_check():
    assert EXAMPLES, "no example specs found — this test would pass vacuously"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_the_loader_accepts_the_shipped_example(path):
    """The strongest form: the file loads. A key the loader refuses fails here."""
    spec = load_spec(str(path))
    assert spec.name


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_every_top_level_key_is_known(path):
    raw = yaml.safe_load(path.read_text())
    unknown = set(raw) - _TOP_KEYS
    assert not unknown, f"{path.name} uses {sorted(unknown)}, loader accepts {sorted(_TOP_KEYS)}"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_every_nested_key_is_known(path):
    """ports, parameters, registers, fields and assigns each have their own set."""
    raw = yaml.safe_load(path.read_text())
    for section in ("ports", "parameters", "registers"):
        allowed = _KEY_SETS[section]
        for item in raw.get(section) or []:
            unknown = set(item) - allowed
            assert not unknown, (
                f"{path.name}: {section} entry {item.get('name')!r} uses "
                f"{sorted(unknown)}; the loader accepts {sorted(allowed)}")
            for f in item.get("fields") or []:
                unknown = set(f) - _KEY_SETS["fields"]
                assert not unknown, (
                    f"{path.name}: field {f.get('name')!r} uses {sorted(unknown)}; "
                    f"the loader accepts {sorted(_KEY_SETS['fields'])}")


def test_an_unknown_nested_key_is_still_rejected(tmp_path):
    """The acceptance tests above must not have been achieved by loosening this."""
    with pytest.raises(SpecError):
        load_spec(str(_write(tmp := tmp_path / "_k", """
module: t
clock: clk
reset: rst
ports:
  - {name: a, dir: input, width: 1, bogus: 1}
""")))
    tmp.unlink()


def _write(p: Path, text: str) -> Path:
    p.write_text(text)
    return p
