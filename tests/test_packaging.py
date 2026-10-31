"""Packaging invariants.

Two strings declare the version — `pyproject.toml` and `wengold/__init__.py` — and
the publish workflow refuses a tag that matches neither. If they disagree, the wheel
is built with one number and reports another, which nobody notices until a user runs
`pip show wengold` and gets a surprise.
"""
import re
from pathlib import Path

import wengold

ROOT = Path(__file__).resolve().parent.parent


def test_the_two_version_strings_agree():
    pyproject = (ROOT / "pyproject.toml").read_text()
    declared = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M).group(1)
    assert declared == wengold.__version__, (
        f"pyproject says {declared}, the package says {wengold.__version__}")


def test_the_version_is_three_numbers():
    assert re.fullmatch(r"\d+\.\d+\.\d+", wengold.__version__), \
        "a publish tag of the form vX.Y.Z must match this"


def test_the_package_has_a_cli_entry_point():
    """The module CLI is how CI and the docs invoke the tool."""
    assert (ROOT / "wengold" / "cli.py").exists()


def test_the_embedded_asset_travels_with_the_package():
    """The desktop app's icon is base64 in `assets.py`, not a file on disk, so the
    wheel does not depend on a path that only exists in the source tree."""
    from wengold.assets import icon_bytes
    data = icon_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 5000


def test_the_publish_workflow_verifies_before_it_uploads():
    """A package that cannot be imported must not reach PyPI."""
    wf = (ROOT / ".github" / "workflows" / "publish.yml").read_text()
    verify = wf.index("Verify the wheel installs and runs")
    upload = wf.index("Publish to PyPI")
    assert verify < upload, "the upload step comes before the verification step"
    assert "python -m wengold.cli --help" in wf


# ---- the release-verification script -------------------------------------
def test_the_verify_script_exists_and_uses_a_fresh_checkout():
    """v0.48.0's note claimed a test count from a working tree, not the repo."""
    script = ROOT / "tools" / "verify-release.sh"
    assert script.exists()
    body = script.read_text()
    assert "codeload.github.com" in body, "it must fetch, not read the local tree"
    assert "mktemp -d" in body, "it must use a throwaway directory"
    assert "env -u PYTHONPATH" in body, "it must not inherit the caller's path"


def test_the_verify_script_does_not_read_the_local_package():
    """If it ran the suite in the repo it would verify the wrong thing.

    The `cd` and the `pytest` are on different physical lines (a line
    continuation), so the check is ordering, not adjacency.
    """
    body = (ROOT / "tools" / "verify-release.sh").read_text()
    cd_at = body.index('cd "$WORK/src"')
    run_at = body.index("pytest")
    assert cd_at < run_at, "the suite is invoked before changing into the checkout"
    assert "env -u PYTHONPATH" in body
