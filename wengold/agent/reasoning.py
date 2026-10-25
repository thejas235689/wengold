"""Reasoning: a chain of thought that cites the graph instead of asserting.

The point of a reasoning trace is to be checkable. This one is produced
deterministically from the design graph and the kernel's classification, so every
step names the nodes or results it rests on — and a reader can verify it against
the graph rather than trusting the prose.

That makes it different from an LLM's chain of thought in the one way that matters
for verification: **it cannot say something the graph does not support.** The
trace is also a prompt — hand `Thought.as_prompt()` to a model if one is wired in,
and the model is reasoning over facts that were read, not recalled.

Each trace answers one question: *why does this result have the verdict it has?*
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..kernel.validity import Execution, Verdict

__all__ = ["Thought", "Trace", "explain"]


@dataclass
class Thought:
    step: int
    claim: str
    because: list[str] = field(default_factory=list)

    def render(self) -> str:
        tail = f"   [{' , '.join(self.because)}]" if self.because else ""
        return f"  {self.step}. {self.claim}{tail}"

    def as_prompt(self) -> str:
        return f"{self.claim} (evidence: {', '.join(self.because) or 'none'})"


@dataclass
class Trace:
    result: str
    verdict: str
    thoughts: list[Thought] = field(default_factory=list)

    def render(self) -> str:
        head = f"{self.result}: {self.verdict}"
        return "\n".join([head] + [t.render() for t in self.thoughts])

    def as_prompt(self) -> str:
        return "\n".join(f"{i}. {t.as_prompt()}"
                         for i, t in enumerate(self.thoughts, 1))


def explain(ctx, result_id: str) -> Trace:
    """Why this result has the verdict it has, one checkable step at a time."""
    result = ctx.results.get(result_id)
    verdict = ctx.verdicts.get(result_id)
    if result is None or verdict is None:
        return Trace(result_id, "not in the result set",
                     [Thought(1, f"no prior result is recorded as {result_id!r}")])

    thoughts: list[Thought] = []
    n = 0

    n += 1
    thoughts.append(Thought(
        n, f"{result_id} is recorded as {getattr(result, 'kind', 'a check')} "
           f"over {len(getattr(result, 'depends_on', set()) or set())} design node(s)",
        sorted(getattr(result, "depends_on", set()) or set())[:6]))

    if verdict is Verdict.INVALIDATED:
        hit = sorted((getattr(result, "depends_on", set()) or set()) & ctx.changed)
        via = sorted(r for r in (getattr(result, "depends_on_results", set()) or set())
                     if ctx.verdicts.get(r) is Verdict.INVALIDATED)
        n += 1
        if hit:
            thoughts.append(Thought(
                n, f"the change touches {len(hit)} node(s) it consumed, so the "
                   f"result cannot be claimed to still hold", hit[:8]))
        elif via:
            # invalidated through a *result* it summarises, not through a node.
            # Saying "the change touches 0 nodes, so it cannot hold" was a
            # contradiction the graph does not support.
            thoughts.append(Thought(
                n, f"it summarises {len(via)} result(s) that are themselves "
                   f"invalidated, so it cannot still hold", via[:8]))
        else:
            thoughts.append(Thought(
                n, "the kernel invalidated it, but no changed node or invalidated "
                   "result is named — this trace cannot explain it"))
        downstream = ctx.dependents.get(result_id, set())
        if downstream:
            n += 1
            thoughts.append(Thought(
                n, f"{len(downstream)} result(s) rest on this one, so they are in "
                   f"doubt too and must be re-established after it",
                sorted(downstream)[:6]))
    elif verdict is Verdict.UNKNOWN:
        deps = getattr(result, "depends_on", set()) or set()
        if not deps:
            n += 1
            thoughts.append(Thought(
                n, "no dependencies were recorded for it, so there is nothing to "
                   "compare the change against — unknown, not valid"))
        else:
            bad = sorted(deps & set(ctx.unresolved))
            n += 1
            if bad:
                thoughts.append(Thought(
                    n, f"{len(bad)} of its dependencies are unresolved in the "
                       f"graph, so its currency cannot be decided", bad[:8]))
            else:
                # the agent's own check looks only at DIRECT dependencies, but the
                # kernel tests the whole upstream closure — on OpenTitan a result
                # whose direct dependency resolved was still unknown because
                # prim_flop sat deeper in its closure. Rather than re-derive the
                # closure here (and get it subtly wrong), quote the kernel: it
                # knows which condition fired and the trace must not contradict it.
                kernel_reason = (getattr(ctx, "reasons", {}) or {}).get(result_id, "")
                if "unresolved node" in kernel_reason:
                    tail = kernel_reason.split(":", 1)[-1].strip()
                    thoughts.append(Thought(
                        n, "something unresolved sits in its dependency closure "
                           f"({tail}), so its currency cannot be decided"))
                elif "absent from the graph" in kernel_reason:
                    tail = kernel_reason.split(":", 1)[-1].strip()
                    thoughts.append(Thought(
                        n, "it depends on node(s) the graph does not contain "
                           f"({tail}), so information was lost and it cannot be "
                           "called unaffected"))
                elif getattr(ctx, "approximate", False):
                    thoughts.append(Thought(
                        n, "the graph was built without a full elaboration, so "
                           "the kernel will not call it valid whatever is run"))
                elif getattr(result, "execution", None) is Execution.NOT_RUN:
                    thoughts.append(Thought(
                        n, "it has never been executed, so there is no evidence "
                           "for it — unknown, not valid", sorted(deps)[:8]))
                else:
                    thoughts.append(Thought(
                        n, f"the kernel says: {kernel_reason or 'unknown'} — this "
                           f"trace cannot add to that"))
    else:
        n += 1
        thoughts.append(Thought(
            n, "nothing it consumed is in the change set, so it is unaffected"))

    if result_id in ctx.todo:
        n += 1
        thoughts.append(Thought(
            n, "it is in the minimum new evidence, so re-establishing it is the "
               "cheapest way to close this out"))
    else:
        n += 1
        thoughts.append(Thought(n, "no new evidence is needed for it"))

    return Trace(result_id, verdict.value, thoughts)


def explain_all(ctx) -> list[Trace]:
    """One trace per result the agent has to act on, then the settled ones."""
    order = list(ctx.todo) + [r for r in ctx.results if r not in ctx.todo]
    return [explain(ctx, r) for r in order]
