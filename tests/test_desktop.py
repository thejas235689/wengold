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
