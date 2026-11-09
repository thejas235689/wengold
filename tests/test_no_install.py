"""WENGOLD runs with no third-party packages at all.

The graph, the kernel, the front-ends and the CLI are standard library only —
`pyproject.toml` lists numpy, but `import wengold` works without it (verified by
blocking the import). That matters because "I cannot install the tools" should not
stop someone using the tool: `./wengold.sh` needs no pip, no root and no package
manager.

These tests run the CLI with numpy, pyslang, z3 and PyQt6 all blocked, so a
regression that quietly adds a hard dependency fails here.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RUNNER = REPO / "wengold.sh"

BLOCK = '''
import sys
BANNED = {"numpy", "pyslang", "z3", "PyQt6"}

class Block:
    def find_module(self, name, path=None):
        if name.split(".")[0] in BANNED:
            return self
    def load_module(self, name):
        raise ImportError("blocked for this test: " + name)

sys.meta_path.insert(0, Block())
'''


def run_blocked(argv):
    code = BLOCK + (
        "import sys\n"
        f"sys.argv = ['wengold'] + {argv!r}\n"
        "from wengold.cli import main\n"
        "raise SystemExit(main())\n")
    return subprocess.run([sys.executable, "-c", code], cwd=REPO,
                          capture_output=True, text=True, timeout=120,
                          env={"PYTHONPATH": str(REPO)})


def test_version_works_with_no_packages():
    r = run_blocked(["--version"])
    assert r.returncode == 0, r.stderr
    assert "wengold" in r.stdout


def test_doctor_works_with_no_packages_and_says_what_is_missing():
    r = run_blocked(["doctor"])
    assert r.returncode == 0, r.stderr
    assert "pyslang" in r.stdout
    # and it must not pretend the design is complete without it
    assert "MISSING" in r.stdout or "fallback" in r.stdout


def test_indexing_works_with_no_packages(tmp_path):
    (tmp_path / "m.sv").write_text(
        "module m(input logic c, output logic q);\n  assign q = c;\nendmodule\n")
    r = run_blocked(["index", str(tmp_path)])
    assert r.returncode == 0, r.stderr
    assert "module" in r.stdout.lower() or "indexed" in r.stdout.lower()


@pytest.mark.skipif(not RUNNER.exists(), reason="no wengold.sh")
def test_the_runner_finds_an_interpreter_and_reports_extras():
    r = subprocess.run(["sh", str(RUNNER), "--where"], cwd=REPO,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "none of these is required" in r.stdout


@pytest.mark.skipif(not RUNNER.exists(), reason="no wengold.sh")
def test_the_runner_runs_the_cli():
    r = subprocess.run(["sh", str(RUNNER), "--version"], cwd=REPO,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "wengold" in r.stdout
