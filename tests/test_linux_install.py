"""The Linux installer.

A shell installer is easy to write and easy to get wrong in ways nobody notices:
a launcher that points at the checkout instead of the installed copy, a desktop
entry with a relative `Exec`, an uninstaller that leaves half its files behind.

These tests run the scripts for real, into a temporary `HOME`, and check the
result. They skip on non-Linux, because that is the only place they mean anything.
"""
import os
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LINUX = ROOT / "linux"

pytestmark = pytest.mark.skipif(
    not platform.system().lower().startswith("linux"),
    reason="the installer is Linux-only")


def run(script, *args, env=None, cwd=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(["sh", str(LINUX / script), *args],
                          capture_output=True, text=True, env=e,
                          cwd=cwd or ROOT, timeout=240)


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return home


# ---- the files exist and are honest --------------------------------------
@pytest.mark.parametrize("name", ["install.sh", "uninstall.sh", "build-deb.sh",
                                  "wengold.desktop.in", "wengold.svg",
                                  "README.md"])
def test_the_installer_files_are_present(name):
    assert (LINUX / name).exists(), name


def test_the_desktop_template_has_the_fields_a_launcher_needs():
    body = (LINUX / "wengold.desktop.in").read_text()
    for key in ("Type=Application", "Name=WENGOLD", "Exec=@BIN@",
                "Icon=@ICON@", "Categories="):
        assert key in body, key


def test_the_icon_is_valid_svg():
    body = (LINUX / "wengold.svg").read_text()
    assert body.lstrip().startswith("<?xml")
    assert "<svg" in body and "</svg>" in body
    assert 'viewBox="0 0 64 64"' in body


# ---- install -------------------------------------------------------------
def test_install_writes_everything_it_promises(fake_home):
    r = run("install.sh", env={"HOME": str(fake_home)})
    assert r.returncode == 0, r.stderr
    local = fake_home / ".local"
    assert (local / "bin" / "wengold").exists()
    assert (local / "share" / "wengold" / "wengold" / "__init__.py").exists()
    assert (local / "share" / "applications" / "wengold.desktop").exists()
    assert (local / "share" / "icons" / "hicolor" / "scalable" / "apps"
            / "wengold.svg").exists()


def test_the_installed_package_imports_without_the_repo_on_the_path(fake_home):
    """The whole point: it must work after the clone is moved or deleted."""
    run("install.sh", env={"HOME": str(fake_home)})
    lib = fake_home / ".local" / "share" / "wengold"
    r = subprocess.run(
        ["python3", "-c", "import wengold; print(wengold.__version__)"],
        capture_output=True, text=True, cwd="/",
        env={**os.environ, "PYTHONPATH": str(lib)}, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().count(".") == 2


def test_the_launcher_does_not_point_at_the_checkout(fake_home):
    """A launcher that runs the clone breaks the moment the clone moves."""
    run("install.sh", env={"HOME": str(fake_home)})
    body = (fake_home / ".local" / "bin" / "wengold").read_text()
    assert str(ROOT) not in body, "the launcher still refers to the repository"
    assert "wengold.native" in body


def test_the_desktop_entry_uses_an_absolute_exec(fake_home):
    run("install.sh", env={"HOME": str(fake_home)})
    body = (fake_home / ".local" / "share" / "applications"
            / "wengold.desktop").read_text()
    exec_line = [l for l in body.splitlines() if l.startswith("Exec=")][0]
    path = exec_line.split("=", 1)[1].split()[0]
    assert path.startswith("/"), exec_line
    assert Path(path).exists(), f"{path} does not exist"


def test_the_desktop_entry_substitutes_both_placeholders(fake_home):
    run("install.sh", env={"HOME": str(fake_home)})
    body = (fake_home / ".local" / "share" / "applications"
            / "wengold.desktop").read_text()
    assert "@BIN@" not in body and "@ICON@" not in body


def test_install_verifies_itself(fake_home):
    """An installer that does not check its own result is a script that hopes."""
    r = run("install.sh", env={"HOME": str(fake_home)})
    assert "verified:" in r.stdout


def test_check_changes_nothing(fake_home):
    r = run("install.sh", "--check", env={"HOME": str(fake_home)})
    assert r.returncode == 0
    assert not (fake_home / ".local").exists(), "--check created files"


def test_install_into_an_explicit_prefix(tmp_path):
    prefix = tmp_path / "opt"
    r = run("install.sh", "--prefix", str(prefix))
    assert r.returncode == 0, r.stderr
    assert (prefix / "bin" / "wengold").exists()


# ---- uninstall -----------------------------------------------------------
def test_uninstall_removes_everything_install_created(fake_home):
    run("install.sh", env={"HOME": str(fake_home)})
    local = fake_home / ".local"
    assert (local / "bin" / "wengold").exists()
    r = run("uninstall.sh", env={"HOME": str(fake_home)})
    assert r.returncode == 0, r.stderr
    assert not (local / "bin" / "wengold").exists()
    assert not (local / "share" / "wengold").exists()
    assert not (local / "share" / "applications" / "wengold.desktop").exists()
    assert not (local / "share" / "icons" / "hicolor" / "scalable" / "apps"
                / "wengold.svg").exists()


def test_uninstall_leaves_project_data_alone(fake_home):
    """`.tof/` is the user's index, not ours to delete."""
    run("install.sh", env={"HOME": str(fake_home)})
    project = fake_home / "proj"
    (project / ".tof").mkdir(parents=True)
    (project / ".tof" / "index.json").write_text("{}")
    run("uninstall.sh", env={"HOME": str(fake_home)})
    assert (project / ".tof" / "index.json").exists()


def test_uninstall_is_safe_when_nothing_is_installed(fake_home):
    r = run("uninstall.sh", env={"HOME": str(fake_home)})
    assert r.returncode == 0
    assert "nothing to remove" in r.stdout


# ---- the Debian package --------------------------------------------------
@pytest.mark.skipif(shutil.which("dpkg-deb") is None,
                    reason="dpkg-deb is not installed")
def test_build_deb_produces_a_well_formed_package(tmp_path):
    out = tmp_path / "dist"
    r = subprocess.run(["sh", str(LINUX / "build-deb.sh")],
                       capture_output=True, text=True, cwd=ROOT,
                       env={**os.environ, "OUT": str(out)}, timeout=280)
    assert r.returncode == 0, r.stderr
    debs = list(out.glob("wengold_*_all.deb"))
    assert len(debs) == 1, debs

    info = subprocess.run(["dpkg-deb", "--info", str(debs[0])],
                          capture_output=True, text=True, timeout=120).stdout
    assert "Package: wengold" in info
    assert "Architecture: all" in info
    # PyQt6 must not be a hard dependency: without it the app still starts
    assert "Depends: python3" in info
    assert "python3-pyqt6" not in info.split("Depends:")[1].split("\n")[0]

    listing = subprocess.run(["dpkg-deb", "-c", str(debs[0])],
                             capture_output=True, text=True, timeout=120).stdout
    for path in ("./usr/bin/wengold", "./usr/share/applications/wengold.desktop",
                 "./usr/share/icons/hicolor/scalable/apps/wengold.svg"):
        assert path in listing, path
