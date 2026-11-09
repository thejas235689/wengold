"""The Linux installer, run for real.

A bug found while writing the Rocky Linux guide: the launcher executed the *GUI*
(`wengold.native`) rather than the CLI, so on an installed copy every subcommand
opened a window — `wengold --version` and `wengold cdc file.sv` both tried to start
Qt. The installer's own verification ran the launcher with `|| true`, so it passed.

These tests run the installer into a throwaway HOME and then use the result the way
a user would.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "linux" / "install.sh"

pytestmark = pytest.mark.skipif(not INSTALL.exists(), reason="no linux/install.sh")


@pytest.fixture
def home(tmp_path):
    """A throwaway HOME with the repo reachable from it."""
    h = tmp_path / "home"
    h.mkdir()
    env = dict(os.environ, HOME=str(h), PYTHONPATH=str(REPO))
    r = subprocess.run(["sh", str(INSTALL)], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=180)
    return h, env, r


def test_the_installer_verifies_its_own_result(home):
    h, env, r = home
    assert r.returncode == 0, r.stdout + r.stderr
    assert "launcher answers --version" in r.stdout, r.stdout


def test_the_launcher_runs_the_cli_not_the_gui(home):
    """`wengold --version` must print a version. It used to start Qt."""
    h, env, r = home
    out = subprocess.run([str(h / ".local/bin/wengold"), "--version"],
                         env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "wengold" in out.stdout


def test_a_subcommand_reaches_the_cli(home):
    h, env, r = home
    out = subprocess.run([str(h / ".local/bin/wengold"), "cdc", "--help"],
                         env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "ipxact" in out.stdout or "--scenarios" in out.stdout


def test_the_desktop_entry_starts_the_window(home):
    """The menu entry is the one place the GUI is the right entry point."""
    h, env, r = home
    entry = (h / ".local/share/applications/wengold.desktop").read_text()
    assert "desktop" in entry.split("Exec=")[1].split("\n")[0]


def test_uninstall_removes_exactly_what_it_made(home):
    h, env, r = home
    assert (h / ".local/share/wengold").is_dir()
    subprocess.run(["sh", str(REPO / "linux/uninstall.sh")], cwd=REPO, env=env,
                   capture_output=True, text=True, timeout=120)
    assert not (h / ".local/share/wengold").exists()
    assert not (h / ".local/bin/wengold").exists()


def test_the_installer_refuses_when_copied_away_from_the_package(tmp_path):
    """It must not half-install from a stray copy.

    The script finds the repo from its own location, not the current directory, so
    running it from any cwd inside a checkout is fine — this checks the case that
    matters: a copy of install.sh with no `wengold/` beside it.
    """
    stray = tmp_path / "linux"
    stray.mkdir()
    shutil.copy(INSTALL, stray / "install.sh")
    r = subprocess.run(["sh", str(stray / "install.sh")], cwd=tmp_path,
                       env=dict(os.environ, HOME=str(tmp_path)),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "checkout" in (r.stdout + r.stderr)
