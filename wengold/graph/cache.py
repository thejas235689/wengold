"""A content-addressed cache for parsed units.

Where the time goes
-------------------
On cva6 (476 SystemVerilog files) indexing takes ~8.5 s and repeats in full on every
run — `agentic` re-perceives between steps, so it pays that cost each time. Splitting
the work:

    preprocess (pp.run)   0.74 s    11%
    extract              6.27 s    89%

Parallelising it does not help: `pyslang` holds the GIL, so a thread pool measured
**0.8x** (slower), and a process pool also measured 0.8x because shipping the file
text and results between processes costs more than the parse.

So the win is not more cores, it is not redoing work.

Why the key is the preprocessed text
------------------------------------
`extract()` is a pure function of the text the preprocessor produced, so caching on
that text is exactly correct. Caching on the *source file* would not be: a file's
`include` resolves against the rest of the file set, so the same source can preprocess
to different text in two projects. Preprocessing therefore always runs — it is the
cheap 11% — and only `extract` is cached.

That also means no invalidation logic and no staleness: identical input, identical
output, keyed by the input itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

__all__ = ["unit_cache", "cache_dir", "disabled", "stats", "clear"]

_LOCK = threading.Lock()
_HITS = 0
_MISSES = 0
_VERSION = "1"


def disabled() -> bool:
    """`WENGOLD_NO_CACHE=1` turns the cache off, for a clean measurement."""
    return os.environ.get("WENGOLD_NO_CACHE", "") not in ("", "0", "false")


def cache_dir() -> Path:
    """Where cached units live. `WENGOLD_CACHE_DIR` overrides, for tests."""
    override = os.environ.get("WENGOLD_CACHE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "wengold" / "units"


def _key(text: str) -> str:
    h = hashlib.sha256()
    h.update(_VERSION.encode())
    h.update(b"\0")
    h.update(text.encode("utf-8", "replace"))
    return h.hexdigest()


def stats() -> dict:
    return {"hits": _HITS, "misses": _MISSES,
            "hit_rate": (_HITS / (_HITS + _MISSES)) if (_HITS + _MISSES) else 0.0}


def clear() -> int:
    """Remove every cached unit. Returns how many files were deleted."""
    d = cache_dir()
    n = 0
    if d.is_dir():
        for p in d.glob("*.json"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    return n


class UnitCache:
    """get/put of a parsed unit, keyed by the text it was parsed from."""

    def __init__(self, directory: Path | None = None):
        self.dir = directory or cache_dir()

    def _path(self, key: str) -> Path:
        # two levels, so a directory with 100k entries stays usable
        return self.dir / key[:2] / f"{key}.json"

    def get(self, text: str) -> dict | None:
        global _HITS, _MISSES
        if disabled():
            return None
        p = self._path(_key(text))
        try:
            with p.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            with _LOCK:
                _MISSES += 1
            return None
        with _LOCK:
            _HITS += 1
        return data

    def put(self, text: str, unit: dict) -> None:
        if disabled():
            return
        p = self._path(_key(text))
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(unit, f)
            os.replace(tmp, p)          # atomic: a reader never sees a half file
        except OSError:
            # a cache that cannot write is a cache that misses, not an error
            pass


_DEFAULT: UnitCache | None = None


def unit_cache() -> UnitCache:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = UnitCache()
    return _DEFAULT
