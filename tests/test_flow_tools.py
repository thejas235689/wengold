"""03 · Around the flow."""
from wengold.tools.registry import tools_in_group

GROUP = tools_in_group("flow")


def _by(key):
    return next(t for t in GROUP if t.key == key)


def test_vcs_forges_and_tracker():
    assert _by("git").role == "vcs"
    assert {_by(k).role for k in ("github", "gitlab")} == {"forge"}
    assert _by("jira").role == "tracker"
    assert _by("slack").role == "chat"


def test_scripting_and_build():
    assert {_by(k).role for k in ("tcl", "python")} == {"script"}
    assert _by("make").role == "build"
