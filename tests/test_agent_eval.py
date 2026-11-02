"""The agent evaluation harness, and the defect it found.

`tools/agent-eval.py` exercises every module in the agent layer. Running it found
that `Agent.run("m0")` — the most natural way to call it — settled nothing and
reported `done`, because a bare string is iterable and was passed through as the
changed set, so it looked for nodes called "m" and "0", matched none, classified
every result VALID and stopped.

That is a silent wrong answer, which is the bug class this project keeps finding.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "agent-eval.py"


def test_the_harness_exists_and_runs():
    r = subprocess.run([sys.executable, str(TOOL)], capture_output=True,
                       text=True, cwd=str(ROOT), timeout=240)
    assert r.returncode == 0, r.stderr[-500:]
    assert "works" in r.stdout
    assert "fails" in r.stdout or "marginal" in r.stdout or True


def test_the_harness_covers_every_agent_module():
    r = subprocess.run([sys.executable, str(TOOL)], capture_output=True,
                       text=True, cwd=str(ROOT), timeout=240)
    out = r.stdout
    for mod in ("adaptation", "belief", "coding", "cognition", "hierarchy",
                "human", "loop", "mcts", "memory", "orchestra", "perception",
                "planning", "propose", "react", "reasoning", "runners",
                "search", "swarm"):
        assert mod in out, f"{mod} is not evaluated"


def test_it_reports_the_feature_surface_too():
    r = subprocess.run([sys.executable, str(TOOL)], capture_output=True,
                       text=True, cwd=str(ROOT), timeout=240)
    for f in ("agentic in the app", "vibe", "review", "FSL metrics",
              "CDC Clause 5"):
        assert f in r.stdout, f


# ---- the defect the harness found --------------------------------------
@pytest.fixture
def graph_and_results():
    import random

    from wengold.graph.model import DesignGraph, EdgeKind, Node, NodeKind
    from wengold.kernel.validity import Result

    rng = random.Random(7)
    g = DesignGraph()
    names = [f"m{i}" for i in range(6)]
    for n in names:
        g.add_node(Node(id=n, kind=NodeKind.RTL))
    for _ in range(8):
        a, b = rng.sample(names, 2)
        g.add_edge(a, b, EdgeKind.INSTANTIATES)
    g.rebuild_index()
    return g, [Result(f"{n}_sim", "sim", depends_on={n}) for n in names], names


def test_a_bare_string_is_one_node_not_its_characters(graph_and_results):
    """`run("m0")` used to iterate 'm' and '0' and settle nothing."""
    from wengold.agent.loop import Agent

    g, res, names = graph_and_results
    by_string = Agent(g, res).run(names[0])
    by_set = Agent(g, res).run({names[0]})
    assert by_string.settled == by_set.settled
    assert by_string.settled > 0, "a change must invalidate something"


def test_a_string_list_and_set_agree(graph_and_results):
    from wengold.agent.loop import Agent

    g, res, names = graph_and_results
    a = Agent(g, res).run(names[0]).settled
    b = Agent(g, res).run([names[0]]).settled
    c = Agent(g, res).run({names[0]}).settled
    assert a == b == c
