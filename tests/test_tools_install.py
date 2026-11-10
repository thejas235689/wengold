"""`wengold tools` turns "simulators aren't installed" into a working toolchain.

A verification run reported "simulator-backed verification: blocked because the
external simulators weren't installed" and WENGOLD correctly called its checks
inconclusive. Honest, and a dead end. These tests cover the way out.

Nothing here downloads the suite: a test that needs 715 MB and the network is a
test that fails for reasons unrelated to the code.
"""
import os
import platform
from pathlib import Path

import pytest

from wengold.tools.install import (_bin_dir, _platform_tag, detect, path_line,
                                   probe, suite_dir)


def test_the_platform_tag_matches_an_asset_name():
    try:
        tag = _platform_tag()
    except RuntimeError:
        pytest.skip(f"no suite build for {platform.system()}")
    assert tag in ("linux-x64", "linux-arm64", "macos-x64", "macos-arm64")


def test_suite_dir_is_one_removable_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("WENGOLD_TOOLS_DIR", str(tmp_path / "t"))
    d = suite_dir()
    assert d == tmp_path / "t"
    # it must be one directory, removable in one step
    assert d.name == "t" and d.parent == tmp_path


def test_probe_reports_a_missing_binary_rather_than_crashing(tmp_path):
    results = probe(tmp_path)          # empty directory
    assert all(r["ok"] is False for r in results)
    assert {r["tool"] for r in results} >= {"iverilog", "yosys"}


def test_detect_says_not_installed_and_names_the_fix(tmp_path, monkeypatch):
    monkeypatch.setenv("WENGOLD_TOOLS_DIR", str(tmp_path / "absent"))
    monkeypatch.setenv("PATH", "/nonexistent")
    d = detect()
    assert d["installed"] is False
    assert d["probe"], "it must still list what it looked for"


def test_the_path_line_is_printed_not_applied(tmp_path):
    line = path_line(tmp_path / "bin")
    assert line.startswith("export PATH=")
    assert str(tmp_path / "bin") in line


def test_bin_dir_finds_the_suites_layout(tmp_path):
    """The archive unpacks to oss-cad-suite/bin; a real install must be found."""
    binp = tmp_path / "oss-cad-suite" / "bin"
    binp.mkdir(parents=True)
    (binp / "yosys").write_text("")
    assert _bin_dir(tmp_path) == binp


def test_the_runner_finds_the_managed_toolchain_without_path(tmp_path, monkeypatch):
    """`wengold tools --install` is useless if the runner cannot see the result."""
    binp = tmp_path / "oss-cad-suite" / "bin"
    binp.mkdir(parents=True)
    for name in ("iverilog", "vvp", "yosys", "verilator", "ghdl"):
        f = binp / name
        f.write_text("#!/bin/sh\nexit 0\n")
        f.chmod(0o755)
    monkeypatch.setenv("WENGOLD_TOOLS_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", "/nonexistent")
    from wengold.agent.runners import Toolchain
    tc = Toolchain()
    assert tc.has("iverilog"), tc.describe()
    assert tc.has("yosys")


def test_an_empty_toolchain_still_finds_nothing(tmp_path, monkeypatch):
    """The no-tools path must stay testable on a machine that has the tools."""
    monkeypatch.setenv("WENGOLD_TOOLS_DIR", str(tmp_path))
    from wengold.agent.runners import Toolchain
    assert Toolchain.empty().describe() == "no simulator or prover found on PATH"
