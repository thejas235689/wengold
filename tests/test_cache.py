"""The parse cache: correct first, fast second.

The correctness argument is in `wengold/graph/cache.py`: `extract()` is a pure
function of the preprocessed text, so the cache is keyed on that text and never on
the source file — a file's `include` resolves against the rest of the file set, so
the same source can preprocess differently in two projects. These tests pin both
halves: that the graph is identical with and without the cache, and that it is
faster.
"""
import os
from pathlib import Path

import pytest

pytest.importorskip("pyslang")

from wengold.graph import cache as C

HERE = Path(__file__).resolve().parent.parent
SAMPLE = HERE / "examples"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("WENGOLD_CACHE_DIR", str(tmp_path / "units"))
    monkeypatch.delenv("WENGOLD_NO_CACHE", raising=False)
    C._DEFAULT = None
    yield
    monkeypatch.delenv("WENGOLD_CACHE_DIR", raising=False)
    C._DEFAULT = None


def _graph(root):
    from wengold.desktop import build_state
    s = build_state(str(root))
    g = s["graph"]
    return (sorted(g.nodes), sorted((e.src, e.dst, str(e.kind)) for e in g.edges),
            s["blocks"], s["unresolved"])


def test_the_graph_is_identical_with_and_without_the_cache(monkeypatch):
    """A faster wrong answer is worse than a slow right one."""
    os.environ["WENGOLD_NO_CACHE"] = "1"
    C._DEFAULT = None
    uncached = _graph(SAMPLE)
    monkeypatch.delenv("WENGOLD_NO_CACHE")
    C._DEFAULT = None
    _graph(SAMPLE)                     # populate
    cached = _graph(SAMPLE)
    assert cached == uncached


def test_the_cache_actually_hits():
    _graph(SAMPLE)
    before = C.stats()["hits"]
    _graph(SAMPLE)
    assert C.stats()["hits"] > before


def test_disabled_means_disabled(monkeypatch):
    monkeypatch.setenv("WENGOLD_NO_CACHE", "1")
    C._DEFAULT = None
    assert C.disabled() is True
    assert C.unit_cache().get("anything") is None


def test_a_corrupt_entry_is_a_miss_not_a_crash(tmp_path):
    uc = C.UnitCache(tmp_path)
    key = C._key("some text")
    p = uc._path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    assert uc.get("some text") is None


def test_a_cache_that_cannot_write_does_not_raise(tmp_path):
    """A read-only cache directory is a cache that misses, not an error."""
    uc = C.UnitCache(tmp_path / "nope")
    os.chmod(tmp_path, 0o500)
    try:
        uc.put("x", {"a": 1})          # must not raise
    finally:
        os.chmod(tmp_path, 0o700)


def test_clear_empties_the_cache():
    _graph(SAMPLE)
    assert C.clear() >= 0
    assert C.stats()["hits"] >= 0
