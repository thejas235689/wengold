"""Tests for dependency-aware parallel agent execution."""
from threading import Barrier, Lock
import time

import pytest

from wengold.agent.parallel import AgentTask, ParallelAgentRunner


def test_independent_agents_execute_concurrently():
    barrier = Barrier(3, timeout=2)

    def run_agent(task, deps, context):
        barrier.wait()
        return task.role

    tasks = [AgentTask(str(i), f"role-{i}", "inspect") for i in range(3)]
    results = ParallelAgentRunner(run_agent, max_workers=3).run(tasks)
    assert [r.status for r in results] == ["completed"] * 3
    assert [r.output for r in results] == ["role-0", "role-1", "role-2"]


def test_only_declared_dependency_results_are_passed():
    seen = []

    def run_agent(task, deps, context):
        seen.append((task.task_id, tuple(deps)))
        return task.task_id

    tasks = [
        AgentTask("rtl", "rtl", "draft"),
        AgentTask("sva", "sva", "review", depends_on=("rtl",)),
        AgentTask("coverage", "coverage", "plan"),
    ]
    results = ParallelAgentRunner(run_agent, max_workers=3).run(tasks)
    assert all(r.status == "completed" for r in results)
    assert ("sva", ("rtl",)) in seen


def test_failed_dependency_blocks_only_dependants():
    def run_agent(task, deps, context):
        if task.task_id == "bad":
            raise RuntimeError("synthetic failure")
        return "ok"

    tasks = [
        AgentTask("bad", "rtl", "fail"),
        AgentTask("blocked", "review", "needs rtl", depends_on=("bad",)),
        AgentTask("independent", "formal", "continue"),
    ]
    results = ParallelAgentRunner(run_agent, max_workers=3).run(tasks)
    states = {r.task_id: r.status for r in results}
    assert states == {"bad": "failed", "blocked": "blocked",
                      "independent": "completed"}


def test_duplicate_unknown_and_cyclic_dependencies_are_rejected():
    runner = ParallelAgentRunner(lambda task, deps, ctx: None)
    with pytest.raises(ValueError, match="duplicate"):
        runner.run([AgentTask("x", "rtl", ""), AgentTask("x", "sva", "")])
    with pytest.raises(ValueError, match="unknown dependencies"):
        runner.run([AgentTask("x", "rtl", "", depends_on=("missing",))])
    with pytest.raises(ValueError, match="dependency cycle"):
        runner.run([
            AgentTask("a", "rtl", "", depends_on=("b",)),
            AgentTask("b", "sva", "", depends_on=("a",)),
        ])


def test_concurrency_is_bounded():
    lock = Lock()
    active = 0
    peak = 0

    def run_agent(task, deps, context):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return "done"

    tasks = [AgentTask(str(i), "agent", "work") for i in range(8)]
    ParallelAgentRunner(run_agent, max_workers=2).run(tasks)
    assert peak == 2
