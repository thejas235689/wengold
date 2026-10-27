"""The desktop app: the server serves what the kernel actually computed.

The load-bearing test is `test_verdicts_are_read_from_the_kernel_not_guessed`.
The first version iterated `ctx.results` as a sequence when it is a dict keyed by
result id, so every row rendered with an id of `?`, an empty reason, and a verdict
of UNKNOWN — the panel looked broken while the kernel underneath was correct. A
UI that misreports a correct kernel is worse than no UI.
"""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from wengold.desktop import HTML, _handler, build_state

SRC = """module leaf(input logic c, output logic q);
  assign q = c;
endmodule
module mid(input logic c, output logic q);
  leaf u(.c(c), .q(q));
endmodule
module top(input logic c, output logic q);
  mid u(.c(c), .q(q));
endmodule
"""


@pytest.fixture(scope="module")
def state(tmp_path_factory):
    d = tmp_path_factory.mktemp("des")
    (d / "a.sv").write_text(SRC)
    return build_state(str(d))


@pytest.fixture(scope="module")
def server(state):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    yield port
    httpd.shutdown()
    httpd.server_close()


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return r.read()


def get_json(port, path):
    return json.loads(get(port, path))


# ---- state -----------------------------------------------------------------
def test_state_counts_the_design(state):
    assert state["files"] == 1
    assert state["blocks"] == 3
    assert 0 <= state["coverage"] <= 100


def test_state_is_json_safe(state):
    """The graph object must not leak into the API response."""
    payload = {k: v for k, v in state.items() if k not in ("graph", "block_names")}
    json.dumps(payload)          # raises if anything is unserialisable


# ---- endpoints -------------------------------------------------------------
def test_root_serves_html(server):
    body = get(server, "/").decode()
    assert "<!doctype html>" in body.lower()
    assert "WEN" in body and "GOLD" in body


def test_summary_endpoint(server):
    d = get_json(server, "/api/summary")
    assert d["blocks"] == 3 and d["files"] == 1
    assert "graph" not in d, "the graph object must not be sent to the browser"


def test_blocks_endpoint_has_one_row_per_block(server):
    d = get_json(server, "/api/blocks")
    assert len(d["blocks"]) == 3
    assert all({"name", "out", "in"} <= set(r) for r in d["blocks"])


def test_verdicts_are_read_from_the_kernel_not_guessed(server):
    """Every row must carry a real id and a real reason.

    The first version produced `?` / UNKNOWN / "" for every row because it read
    the wrong field. This asserts the ids come from the kernel's own dict.
    """
    d = get_json(server, "/api/verdicts")
    assert d["results"], "the kernel produced no verdicts"
    assert all(r["id"] != "?" for r in d["results"]), \
        f"ids not resolved: {d['results'][:2]}"
    assert any(r["reason"] for r in d["results"]), "no reasons carried through"
    assert d["change"] in {r["id"] for r in d["results"]} or d["change"]


def test_verdict_counts_match_the_rows(server):
    d = get_json(server, "/api/verdicts")
    total = sum(d["counts"].values())
    assert total == len(d["results"]), (d["counts"], len(d["results"]))
    assert set(d["counts"]) <= {"VALID", "INVALIDATED", "UNKNOWN"}


def test_singularity_endpoint(server):
    d = get_json(server, "/api/singularity")
    assert d["blocks"] == 3
    assert d["condition_number"] >= 1.0
    assert isinstance(d["singular"], list)


def test_an_unknown_route_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(server, "/api/nope")
    assert e.value.code == 404


# ---- the shell itself ------------------------------------------------------
def test_the_html_has_no_external_dependencies():
    """A desktop app that needs a CDN is not a desktop app."""
    assert "http://" not in HTML.split("<script>")[0]
    assert "cdn" not in HTML.lower()
    assert "<script src=" not in HTML


# ---- real app window -------------------------------------------------------
def test_a_browser_supporting_app_mode_is_found_or_absent_cleanly():
    """Absence must not raise — a machine without Chrome still runs the app."""
    from wengold.desktop import find_app_browser
    found = find_app_browser()
    assert found is None or isinstance(found, str)


def test_app_mode_passes_app_and_an_isolated_profile(monkeypatch):
    """The separate profile matters: joining the user's session means closing
    the window can take their other tabs with it."""
    import subprocess
    from wengold.desktop import launch_app

    captured = {}

    class FakePopen:
        def __init__(self, args, **kw):
            captured["args"] = args

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    ok = launch_app("http://127.0.0.1:9/", browser="/usr/bin/google-chrome")
    assert ok
    args = captured["args"]
    assert "--app=http://127.0.0.1:9/" in args
    assert any(a.startswith("--user-data-dir=") for a in args)
    assert any(a.startswith("--window-size=") for a in args)


def test_no_browser_means_no_window_not_an_exception():
    from wengold.desktop import launch_app
    assert launch_app("http://127.0.0.1:9/", browser="/nonexistent/browser") is False


def test_the_shortcut_is_a_valid_desktop_entry(tmp_path):
    from wengold.desktop import install_shortcut

    p = install_shortcut(8765, "/tmp/proj", dest=str(tmp_path / "w.desktop"))
    if p is None:
        pytest.skip("no automatic shortcut on this platform")
    body = open(p).read()
    assert body.startswith("[Desktop Entry]")
    for key in ("Type=Application", "Name=WENGOLD", "Exec=", "Icon="):
        assert key in body
    assert "app_mode=True" in body, "the shortcut must open the app, not a tab"


def test_the_icon_is_self_contained():
    """A desktop icon that needs a CDN is not an icon."""
    from wengold.desktop import SHORTCUT_SVG
    assert SHORTCUT_SVG.startswith("<svg")
    # the xmlns is a namespace URI, not a fetch — look for actual references
    assert "href" not in SHORTCUT_SVG and "src=" not in SHORTCUT_SVG


# ---- the agent transcript --------------------------------------------------
def test_the_agent_reports_timed_steps_not_just_an_answer():
    """A command prompt gives the answer; a transcript gives the working.

    Each step must carry the command that ran, what it produced and how long it
    took — that is what a reviewer needs to trust the answer.
    """
    from wengold.desktop import _agent, build_state
    st = build_state("examples")
    a = _agent(st, "what must I re-run?")
    assert a["ok"] and len(a["steps"]) >= 4
    for s in a["steps"]:
        assert s["label"] and s["cmd"] and s["detail"]
        assert isinstance(s["secs"], (int, float)) and s["secs"] >= 0
        assert s["done"] is True
    assert a["total_secs"] >= 0
    assert a["summary"], "a transcript must end with a conclusion"


def test_the_transcript_names_the_command_it_ran():
    from wengold.desktop import _agent, build_state
    a = _agent(build_state("examples"), "check dma")
    cmds = " ".join(s["cmd"] for s in a["steps"])
    for expect in ("wengold index", "wengold ingest graph", "wengold verdicts"):
        assert expect in cmds, f"{expect} missing from the transcript"


def test_the_agent_endpoint_serves_the_transcript(server):
    d = get_json(server, "/api/agent?q=what+changed")
    assert d["ok"] and d["steps"]
    assert d["request"] == "what changed"


def test_the_page_deep_links_a_request():
    from wengold.desktop import HTML
    assert "URLSearchParams" in HTML and "ask" in HTML


# ---- the frame -------------------------------------------------------------
def test_the_app_is_one_panel_not_a_page():
    """The whole app sits in a rounded bordered panel inset from the viewport —
    a window, not a page. The title strip reads like a revision line."""
    from wengold.desktop import HTML
    assert 'id="frame"' in HTML
    assert 'id="titlebar"' in HTML
    assert "border-radius:10px" in HTML
    assert "position:absolute;inset:14px" in HTML
    # the strip carries project — tool — revision — size, the way a build line does
    for part in ('id="tname"', 'id="trev"', "wengold</span>", 'id="tdims"'):
        assert part in HTML, f"title strip missing {part}"


def test_the_title_strip_has_no_logo_beside_it():
    """The 512px mark is a dark chip on black; at 15px on a light strip it renders
    as a black blob. The mark belongs in the favicon and the app icon, not here."""
    from wengold.desktop import HTML
    bar = HTML[HTML.index('id="titlebar"'):HTML.index("</div>", HTML.index('id="titlebar"'))]
    assert "/icon.png" not in bar
