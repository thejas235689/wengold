"""pyslang is optional — `vibe` must not die with a traceback without it.

Found by actually running `wengold vibe` on a machine without pyslang: it exited
with a raw `ModuleNotFoundError` from a module-level import, which reads as a broken
install rather than a missing optional tool. Every other part of the project treats
pyslang as optional and says so; this one did not.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_conform_imports_without_pyslang():
    """Importing the module must work; only *parsing* may need pyslang."""
    code = '''
import sys
class Block:
    def find_module(self, name, path=None):
        if name == "pyslang" or name.startswith("pyslang."):
            return self
    def load_module(self, name):
        raise ImportError("blocked for this test")
sys.meta_path.insert(0, Block())
import wengold.generate.conform as c
print("imported", c._HAVE_SLANG)
'''
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                       capture_output=True, text=True, timeout=120,
                       env={**os.environ, "PYTHONPATH": str(REPO)})
    assert r.returncode == 0, r.stderr
    assert "imported False" in r.stdout


def test_parsing_without_pyslang_refuses_clearly():
    """It must refuse, not imitate the check with a regex — a regex would report
    conformance it had not established."""
    code = '''
import sys
class Block:
    def find_module(self, name, path=None):
        if name == "pyslang" or name.startswith("pyslang."):
            return self
    def load_module(self, name):
        raise ImportError("blocked")
sys.meta_path.insert(0, Block())
from wengold.generate.conform import _parse
try:
    _parse("module m; endmodule")
except RuntimeError as e:
    print("REFUSED:", e)
'''
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                       capture_output=True, text=True, timeout=120,
                       env={**os.environ, "PYTHONPATH": str(REPO)})
    assert r.returncode == 0, r.stderr
    assert "REFUSED" in r.stdout
    assert "pip install" in r.stdout, "it must say how to fix it"


def test_vibe_does_not_traceback_without_pyslang(tmp_path):
    """The command a user actually types."""
    spec = REPO / "examples" / "timer" / "timer.spec.yaml"
    if not spec.exists():
        pytest.skip("no example spec")
    code = '''
import sys
class Block:
    def find_module(self, name, path=None):
        if name == "pyslang" or name.startswith("pyslang."):
            return self
    def load_module(self, name):
        raise ImportError("blocked")
sys.meta_path.insert(0, Block())
sys.argv = ["wengold", "vibe", %r, "--out", %r]
from wengold.cli import main
raise SystemExit(main())
''' % (str(spec), str(tmp_path / "out"))
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                       capture_output=True, text=True, timeout=180,
                       env={**os.environ, "PYTHONPATH": str(REPO)})
    assert "ModuleNotFoundError" not in r.stderr, r.stderr[-400:]
    assert "Traceback" not in r.stderr, r.stderr[-400:]
