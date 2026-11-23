"""Bounded dependency-aware parallel execution for WENGOLD agents."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable, Mapping

__all__ = ["AgentTask", "AgentResult", "ParallelAgentRunner"]


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    role: str
    prompt: str
    depends_on: tuple[str, ...] = ()
    priority: int = 0


@dataclass
class AgentResult:
    task_id: str
    role: str
    status: str
    output: Any = None
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.finished_at - self.started_at)


AgentCallable = Callable[[AgentTask, Mapping[str, AgentResult], Any], Any]


@dataclass
class ParallelAgentRunner:
    """Run independent agents concurrently, respecting explicit dependencies.

    The injected backend decides whether inference is concurrent, batched or
    serialized. This scheduler does not claim that model weights are shared.
    """

    run_agent: AgentCallable
    max_workers: int = 8

    def __post_init__(self) -> None:
        if self.max_workers < 1:
            raise ValueError("max_workers must be at least 1")

    def run(self, tasks: list[AgentTask], context: Any = None) -> list[AgentResult]:
        by_id: dict[str, AgentTask] = {}
        for task in tasks:
            if not task.task_id or task.task_id in by_id:
                raise ValueError(f"empty or duplicate task_id: {task.task_id!r}")
            by_id[task.task_id] = task
        for task in tasks:
            unknown = set(task.depends_on) - by_id.keys()
            if unknown:
                raise ValueError(f"{task.task_id} has unknown dependencies: {sorted(unknown)}")
            if task.task_id in task.depends_on:
                raise ValueError(f"{task.task_id} cannot depend on itself")

        order = {task.task_id: i for i, task in enumerate(tasks)}
        results: dict[str, AgentResult] = {}
        pending = set(by_id)
        running: dict[Future, AgentTask] = {}

        def invoke(task: AgentTask, dependencies: dict[str, AgentResult]) -> AgentResult:
            started = monotonic()
            try:
                output = self.run_agent(task, dependencies, context)
                return AgentResult(task.task_id, task.role, "completed",
                                   output=output, started_at=started,
                                   finished_at=monotonic())
            except Exception as exc:
                return AgentResult(task.task_id, task.role, "failed",
                                   error=f"{type(exc).__name__}: {exc}",
                                   started_at=started, finished_at=monotonic())

        with ThreadPoolExecutor(max_workers=self.max_workers,
                                thread_name_prefix="wengold-agent") as pool:
            while pending or running:
                progressed = False
                for task_id in sorted(tuple(pending),
                                      key=lambda key: (-by_id[key].priority, order[key])):
                    task = by_id[task_id]
                    states = [results[d].status for d in task.depends_on if d in results]
                    if any(state in {"failed", "blocked"} for state in states):
                        results[task_id] = AgentResult(
                            task_id, task.role, "blocked",
                            error="one or more dependencies did not complete")
                        pending.remove(task_id)
                        progressed = True
                    elif len(states) == len(task.depends_on) and len(running) < self.max_workers:
                        deps = {d: results[d] for d in task.depends_on}
                        future = pool.submit(invoke, task, deps)
                        running[future] = task
                        pending.remove(task_id)
                        progressed = True

                if running:
                    done, _ = wait(tuple(running), return_when=FIRST_COMPLETED)
                    for future in done:
                        task = running.pop(future)
                        results[task.task_id] = future.result()
                        progressed = True
                elif pending and not progressed:
                    cycle = sorted(pending, key=lambda key: order[key])
                    raise ValueError(f"dependency cycle among tasks: {cycle}")

        return [results[task.task_id] for task in tasks]
